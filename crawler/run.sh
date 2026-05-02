#!/usr/bin/env bash
# 月度爬虫入口：默认抓取上个月完整月榜 → 聚合 → 写入 data/ranking.json
set -euo pipefail

cd "$(dirname "$0")"

# 若存在虚拟环境则启用
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python sync_seed_data.py
python crawl_fanza.py
python aggregator.py
