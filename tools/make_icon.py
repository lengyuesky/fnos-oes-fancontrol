"""用标准库绘制应用图标，输出透明 PNG。"""
import math
from pathlib import Path
import struct
import zlib

root = Path(__file__).resolve().parents[1]


def png(path, size):
    data = bytearray()
    for y in range(size):
        data.append(0)
        for x in range(size):
            px, py = (x + .5) / size * 2 - 1, (y + .5) / size * 2 - 1
            r = math.hypot(px, py)
            inside = abs(px) <= .72 or abs(py) <= .72 or math.hypot(abs(px) - .72, abs(py) - .72) <= .25
            if not inside:
                data.extend((0, 0, 0, 0))
                continue
            color = (29, 91, 65, 255)
            angle = math.atan2(py, px)
            blade = (angle + r * 2.5) % (math.pi * 2 / 3)
            if .20 < r < .66 and .15 < blade < 1.3:
                color = (215, 240, 219, 255)
            if r < .145:
                color = (236, 249, 238, 255)
            if .755 < r < .78:
                color = (82, 140, 105, 255)
            data.extend(color)

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))

    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    path.write_bytes(raw + chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b""))


for name, size in [("ICON.PNG", 64), ("ICON_256.PNG", 256),
                   ("app/ui/images/icon_64.png", 64), ("app/ui/images/icon_256.png", 256)]:
    png(root / name, size)
