"""
FANZA data persistence helpers.

Runtime data may live in a Docker volume while repository seed data is copied
into the image at /var/www/ranking-site/data-seed. All crawler reads/writes go
through this module so seed and runtime payloads are compared consistently.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("FANZA_DATA_DIR", ROOT / "data"))
SEED_DATA_DIR = Path(os.environ.get("FANZA_SEED_DATA_DIR", ROOT / "data-seed"))
RAW_DIR = DATA_DIR / "raw"
SEED_RAW_DIR = SEED_DATA_DIR / "raw"
RANKING_FILE = DATA_DIR / "ranking.json"


def ensure_data_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "covers").mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def normalize_month(month: str | None) -> str:
    if not month:
        return ""
    try:
        year, month_no = month.split("-", 1)
        return f"{int(year):04d}-{int(month_no):02d}"
    except (TypeError, ValueError):
        return ""


def is_2026_or_later(month: str | None) -> bool:
    normalized = normalize_month(month)
    return bool(normalized and normalized >= "2026-01")


def is_complete_month(month: str | None, today: datetime.date | None = None) -> bool:
    normalized = normalize_month(month)
    if not normalized:
        return False
    today = today or datetime.date.today()
    year, month_no = map(int, normalized.split("-"))
    return (year, month_no) < (today.year, today.month)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _item_count(payload: dict[str, Any] | None) -> int:
    if not payload:
        return -1
    items = payload.get("items")
    return len(items) if isinstance(items, list) else 0


def mark_month_payload(payload: dict[str, Any], origin: str | None = None) -> dict[str, Any]:
    month = normalize_month(payload.get("month"))
    if month:
        payload["month"] = month
        payload["complete_month"] = is_complete_month(month)
    if origin:
        payload["origin"] = origin
    if payload.get("complete_month") and not payload.get("completed_at"):
        payload["completed_at"] = now_iso()
    return payload


def payload_score(payload: dict[str, Any] | None) -> tuple[int, int, int, int]:
    if not payload:
        return (-1, -1, -1, -1)
    unavailable = 0 if payload.get("unavailable") else 1
    complete = 1 if payload.get("complete_month") else 0
    count = _item_count(payload)
    fetched = 1 if payload.get("fetched_at") else 0
    return (unavailable, complete, count, fetched)


def better_payload(
    current: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    *,
    prefer_candidate: bool = False,
) -> dict[str, Any] | None:
    if not candidate:
        return current
    if not current:
        return candidate

    current = mark_month_payload(current)
    candidate = mark_month_payload(candidate)
    if prefer_candidate and not candidate.get("unavailable"):
        return candidate
    return candidate if payload_score(candidate) > payload_score(current) else current


def month_paths(month: str) -> tuple[Path, Path]:
    normalized = normalize_month(month)
    return RAW_DIR / f"{normalized}.json", SEED_RAW_DIR / f"{normalized}.json"


def read_month_payload(month: str, *, repair: bool = True) -> dict[str, Any] | None:
    runtime_path, seed_path = month_paths(month)
    runtime = load_json(runtime_path)
    seed = load_json(seed_path) if is_2026_or_later(month) else None
    if seed:
        seed = mark_month_payload(seed, origin="repository-seed")

    best = better_payload(runtime, seed)
    if best:
        best = mark_month_payload(best)

    if repair and best and best is not runtime:
        write_month_payload(best, reason="seed-repair", prefer_new=True)
    elif repair and runtime and best is runtime:
        marked = mark_month_payload(runtime)
        runtime_path.write_text(json.dumps(marked, ensure_ascii=False, indent=2), encoding="utf-8")
    return best


def write_month_payload(
    payload: dict[str, Any],
    *,
    reason: str = "write",
    prefer_new: bool = False,
) -> dict[str, Any]:
    ensure_data_dirs()
    payload = mark_month_payload(payload)
    month = payload.get("month")
    if not month:
        raise ValueError("payload 缺少 month 字段")

    runtime_path, seed_path = month_paths(month)
    current = load_json(runtime_path)
    seed = load_json(seed_path) if is_2026_or_later(month) else None

    best = better_payload(current, seed)
    best = better_payload(best, payload, prefer_candidate=prefer_new)
    best = mark_month_payload(best or payload)
    best["saved_at"] = now_iso()
    best["save_reason"] = reason
    if reason == "seed-repair":
        best["origin"] = "repository-seed"

    runtime_path.write_text(json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8")
    return best


def sync_seed_data() -> dict[str, Any]:
    ensure_data_dirs()
    copied = []
    repaired = []

    if SEED_DATA_DIR.exists():
        for child in SEED_DATA_DIR.iterdir():
            if child.name == "raw":
                continue
            target = DATA_DIR / child.name
            if child.is_dir():
                if not target.exists():
                    shutil.copytree(child, target)
                    copied.append(child.name)
            elif not target.exists():
                shutil.copy2(child, target)
                copied.append(child.name)

    if SEED_RAW_DIR.exists():
        for seed_file in sorted(SEED_RAW_DIR.glob("*.json")):
            month = seed_file.stem
            if not is_2026_or_later(month):
                continue
            before = payload_score(load_json(RAW_DIR / seed_file.name))
            after = read_month_payload(month, repair=True)
            if after and payload_score(after) != before:
                repaired.append(month)

    return {"copied": copied, "repaired_months": repaired}
