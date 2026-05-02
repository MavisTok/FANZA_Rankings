"""
评分逻辑：
- 排名赋分：第 1 名 6 分；2-10 名 4 分；11-30 名 3 分；31-50 名 2 分；51-100 名 1 分
- 不再根据出现次数加权
- 同分按最佳排名（best_rank）优先
"""
from typing import Dict, List


# 排名分段表 (low, high, score)
RANK_TABLE = [
    (1, 1, 6),
    (2, 10, 4),
    (11, 30, 3),
    (31, 50, 2),
    (51, 100, 1),
]


def rank_score(rank: int) -> int:
    """根据排名返回基础分"""
    for low, high, score in RANK_TABLE:
        if low <= rank <= high:
            return score
    return 0


def aggregate(monthly_payloads: List[Dict]) -> List[Dict]:
    """
    将多个月度排行榜合并为最终排行：
    - 以 url 为去重主键（缺失则退化为 name）
    - 累加得分、统计上榜次数、记录最佳名次（仅记录，不参与评分）
    """
    bucket: Dict[str, Dict] = {}

    for payload in monthly_payloads:
        for item in payload.get("items", []):
            key = item.get("url") or item.get("name")
            if not key:
                continue

            base = rank_score(item.get("rank", 0))

            if key not in bucket:
                bucket[key] = {
                    "name": item.get("name", ""),
                    "url": item.get("url", ""),
                    "code": item.get("code", ""),
                    "cover": item.get("cover", ""),
                    "cover_url": item.get("cover_url", ""),
                    "description": item.get("description", ""),
                    "category": item.get("category", ""),
                    "score": 0,
                    "appearances": 0,
                    "best_rank": item.get("rank", 0) or 9999,
                }

            entry = bucket[key]

            # 补全字段（只在缺失时填充）
            if not entry.get("code") and item.get("code"):
                entry["code"] = item["code"]
            if not entry.get("cover") and item.get("cover"):
                entry["cover"] = item["cover"]
            if not entry.get("cover_url") and item.get("cover_url"):
                entry["cover_url"] = item["cover_url"]
            if not entry.get("description") and item.get("description"):
                entry["description"] = item["description"]

            # 核心：只累计基础分
            entry["score"] += base
            entry["appearances"] += 1

            if item.get("rank", 0):
                entry["best_rank"] = min(entry["best_rank"], item["rank"])

    # ❌ 已移除 appearances 加权

    ranked: List[Dict] = list(bucket.values())

    # 排序：得分降序 → 最佳名次升序
    ranked.sort(key=lambda x: (-x["score"], x["best_rank"]))

    for i, entry in enumerate(ranked, 1):
        entry["rank"] = i

    return ranked
