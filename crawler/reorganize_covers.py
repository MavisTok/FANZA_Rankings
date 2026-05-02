#!/usr/bin/env python3
"""
将 data/covers/ 平铺的封面图片按数据源/月份重新归档。

迁移规则：
  /data/covers/{rank:03d}-{cid}.{ext}   → /data/covers/fanza/{YYYY-MM}/{cid}.{ext}
  /data/covers/actresses/...            → /data/covers/jinjier/actresses/...
  /data/covers/sample-*.svg             → /data/covers/samples/sample-*.svg

默认 dry-run，仅打印计划与统计；加 --apply 才真正移动文件并改写相关 JSON。
执行 --apply 时会自动把 data/ranking.json、data/raw/*.json、
data/jinjier/fanza_actresses.json 备份为 *.bak.{timestamp}。
脚本是幂等的：重复执行不会破坏已迁移结果。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COVER_DIR = ROOT / "data" / "covers"
RAW_DIR = ROOT / "data" / "raw"
RANKING_JSON = ROOT / "data" / "ranking.json"
JINJIER_JSON = ROOT / "data" / "jinjier" / "fanza_actresses.json"


def web_to_disk(web_path: str) -> Path | None:
    """ /data/covers/xxx → <ROOT>/data/covers/xxx；非该前缀返回 None。"""
    if not web_path or not web_path.startswith("/data/covers/"):
        return None
    return ROOT / web_path.lstrip("/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def collect_fanza_mapping() -> dict[str, str]:
    """从 raw/*.json 和 ranking.json 的 monthly_entries 收集 fanza 月度封面映射。"""
    mapping: dict[str, str] = {}

    def add(month: str, cid: str, old_cover: str) -> None:
        if not (month and cid and old_cover):
            return
        if not old_cover.startswith("/data/covers/"):
            return
        rel = old_cover[len("/data/covers/"):]
        # 仅处理根目录平铺的旧文件，子目录中的（已含分类）跳过
        if "/" in rel:
            return
        suffix = Path(rel).suffix.lower() or ".jpg"
        mapping[old_cover] = f"/data/covers/fanza/{month}/{cid}{suffix}"

    if RAW_DIR.exists():
        for raw_file in sorted(RAW_DIR.glob("*.json")):
            data = load_json(raw_file)
            month = data.get("month") or raw_file.stem
            for item in data.get("items", []):
                add(month, item.get("code") or "", item.get("cover", ""))

    if RANKING_JSON.exists():
        data = load_json(RANKING_JSON)
        for item in data.get("monthly_entries", []):
            add(item.get("month", ""), item.get("code", ""), item.get("cover", ""))

    return mapping


def collect_actresses_mapping() -> dict[str, str]:
    src_dir = COVER_DIR / "actresses"
    if not src_dir.exists():
        return {}
    return {
        f"/data/covers/actresses/{f.name}": f"/data/covers/jinjier/actresses/{f.name}"
        for f in src_dir.iterdir() if f.is_file()
    }


def collect_samples_mapping() -> dict[str, str]:
    return {
        f"/data/covers/{f.name}": f"/data/covers/samples/{f.name}"
        for f in COVER_DIR.glob("sample-*.svg")
    }


def replace_in_obj(obj: Any, mapping: dict[str, str]) -> int:
    """递归把对象中匹配 mapping key 的字符串替换为 mapping value，返回替换次数。"""
    count = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str) and v in mapping:
                obj[k] = mapping[v]
                count += 1
            elif isinstance(v, (dict, list)):
                count += replace_in_obj(v, mapping)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and v in mapping:
                obj[i] = mapping[v]
                count += 1
            elif isinstance(v, (dict, list)):
                count += replace_in_obj(v, mapping)
    return count


def summarize(mapping: dict[str, str]) -> dict[str, int]:
    to_move = missing_src = dst_exists = 0
    for old, new in mapping.items():
        src = web_to_disk(old)
        dst = web_to_disk(new)
        if src is None or not src.exists():
            missing_src += 1
            continue
        if dst is not None and dst.exists():
            dst_exists += 1
            continue
        to_move += 1
    return {"total": len(mapping), "to_move": to_move,
            "dst_exists": dst_exists, "missing_src": missing_src}


def move_files(mapping: dict[str, str], label: str) -> None:
    moved = skipped_existed = skipped_missing = errors = 0
    for old, new in mapping.items():
        src = web_to_disk(old)
        dst = web_to_disk(new)
        if src is None or dst is None:
            continue
        if not src.exists():
            skipped_missing += 1
            continue
        if dst.exists():
            # 目标已存在：删除旧源（重复内容），保持磁盘干净
            try:
                src.unlink()
            except OSError:
                pass
            skipped_existed += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dst))
            moved += 1
        except OSError as e:
            print(f"  [error] {old} → {new}: {e}", file=sys.stderr)
            errors += 1
    print(f"  {label}: moved={moved} dst_existed={skipped_existed} "
          f"src_missing={skipped_missing} errors={errors}")


def cleanup_empty_dir(path: Path) -> None:
    if path.exists() and path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        print(f"  removed empty dir {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="真正执行；省略则 dry-run，仅展示计划")
    parser.add_argument("--show-samples", type=int, default=3,
                        help="dry-run 输出前 N 条映射示例（默认 3）")
    args = parser.parse_args()

    fanza_map = collect_fanza_mapping()
    actresses_map = collect_actresses_mapping()
    samples_map = collect_samples_mapping()

    # 合并 mapping 用于 JSON 替换
    full_map: dict[str, str] = {}
    full_map.update(fanza_map)
    full_map.update(actresses_map)
    full_map.update(samples_map)

    print("== covers reorganize plan ==")
    print(f"  FANZA monthly  : {summarize(fanza_map)}")
    print(f"  jinjier actress: {summarize(actresses_map)}")
    print(f"  samples        : {summarize(samples_map)}")
    print(f"  total mappings : {len(full_map)}")

    if args.show_samples > 0 and full_map:
        print("\n  示例（前 {} 条）:".format(args.show_samples))
        for old, new in list(full_map.items())[:args.show_samples]:
            print(f"    {old}\n      → {new}")

    if not args.apply:
        print("\n[dry-run] 加 --apply 真正执行。会先备份相关 JSON 到 .bak.<timestamp>。")
        return 0

    # ---------------- apply ----------------
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"\n== applying (backup suffix .bak.{timestamp}) ==")

    json_targets = [p for p in (RANKING_JSON, JINJIER_JSON) if p.exists()]
    if RAW_DIR.exists():
        json_targets.extend(sorted(RAW_DIR.glob("*.json")))

    for jpath in json_targets:
        bak = jpath.with_suffix(jpath.suffix + f".bak.{timestamp}")
        shutil.copy2(jpath, bak)
        data = load_json(jpath)
        replaced = replace_in_obj(data, full_map)
        save_json(jpath, data)
        print(f"  {jpath.relative_to(ROOT)}: replaced={replaced} backup={bak.name}")

    print("\n== moving files ==")
    move_files(fanza_map, "fanza")
    move_files(actresses_map, "actresses")
    move_files(samples_map, "samples")

    print("\n== cleanup ==")
    cleanup_empty_dir(COVER_DIR / "actresses")

    print("\n完成。如需回滚，使用 .bak.<timestamp> 副本恢复。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
