"""
FANZA 月度排行榜爬虫
- 抓取公开 GraphQL 排行榜接口
- 输出原始月度数据到 data/raw/<YYYY-MM>.json
"""
import argparse
import datetime
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from storage import DATA_DIR, RAW_DIR, mark_month_payload, read_month_payload, write_month_payload


GRAPHQL_URL = "https://api.video.dmm.co.jp/graphql"
REFERER_URL = "https://video.dmm.co.jp/av/ranking/?term=monthly"
CONTENT_URL = "https://video.dmm.co.jp/av/content/?id={content_id}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja,en;q=0.8",
    "Origin": "https://video.dmm.co.jp",
    "Referer": REFERER_URL,
    "Cookie": "age_check_done=1",
}
TIMEOUT = 30
SLEEP_RANGE = (0.2, 0.5)
REQUEST_RETRIES = 3
RETRY_SLEEP_RANGE = (1.5, 3.0)
MAX_RANK = 100

ROOT = Path(__file__).resolve().parent.parent
COVER_DIR = DATA_DIR / "covers"
FANZA_COVER_DIR = COVER_DIR / "fanza"
RAW_DIR.mkdir(parents=True, exist_ok=True)
COVER_DIR.mkdir(parents=True, exist_ok=True)
FANZA_COVER_DIR.mkdir(parents=True, exist_ok=True)

