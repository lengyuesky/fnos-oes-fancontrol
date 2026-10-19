"""验证定时关闭到点恢复、永久关闭跨重启保留。"""
import sys
import tempfile
import time
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import hardware

hardware.temperatures = lambda: ([45.0, 45.0], [])


class FakeHardware:
    chip = "/dev/gpiochip0"
    line = 45

    def __init__(self):
        self.values = []

    def set(self, on):
        self.values.append(on)


def configure(controller, settings):
    return controller.request({"action": "configure", "settings": settings})


with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    hw = FakeHardware()
    controller = hardware.Controller(directory, hw)
    assert controller.config["mode"] == "auto"

    state = configure(controller, {"mode": "off", "off_minutes": 30})
    assert state["config"]["mode"] == "off"
    assert state["config"]["off_minutes"] == 30
    assert state["config"]["off_permanent"] is False
    assert 29 * 60 < state["off_remaining"] <= 30 * 60
    assert hw.values[-1] is False

    controller.policy.off_until = time.monotonic() - 1
    controller.tick()
    assert controller.config["mode"] == "auto"
    assert controller.state["on"] is True

    state = configure(controller, {"mode": "off", "off_permanent": True})
    assert state["config"]["off_permanent"] is True
    assert state["off_remaining"] == 0
    assert hw.values[-1] is False

    restarted = hardware.Controller(directory, FakeHardware())
    assert restarted.config["mode"] == "off"
    assert restarted.config["off_permanent"] is True
    assert restarted.state["on"] is False

    hardware.temperatures = lambda: ([66.0, 45.0], [])
    restarted.tick()
    assert restarted.state["on"] is True
    hardware.temperatures = lambda: ([45.0, 45.0], [])
    restarted.tick()
    assert restarted.state["on"] is False

    configure(controller, {"mode": "off", "off_permanent": False, "off_minutes": 10})
    restarted = hardware.Controller(directory, FakeHardware())
    assert restarted.config["mode"] == "auto"
    assert restarted.config["off_permanent"] is False
    assert restarted.state["on"] is True

print("关闭时长与永久关闭测试通过")
