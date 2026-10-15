# -*- coding: utf-8 -*-
"""生成期货行情面板图标：icon.png(预览) + app.ico(多尺寸)。
风格：深蓝黑圆角背景 + 红/绿K线(红涨绿跌) + 青色趋势折线 + 底部成交量柱。
"""
import math
from PIL import Image, ImageDraw, ImageFilter

S = 256  # 主尺寸


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vertical_gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        c = lerp(top, bottom, t)
        for x in range(w):
            px[x, y] = c
    return img


def draw_icon():
    # 1) 垂直渐变背景（深蓝 -> 墨黑）
    base = vertical_gradient((S, S), (24, 34, 62), (8, 12, 26))

    # 圆角遮罩
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, S - 1, S - 1], radius=48, fill=255)
    img = Image.new("RGB", (S, S), (0, 0, 0))
    img.paste(base, (0, 0), mask)

    d = ImageDraw.Draw(img)

    # 2) K线区参数
    x0, x1 = 46, 210          # 横向范围
    y_top, y_bot = 44, 182    # 纵向范围（K线主体）
    n = 6                     # K线根数
    bar_w = 16
    gap = (x1 - x0 - n * bar_w) / (n - 1)
    RED, GREEN = (233, 84, 78), (52, 199, 132)

    # 每根K线: (开盘, 收盘, 最高, 最低) 相对 y_bot..y_top
    seq = [
        (0.72, 0.58, 0.80, 0.50),   # 阴
        (0.58, 0.66, 0.74, 0.52),   # 阳
        (0.66, 0.50, 0.70, 0.44),   # 阴
        (0.50, 0.62, 0.68, 0.46),   # 阳
        (0.62, 0.78, 0.84, 0.60),   # 阳
        (0.78, 0.88, 0.92, 0.76),   # 阳 上冲
    ]
    closes = []
    for i in range(n):
        o, c, h, l = seq[i]
        cx = x0 + i * (bar_w + gap)
        def Y(v): return y_bot - (v - 0.0) * (y_bot - y_top)
        color = RED if c >= o else GREEN
        # 影线
        d.line([cx + bar_w / 2, Y(h), cx + bar_w / 2, Y(l)], fill=color, width=3)
        # 实体
        top = Y(max(o, c)); bot = Y(min(o, c))
        d.rounded_rectangle([cx, top, cx + bar_w, bot], radius=2, fill=color)
        closes.append((cx + bar_w / 2, Y(c)))

    # 3) 青色趋势折线
    pts = closes
    d.line(pts, fill=(79, 197, 255), width=4, joint="curve")
    # 端点小圆点
    ex, ey = pts[-1]
    d.ellipse([ex - 5, ey - 5, ex + 5, ey + 5], fill=(255, 255, 255))

    # 4) 底部成交量柱（低亮）
    vbase = 214
    vh = 22
    for i in range(n):
        cx = x0 + i * (bar_w + gap)
        o, c, h, l = seq[i]
        color = RED if c >= o else GREEN
        val = 0.25 + 0.75 * (i / (n - 1))
        bh = vh * val
        d.rectangle([cx + 1, vbase - bh, cx + bar_w - 1, vbase], fill=(color[0], color[1], color[2], 0) if False else color)
    # 成交量柱降透明度：用带 alpha 覆盖
    overlay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(n):
        cx = x0 + i * (bar_w + gap)
        o, c, h, l = seq[i]
        color = RED if c >= o else GREEN
        val = 0.25 + 0.75 * (i / (n - 1))
        bh = vh * val
        od.rectangle([cx + 1, vbase - bh, cx + bar_w - 1, vbase], fill=color + (150,))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)

    return img.convert("RGB")


img = draw_icon()
img.save("icon.png")
# 多尺寸 ico
img.save("app.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon.png + app.ico 已生成")
