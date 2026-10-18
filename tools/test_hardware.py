"""短时开关实机测试，无论成功失败均恢复系统控制。"""
from pathlib import Path
import sys
import time
sys.path.insert(0, "/tmp/oes-fan-test-20261018")
from hardware import Hardware, discover, temperatures

directory = Path("/tmp/oes-fan-test-20261018/state")
directory.mkdir(exist_ok=True)
print("设备树确认：", discover(), flush=True)
print("当前温度：", temperatures(), flush=True)
hw = Hardware(directory)
try:
    hw.set(True)
    print("开启命令与 GPIO 回读一致", flush=True)
    time.sleep(3)
    soc, _ = temperatures()
    if any(v is None or v >= 60 for v in soc):
        raise RuntimeError("温度不满足短时关闭测试条件")
    hw.set(False)
    print("关闭命令与 GPIO 回读一致，仅持续 3 秒", flush=True)
    time.sleep(3)
    hw.set(True)
    print("重新开启与 GPIO 回读一致", flush=True)
finally:
    hw.close()
    print("测试结束，已执行系统控制恢复", flush=True)
