# -*- coding: utf-8 -*-
"""翻页时钟配色方案对比预览（按 main.cpp 的布局常量 1:1 绘制，放大 2x 输出）"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

from PIL import Image, ImageDraw, ImageFont

SCR_W, SCR_H = 160, 128
FC_W, FC_H, FC_HALF = 22, 42, 20
FC_X = [4, 28, 57, 81, 110, 134]
FC_Y = 26
SCALE = 2

def font_of(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

F_DIG = font_of("C:/Windows/Fonts/arialbd.ttf", 30)   # 卡片数字 ~26px 高
F_DATE = font_of("C:/Windows/Fonts/arialbd.ttf", 13)  # 日期
F_UP = font_of("C:/Windows/Fonts/arial.ttf", 8)       # uptime

THEMES = [
    ("A  现状 · 近白", {
        "bg": (0x0E, 0x0E, 0x13), "card_t": (0x26, 0x26, 0x31), "card_b": (0x1A, 0x1A, 0x22),
        "card_l": (0x3C, 0x3C, 0x48), "fold": (0x08, 0x08, 0x0C),
        "dig": (0xEE, 0xEE, 0xF2), "date": (0x73, 0x73, 0x82), "up": (0x2A, 0x2A, 0x34),
        "group": False}),
    ("B  琥珀 · 复古", {
        "bg": (0x12, 0x0E, 0x0A), "card_t": (0x33, 0x26, 0x18), "card_b": (0x24, 0x1A, 0x10),
        "card_l": (0x59, 0x44, 0x28), "fold": (0x0C, 0x08, 0x05),
        "dig": (0xFF, 0xB3, 0x3D), "date": (0xC9, 0x8A, 0x3C), "up": (0x4A, 0x36, 0x20),
        "group": False}),
    ("C  青绿 · 冷调", {
        "bg": (0x0A, 0x11, 0x12), "card_t": (0x1B, 0x30, 0x33), "card_b": (0x12, 0x22, 0x24),
        "card_l": (0x2E, 0x52, 0x56), "fold": (0x05, 0x0A, 0x0B),
        "dig": (0x4D, 0xE0, 0xD0), "date": (0x3F, 0x9A, 0x92), "up": (0x22, 0x38, 0x3A),
        "group": False}),
    ("D  三色分组", {
        "bg": (0x0E, 0x0E, 0x13), "card_t": (0x26, 0x26, 0x31), "card_b": (0x1A, 0x1A, 0x22),
        "card_l": (0x3C, 0x3C, 0x48), "fold": (0x08, 0x08, 0x0C),
        "dig": (0xEE, 0xEE, 0xF2), "date": (0x73, 0x73, 0x82), "up": (0x2A, 0x2A, 0x34),
        "group": True}),
]

GROUP_COL = [(0x4D, 0xE0, 0xD0), (0x4D, 0xE0, 0xD0),    # HH 青绿
             (0xFF, 0xB3, 0x3D), (0xFF, 0xB3, 0x3D),    # MM 琥珀
             (0xB0, 0x86, 0xF0), (0xB0, 0x86, 0xF0)]    # SS 紫

DIGITS = "105243"          # 示例时间 10:52:43
DATE = "2026-09-10"
UP = "UP 3D 07:12"


def rr(d, box, r, fill, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill,
                        outline=outline, width=width)


def draw_panel(t):
    c = t[1]
    img = Image.new("RGB", (SCR_W, SCR_H), c["bg"])
    d = ImageDraw.Draw(img)

    for i, x in enumerate(FC_X):
        col = GROUP_COL[i] if c["group"] else c["dig"]
        # 上下半卡面
        rr(d, [x, FC_Y, x + FC_W - 1, FC_Y + FC_HALF - 1], 3, c["card_t"])
        rr(d, [x, FC_Y + FC_HALF, x + FC_W - 1, FC_Y + FC_H - 1], 3, c["card_b"])
        d.rectangle([x, FC_Y + FC_HALF - 4, x + FC_W - 1, FC_Y + FC_HALF - 1],
                    fill=c["card_t"])   # 补平上半圆角接缝
        # 数字（跨中缝，居中）
        cx, cy = x + FC_W / 2, FC_Y + FC_H / 2
        d.text((cx, cy), DIGITS[i], font=F_DIG, fill=col, anchor="mm")
        # 中缝 + 描边
        d.line([x + 1, FC_Y + FC_HALF, x + FC_W - 2, FC_Y + FC_HALF], fill=c["fold"])
        rr(d, [x, FC_Y, x + FC_W - 1, FC_Y + FC_H - 1], 3, None, outline=c["card_l"])

    # 组间冒号点
    cy = FC_Y + FC_H // 2
    for k in (0, 1):
        cxx = (FC_X[1] + FC_W + 3) if k == 0 else (FC_X[3] + FC_W + 3)
        d.rectangle([cxx, cy - 6, cxx + 1, cy - 5], fill=c["date"])
        d.rectangle([cxx, cy + 4, cxx + 1, cy + 5], fill=c["date"])

    d.text((SCR_W / 2, 92), DATE, font=F_DATE, fill=c["date"], anchor="mm")
    d.text((SCR_W / 2, 112), UP, font=F_UP, fill=c["up"], anchor="mm")
    return img


GAP = 10
panels = [draw_panel(t) for t in THEMES]
W = SCR_W * len(panels) + GAP * (len(panels) - 1)
out = Image.new("RGB", (W, SCR_H), (0x22, 0x22, 0x28))
for i, p in enumerate(panels):
    out.paste(p, (i * (SCR_W + GAP), 0))

out = out.resize((W * SCALE, SCR_H * SCALE), Image.NEAREST)
out.save(_TOOLS_DIR + "clock_themes.png")
print("saved clock_themes.png", out.size)
