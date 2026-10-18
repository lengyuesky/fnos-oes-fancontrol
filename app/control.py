"""温控决策与配置校验，不直接访问硬件。"""
import math

DEFAULTS = {"mode": "auto", "on_temp": 45, "off_temp": 40,
            "disk_on": 45, "disk_off": 40, "min_on": 60}


def validate(change, current):
    if not isinstance(change, dict) or set(change) - set(DEFAULTS):
        raise ValueError("配置字段不合法")
    result = dict(current, **change)
    if result["mode"] not in ("auto", "on", "off"):
        raise ValueError("运行模式不合法")
    limits = {"on_temp": (30, 60), "off_temp": (25, 55),
              "disk_on": (35, 50), "disk_off": (25, 45), "min_on": (10, 300)}
    for key, (low, high) in limits.items():
        value = result[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{key} 必须是 {low} 到 {high} 之间的整数")
    if result["on_temp"] < result["off_temp"] + 3 or result["disk_on"] < result["disk_off"] + 3:
        raise ValueError("开启温度必须至少比关闭温度高 3℃")
    return result


class Policy:
    def __init__(self):
        self.on = True
        self.since = 0
        self.emergency = False
        self.off_until = 0

    def decide(self, cfg, soc, disks, now):
        if len(soc) < 2 or any(v is None or not math.isfinite(v) or not 0 < v < 130 for v in soc):
            return True, "温度传感器异常，保护开启"
        hottest = max(soc)
        disk = max(disks, default=0)
        if hottest >= 65 or disk >= 55:
            self.emergency = True
        elif hottest < 60 and disk < 50:
            self.emergency = False
        if self.emergency:
            return True, "过热保护：芯片≥65℃或硬盘≥55℃"
        if cfg["mode"] == "on":
            return True, "手动常开"
        if cfg["mode"] == "off" and now < self.off_until:
            return False, "临时关闭，10 分钟后恢复自动"
        if hottest >= cfg["on_temp"] or disk >= cfg["disk_on"]:
            return True, "达到开启温度"
        if self.on and now - self.since < cfg["min_on"]:
            return True, "最短运行时间保护"
        if hottest <= cfg["off_temp"] and disk <= cfg["disk_off"]:
            return False, "低于关闭温度"
        return self.on, "温度处于迟滞区间"

    def applied(self, on, now):
        if on != self.on:
            self.on = on
            self.since = now
