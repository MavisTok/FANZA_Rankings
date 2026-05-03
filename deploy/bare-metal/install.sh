#!/usr/bin/env bash
# 裸机/VPS 部署脚本：将仓库内容安装到 /var/www/ranking-site，
# 注册 systemd 服务与 timer，并部署 nginx 站点配置。
#
# 用法（在仓库根目录执行）：
#   sudo deploy/bare-metal/install.sh
#
# 前置条件：
#   - 已安装 nginx、python3.10+、python3-venv、nodejs >= 20、npm
#   - 系统支持 systemd（Debian/Ubuntu/CentOS 等）
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET_DIR="/var/www/ranking-site"
SERVICE_USER="www-data"
SERVICE_GROUP="www-data"

echo "[install] 仓库目录: $REPO_DIR"
echo "[install] 安装目标: $TARGET_DIR"

if [ "$(id -u)" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本" >&2
    exit 1
fi

echo "[install] 构建前端 (npm run build)..."
( cd "$REPO_DIR/web" && npm ci && npm run build )

echo "[install] 同步文件到 $TARGET_DIR..."
mkdir -p "$TARGET_DIR/web/dist" "$TARGET_DIR/data" "$TARGET_DIR/crawler"
rsync -a --delete "$REPO_DIR/web/dist/" "$TARGET_DIR/web/dist/"
rsync -a "$REPO_DIR/crawler/" "$TARGET_DIR/crawler/"

# 仅在数据目录为空时复制种子数据，避免覆盖已有抓取结果
if [ ! -f "$TARGET_DIR/data/ranking.json" ]; then
    echo "[install] 复制种子数据..."
    rsync -a "$REPO_DIR/data/" "$TARGET_DIR/data/"
fi

echo "[install] 创建 Python 虚拟环境..."
python3 -m venv "$TARGET_DIR/.venv"
"$TARGET_DIR/.venv/bin/pip" install --upgrade pip
if [ -s "$TARGET_DIR/crawler/requirements.txt" ]; then
    "$TARGET_DIR/.venv/bin/pip" install -r "$TARGET_DIR/crawler/requirements.txt"
fi

chown -R "$SERVICE_USER:$SERVICE_GROUP" "$TARGET_DIR"
chmod +x "$TARGET_DIR/crawler/run.sh"

echo "[install] 安装 systemd 单元..."
install -m 0644 "$REPO_DIR/deploy/bare-metal/fanza-rankings-api.service"   /etc/systemd/system/fanza-rankings-api.service
install -m 0644 "$REPO_DIR/deploy/bare-metal/fanza-rankings-cron.service"  /etc/systemd/system/fanza-rankings-cron.service
install -m 0644 "$REPO_DIR/deploy/bare-metal/fanza-rankings-cron.timer"    /etc/systemd/system/fanza-rankings-cron.timer

systemctl daemon-reload
systemctl enable --now fanza-rankings-api.service
systemctl enable --now fanza-rankings-cron.timer

echo "[install] 安装 nginx 站点配置..."
NGINX_CONF_DIR="/etc/nginx/conf.d"
[ -d "/etc/nginx/sites-available" ] && NGINX_CONF_DIR="/etc/nginx/sites-available"
install -m 0644 "$REPO_DIR/deploy/bare-metal/nginx.conf" "$NGINX_CONF_DIR/fanza-rankings.conf"

if [ -d "/etc/nginx/sites-enabled" ]; then
    ln -sf "$NGINX_CONF_DIR/fanza-rankings.conf" /etc/nginx/sites-enabled/fanza-rankings.conf
fi

nginx -t
systemctl reload nginx

echo "[install] 完成。访问 http://<服务器IP>/ 验证站点。"
echo "[install] 查看日志：journalctl -u fanza-rankings-api -f"
