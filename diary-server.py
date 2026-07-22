#!/usr/bin/env python
"""日记 AI 代理 — 部署到 Render/Railway 等云平台，API key 通过环境变量传入"""
import json
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

API_KEY = os.environ.get("DEEPSEEK_KEY", "")
API_BASE = "https://api.deepseek.com/anthropic/v1/messages"
MODEL = "deepseek-chat"
PORT = int(os.environ.get("PORT", 8787))


class ProxyHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/chat":
            self._handle_chat()
        elif path == "/api/weekly-report":
            self._handle_weekly_report()
        else:
            self._send_json(404, {"error": "not found"})

    def _call_claude(self, system_prompt, user_message, max_tokens=1024):
        if not API_KEY:
            raise RuntimeError("DEEPSEEK_KEY env not set")

        payload = json.dumps({
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}]
        }).encode("utf-8")

        req = urllib.request.Request(API_BASE, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", API_KEY)
        req.add_header("anthropic-version", "2023-06-01")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data.get("content", [])
                if isinstance(content, list):
                    return "".join(
                        block.get("text", "")
                        for block in content
                        if block.get("type") == "text"
                    )
                return str(content)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"API error ({e.code})")
        except Exception as e:
            raise RuntimeError(str(e))

    def _handle_chat(self):
        try:
            body = self._read_body()
            user_message = body.get("message", "")
            system_prompt = body.get("system", "")
            max_tokens = body.get("max_tokens", 1024)
            if not user_message:
                self._send_json(400, {"error": "no message"})
                return
            result = self._call_claude(system_prompt, user_message, max_tokens)
            self._send_json(200, {"content": result})
        except RuntimeError as e:
            self._send_json(500, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_weekly_report(self):
        try:
            body = self._read_body()
            entries = body.get("entries", [])
            if not entries:
                self._send_json(400, {"error": "no entries"})
                return
            diary_text = "\n\n---\n\n".join(
                f"【{e.get('date','?')}】{e.get('title','')}\n"
                f"Mood: {e.get('mood','')}  Weather: {e.get('weather','')}\n"
                f"{e.get('content','')}"
                for e in entries
            )
            sp = (
                "你是一位温暖的心理分析师。根据用户一周的日记，生成简洁的情绪周报。"
                "包含：1) 本周情绪趋势 2) 亮点时刻 3) 一个温柔的建议。用中文，300字以内。"
            )
            result = self._call_claude(sp, diary_text, 800)
            self._send_json(200, {"content": result})
        except RuntimeError as e:
            self._send_json(500, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def log_message(self, format, *args):
        print(f"[proxy] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"Proxy running on port {PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
