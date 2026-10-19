"""验证过热保护、临时/永久关闭、常开调速、迟滞和配置拒绝条件。"""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from control import DEFAULTS, Policy, duty_on, validate

p = Policy()
p.since = 0
assert p.decide(DEFAULTS, [46, 42], [], 100)[0]
assert not p.decide(DEFAULTS, [39, 38], [], 100)[0]
assert p.decide(DEFAULTS, [None, 38], [], 100)[0]
assert p.decide(DEFAULTS, [0, 38], [], 100)[0]
off = dict(DEFAULTS, mode="off")
p.off_until = 1000
assert not p.decide(off, [45, 45], [], 100)[0]
assert p.decide(off, [65, 45], [], 100)[0]
assert p.decide(off, [62, 45], [], 100)[0]
assert not p.decide(off, [59, 45], [], 100)[0]
assert p.decide(off, [45, 45], [55], 100)[0]
off_permanent = dict(DEFAULTS, mode="off", off_permanent=True)
p = Policy()
assert not p.decide(off_permanent, [45, 45], [], 10000)[0]
assert p.decide(off_permanent, [66, 45], [], 10000)[0]
assert p.decide(off_permanent, [None, 45], [], 10000)[0]
p = Policy()
assert p.decide(dict(DEFAULTS, mode="on", on_speed=60), [45, 45], [], 100) == (True, "手动常开 · 转速 60%")
assert p.decide(dict(DEFAULTS, mode="on", on_speed=0), [45, 45], [], 100) == (True, "手动常开 · 转速 0%")
assert p.decide(dict(DEFAULTS, mode="on"), [45, 45], [], 100) == (True, "手动常开")
assert duty_on(0, 0, 100) and duty_on(0.99, 0, 100)
assert not duty_on(0, 0, 0)
assert duty_on(0, 0, 60) and duty_on(0.59, 0, 60)
assert not duty_on(0.6, 0, 60) and not duty_on(0.99, 0, 60)
assert duty_on(1.0, 0, 60)
assert duty_on(0.39, 0, 40) and not duty_on(0.4, 0, 40)
assert duty_on(0, 0, 50, 0.1) and duty_on(0.049, 0, 50, 0.1)
assert not duty_on(0.05, 0, 50, 0.1) and not duty_on(0.099, 0, 50, 0.1)
assert duty_on(0.1, 0, 50, 0.1)
assert duty_on(0, 0, 60, 2.0) and duty_on(1.19, 0, 60, 2.0)
assert not duty_on(1.2, 0, 60, 2.0) and duty_on(2.0, 0, 60, 2.0)
assert duty_on(0, 0, 60, 10.0) and not duty_on(6.0, 0, 60, 10.0)
p = Policy()
p.on = False
assert not p.decide(DEFAULTS, [43, 43], [], 100)[0]
p.applied(True, 100)
assert p.decide(DEFAULTS, [38, 38], [], 110)[0]
assert not p.decide(DEFAULTS, [38, 38], [], 161)[0]
for change in ({"mode": "bad"}, {"on_temp": 40}, {"on_temp": True},
               {"min_on": 0}, {"script": "anything"}, {"off_temp": 50},
               {"off_minutes": 0}, {"off_minutes": 1441},
               {"off_permanent": 1}, {"off_minutes": "30"},
               {"on_speed": -1}, {"on_speed": 101},
               {"on_speed": True}, {"on_speed": "60"},
               {"on_period": 0.09}, {"on_period": 10.1},
               {"on_period": True}, {"on_period": "1"}):
    try:
        validate(change, DEFAULTS)
        raise AssertionError("非法配置被接受")
    except ValueError:
        pass
assert validate({"on_temp": 50, "off_temp": 45}, DEFAULTS)["on_temp"] == 50
assert validate({"off_minutes": 30}, DEFAULTS)["off_minutes"] == 30
assert validate({"on_speed": 0}, DEFAULTS)["on_speed"] == 0
assert validate({"on_speed": 60}, DEFAULTS)["on_speed"] == 60
assert validate({"on_speed": 100}, DEFAULTS)["on_speed"] == 100
assert validate({"on_period": 0.1}, DEFAULTS)["on_period"] == 0.1
assert validate({"on_period": 1}, DEFAULTS)["on_period"] == 1.0
assert validate({"on_period": 10}, DEFAULTS)["on_period"] == 10.0
permanent = validate({"mode": "off", "off_permanent": True}, DEFAULTS)
assert permanent["off_permanent"] is True
assert validate({"mode": "on"}, permanent)["off_permanent"] is False
print("温控边界测试通过")
