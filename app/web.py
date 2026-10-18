"""无特权网页服务：仅通过受限本地套接字请求硬件操作。"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import sys
from urllib.parse import urlsplit

PREFIX = "/app/oes-fancontrol"
TOKEN = secrets.token_urlsafe(32)
PAGE = Path(__file__).with_name("www") / "index.html"


def rpc(directory, data):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(directory / "hardware.sock"))
        client.sendall((json.dumps(data) + "\n").encode())
        with client.makefile("rb") as stream:
            raw = stream.readline(262144)
        return json.loads(raw)


class Server(socketserver.ThreadingMixIn, HTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = 0


class Handler(BaseHTTPRequestHandler):
    server_version = "OESFan/1.0"

    def setup(self):
        self.request.settimeout(8)
        super().setup()

    def log_message(self, *_):
        pass

    def send(self, code, data, mime="application/json; charset=utf-8"):
        raw = data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def authenticated(self):
        if self.headers.get("X-Trim-Isadmin", "").lower() != "true" or not self.headers.get("X-Trim-Userid", "").isdigit():
            self.send(403, {"error": "请通过飞牛管理员账号打开此应用"})
            return False
        return True

    def do_GET(self):
        if not self.authenticated():
            return
        path = urlsplit(self.path).path.rstrip("/")
        if path == PREFIX:
            return self.send(200, PAGE.read_text(), "text/html; charset=utf-8")
        if path == PREFIX + "/api/status":
            try:
                response = rpc(self.server.directory, {"action": "status"})
                response["csrf"] = TOKEN
                return self.send(200, response)
            except (OSError, ValueError):
                return self.send(503, {"error": "硬件控制服务暂不可用，系统将尝试恢复控制"})
        self.send(404, {"error": "页面不存在"})

    def do_POST(self):
        if not self.authenticated():
            return
        if urlsplit(self.path).path != PREFIX + "/api/settings":
            return self.send(404, {"error": "接口不存在"})
        if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), TOKEN):
            return self.send(403, {"error": "页面校验失败，请刷新重试"})
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.send(403, {"error": "拒绝跨站请求"})
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("需要 JSON 请求")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                raise ValueError("请求长度不合法")
            settings = json.loads(self.rfile.read(length))
            response = rpc(self.server.directory, {"action": "configure", "settings": settings})
            self.send(200 if response["ok"] else 400, response)
        except ValueError as error:
            self.send(400, {"error": str(error)})
        except OSError:
            self.send(503, {"error": "硬件控制服务暂不可用"})


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    uid, gid = int(sys.argv[2]), int(sys.argv[3])
    path = Path(__file__).with_name("app.sock")
    path.unlink(missing_ok=True)
    server = Server(str(path), Handler)
    server.directory = directory
    os.chown(path, uid, gid)
    os.chmod(path, 0o600)
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    server.serve_forever()
