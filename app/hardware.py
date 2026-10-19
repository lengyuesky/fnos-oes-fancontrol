"""仅使用已核对设备树的 OES 风扇 GPIO，不猜测引脚。"""
import glob
import json
import math
import os
from pathlib import Path
import signal
import socket
import socketserver
import struct
import subprocess
import sys
import time
from collections import deque
from control import DEFAULTS, Policy, duty_on, validate

DRIVER = Path("/sys/bus/platform/drivers/gpio-fan")
DEVICE = Path("/sys/bus/platform/devices/gpio-fan")
DT = Path("/sys/firmware/devicetree/base")
SERVICE = "pwm-fancontrol.service"


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=15)


def atomic(path, data, mode=0o600):
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, mode)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def discover():
    if b"onethingcloud,oes" not in (DT / "compatible").read_bytes().split(b"\0"):
        raise RuntimeError("当前设备不是已验证的 OneThing Cloud OES")
    raw = (DT / "gpio-fan/gpios").read_bytes()
    if len(raw) != 12:
        raise RuntimeError("不支持的风扇 GPIO 设备树格式")
    phandle, line, flags = struct.unpack(">III", raw)
    speeds = (DT / "gpio-fan/gpio-fan,speed-map").read_bytes()
    if len(speeds) != 16 or struct.unpack(">IIII", speeds) != (0, 0, 3000, 1):
        raise RuntimeError("风扇并非已验证的两档硬件")
    if flags not in (0, 1):
        raise RuntimeError("不支持的 GPIO 电气标志")
    chips = []
    for node in Path("/sys/bus/gpio/devices").glob("gpiochip*"):
        try:
            if (node / "of_node/phandle").read_bytes() == struct.pack(">I", phandle):
                chips.append("/dev/" + node.name)
        except OSError:
            pass
    if len(chips) != 1:
        raise RuntimeError("无法唯一定位风扇 GPIO 控制器")
    return chips[0], line, flags


def restore(directory):
    record = directory / "original.json"
    if not record.exists():
        return
    data = json.loads(record.read_text())
    if data["bound"] and not (DEVICE / "driver").exists():
        (DRIVER / "bind").write_text("gpio-fan")
    if data["active"]:
        run("systemctl", "restart", SERVICE)
    record.unlink()
    print("已恢复原驱动和系统风扇服务", flush=True)


class Hardware:
    def __init__(self, directory):
        import fcntl
        self.fd = None
        self.directory = directory
        self.chip, self.line, self.flags = discover()
        restore(directory)
        active = run("systemctl", "is-active", SERVICE, check=False).returncode == 0
        bound = (DEVICE / "driver").exists()
        if not bound:
            raise RuntimeError("系统风扇驱动未绑定，拒绝覆盖其他控制程序")
        atomic(directory / "original.json", {"active": active, "bound": bound})
        try:
            if active:
                run("systemctl", "stop", SERVICE)
            (DRIVER / "unbind").write_text("gpio-fan")
            request = bytearray(364)
            struct.pack_into("=I", request, 0, self.line)
            struct.pack_into("=I", request, 256, 2 | (4 if self.flags & 1 else 0))
            request[260] = 1
            request[324:324 + 14] = b"oes-fancontrol"
            struct.pack_into("=I", request, 356, 1)
            with open(self.chip, "rb", buffering=0) as chip:
                fcntl.ioctl(chip, 0xC16CB403, request, True)
            self.fd = struct.unpack_from("=i", request, 360)[0]
            self.set(True)
        except BaseException:
            self.close()
            raise

    def set(self, on):
        import fcntl
        data = bytearray(64)
        data[0] = int(on)
        fcntl.ioctl(self.fd, 0xC040B409, data, True)
        actual = bytearray(64)
        fcntl.ioctl(self.fd, 0xC040B408, actual, True)
        if actual[0] != int(on):
            raise RuntimeError("GPIO 输出回读不一致")

    def close(self):
        if self.fd is not None:
            try:
                self.set(True)
            finally:
                os.close(self.fd)
                self.fd = None
        restore(self.directory)


def temperatures():
    values = {}
    for node in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            name = (node / "type").read_text().strip()
            if name in ("cpu-thermal", "ddr-thermal"):
                value = int((node / "temp").read_text()) / 1000
                values[name] = value if 0 < value < 130 else None
        except (ValueError, OSError):
            pass
    disks = []
    for node in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (node / "name").read_text().strip() in ("drivetemp", "nvme"):
                for sensor in node.glob("temp*_input"):
                    value = int(sensor.read_text()) / 1000
                    if 0 < value < 100:
                        disks.append(value)
        except (ValueError, OSError):
            pass
    return [values.get("cpu-thermal"), values.get("ddr-thermal")], disks


