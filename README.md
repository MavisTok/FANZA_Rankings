# FANZA Rankings

FANZA 月度／年度榜单的抓取、聚合与展示项目。前端使用 Vue 3 + Vite，后端使用 Python 标准库 HTTP 服务，数据通过定时任务在每月 1 日凌晨自动更新。

---

## 部署方式

按使用场景从易到难，提供四种部署方式，可任选其一。

### 方式一：Docker Compose（推荐）

适合大多数 VPS／本地环境。容器内完成前端构建、Python 依赖安装、nginx + cron 配置。

```bash
docker compose up --build -d
```

启动后访问 <http://127.0.0.1:5174/>。

数据目录挂载在 named volume `fanza-rankings_fanza-data`，首次启动会从镜像内 `data/` 复制种子数据进去；之后爬虫更新会直接写入该 volume。

### 方式二：Docker Compose（预构建前端，低内存 VPS）

如果 VPS 内存较小（< 1 GB），无法在容器里跑 `npm run build`，可以在本机预先构建好前端产物，再用精简版镜像启动。

```bash
# 1. 本机构建前端（仅一次或前端有变更时执行）
cd web && npm ci && npm run build && cd ..

# 2. 使用预构建版 compose 启动
docker compose -f docker-compose.prebuilt.yml up --build -d
```

对应文件：[Dockerfile.prebuilt](Dockerfile.prebuilt)、[docker-compose.prebuilt.yml](docker-compose.prebuilt.yml)。

### 方式三：裸机／VPS（systemd + nginx + cron）

不依赖 Docker，直接用系统 nginx 提供静态文件、用 systemd 守护 Python API、用 systemd timer 触发月度抓取。

前置依赖：`nginx`、`python3.10+`、`python3-venv`、`nodejs >= 20`、`npm`、`rsync`。

```bash
sudo deploy/bare-metal/install.sh
```

脚本会自动完成：

- 在 [web/](web/) 内执行 `npm ci && npm run build`
- 同步前端产物、爬虫脚本、种子数据到 `/var/www/ranking-site/`
- 创建 Python venv 并安装 [crawler/requirements.txt](crawler/requirements.txt)
- 注册 systemd 服务 `fanza-rankings-api.service` 与定时器 `fanza-rankings-cron.timer`
- 部署 nginx 站点配置到 `/etc/nginx/conf.d/fanza-rankings.conf`

常用运维命令：

```bash
systemctl status fanza-rankings-api          # 查看 API 服务
journalctl -u fanza-rankings-api -f          # 实时日志
systemctl list-timers | grep fanza-rankings  # 查看下次抓取时间
systemctl start fanza-rankings-cron.service  # 手动触发一次抓取
```

相关文件位于 [deploy/bare-metal/](deploy/bare-metal/)。

### 方式四：本地开发模式（无 Docker）

适合修改前端／爬虫脚本时本地调试。

```bash
# 终端 1：前端 dev server（内置 /api 代理与 /data 访问）
cd web && npm install && npm run dev

# 终端 2（可选）：手动触发爬虫
cd crawler && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python crawl_fanza.py --month 2026-04
python aggregator.py
```

Vite dev server 默认监听 <http://127.0.0.1:5173/>，已在 [web/vite.config.js](web/vite.config.js) 中内置 `/api/ensure-ranking` 与 `/data/` 处理逻辑，无需另起 Python API。

---

## 数据自愈机制

启动和读写数据时会比较运行目录与镜像／仓库内的种子数据：

- `2026-01` 之后月份如果在线拉取失败或 FANZA 返回空榜，会自动从仓库 [data/raw/](data/raw/) 的种子数据回填。
- 如果运行目录里的月份文件缺失、损坏或比种子数据更不完整，会用种子数据修复。
- 成功在线抓取到非空月榜时会覆盖保存该月数据，保证每月 1 号补全上个月后以最新完整数据为准。
- 完整月份会在月度 JSON 中写入 `complete_month: true`，聚合结果中也会输出 `months_complete`。

## 月度自动抓取

| 部署方式             | 触发机制        | 时间（Asia/Shanghai） |
| -------------------- | --------------- | --------------------- |
| 方式一／二（Docker） | 容器内 `crond`  | 每月 1 日 03:00       |
| 方式三（裸机）       | `systemd timer` | 每月 1 日 03:00       |
| 方式四（本地开发）   | 手动执行        | —                     |

实际执行的脚本均为 [crawler/run.sh](crawler/run.sh)：先同步种子数据，再抓取上个月并覆盖保存，最后重新聚合 [data/ranking.json](data/ranking.json)。

## 手动触发某月抓取

页面切换到 FANZA 月度或年度榜单时，如果本地缺少对应月份，会调用：

```text
/api/ensure-ranking?months=YYYY-MM
```

也可以在容器内（或裸机部署目录）手动执行：

```bash
python crawler/crawl_fanza.py --month 2026-04
python crawler/aggregator.py
```

## 数据资源致谢

感谢 [jinjier.art/sql](https://jinjier.art/sql) 提供的数据资源支持，本项目引用了其公开数据资源用于榜单数据补全与校验。

## 使用 GitHub Actions 自动采集并写回仓库

如果你希望不用常驻服务器，也可以直接让 GitHub Actions 每月自动执行爬虫，并把最新 `data/` 提交回仓库。

### 1) 新增工作流文件

仓库已提供示例工作流：`.github/workflows/update-fanza-ranking.yml`。

主要行为：

- 每月末（UTC 的 28~31 日 19:00）触发，并在脚本中校验 **Asia/Shanghai 每月 1 日** 才真正执行。
- 支持 `workflow_dispatch` 手动触发。
- 自动计算“上个月（YYYY-MM）”，执行 `sync_seed_data.py`，并对该月份抓取失败时最多重试 3 次，成功即停止重试并聚合。
- 若 `data/` 发生变化，则自动 `commit` 并 `push` 到当前分支。

### 2) 打开仓库 Actions 权限

在 GitHub 仓库页面检查：

- `Settings -> Actions -> General`：允许工作流运行。
- `Settings -> Actions -> General -> Workflow permissions`：选择 **Read and write permissions**（需要写回仓库）。

### 3) 可选：限制触发分支

如果只希望在 `main` 运行，可在工作流的 `on` 或 job 条件中增加分支限制；当前示例默认在工作流所在分支可执行。

### 4) 手动测试

在 `Actions` 页面找到 `Update FANZA Rankings`，点击 `Run workflow`。

首次测试建议关注：

- 依赖安装是否成功（`crawler/requirements.txt`）。
- FANZA 抓取是否返回有效数据。
- 日志中是否出现 `No data changes`（说明本次无新增或无差异）。

### 5) 常见问题

- **为什么不是“每月 1 日 03:00”直接写在 cron？**  
  GitHub Actions cron 使用 UTC，且不支持时区参数。示例采用“UTC 月末窗口触发 + 上海时区 gate”的方式，确保只在上海时区每月 1 日执行一次。

- **为什么没有提交变更？**  
  只有仓库文件产生 diff 才会提交；若抓取结果与现有数据一致，会输出 `No data changes`。

- **会不会并发重复写入？**  
  示例配置了 `concurrency`，避免同一时间重复执行同一工作流。
