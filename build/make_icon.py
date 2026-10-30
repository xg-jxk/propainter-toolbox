# -*- coding: utf-8 -*-
"""生成 app/resources/app.ico（打包与窗口图标共用）。

跑法： .venv\\Scripts\\python.exe build\\make_icon.py
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "app", "resources", "app.ico")


def main(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角方块 + 竖向渐变的蓝色
    radius = int(size * 0.22)
    for y in range(size):
        t = y / float(size - 1)
        r = int(47 + (24 - 47) * t)
        g = int(111 + (66 - 111) * t)
        b = int(235 + (180 - 235) * t)
        d.line([(0, y), (size, y)], fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.putalpha(mask)

    # 白色"擦除"造型：一个圆环 + 一道斜杠
    d = ImageDraw.Draw(img)
    cx, cy = size * 0.5, size * 0.46
    ring = size * 0.26
    width = max(6, int(size * 0.065))
    d.ellipse([cx - ring, cy - ring, cx + ring, cy + ring], outline=(255, 255, 255, 255), width=width)
    for i in range(-width, width + 1):
        off = i
        d.line([(cx - ring * 0.72 + off, cy + ring * 0.74),
                (cx + ring * 0.74 + off, cy - ring * 0.72)],
               fill=(255, 255, 255, 255), width=3)

    # 底部三个"帧"点，点明是视频
    for k in (-1, 0, 1):
        x = cx + k * size * 0.11
        y = size * 0.855
        rr = size * 0.022
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(255, 255, 255, 235))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("OK", OUT, os.path.getsize(OUT))


if __name__ == "__main__":
    main()
