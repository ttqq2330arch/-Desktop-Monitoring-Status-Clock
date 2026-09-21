# -*- coding: utf-8 -*-
"""
时钟页整页 PC 预览：复刻固件 drawFlipCard / blitHalf 的 alpha 混合渲染，
读 _clock_masks.json（gen_clock_font.py 导出的瘦高字模），输出每套字体一张
完整 HH:MM:SS 时钟页，纵向拼成对比图。用于视觉验收，不影响固件。
"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

import json
import os
from PIL import Image, ImageDraw, ImageFont

TOOLS = _TOOLS_DIR
JS = json.load(open(TOOLS + "_clock_masks.json", encoding="utf-8"))
FC_GW, FC_H = JS["FC_GW"], JS["FC_H"]
FONTS = JS["fonts"]
MASKS = JS["masks"]            # [font][digit][row][col]，a 值 0..15

SCR_W, SCR_H = 160, 128
# 与固件 main.cpp 一致的配色与布局
C_BG       = (14, 14, 19)
C_CARD_TOP = (36, 36, 46)
C_CARD_BOT = (23, 23, 30)
C_CARD_DIG = [(255, 79, 129), (255, 176, 0), (255, 244, 92),
              (92, 255, 138), (79, 195, 255), (179, 136, 255)]
C_FOLD     = (8, 8, 12)
C_DATE     = (142, 142, 147)
C_COLON    = (142, 142, 147)
C_DIM      = (115, 115, 130)
C_ACC      = (77, 208, 196)

FC_W    = FC_GW + 2            # 20（卡片宽 = 字模宽 + 2）
FC_HALF = 29
FC_HB   = 29
FC_Y    = 26
FC_X    = [9, 31, 59, 81, 109, 131]   # 适配 FC_W=20 的居中布局


def blend(bg, fg, a):
    t = a / 15.0
    return tuple(int(bg[i] * (1 - t) + fg[i] * t) for i in range(3))


def render_page(font_idx, digits):
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    d = ImageDraw.Draw(img)
    for i in range(6):
        x = FC_X[i]
        digit = digits[i]
        cTop, cBot, cDig = C_CARD_TOP, C_CARD_BOT, C_CARD_DIG[i]
        # 卡片背景（上 20 行圆角块 + 下 22 行圆角块 + 中缝抹平）
        d.rounded_rectangle([x, FC_Y, x + FC_W, FC_Y + FC_HALF], radius=3, fill=cTop)
        d.rounded_rectangle([x, FC_Y + FC_HALF, x + FC_W, FC_Y + FC_HALF + FC_HB], radius=3, fill=cBot)
        d.rectangle([x, FC_Y + FC_HALF - 4, x + FC_W, FC_Y + FC_HALF + 3], fill=cTop)
        # 数字（alpha 混合卡面色）：上半 row<20 用 cTop，下半用 cBot
        m = MASKS[font_idx][digit]
        ix, topY, botY = x + 1, FC_Y, FC_Y + FC_HALF
        for row in range(FC_H):
            for col in range(FC_GW):
                a = m[row][col]
                if a:
                    bg = cTop if row < FC_HALF else cBot
                    img.putpixel((ix + col, topY + row), blend(bg, cDig, a))
        # 中缝线（覆盖在 row=botY）
        d.line([x + 1, botY, x + FC_W - 1, botY], fill=C_FOLD)
    # 组间冒号点
    cy = FC_Y + FC_H // 2
    for cx in (FC_X[1] + FC_W + 3, FC_X[3] + FC_W + 3):
        d.rectangle([cx, cy - 6, cx + 2, cy - 4], fill=C_COLON)
        d.rectangle([cx, cy + 4, cx + 2, cy + 6], fill=C_COLON)
    # 日期
    fnt = ImageFont.truetype(TOOLS + "fonts/Nunito_wght.ttf", 14)
    ds = "2026-09-20"
    d.text(((SCR_W - d.textlength(ds, font=fnt)) / 2, 92), ds, font=fnt, fill=C_DATE)
    # 分页点（3 个，时钟页=第 2 个高亮）
    doty, gap, r, n, cur = 112, 8, 2, 3, 1
    x0 = (SCR_W - (n - 1) * gap) / 2
    for p in range(n):
        cxx = x0 + p * gap
        d.ellipse([cxx - r, doty - r, cxx + r, doty + r], fill=C_ACC if p == cur else C_DIM)
    return img


def main():
    digits = [1, 2, 3, 4, 5, 6]
    gap = 6
    H = SCR_H * len(FONTS) + gap * (len(FONTS) - 1) + 16
    big = Image.new("RGB", (SCR_W, H), C_BG)
    y = 12
    lbl = ImageFont.truetype(TOOLS + "fonts/Nunito_wght.ttf", 10)
    for fi in range(len(FONTS)):
        pg = render_page(fi, digits)
        big.paste(pg, (0, y))
        ImageDraw.Draw(big).text((4, y - 11), FONTS[fi], font=lbl, fill=C_DATE)
        y += SCR_H + gap
    out = TOOLS + "clock_page_preview.png"
    big.save(out)
    print("saved", out, big.size)


if __name__ == "__main__":
    main()
