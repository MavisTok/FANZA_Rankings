"""
用 FANZA 女演员月榜补齐 Jinjier 女优榜本地图片。

脚本从 FANZA 当前月度女演员榜抓取姓名和 imageUrl，按姓名匹配
data/jinjier/fanza_actresses.json 中的 Jinjier 记录。匹配成功后会下载图片到
data/covers/jinjier/actresses，并在 JSON 记录上写入 local_cover / fanza_image_url。
"""
import argparse
import datetime as dt
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "jinjier" / "fanza_actresses.json"
COVER_DIR = ROOT / "data" / "covers" / "jinjier" / "actresses"
GRAPHQL_URL = "https://api.video.dmm.co.jp/graphql"
REFERER_URL = "https://video.dmm.co.jp/av/ranking/?term=monthly&type=actress"
TIMEOUT = 30
REQUEST_RETRIES = 3
SLEEP_RANGE = (0.35, 0.8)
IMAGE_SIZE = 800

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en;q=0.8",
    "Origin": "https://video.dmm.co.jp",
    "Referer": REFERER_URL,
    "Cookie": "age_check_done=1",
}

ACTRESS_RANKING_QUERY = """
query ActressRankingPage(
  $limit: Int!,
  $offset: Int,
  $filter: PPVActressRankingFilterInput!
) {
  ppvActressRanking(limit: $limit, offset: $offset, filter: $filter) {
    items {
      id
      rank
      actress {
        id
        name
        imageUrl
        contentsCountOnSale
        latestContent {
          id
          title
          ... on PPVContentSummary {
            packageImage {
              mediumUrl
              largeUrl
            }
          }
        }
      }
    }
  }
}
"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("jinjier-cover")


def normalize_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", value or "")
    normalized = normalized.replace("（", "(").replace("）", ")")
    return normalized


def name_keys(value: str) -> set[str]:
    raw = normalize_name(value)
    keys = {raw} if raw else set()
    without_parens = re.sub(r"\([^)]*\)", "", raw)
    if without_parens:
        keys.add(without_parens)
    for inner in re.findall(r"\(([^)]*)\)", raw):
        if inner:
            keys.add(inner)
    return keys


def post_graphql(query: str, variables: Dict) -> Dict:
    payload = json.dumps({
        "operationName": "ActressRankingPage",
        "query": query,
        "variables": variables,
    }).encode("utf-8")
    req = Request(
        GRAPHQL_URL,
        data=payload,
        headers={**HEADERS, "Content-Type": "application/json"},
    )

    last_error: Exception | None = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            with urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            if data.get("errors"):
                raise RuntimeError(f"GraphQL 返回错误: {data['errors']}")
            return data
        except HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"GraphQL HTTP {e.code}: {detail[:500]}") from e
        except (URLError, TimeoutError, RuntimeError) as e:
            last_error = e
            if attempt >= REQUEST_RETRIES:
                break
            wait = random.uniform(1.5, 3.0) * attempt
            log.warning("GraphQL 请求失败，%.1fs 后重试 %s/%s: %s", wait, attempt + 1, REQUEST_RETRIES, e)
            time.sleep(wait)

    raise RuntimeError(f"GraphQL 请求失败: {last_error}")


def crawl_actress_ranking(max_rank: int, page_size: int) -> list[dict]:
    items: list[dict] = []
    for offset in range(0, max_rank, page_size):
        limit = min(page_size, max_rank - offset)
        variables = {
            "limit": limit,
            "offset": offset,
            "filter": {"monthly": {"floor": "AV"}},
        }
        data = post_graphql(ACTRESS_RANKING_QUERY, variables)
        page_items = ((data.get("data") or {}).get("ppvActressRanking") or {}).get("items") or []
        if not page_items:
            break
        items.extend(page_items)
        time.sleep(random.uniform(*SLEEP_RANGE))
        if len(page_items) < limit:
            break
    return items[:max_rank]


def index_by_name(ranking_items: list[dict]) -> dict[str, dict]:
    index = {}
    for item in ranking_items:
        actress = item.get("actress") or {}
        image_url = actress.get("imageUrl") or ""
        name = actress.get("name") or ""
        if not name or not image_url:
            continue
        latest_content = actress.get("latestContent") or {}
        package_image = latest_content.get("packageImage") or {}
        cover_image_url = package_image.get("largeUrl") or package_image.get("mediumUrl") or image_url
        record = {
            "id": actress.get("id") or item.get("id") or "",
            "name": name,
            "rank": item.get("rank") or 0,
            "image_url": cover_image_url,
            "avatar_url": image_url,
            "latest_content_id": latest_content.get("id") or "",
            "latest_content_title": latest_content.get("title") or "",
            "latest_content_cover_url": cover_image_url if cover_image_url != image_url else "",
            "contents_count_on_sale": actress.get("contentsCountOnSale") or 0,
        }
        for key in name_keys(name):
            existing = index.get(key)
            if not existing or record["rank"] < existing["rank"]:
                index[key] = record
    return index


def cover_filename(record: dict) -> str:
    parsed = urlparse(record["image_url"])
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    latest_content_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(record.get("latest_content_id") or "")).strip("-")
    stem = latest_content_id or Path(parsed.path).stem or "actress"
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-") or "actress"
    actress_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(record.get("id") or "")).strip("-")
    prefix = f"{actress_id}-" if actress_id else ""
    return f"{prefix}{safe_stem}{suffix}"


def sized_image_url(url: str, image_size: int) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}w={image_size}&h={image_size}&q=90&t=margin"


def download_cover(record: dict, skip_downloads: bool, force: bool, image_size: int) -> str:
    filename = cover_filename(record)
    local_path = COVER_DIR / filename
    local_url = f"/data/covers/jinjier/actresses/{filename}"
    if skip_downloads or (local_path.exists() and not force):
        return local_url

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    req = Request(sized_image_url(record["image_url"], image_size), headers=HEADERS)
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            local_path.write_bytes(resp.read())
        return local_url
    except (HTTPError, URLError, TimeoutError) as e:
        log.warning("图片下载失败 name=%s url=%s: %s", record["name"], record["image_url"], e)
        return ""


def enrich_payload(
    payload: dict,
    fanza_index: dict[str, dict],
    skip_downloads: bool,
    force: bool,
    image_size: int,
) -> tuple[dict, int, int]:
    matched_names = set()
    cover_cache = {}
    changed = 0

    for item in payload.get("items") or []:
        match = next((fanza_index[key] for key in name_keys(item.get("name", "")) if key in fanza_index), None)
        if not match:
            continue

        cache_key = match["id"] or match["image_url"]
        if cache_key not in cover_cache:
            cover_cache[cache_key] = download_cover(
                match,
                skip_downloads=skip_downloads,
                force=force,
                image_size=image_size,
            )
        local_cover = cover_cache[cache_key]
        if not local_cover:
            continue

        before = (
            item.get("local_cover"),
            item.get("fanza_image_url"),
            item.get("fanza_actress_id"),
            item.get("fanza_actress_rank"),
        )
        item["local_cover"] = local_cover
        item["fanza_image_url"] = match["image_url"]
        item["fanza_avatar_url"] = match["avatar_url"]
        item["fanza_actress_id"] = match["id"]
        item["fanza_actress_rank"] = match["rank"]
        item["fanza_actress_name"] = match["name"]
        item["fanza_latest_content_id"] = match["latest_content_id"]
        item["fanza_latest_content_title"] = match["latest_content_title"]
        item["fanza_latest_content_cover_url"] = match["latest_content_cover_url"]
        item["fanza_contents_count_on_sale"] = match["contents_count_on_sale"]
        after = (
            item.get("local_cover"),
            item.get("fanza_image_url"),
            item.get("fanza_actress_id"),
            item.get("fanza_actress_rank"),
        )
        if before != after:
            changed += 1
        matched_names.add(item.get("name", ""))

    payload["image_enriched_at"] = dt.datetime.now().isoformat(timespec="seconds")
    payload["fanza_actress_ranking_source"] = REFERER_URL
    payload["fanza_actress_cover_matches"] = len(matched_names)
    return payload, len(matched_names), changed


def main() -> None:
    parser = argparse.ArgumentParser(description="用 FANZA 女演员月榜图片补齐 Jinjier 女优榜")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-rank", type=int, default=100)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--image-size", type=int, default=IMAGE_SIZE)
    parser.add_argument("--force", action="store_true", help="覆盖已经存在的本地图片")
    parser.add_argument("--skip-downloads", action="store_true", help="只写本地路径，不实际下载图片")
    args = parser.parse_args()

    out_path = args.output or args.input
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    ranking_items = crawl_actress_ranking(max_rank=args.max_rank, page_size=args.page_size)
    fanza_index = index_by_name(ranking_items)
    payload, matched_names, changed = enrich_payload(
        payload,
        fanza_index,
        skip_downloads=args.skip_downloads,
        force=args.force,
        image_size=args.image_size,
    )
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[OK] fanza_rank_items={len(ranking_items)} "
        f"matched_names={matched_names} changed_rows={changed} out={out_path}"
    )


if __name__ == "__main__":
    main()
