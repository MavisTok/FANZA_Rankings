"""
导入 jinjier.art/sql 的 FANZA 通贩销量榜数据。

来源页面加载的是一个 zip 包，包内为 jinjier.sqlite3。脚本会下载数据库，
查询 ranks 表中的「影片榜」和「女优榜」，清洗后输出到 data/jinjier/*.json。
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DB_URL = "https://jinjier.art/20260112.gif"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "jinjier"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://jinjier.art/sql",
}

MONTH_NOTE_RE = re.compile(r"^(影片榜|女优榜) - (\d{4})年(\d{1,2})月$")
HALF_NOTE_RE = re.compile(r"^(影片榜|女优榜) - (\d{4})上半年$")
YEAR_NOTE_RE = re.compile(r"^(影片榜|女优榜) - (\d{4})全年$")
CODE_RE = re.compile(r"^([A-Z]+-\d+[A-Z]?)\s+(.+)$")


def fetch_database(db_url: str) -> Path:
    req = Request(db_url, headers=HEADERS)
    with urlopen(req, timeout=30) as resp:
        body = resp.read()

    tmp_dir = Path(tempfile.mkdtemp(prefix="jinjier-"))
    zip_path = tmp_dir / "jinjier.zip"
    db_path = tmp_dir / "jinjier.sqlite3"
    zip_path.write_bytes(body)

    with zipfile.ZipFile(zip_path) as archive:
        db_path.write_bytes(archive.read("jinjier.sqlite3"))
    return db_path


def parse_note(note: str) -> dict:
    if match := MONTH_NOTE_RE.match(note):
        source_type, year, month = match.groups()
        month_key = f"{int(year):04d}-{int(month):02d}"
        return {
            "source_type": "movie" if source_type == "影片榜" else "actress",
            "period": "month",
            "year": int(year),
            "month": month_key,
            "period_start": month_key,
            "period_end": month_key,
        }

    if match := HALF_NOTE_RE.match(note):
        source_type, year = match.groups()
        return {
            "source_type": "movie" if source_type == "影片榜" else "actress",
            "period": "half_year",
            "year": int(year),
            "month": "",
            "period_start": f"{int(year):04d}-01",
            "period_end": f"{int(year):04d}-06",
        }

    if match := YEAR_NOTE_RE.match(note):
        source_type, year = match.groups()
        return {
            "source_type": "movie" if source_type == "影片榜" else "actress",
            "period": "year",
            "year": int(year),
            "month": "",
            "period_start": f"{int(year):04d}-01",
            "period_end": f"{int(year):04d}-12",
        }

    return {}


def cid_from_icon(icon_url: str) -> str:
    if not icon_url:
        return ""
    name = Path(urlparse(icon_url).path).name
    return re.sub(r"p?t\.jpg$", "", name, flags=re.I)


def clean_movie_name(name: str) -> dict:
    match = CODE_RE.match(name.strip())
    if not match:
        return {
            "code": "",
            "title": name.strip(),
            "is_bluray": "ブルーレイディスク" in name,
        }

    code, title = match.groups()
    return {
        "code": code,
        "title": title.strip(),
        "is_bluray": "ブルーレイディスク" in title,
    }


def detail_url(cid: str) -> str:
    if not cid:
        return ""
    return f"https://www.dmm.co.jp/mono/dvd/-/detail/=/cid={cid}/"


def query_rows(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT number, icon_url, name, note, date
            FROM ranks
            WHERE note LIKE '影片榜 - %' OR note LIKE '女优榜 - %'
            ORDER BY date, note, number
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def clean_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    movies = []
    actresses = []

    for row in rows:
        note_info = parse_note(row["note"] or "")
        if not note_info:
            continue

        base = {
            "rank": int(row["number"]),
            "name": row["name"].strip(),
            "cover_url": row["icon_url"] or "",
            "note": row["note"],
            "date": row["date"],
            **note_info,
        }

        if note_info["source_type"] == "movie":
            movie = clean_movie_name(row["name"])
            cid = cid_from_icon(row["icon_url"] or "")
            movies.append({
                **base,
                "code": movie["code"],
                "title": movie["title"],
                "is_bluray": movie["is_bluray"],
                "cid": cid,
                "url": detail_url(cid),
            })
        else:
            actresses.append(base)

    return dedupe_movies(movies), actresses


def dedupe_movies(rows: list[dict]) -> list[dict]:
    deduped = {}
    for row in rows:
        key = (
            row["period"],
            row.get("period_start", ""),
            row.get("period_end", ""),
            row.get("code") or row["name"],
        )
        existing = deduped.get(key)
        if not existing or row["rank"] < existing["rank"]:
            next_row = {**row}
            next_row["duplicate_count"] = (existing or {}).get("duplicate_count", 0) + 1
            deduped[key] = next_row
        else:
            existing["duplicate_count"] = existing.get("duplicate_count", 1) + 1
    return sorted(deduped.values(), key=lambda item: (item["date"], item["note"], item["rank"]))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 jinjier.art/sql FANZA 榜单数据")
    parser.add_argument("--db-url", default=DB_URL)
    args = parser.parse_args()

    db_path = fetch_database(args.db_url)
    rows = query_rows(db_path)
    movies, actresses = clean_rows(rows)
    now = dt.datetime.now().isoformat(timespec="seconds")

    write_json(OUT_DIR / "fanza_movies.json", {
        "source": args.db_url,
        "generated_at": now,
        "total": len(movies),
        "items": movies,
    })
    write_json(OUT_DIR / "fanza_actresses.json", {
        "source": args.db_url,
        "generated_at": now,
        "total": len(actresses),
        "items": actresses,
    })
    write_json(OUT_DIR / "summary.json", {
        "source": args.db_url,
        "generated_at": now,
        "movies_total": len(movies),
        "actresses_total": len(actresses),
        "movie_months": sorted({item["month"] for item in movies if item["period"] == "month"}),
        "actress_months": sorted({item["month"] for item in actresses if item["period"] == "month"}),
    })
    print(f"[OK] movies={len(movies)} actresses={len(actresses)} out={OUT_DIR}")


if __name__ == "__main__":
    main()
