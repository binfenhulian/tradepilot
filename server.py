"""HTTP 服务：标准库 http.server。

提供：持仓 CRUD、行情查询、投资偏好、辩论 SSE 流，并托管前端静态文件。
运行：python3 server.py  然后浏览器打开 http://localhost:8000
"""

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import market
import storage
import config
import debate
import logbook

_ROOT = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_ROOT, "static")
PORT = int(os.environ.get("PORT", "8000"))

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _portfolio():
    """持仓 + 实时行情 + 盈亏 + 迷你走势。"""
    rows = []
    total_mv = 0.0
    total_cost = 0.0
    total_day_pnl = 0.0
    for h in storage.list_holdings():
        row = {"ticker": h["ticker"], "shares": h["shares"], "cost": h["cost"]}
        try:
            q = market.get_quote(h["ticker"])
            spark = market.get_sparkline(h["ticker"], rng="3mo")
            price = q["price"] or 0
            mv = price * h["shares"]
            cost_val = h["cost"] * h["shares"]
            pnl = mv - cost_val
            day_pnl = (q["change"] or 0) * h["shares"]
            total_mv += mv
            total_cost += cost_val
            total_day_pnl += day_pnl
            row.update({
                "name": q["name"],
                "price": price,
                "changePct": q["changePct"],
                "marketStateLabel": q.get("marketStateLabel"),
                "quoteTime": q.get("quoteTime"),
                "extended": q.get("extended"),
                "marketValue": round(mv, 2),
                "pnl": round(pnl, 2),
                "pnlPct": round(pnl / cost_val * 100, 2) if cost_val else 0,
                "dayPnl": round(day_pnl, 2),
                "spark": spark["points"],
            })
        except Exception as e:
            row.update({"error": str(e)})
        rows.append(row)
    # 市场时段对所有美股相同：自己按美东时间算，再取任一行的行情时间戳
    session_label = market.us_market_session()[0]
    quote_time = next((r.get("quoteTime") for r in rows if r.get("quoteTime")), None)
    summary = {
        "marketValue": round(total_mv, 2),
        "cost": round(total_cost, 2),
        "pnl": round(total_mv - total_cost, 2),
        "pnlPct": round((total_mv - total_cost) / total_cost * 100, 2) if total_cost else 0,
        "dayPnl": round(total_day_pnl, 2),
        "session": session_label,
        "quoteTime": quote_time,
    }
    return {"holdings": rows, "summary": summary}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静默，避免刷屏

    # ---------- 工具 ----------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _serve_static(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        fpath = os.path.normpath(os.path.join(_STATIC, path.lstrip("/")))
        if not fpath.startswith(_STATIC) or not os.path.isfile(fpath):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(fpath)[1]
        with open(fpath, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        try:
            if path == "/api/config":
                cfg = config.load_config()
                return self._send_json({
                    "keys": config.status(),
                    "roles": cfg["roles"],
                    "models": cfg["models"],
                })
            if path == "/api/portfolio":
                return self._send_json(_portfolio())
            if path == "/api/profile":
                return self._send_json(storage.get_profile())
            if path == "/api/quote":
                ticker = (qs.get("ticker", [""])[0]).strip()
                if not ticker:
                    return self._send_json({"error": "缺少 ticker"}, 400)
                ctx = market.build_market_context(ticker)
                spark = market.get_sparkline(ticker, rng="6mo")
                return self._send_json({
                    "quote": ctx["quote"],
                    "indicators": ctx["indicators"],
                    "spark": spark["points"],
                })
            if path == "/api/logs":
                return self._send_json({"sessions": logbook.list_sessions()})
            if path == "/api/log":
                fname = (qs.get("file", [""])[0]).strip()
                s = logbook.read_session(fname)
                if s is None:
                    return self._send_json({"error": "日志不存在"}, 404)
                return self._send_json(s)
            if path == "/api/debate":
                topic = (qs.get("topic", [""])[0]).strip()
                ticker = (qs.get("ticker", [""])[0]).strip()
                conv = (qs.get("conv", [""])[0]).strip()
                return self._stream_debate(topic, ticker, conv)
            # 否则当静态文件
            return self._serve_static(path)
        except Exception as e:
            traceback.print_exc()
            return self._send_json({"error": str(e)}, 500)

    # ---------- POST ----------
    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        try:
            body = self._read_body()
            if path == "/api/holdings":
                item = storage.upsert_holding(
                    body.get("ticker"), body.get("shares"), body.get("cost")
                )
                return self._send_json({"ok": True, "item": item})
            if path == "/api/holdings/delete":
                ok = storage.delete_holding(body.get("ticker"))
                return self._send_json({"ok": ok})
            if path == "/api/profile":
                p = storage.set_profile(body.get("preferences", ""))
                return self._send_json({"ok": True, "profile": p})
            if path == "/api/roles":
                new = config.save_roles(body.get("roles", {}))
                return self._send_json({"ok": True, "roles": new})
            return self._send_json({"error": "未知接口"}, 404)
        except Exception as e:
            traceback.print_exc()
            return self._send_json({"error": str(e)}, 400)

    # ---------- SSE 辩论 ----------
    def _stream_debate(self, topic, ticker, conv=""):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(obj):
            chunk = f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
            self.wfile.write(chunk)
            self.wfile.flush()

        try:
            emit({"type": "start", "topic": topic, "ticker": ticker.upper()})
            for ev in debate.run_debate(topic, ticker, conv_id=conv or None):
                if "error" in ev:
                    emit({"type": "error", "message": ev["error"]})
                else:
                    emit({"type": "message", **ev})
            emit({"type": "done"})
        except Exception as e:
            try:
                emit({"type": "error", "message": str(e)})
            except Exception:
                pass


def main():
    os.chdir(_ROOT)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"📈 股票辩论室已启动： http://localhost:{PORT}")
    print(f"   API key 状态：{config.status()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()
