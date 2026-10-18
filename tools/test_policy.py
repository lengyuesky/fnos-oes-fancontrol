"""验证过热保护、临时关闭、迟滞和配置拒绝条件。"""
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from control import DEFAULTS, Policy, validate

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
p = Policy()
p.on = False
assert not p.decide(DEFAULTS, [43, 43], [], 100)[0]
p.applied(True, 100)
assert p.decide(DEFAULTS, [38, 38], [], 110)[0]
assert not p.decide(DEFAULTS, [38, 38], [], 161)[0]
for change in ({"mode": "bad"}, {"on_temp": 40}, {"on_temp": True},
               {"min_on": 0}, {"script": "anything"}, {"off_temp": 50}):
    try:
        validate(change, DEFAULTS)
        raise AssertionError("非法配置被接受")
    except ValueError:
        pass
assert validate({"on_temp": 50, "off_temp": 45}, DEFAULTS)["on_temp"] == 50
print("温控边界测试通过")
