#!/bin/sh
set -e

DATA_DIR="/var/www/ranking-site/data"
SEED_DIR="/var/www/ranking-site/data-seed"
export FANZA_DATA_DIR="$DATA_DIR"
export FANZA_SEED_DATA_DIR="$SEED_DIR"

# 首次启动：若 volume 为空则从镜像内复制初始数据
if [ ! -f "$DATA_DIR/ranking.json" ] && [ -d "$SEED_DIR" ]; then
    echo "[entrypoint] 初始化数据目录..."
    cp -a "$SEED_DIR/." "$DATA_DIR/"
fi

if [ -d "$SEED_DIR" ]; then
    echo "[entrypoint] 比较并修复 2026+ 种子数据..."
    python /var/www/ranking-site/crawler/sync_seed_data.py
fi

exec supervisord -c /etc/supervisord.conf
