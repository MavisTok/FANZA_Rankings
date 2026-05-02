"""
聚合脚本：读取 data/raw/*.json → 合并评分 → 输出 data/ranking.json
"""
import json
import datetime

from scoring import aggregate
from storage import RAW_DIR, RANKING_FILE, read_month_payload, sync_seed_data


def main() -> None:
    sync_seed_data()
    payloads = []
    monthly_entries = []
    unavailable_months = []
    complete_months = []
    for fp in sorted(RAW_DIR.glob("*.json")):
        payload = read_month_payload(fp.stem, repair=True)
        if not payload:
            print(f"[WARN] 跳过损坏文件 {fp.name}")
            continue
        payloads.append(payload)
        month = payload.get("month")
        if payload.get("unavailable") and month:
            unavailable_months.append(month)
        if payload.get("complete_month") and month:
            complete_months.append(month)
        for item in payload.get("items", []):
            monthly_entries.append({**item, "month": month})

    items = aggregate(payloads)

    out = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "months_included": [p.get("month") for p in payloads if p.get("month")],
        "months_complete": complete_months,
        "months_unavailable": unavailable_months,
        "monthly_entries": monthly_entries,
        "total": len(items),
        "items": items,
    }
    RANKING_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] 写入 {RANKING_FILE}（{len(items)} 条，覆盖 {len(payloads)} 个月份）")


if __name__ == "__main__":
    main()