CONTENT_RANKING_QUERY = """
query ContentRankingPage(
  $limit: Int!,
  $offset: Int!,
  $filter: PPVContentRankingFilterInput,
  $isAmateur: Boolean = false,
  $isAnime: Boolean = false
) {
  ppvContentRanking(limit: $limit, offset: $offset, filter: $filter) {
    items {
      id
      rank
      content {
        title
        releaseStatus
        packageImage {
          mediumUrl
          largeUrl
        }
        wishlistCount
        isExclusiveDelivery
        contentType
        pricing {
          lowestEffectivePriceInclusiveTax
          lowestRegularPriceInclusiveTax
          hasMultiplePrices
        }
        actresses @skip(if: $isAmateur) {
          id
          name
        }
        maker @include(if: $isAnime) {
          id
          name
        }
        sampleImages {
          number
          largeImageUrl
        }
        hasSampleMovie
        review {
          average
          total
        }
      }
    }
  }
}
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("crawler")


def polite_sleep() -> None:
    time.sleep(random.uniform(*SLEEP_RANGE))


def parse_month(month: str | None) -> tuple[int, int, str]:
    if not month:
        today = datetime.date.today()
        first_day_this_month = today.replace(day=1)
        last_month = first_day_this_month - datetime.timedelta(days=1)
        return last_month.year, last_month.month, last_month.strftime("%Y-%m")
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", month.strip())
    if not match:
        raise ValueError("月份格式应为 YYYY-MM，例如 2026-04")
    year = int(match.group(1))
    month_no = int(match.group(2))
    if month_no < 1 or month_no > 12:
        raise ValueError("月份必须在 1-12 之间")
    return year, month_no, f"{year}-{month_no:02d}"


def post_graphql(query: str, variables: Dict) -> Dict:
    payload = json.dumps({
        "operationName": "ContentRankingPage",
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
            break
        except HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"GraphQL HTTP {e.code}: {detail[:500]}") from e
        except URLError as e:
            last_error = e
            if attempt >= REQUEST_RETRIES:
                raise RuntimeError(f"GraphQL 请求失败: {e}") from e
            wait = random.uniform(*RETRY_SLEEP_RANGE) * attempt
            log.warning("GraphQL 请求失败，%.1fs 后重试 %s/%s: %s", wait, attempt + 1, REQUEST_RETRIES, e)
            time.sleep(wait)
    else:
        raise RuntimeError(f"GraphQL 请求失败: {last_error}")

    data = json.loads(body)
    if data.get("errors"):
        raise RuntimeError(f"GraphQL 返回错误: {data['errors']}")
    return data


def cover_filename(url: str, content_id: str) -> str:
    """
    用 content_id 作为文件名（稳定 ID），避免 rank 变化导致同图多副本。
    跨月同作品会在各自月份目录下各保留一份。
    """
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", content_id).strip("-") or "cover"
    return f"{safe_id}{suffix}"


def download_cover(url: str, content_id: str, month: str, force: bool = False) -> str:
    """
    按月归档：data/covers/fanza/{YYYY-MM}/{content_id}.{ext}
    返回前端可访问的 web 路径。
    force=True 时无视已有文件，强制重新下载。
    """
    if not url:
        return ""
    filename = cover_filename(url, content_id)
    out_dir = FANZA_COVER_DIR / month
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    web_path = f"/data/covers/fanza/{month}/{filename}"
    if out_path.exists():
        if not force and out_path.stat().st_size >= 30_000:
            return web_path
        reason = "强制覆盖" if force else f"旧缩略图（{out_path.stat().st_size} bytes）"
        log.info("覆盖 %s %s → 重新下载", out_path.name, reason)
        out_path.unlink()
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            out_path.write_bytes(resp.read())
        return web_path
    except (HTTPError, URLError) as e:
        log.warning("封面下载失败 month=%s id=%s url=%s: %s", month, content_id, url, e)
        return ""


def product_code_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return (
        query.get("id", [""])[0]
        or query.get("cid", [""])[0]
        or query.get("product_id", [""])[0]
        or query.get("content_id", [""])[0]
    ).strip()


def item_from_graphql(node: Dict, month: str, skip_covers: bool, force_covers: bool = False) -> Dict:
    content = node.get("content") or {}
    image = content.get("packageImage") or {}
    content_id = node.get("id") or ""
    rank = node.get("rank") or 0
    # 优先取 largeUrl（pl.jpg ~800×538），其次 mediumUrl，避免列表用 smallUrl/ps.jpg 缩略图
    cover_url = image.get("largeUrl") or image.get("mediumUrl") or image.get("smallUrl") or ""
    actresses = content.get("actresses") or []
    actress_names = [x.get("name", "") for x in actresses if x.get("name")]
    description = " / ".join(actress_names)

    url = CONTENT_URL.format(content_id=content_id)
    return {
        "rank": rank,
        "name": content.get("title", ""),
        "url": url,
        "code": product_code_from_url(url) or content_id,
        "cover": "" if skip_covers else download_cover(cover_url, content_id, month, force=force_covers),
        "cover_url": cover_url,
        "description": description,
        "category": "videoa-monthly",
    }


def crawl_month(month: str | None = None, skip_covers: bool = False, force_covers: bool = False) -> Dict:
    year, month_no, month_key = parse_month(month)
    log.info("开始抓取 %s FANZA 月度排行榜", month_key)

    variables = {
        "limit": MAX_RANK,
        "offset": 0,
        "filter": {
            "monthly": {
                "floor": "AV",
                "targetMonth": {"year": year, "month": month_no},
            },
        },
        "isAmateur": False,
        "isAnime": False,
    }
    data = post_graphql(CONTENT_RANKING_QUERY, variables)
    ranking = (data.get("data") or {}).get("ppvContentRanking")
    if ranking is None:
        payload = {
            "month": month_key,
            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "source": REFERER_URL,
            "items": [],
            "unavailable": True,
            "unavailable_reason": "FANZA GraphQL returned null ppvContentRanking for this targetMonth",
        }
        saved = write_month_payload(payload, reason="fanza-unavailable", prefer_new=False)
        if not saved.get("unavailable"):
            log.warning("%s 月榜接口无数据，已从本地种子/历史数据保留 %d 条", month_key, len(saved.get("items", [])))
            return saved
        log.warning("%s 月榜接口无数据，已写入空占位 %s", month_key, RAW_DIR / f"{month_key}.json")
        return saved

    nodes = ranking.get("items", [])
    all_items: List[Dict] = []
    for node in nodes[:MAX_RANK]:
        all_items.append(item_from_graphql(node, month=month_key, skip_covers=skip_covers, force_covers=force_covers))
        polite_sleep()

    payload = {
        "month": month_key,
        "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": REFERER_URL,
        "items": all_items,
    }

    saved = write_month_payload(payload, reason="fanza-crawl", prefer_new=True)
    log.info("已写入 %s（%d 条）", RAW_DIR / f"{month_key}.json", len(saved.get("items", [])))
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 FANZA 月度排行榜")
    parser.add_argument("--month", help="指定月份，格式 YYYY-MM；默认上个月")
    parser.add_argument("--skip-covers", action="store_true", help="只抓数据，不下载封面")
    parser.add_argument("--force-covers", action="store_true", help="强制重新下载所有封面")
    args = parser.parse_args()
    try:
        crawl_month(month=args.month, skip_covers=args.skip_covers, force_covers=args.force_covers)
    except Exception as e:
        _, _, month_key = parse_month(args.month)
        fallback = read_month_payload(month_key, repair=True)
        if fallback and not fallback.get("unavailable"):
            log.warning("%s 在线抓取失败，已使用本仓库种子/本地数据: %s", month_key, e)
            return
        raise


if __name__ == "__main__":
    main()
