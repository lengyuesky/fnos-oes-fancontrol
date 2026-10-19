"""在没有官方 fnpack 的环境中生成结构等价的 FPK。

官方构建仍应使用 tools/build.py + fnpack；本脚本用于本机没有 fnpack 时
生成同样的 tar.gz 结构和 md5(app.tgz) 校验和，便于本地安装验证。
"""
import argparse
import hashlib
import io
from pathlib import Path
import shutil
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.sock", "*.log", ".DS_Store")


def add_bytes(tar, name, data, mode, mtime):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = mtime
    tar.addfile(info, io.BytesIO(data))


def add_dir(tar, name, mtime):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = mtime
    tar.addfile(info)


def add_tree(tar, source, prefix, mtime):
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        name = prefix + entry.name
        if entry.is_dir():
            add_dir(tar, name, mtime)
            add_tree(tar, entry, name + "/", mtime)
        elif entry.is_file():
            add_bytes(tar, name, entry.read_bytes(),
                      0o755 if name.startswith("cmd/") else 0o644, mtime)


def main():
    parser = argparse.ArgumentParser(description="本地生成 OES 风扇助手 FPK")
    parser.add_argument("--output", type=Path, default=root / "dist")
    args = parser.parse_args()
    version = next(line.split("=", 1)[1].strip()
                   for line in (root / "manifest").read_text().splitlines()
                   if line.split("=", 1)[0].strip() == "version")
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / f"oes-fancontrol_{version}_arm.fpk"
    mtime = int((root / "manifest").stat().st_mtime)
    with tempfile.TemporaryDirectory(prefix="oes-fan-pack-") as temporary:
        stage = Path(temporary)
        app = stage / "app"
        shutil.copytree(root / "app", app, ignore=IGNORE)
        (app / "server").mkdir(exist_ok=True)
        shutil.copytree(root / "config", app / "config", ignore=IGNORE)
        app_tgz = stage / "app.tgz"
        with tarfile.open(app_tgz, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            add_tree(tar, app, "", mtime)
        app_data = app_tgz.read_bytes()
        checksum = hashlib.md5(app_data).hexdigest()
        manifest = ((root / "manifest").read_text().rstrip()
                    + f"\nchecksum              = {checksum}\n")
        with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            add_bytes(tar, "app.tgz", app_data, 0o644, mtime)
            add_dir(tar, "cmd", mtime)
            add_tree(tar, root / "cmd", "cmd/", mtime)
            add_dir(tar, "config", mtime)
            add_tree(tar, root / "config", "config/", mtime)
            add_bytes(tar, "ICON.PNG", (root / "ICON.PNG").read_bytes(), 0o644, mtime)
            add_bytes(tar, "ICON_256.PNG", (root / "ICON_256.PNG").read_bytes(), 0o644, mtime)
            add_bytes(tar, "manifest", manifest.encode(), 0o644, mtime)
            add_dir(tar, "wizard", mtime)
    with tarfile.open(destination, "r:gz") as tar:
        packaged = hashlib.md5(tar.extractfile("app.tgz").read()).hexdigest()
    if packaged != checksum:
        raise RuntimeError("FPK 内 app.tgz 校验和不一致")
    print(destination)


if __name__ == "__main__":
    main()
