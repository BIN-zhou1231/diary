"""Vercel serverless 代理 — 转发到 DeepSeek API"""
import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler
from io import BytesIO

API_KEY = os.environ.get("DEEPSEEK_KEY", "")
API_BASE = "https://api.deepseek.com/anthropic/v1/messages"
MODEL = "deepseek-chat"


class handler(BaseHTTPRequestHandler):
    """Vercel Python serverless handler"""

    def do_GET(self):
        self._json(200, {"status": "ok"})

    def do_POST(self):
        body = self._read_body()
        path = self.path.rstrip("/")

        if path in ("/api/chat", "/api/chat/"):
            self._chat(body)
        elif path in ("/api/weekly-report", "/api/weekly-report/"):
            self._report(body)
        else:
            self._json(404, {"error": "not found"})

    def _chat(self, body):
        msg = body.get("message", "")
        sp = body.get("system", "")
        mt = body.get("max_tokens", 1024)
        if not msg:
            self._json(400, {"error": "no message"})
            return
        try:
            result = self._call(sp, msg, mt)
            self._json(200, {"content": result})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _report(self, body):
        entries = body.get("entries", [])
        if not entries:
            self._json(400, {"error": "no entries"})
            return
        text = "\n\n---\n\n".join(
            f"[{e.get('date','?')}] {e.get('title','')}\n"
            f"{e.get('content','')}"
            for e in entries
        )
        sp = "用中文生成情绪周报：1)情绪趋势 2)亮点 3)建议。300字内。"
        try:
            result = self._call(sp, text, 800)
            self._json(200, {"content": result})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _call(self, system, user, max_tokens=1024):
        payload = json.dumps({
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}]
        }).encode("utf-8")

        req = urllib.request.Request(API_BASE, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", API_KEY)
        req.add_header("anthropic-version", "2023-06-01")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data.get("content"), list):
                    return "".join(
                        b.get("text", "")
                        for b in data["content"]
                        if b.get("type") == "text"
                    )
                return str(data.get("content", ""))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"API error {e.code}")

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
