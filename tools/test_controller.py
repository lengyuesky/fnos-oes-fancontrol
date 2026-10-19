"""验证定时关闭、永久关闭和常开间歇调速。"""
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

with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    hw = FakeHardware()
    controller = hardware.Controller(directory, hw)
    state = configure(controller, {"mode": "on", "on_speed": 60})
    assert state["config"]["on_speed"] == 60
    assert state["config"]["on_period"] == 1.0
    assert state["on"] is True
    assert state["reason"] == "手动常开 · 转速 60%"
    assert state["output_on"] is True

    restarted = hardware.Controller(directory, FakeHardware())
    assert restarted.config["mode"] == "on"
    assert restarted.config["on_speed"] == 60
    assert restarted.config["on_period"] == 1.0
    assert restarted.state["output_on"] is True

    controller.speed_since = time.monotonic() - 0.8
    controller.tick()
    assert controller.state["output_on"] is False
    assert hw.values[-1] is False
    controller.speed_since = time.monotonic() - 0.2
    controller.tick()
    assert controller.state["output_on"] is True
    assert hw.values[-1] is True

    hardware.temperatures = lambda: ([66.0, 45.0], [])
    controller.speed_since = time.monotonic() - 0.8
    controller.tick()
    assert controller.state["output_on"] is True
    assert controller.state["reason"].startswith("过热保护")
    hardware.temperatures = lambda: ([45.0, 45.0], [])
    controller.speed_since = time.monotonic() - 0.8
    controller.tick()
    assert controller.state["output_on"] is False

    state = configure(controller, {"on_period": 2.0})
    assert state["config"]["on_period"] == 2.0
    assert state["output_on"] is True
    controller.speed_since = time.monotonic() - 1.3
    controller.tick()
    assert controller.state["output_on"] is False
    controller.speed_since = time.monotonic() - 1.1
    controller.tick()
    assert controller.state["output_on"] is True
    restarted = hardware.Controller(directory, FakeHardware())
    assert restarted.config["on_period"] == 2.0

    controller.speed_since = time.monotonic() - 1.3
    controller.tick()
    assert controller.state["output_on"] is False
    before = controller.speed_since
    state = configure(controller, {"on_period": 0.5})
    assert state["config"]["on_period"] == 0.5
    assert controller.speed_since > before
    assert state["output_on"] is True
    controller.speed_since = time.monotonic() - 0.4
    controller.tick()
    assert controller.state["output_on"] is False

    state = configure(controller, {"on_period": 0.1})
    assert state["config"]["on_period"] == 0.1
    controller.speed_since = time.monotonic() - 0.08
    controller.tick()
    assert controller.state["output_on"] is False
    controller.speed_since = time.monotonic() - 0.02
    controller.tick()
    assert controller.state["output_on"] is True

    state = configure(controller, {"mode": "on", "on_speed": 100})
    assert state["config"]["on_speed"] == 100
    assert state["output_on"] is True
    controller.speed_since = time.monotonic() - 0.8
    controller.tick()
    assert controller.state["output_on"] is True

    state = configure(controller, {"mode": "on", "on_speed": 0})
    assert state["config"]["on_speed"] == 0
    assert state["output_on"] is False
    assert state["reason"] == "手动常开 · 转速 0%"
    hardware.temperatures = lambda: ([66.0, 45.0], [])
    controller.tick()
    assert controller.state["output_on"] is True
    hardware.temperatures = lambda: ([45.0, 45.0], [])
    controller.tick()
    assert controller.state["output_on"] is False

print("关闭时长、永久关闭与常开调速测试通过")
