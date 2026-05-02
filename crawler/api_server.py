"""
纯 stdlib HTTP 服务，提供 /api/ensure-ranking 端点。
替代 Vite dev 插件中的 serveDataPlugin，用于生产环境。
"""
import json
import datetime
import os
import re
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from storage import RAW_DIR, RANKING_FILE, read_month_payload, sync_seed_data

ROOT = Path(__file__).resolve().parent.parent
CRAWLER_DIR = ROOT / "crawler"
UNAVAILABLE_TTL_HOURS = 24


def parse_months(value):
    months = []
    for m in (value or "").split(","):
        m = m.strip()
        if re.match(r"^\d{4}-\d{2}$", m):
            if m not in months:
                months.append(m)
    return months


def read_payload(raw_file):
    month = Path(raw_file).stem
    return read_month_payload(month, repair=True)


def parse_iso_timestamp(value):
    if not value:
        return 0
    try:
        return datetime.datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0


def decide_fetch(raw_file, force):
    if force:
        return True, "force"
    if not os.path.exists(raw_file):
        return True, "missing"
    payload = read_payload(raw_file)
    if not payload:
        return True, "corrupt"
    if not payload.get("unavailable"):
        return False, "cached"

    ts = payload.get("fetched_at")
    timestamp = parse_iso_timestamp(ts)
    age_h = (time.time() - timestamp) / 3600 if timestamp else float("inf")

    if age_h >= UNAVAILABLE_TTL_HOURS:
        return True, "retry-unavailable"
    return False, "unavailable-cooldown"


def ensure_ranking_months(months, force=False):
    sync_seed_data()
    cached = []
    cooldown = []
    crawled = []
    restored = []
    still_unavailable = []
    failed = []
    dirty = False

    for month in months:
        raw_file = RAW_DIR / f"{month}.json"
        should_fetch, reason = decide_fetch(str(raw_file), force)

        if not should_fetch:
            if reason == "unavailable-cooldown":
                cooldown.append(month)
            else:
                cached.append(month)
            continue

        try:
            result = subprocess.run(
                [sys.executable, "crawl_fanza.py", "--month", month],
                cwd=str(CRAWLER_DIR),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout)

            after = read_payload(str(raw_file))
            if after and after.get("unavailable"):
                still_unavailable.append(month)
            elif after and after.get("origin") in {"seed-repair", "repository-seed"}:
                restored.append(month)
            else:
                crawled.append(month)
            dirty = True
        except subprocess.TimeoutExpired:
            fallback = read_payload(str(raw_file))
            if fallback and not fallback.get("unavailable"):
                restored.append(month)
                dirty = True
            else:
                failed.append({"month": month, "error": "timeout"})
        except Exception as e:
            fallback = read_payload(str(raw_file))
            if fallback and not fallback.get("unavailable"):
                restored.append(month)
                dirty = True
            else:
                failed.append({"month": month, "error": str(e)[:1200]})

        time.sleep(1.5)

    if dirty:
        try:
            subprocess.run(
                [sys.executable, "aggregator.py"],
                cwd=str(CRAWLER_DIR),
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        except Exception as e:
            failed.append({"month": "aggregator", "error": str(e)[:1200]})

    ranking = None
    if RANKING_FILE.exists():
        ranking = json.loads(RANKING_FILE.read_text(encoding="utf-8"))

    return {
        "ok": len(failed) == 0,
        "cached": cached,
        "cooldown": cooldown,
        "crawled": crawled,
        "restored_from_seed": restored,
        "still_unavailable": still_unavailable,
        "failed": failed,
        "existing": cached,
        "ranking": ranking,
    }


class APIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/ensure-ranking":
            params = parse_qs(parsed.query)
            months_raw = params.get("months", [""])[0]
            months = parse_months(months_raw)
            if not months:
                self._send_json(400, {"ok": False, "error": "缺少有效月份参数"})
                return
            force = params.get("force", ["0"])[0] == "1"
            result = ensure_ranking_months(months, force=force)
            self._send_json(200 if result["ok"] else 500, result)
        elif parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        print(f"[api] {args[0]}", flush=True)


def main():
    port = int(os.environ.get("API_PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    print(f"[api] listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