class Controller:
    def __init__(self, directory, hw):
        self.directory, self.hw = directory, hw
        self.config = dict(DEFAULTS)
        file = directory / "settings.json"
        if file.exists():
            self.config = validate(json.loads(file.read_text()), self.config)
        self.policy = Policy()
        if self.config["mode"] == "off":
            if self.config["off_permanent"]:
                self.policy.off_until = math.inf
            else:
                # 临时关闭不跨应用重启；永久关闭保留。
                self.config["mode"] = "auto"
                self.config["off_permanent"] = False
                atomic(directory / "settings.json", self.config)
        self.policy.since = time.monotonic()
        self.speed_since = time.monotonic()
        self.output_on = None
        self.history = deque(maxlen=720)
        self.events = deque(maxlen=30)
        self.last_history = 0
        self.state = {}
        self.tick()

    def tick(self):
        now = time.monotonic()
        if (self.config["mode"] == "off" and not self.config["off_permanent"]
                and now >= self.policy.off_until):
            self.config["mode"] = "auto"
            atomic(self.directory / "settings.json", self.config)
        soc, disks = temperatures()
        on, reason = self.policy.decide(self.config, soc, disks, now)
        if on != self.policy.on or reason != self.state.get("reason"):
            event = {"time": int(time.time()), "on": on, "reason": reason}
            self.events.append(event)
            print(json.dumps(event, ensure_ascii=False), flush=True)
        self.policy.applied(on, now)
        self.state = {"cpu": soc[0], "ddr": soc[1], "disks": disks,
                      "on": on, "output_on": self.output_on, "reason": reason,
                      "config": self.config, "emergency": self.policy.emergency,
                      "off_remaining": (max(0, int(self.policy.off_until - now))
                                        if self.config["mode"] == "off" and not self.config["off_permanent"] else 0),
                      "chip": self.hw.chip, "line": self.hw.line,
                      "time": int(time.time()), "model": "OneThing Cloud OES · A311D"}
        self.pulse()
        if now - self.last_history >= 60:
            self.history.append({"time": int(time.time()), "cpu": soc[0], "ddr": soc[1], "on": on})
            self.last_history = now

    def pulse(self):
        if not self.state:
            return
        output_on = self.state["on"]
        if self.state["reason"].startswith("手动常开") and self.config["on_speed"] < 100:
            output_on = duty_on(time.monotonic(), self.speed_since,
                                self.config["on_speed"], self.config["on_period"])
        self.state["output_on"] = output_on
        if output_on != self.output_on:
            self.hw.set(output_on)
            self.output_on = output_on

    def request(self, data):
        if data == {"action": "status"}:
            return dict(self.state, history=list(self.history), events=list(self.events))
        if isinstance(data, dict) and set(data) == {"action", "settings"} and data["action"] == "configure":
            previous = self.config
            config = validate(data["settings"], self.config)
            changed = set(data["settings"])
            atomic(self.directory / "settings.json", config)
            self.config = config
            if (config["mode"] == "on"
                    and (previous["mode"] != "on" or previous["on_speed"] != config["on_speed"]
                         or previous["on_period"] != config["on_period"])):
                self.speed_since = time.monotonic()
            if config["mode"] == "off":
                if config["off_permanent"]:
                    self.policy.off_until = math.inf
                elif changed & {"mode", "off_minutes", "off_permanent"}:
                    self.policy.off_until = time.monotonic() + config["off_minutes"] * 60
            else:
                self.policy.off_until = 0
            self.tick()
            return self.request({"action": "status"})
        raise ValueError("不支持的请求")


def serve(directory, uid, gid):
    import fcntl
    lock = open(directory / "hardware.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    hw = Hardware(directory)
    server = None
    try:
        controller = Controller(directory, hw)

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(3)
                _, peer_uid, _ = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if peer_uid not in (0, uid):
                    return
                try:
                    raw = self.rfile.readline(4097)
                    if len(raw) > 4096:
                        raise ValueError("请求过大")
                    response = {"ok": True, "data": controller.request(json.loads(raw))}
                except (ValueError, OSError) as error:
                    response = {"ok": False, "error": str(error)}
                self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode())

        path = directory / "hardware.sock"
        path.unlink(missing_ok=True)
        server = socketserver.UnixStreamServer(str(path), Handler)
        os.chown(path, 0, gid)
        os.chmod(path, 0o660)
        server.timeout = 0.01
        alive = True

        def stop(*_):
            nonlocal alive
            alive = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        last_tick = 0
        last_pulse = 0
        while alive:
            now = time.monotonic()
            if now - last_tick >= 2:
                controller.tick()
                last_tick = now
            if now - last_pulse >= 0.01:
                controller.pulse()
                last_pulse = now
            server.handle_request()
    finally:
        if server:
            server.server_close()
        hw.close()


if __name__ == "__main__":
    directory = Path(sys.argv[2])
    if sys.argv[1] == "restore":
        restore(directory)
    elif sys.argv[1] == "probe":
        print(discover())
        print(temperatures())
    else:
        serve(directory, int(sys.argv[3]), int(sys.argv[4]))
