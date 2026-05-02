"""
探测 FANZA 月度排行榜当前提供的可用窗口。
- 不下载封面、不写入 raw 文件
- 仅以 limit=1 调用 GraphQL，判断该月是否返回 ppvContentRanking
- 默认从当前月回溯 24 个月，命中第一个连续 3 次 unavailable 即停止
"""
import argparse
import datetime
import json
import sys
import time

from crawl_fanza import (
    CONTENT_RANKING_QUERY,
    SLEEP_RANGE,
    post_graphql,
)


def month_iter(start_year: int, start_month: int, count: int):
    """从 (start_year, start_month) 回溯 count 个月（含起点）"""
    y, m = start_year, start_month
    for _ in range(count):
        yield y, m
        m -= 1
        if m == 0:
            m = 12
            y -= 1


def probe(year: int, month: int) -> bool:
    """True = 该月有数据；False = 接口返回 null"""
    variables = {
        "limit": 1,
        "offset": 0,
        "filter": {
            "monthly": {
                "floor": "AV",
                "targetMonth": {"year": year, "month": month},
            }
        },
        "isAmateur": False,
        "isAnime": False,
    }
    data = post_graphql(CONTENT_RANKING_QUERY, variables)
    ranking = (data.get("data") or {}).get("ppvContentRanking")
    return ranking is not None and bool(ranking.get("items"))


def main() -> int:
    parser = argparse.ArgumentParser(description="探测 FANZA 月度排行可用窗口")
    parser.add_argument("--max", type=int, default=24, help="最多回溯多少个月（默认 24）")
    parser.add_argument("--stop-after", type=int, default=3,
                        help="连续 N 个月不可用后停止探测（默认 3）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出，便于脚本消费")
    args = parser.parse_args()

    today = datetime.date.today()
    available, unavailable = [], []
    miss_streak = 0

    for y, m in month_iter(today.year, today.month, args.max):
        key = f"{y:04d}-{m:02d}"
        try:
            ok = probe(y, m)
        except Exception as e:  # noqa: BLE001
            print(f"[ERR] {key}: {e}", file=sys.stderr)
            ok = False

        marker = "OK " if ok else "----"
        print(f"{marker} {key}", file=sys.stderr)

        if ok:
            available.append(key)
            miss_streak = 0
        else:
            unavailable.append(key)
            miss_streak += 1
            if miss_streak >= args.stop_after:
                break

        time.sleep(SLEEP_RANGE[0])

    available.sort()
    unavailable.sort()
    summary = {
        "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "available": available,
        "unavailable": unavailable,
        "window_start": available[0] if available else None,
        "window_end": available[-1] if available else None,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print()
        print(f"可用窗口: {summary['window_start']} ~ {summary['window_end']}"
              if available else "未发现任何可用月份")
        print(f"可用月份 ({len(available)}): {', '.join(available)}")
        print(f"不可用月份 ({len(unavailable)}): {', '.join(unavailable)}")

    return 0 if available else 1


if __name__ == "__main__":
    sys.exit(main())
