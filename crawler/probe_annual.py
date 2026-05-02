"""
探测 FANZA GraphQL 是否提供"年榜"维度。
- 第一步：用 introspection 查 PPVContentRankingFilterInput 的全部字段名
- 第二步：穷举多种可能的 schema 形态构造一次最小查询，看哪种能通
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from crawl_fanza import (
    CONTENT_RANKING_QUERY,
    GRAPHQL_URL,
    HEADERS,
    TIMEOUT,
)


INTROSPECTION_QUERY = """
query ProbeFilterShape {
  __type(name: "PPVContentRankingFilterInput") {
    name
    inputFields {
      name
      type {
        name
        kind
        ofType { name kind }
      }
    }
  }
}
"""


def post(query: str, variables=None, op_name: str | None = None) -> dict:
    payload: dict = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    if op_name:
        payload["operationName"] = op_name
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        GRAPHQL_URL,
        data=body,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return {
            "_http_error": e.code,
            "_body": e.read().decode("utf-8", "replace")[:500],
        }
    except URLError as e:
        return {"_network_error": str(e)}


def step_introspection() -> list[str] | None:
    print("== Step 1: Introspection PPVContentRankingFilterInput ==")
    res = post(INTROSPECTION_QUERY)
    if res.get("_http_error") or res.get("_network_error"):
        print(f"  网络/HTTP 错误：{res}")
        return None

    typ = (res.get("data") or {}).get("__type")
    if not typ:
        if res.get("errors"):
            print("  introspection 被屏蔽 / 错误：")
            print("  " + json.dumps(res["errors"], ensure_ascii=False))
        else:
            print("  __type 返回空，可能 schema 已变更")
        return None

    fields = typ.get("inputFields") or []
    print(f"  发现 {len(fields)} 个字段：")
    for f in fields:
        t = f.get("type") or {}
        of = t.get("ofType") or {}
        type_repr = t.get("name") or of.get("name") or t.get("kind")
        print(f"    - {f['name']}: {type_repr}")
    return [f["name"] for f in fields]


# 候选 schema 构造器：(label, build(year)->filter_dict)
CANDIDATES = [
    ("annual + targetYear.year", lambda y: {"annual": {"floor": "AV", "targetYear": {"year": y}}}),
    ("annual + targetYear (Int)", lambda y: {"annual": {"floor": "AV", "targetYear": y}}),
    ("annual + year", lambda y: {"annual": {"floor": "AV", "year": y}}),
    ("yearly + targetYear.year", lambda y: {"yearly": {"floor": "AV", "targetYear": {"year": y}}}),
    ("yearly + year", lambda y: {"yearly": {"floor": "AV", "year": y}}),
    ("year + year", lambda y: {"year": {"floor": "AV", "year": y}}),
]


def step_trial(year: int = 2024) -> list[str]:
    print(f"\n== Step 2: 构造测试查询 (year={year}) ==")
    workable = []
    for label, build in CANDIDATES:
        variables = {
            "limit": 1,
            "offset": 0,
            "filter": build(year),
            "isAmateur": False,
            "isAnime": False,
        }
        res = post(CONTENT_RANKING_QUERY, variables, "ContentRankingPage")

        if res.get("_http_error"):
            tag = f"❌ HTTP {res['_http_error']}"
            detail = res["_body"][:200]
        elif res.get("_network_error"):
            tag = "❌ 网络异常"
            detail = res["_network_error"]
        elif res.get("errors"):
            tag = "❌ GraphQL 错误"
            err = res["errors"][0] if res["errors"] else {}
            detail = err.get("message", json.dumps(err, ensure_ascii=False))[:240]
        else:
            data = (res.get("data") or {}).get("ppvContentRanking")
            if data is None:
                tag = "⚠️ schema 通过但 ppvContentRanking == null"
                detail = "可能该年无数据，schema 形态本身可用"
                workable.append(label)
            else:
                items = data.get("items", [])
                tag = f"✅ 命中 {len(items)} 条"
                detail = ""
                workable.append(label)

        print(f"  {tag}  [{label}]")
        if detail:
            print(f"      → {detail}")

    return workable


def main() -> int:
    fields = step_introspection()
    if fields is not None:
        keywords = ("annual", "yearly", "year")
        hits = [f for f in fields if f in keywords or any(k in f.lower() for k in keywords)]
        if hits:
            print(f"\n  ⭐ filter 中存在年度相关字段：{hits}")
        else:
            print("\n  ⚠️ filter 中未发现 annual / yearly / year 相关字段")

    workable = step_trial(2024)
    print("\n== 结论 ==")
    if workable:
        print("可用形态：")
        for w in workable:
            print(f"  - {w}")
        print("\n下一步：把 crawl_fanza.py 中 monthly filter 替换为上面任一形态，新增 --year 参数即可抓年榜。")
        return 0
    else:
        print("FANZA GraphQL 似乎不提供年榜接口。建议改走 Wayback / 持续累积 等方案。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
