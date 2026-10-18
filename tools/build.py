"""在干净临时目录中调用官方 fnpack，避免将缓存打入 FPK。"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="构建 OES 风扇助手 FPK")
parser.add_argument("--fnpack", default="fnpack", help="官方 fnpack 可执行文件路径")
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="oes-fan-build-") as temporary:
    stage = Path(temporary)
    for name in ("app", "cmd", "config", "wizard"):
        shutil.copytree(root / name, stage / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    for name in ("manifest", "ICON.PNG", "ICON_256.PNG"):
        shutil.copyfile(root / name, stage / name)
    executable = shutil.which(args.fnpack) or str(Path(args.fnpack).resolve())
    subprocess.run([executable, "build", "--directory", str(stage)], cwd=root, check=True)
    package = root / "oes.fancontrol.fpk"
    if not package.exists():
        raise RuntimeError("fnpack 未生成安装包")
    version = next(line.split("=", 1)[1].strip() for line in (root / "manifest").read_text(encoding="utf-8").splitlines()
                   if line.split("=", 1)[0].strip() == "version")
    destination = root / "dist" / f"oes-fancontrol_{version}_arm.fpk"
    destination.parent.mkdir(exist_ok=True)
    shutil.copyfile(package, destination)
    print(destination)
