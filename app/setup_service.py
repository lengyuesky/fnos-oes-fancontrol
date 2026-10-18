"""创建应用专用虚拟环境及可恢复的 systemd 服务。"""
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time

UNITS = ("oes-fan-hardware.service", "oes-fan-web.service")


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=40)


def prepare(target, directory, username):
    user = pwd.getpwnam(username)
    # 飞牛默认会给包用户写入源码的 ACL；特权服务代码必须仅 root 可写。
    acl = shutil.which("setfacl")
    if not acl:
        raise RuntimeError("缺少 setfacl，无法保证特权服务代码权限")
    for parent, dirs, files in os.walk(target):
        for path in [Path(parent)] + [Path(parent) / name for name in files]:
            if path.is_socket():
                continue
            if path.is_symlink():
                raise RuntimeError("应用代码目录中出现了意外软链接")
            run(acl, "-b", str(path))
            os.chown(path, 0, 0)
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
    directory.mkdir(parents=True, exist_ok=True)
    os.chown(directory, 0, user.pw_gid)
    run(acl, "-b", str(directory))
    os.chmod(directory, 0o750)
    venv = directory / "venv"
    if not (venv / "bin/python3").exists():
        uv = shutil.which("uv")
        if uv:
            run(uv, "venv", "--python", "/usr/bin/python3", str(venv))
        else:
            # 设备未提供 uv 时，使用标准库建立无第三方依赖的隔离环境。
            run("/usr/bin/python3", "-m", "venv", "--without-pip", str(venv))
    python = venv / "bin/python3"
    common = """[Unit]
Description=OES 风扇助手
After=local-fs.target
[Service]
Type=simple
Restart=on-failure
RestartSec=3
TimeoutStopSec=25
UMask=0027
Environment=PYTHONDONTWRITEBYTECODE=1
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
RestrictAddressFamilies=AF_UNIX
"""
    worker = common + f"""ReadWritePaths={directory} /sys/bus/platform/drivers/gpio-fan
ExecStart={python} {target}/hardware.py serve {directory} {user.pw_uid} {user.pw_gid}
ExecStopPost={python} {target}/hardware.py restore {directory}
"""
    web = common + f"""ReadWritePaths={directory} {target}
ExecStart={python} {target}/web.py {directory} {user.pw_uid} {user.pw_gid}
"""
    changed = False
    for name, content in zip(UNITS, (worker, web)):
        path = Path("/etc/systemd/system") / name
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
            changed = True
    if changed:
        run("systemctl", "daemon-reload")
    return python, user


def main():
    action = sys.argv[1]
    target = Path(os.environ["TRIM_APPDEST"]).resolve()
    directory = Path(os.environ["TRIM_PKGVAR"]).resolve()
    if action == "start":
        prepare(target, directory, os.environ["TRIM_USERNAME"])
        run("systemctl", "reset-failed", *UNITS, check=False)
        run("systemctl", "start", UNITS[0])
        from web import rpc
        for _ in range(30):
            try:
                if rpc(directory, {"action": "status"})["ok"]:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("硬件服务未就绪，请查看应用日志")
        run("systemctl", "start", UNITS[1])
        for _ in range(30):
            if (target / "app.sock").exists():
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("网页服务未就绪")
    elif action == "stop":
        run("systemctl", "stop", UNITS[1], check=False)
        run("systemctl", "stop", UNITS[0])
        run("/usr/bin/python3", str(target / "hardware.py"), "restore", str(directory))
        (directory / "hardware.sock").unlink(missing_ok=True)
        (target / "app.sock").unlink(missing_ok=True)
    elif action == "remove":
        run("systemctl", "stop", *reversed(UNITS), check=False)
        run("/usr/bin/python3", str(target / "hardware.py"), "restore", str(directory))
        for name in UNITS:
            (Path("/etc/systemd/system") / name).unlink(missing_ok=True)
        run("systemctl", "daemon-reload")
    elif action == "status":
        sys.exit(0 if all(run("systemctl", "is-active", name, check=False).returncode == 0 for name in UNITS) else 3)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if len(sys.argv) > 1 and sys.argv[1] == "start":
            # 启动失败时停止残留组件，触发硬件恢复。
            run("systemctl", "stop", *reversed(UNITS), check=False)
        print(f"OES 风扇助手：{error}", file=sys.stderr)
        error_file = os.environ.get("TRIM_TEMP_LOGFILE")
        if error_file:
            Path(error_file).write_text(str(error))
        sys.exit(1)
