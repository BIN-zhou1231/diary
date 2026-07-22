"""
日记 AI 后端代理
转发请求到 DeepSeek Anthropic 端点，解决前端 CORS 和安全问题
启动: python diary-server.py
端口: 8787
"""
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

API_KEY = "sk-05c68f0152734aabbd3098897f54167d"
API_BASE = "https://api.deepseek.com/anthropic/v1/messages"
MODEL = "deepseek-chat"  # DeepSeek 的 Anthropic 兼容模型

PORT = 8787


class ProxyHandler(BaseHTTPRequestHandler):
    """Claude API 代理处理器"""

    def _send_json(self, status: int, data: dict) -> None:
        """发送 JSON 响应"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        """读取请求体 JSON"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        """处理 GET 请求（健康检查等）"""
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"status": "ok", "model": MODEL})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:
        """CORS 预检"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        """处理 POST 请求"""
        path = urlparse(self.path).path

        if path == "/api/chat":
            self._handle_chat()
        elif path == "/api/weekly-report":
            self._handle_weekly_report()
        elif path == "/api/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def _call_claude(self, system_prompt: str, user_message: str, max_tokens: int = 1024) -> str:
        """调用 DeepSeek Anthropic 兼容 API"""
        payload = json.dumps({
            "model": MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_message}
            ]
        }).encode("utf-8")

        req = urllib.request.Request(API_BASE, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-api-key", API_KEY)
        req.add_header("anthropic-version", "2023-06-01")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Anthropic 格式响应
                content = data.get("content", [])
                if isinstance(content, list):
                    return "".join(
                        block.get("text", "")
                        for block in content
                        if block.get("type") == "text"
                    )
                return str(content)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API 错误 ({e.code}): {error_body[:300]}")
        except Exception as e:
            raise RuntimeError(f"请求失败: {str(e)}")

    def _handle_chat(self) -> None:
        """处理普通聊天请求"""
        try:
            body = self._read_body()
            user_message = body.get("message", "")
            system_prompt = body.get("system", "你是一个有帮助的助手。请用中文回答。")
            max_tokens = body.get("max_tokens", 1024)

            if not user_message:
                self._send_json(400, {"error": "no message"})
                return

            result = self._call_claude(system_prompt, user_message, max_tokens)
            self._send_json(200, {"content": result})

        except RuntimeError as e:
            self._send_json(500, {"error": str(e)})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"error": f"internal error: {e}"})

    def _handle_weekly_report(self) -> None:
        """处理周报生成请求"""
        try:
            body = self._read_body()
            entries = body.get("entries", [])  # [{date, title, content, mood, weather}, ...]

            if not entries:
                self._send_json(400, {"error": "缺少日记数据"})
                return

            # 拼接日记内容
            diary_text = "\n\n---\n\n".join(
                f"【{e.get('date', '?')}】{e.get('title', '无标题')}\n"
                f"心情: {e.get('mood', '未知')}  天气: {e.get('weather', '未知')}\n"
                f"{e.get('content', '')}"
                for e in entries
            )

            system_prompt = (
                "你是一位温暖的心理分析师和写作教练。根据用户一周的日记，生成一份简洁的情绪周报。"
                "包含：1) 本周情绪趋势（一句话概括）2) 亮点时刻 3) 一个温柔的建议。"
                "用温暖、鼓励的语气，控制在 300 字以内。"
            )

            result = self._call_claude(system_prompt, diary_text, max_tokens=800)
            self._send_json(200, {"content": result})

        except RuntimeError as e:
            self._send_json(500, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": f"服务器内部错误: {str(e)}"})

    def log_message(self, format, *args) -> None:
        """自定义日志格式"""
        print(f"[diary-server] {args[0]}")


def main() -> None:
    """启动代理服务器"""
    server = HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(f"Diary AI backend started -> http://127.0.0.1:{PORT}")
    print(f"   API: http://127.0.0.1:{PORT}/api/chat")
    print(f"   Health: http://127.0.0.1:{PORT}/api/health")
    print(f"   Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDiary AI backend stopped")
        server.shutdown()


if __name__ == "__main__":
    main()
