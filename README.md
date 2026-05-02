# FANZA Rankings

## Docker 一键启动

```bash
docker compose up --build
```

启动后打开：

```text
http://127.0.0.1:5174/
```

数据目录挂载在 Docker named volume `fanza-rankings_fanza-data`。首次启动会把镜像内的 `data/` 种子数据复制进去，之后爬虫更新会直接写入该 volume。

启动和读写数据时会比较运行目录与镜像内的仓库种子数据：

- `2026-01` 之后月份如果在线拉取失败或 FANZA 返回空榜，会自动从仓库 `data/raw/` 的种子数据回填。
- 如果运行 volume 里的月份文件缺失、损坏或比种子数据更不完整，会用种子数据修复。
- 成功在线抓取到非空月榜时会覆盖保存该月数据，保证每月 1 号补全上个月后以最新完整数据为准。
- 完整月份会在月度 JSON 中写入 `complete_month: true`，聚合结果中也会输出 `months_complete`。

## 月度自动抓取

容器内 cron 会在每月 1 日凌晨 3 点（`Asia/Shanghai`）运行：

```bash
/var/www/ranking-site/crawler/run.sh
```

该脚本默认抓取上个月完整 FANZA 月榜，然后重生成 `/var/www/ranking-site/data/ranking.json`。

月度任务会先执行种子数据同步，再抓取上个月并覆盖保存，最后重新聚合。

## 手动触发某月抓取

页面切换到 FANZA 月度或年度榜单时，如果本地缺少对应月份，会调用：

```text
/api/ensure-ranking?months=YYYY-MM
```

也可以在容器内手动执行：

```bash
python /var/www/ranking-site/crawler/crawl_fanza.py --month 2026-04
python /var/www/ranking-site/crawler/aggregator.py
```
