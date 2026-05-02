# Stage 1: 构建前端
FROM node:20-alpine AS builder
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: 生产镜像
FROM python:3.12-alpine

ENV API_PORT=8080 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    FANZA_DATA_DIR=/var/www/ranking-site/data \
    FANZA_SEED_DATA_DIR=/var/www/ranking-site/data-seed

RUN apk add --no-cache bash nginx supervisor tzdata

# 创建部署目录
RUN mkdir -p /var/www/ranking-site/web/dist \
             /var/www/ranking-site/data \
             /var/www/ranking-site/data-seed \
             /var/www/ranking-site/crawler \
             /var/log/nginx \
             /run/nginx \
             /var/spool/cron/crontabs

# 前端静态文件
COPY --from=builder /build/dist/ /var/www/ranking-site/web/dist/

# 爬虫脚本
COPY crawler/ /var/www/ranking-site/crawler/

RUN if [ -s /var/www/ranking-site/crawler/requirements.txt ]; then \
      pip install --no-cache-dir -r /var/www/ranking-site/crawler/requirements.txt; \
    fi

# 种子数据（首次启动无 volume 时通过 entrypoint 复制）
COPY data/ /var/www/ranking-site/data-seed/

# nginx 配置
COPY deploy/nginx.conf /etc/nginx/http.d/default.conf

# supervisord 配置
COPY deploy/supervisord.conf /etc/supervisord.conf

# entrypoint
COPY deploy/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# cron 定时任务
RUN echo '0 3 1 * * /var/www/ranking-site/crawler/run.sh >> /dev/stdout 2>&1' \
      > /var/spool/cron/crontabs/root \
    && chmod 600 /var/spool/cron/crontabs/root

# 确保脚本可执行
RUN chmod +x /var/www/ranking-site/crawler/run.sh

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
