"""验证已安装应用的鉴权、设置校验与进程异常恢复。"""
import http.client
import json
from pathlib import Path
import socket
import subprocess
import time

target = Path("/var/apps/oes.fancontrol/target")


class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(6)
        self.sock.connect(str(target / "app.sock"))


def request(method="GET", data=None, admin=True, csrf=None):
    client = Connection("localhost")
    headers = {"X-Trim-Isadmin": "true", "X-Trim-Userid": "1000"} if admin else {}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if data is not None:
        headers["Content-Type"] = "application/json"
    client.request(method, "/app/oes-fancontrol/api/" + ("status" if method == "GET" else "settings"),
                   json.dumps(data) if data is not None else None, headers)
    response = client.getresponse()
    result = response.status, json.loads(response.read())
    client.close()
    return result


assert request(admin=False)[0] == 403
status, state = request()
assert status == 200 and state["ok"]
token = state["csrf"]
before = state["data"]["config"]
assert request("POST", {"mode": "off"})[0] == 403
assert request("POST", {"off_temp": 55}, csrf=token)[0] == 400
assert request()[1]["data"]["config"] == before
assert request("POST", {"mode": "on"}, csrf=token)[1]["data"]["on"]
state = request("POST", {"mode": "off"}, csrf=token)[1]["data"]
assert not state["on"] and state["off_remaining"] > 590
assert request("POST", {"mode": "auto"}, csrf=token)[1]["data"]["config"]["mode"] == "auto"
print("鉴权、CSRF、非法配置拒绝、手动开关和自动模式验证通过", flush=True)
old_pid = subprocess.check_output(["systemctl", "show", "oes-fan-hardware", "-p", "MainPID", "--value"], text=True).strip()
subprocess.run(["systemctl", "kill", "--signal=SIGKILL", "--kill-whom=main", "oes-fan-hardware"], check=True)
for _ in range(30):
    time.sleep(.5)
    try:
        current = request()[1]
        pid = subprocess.check_output(["systemctl", "show", "oes-fan-hardware", "-p", "MainPID", "--value"], text=True).strip()
        if current.get("ok") and pid != old_pid and pid != "0":
            print("硬件进程异常退出后，原驱动恢复并自动重新接管；新 PID：", pid, flush=True)
            break
    except (OSError, ValueError):
        pass
else:
    raise RuntimeError("硬件服务未自动恢复")
print(json.dumps(request()[1]["data"], ensure_ascii=False), flush=True)
