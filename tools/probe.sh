#!/bin/sh
# 只读检测：不加载驱动、不导出 GPIO、不写入风扇接口。
set -u
printf '\n=== 系统与权限 ===\n'
id
uname -a
cat /etc/os-release 2>/dev/null
printf '\n=== 设备树型号 ===\n'
for p in /sys/firmware/devicetree/base/model /sys/firmware/devicetree/base/compatible; do
    if [ -r "$p" ]; then printf '%s: ' "$p"; tr '\000' '\n' < "$p"; fi
done
printf '\n=== 风扇设备树 ===\n'
find /sys/firmware/devicetree/base -maxdepth 5 -iname '*fan*' -print 2>/dev/null
for d in /sys/firmware/devicetree/base/*fan*; do
    [ -d "$d" ] || continue
    for p in "$d"/compatible "$d"/status; do
        if [ -r "$p" ]; then printf '%s: ' "$p"; tr '\000' '\n' < "$p"; fi
    done
    for p in "$d"/gpios "$d"/gpio-fan,speed-map "$d"/pwms; do
        if [ -r "$p" ]; then printf '%s: ' "$p"; od -An -tx1 "$p"; fi
    done
done
printf '\n=== 硬件监控接口 ===\n'
for d in /sys/class/hwmon/hwmon*; do
    [ -d "$d" ] || continue
    printf '\n%s -> %s\n' "$d" "$(readlink -f "$d")"
    for p in "$d"/name "$d"/temp*_input "$d"/temp*_label "$d"/fan*_input "$d"/fan*_target "$d"/pwm*; do
        if [ -f "$p" ] && [ -r "$p" ]; then printf '%s: ' "$p"; cat "$p"; fi
    done
done
printf '\n=== 温控接口 ===\n'
for d in /sys/class/thermal/thermal_zone* /sys/class/thermal/cooling_device*; do
    [ -d "$d" ] || continue
    for p in "$d"/type "$d"/temp "$d"/cur_state "$d"/max_state "$d"/policy; do
        if [ -r "$p" ]; then printf '%s: ' "$p"; cat "$p"; fi
    done
done
printf '\n=== GPIO 工具与驱动 ===\n'
command -v gpioinfo gpioset gpioget python3 uv appcenter-cli 2>/dev/null
ls -l /dev/gpiochip* /sys/class/gpio/gpiochip* 2>/dev/null
lsmod | head -60
if command -v gpioinfo >/dev/null 2>&1; then gpioinfo 2>&1; fi
printf '\n=== 已有风扇服务 ===\n'
systemctl list-units --all --no-pager 2>/dev/null | grep -Ei 'fan|thermal' || true
systemctl list-unit-files --no-pager 2>/dev/null | grep -Ei 'fan|thermal' || true
ps -eo pid,user,args | grep -Ei '[f]anctl|[g]pioset|[f]ancontrol|[t]hermald' || true
printf '\n=== 应用目录 ===\n'
ls /var/apps 2>/dev/null
printf '\n=== 检测结束 ===\n'
