# -*- coding: utf-8 -*-
"""Render a 4x preview PNG of the calendar page title + grid using the
actual 16x16 glyph bitmaps from cn_font.h (what the device will draw)."""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

import re
from PIL import Image, ImageDraw, ImageFont

H_PATH = _SRC_DIR + "cn_font.h"
OUT = _TOOLS_DIR + "calendar_cn_preview.png"
S = 4  # scale
BG, TXT, DIM, LINE, ACC = (16, 18, 22), (238, 240, 242), (120, 126, 134), (52, 56, 62), (0, 200, 170)

src = open(H_PATH, encoding="utf-8").read()
blocks = re.findall(r"// (.)\n\s*\{([0-9A-Fx,]+)\},", src)
glyphs = {}
for ch, body in blocks:
    vals = [int(v, 16) for v in body.split(",")]
    glyphs[ch] = [[(vals[r*2] << 8 | vals[r*2+1]) & (0x8000 >> c) != 0 for c in range(16)] for r in range(16)]

img = Image.new("RGB", (160 * S, 128 * S), BG)
d = ImageDraw.Draw(img)
font14 = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 14 * S)

def blit(ch, x, y, col):
    for r in range(16):
        for c in range(16):
            if glyphs[ch][r][c]:
                d.rectangle([x + c * S, y + r * S, x + c * S + S - 1, y + r * S + S - 1], fill=col)

def text(s, cx, cy, col=TXT):
    w = d.textlength(s, font=font14)
    d.text((cx * S - w / 2, cy * S - 7 * S), s, font=font14, fill=col)

def title(year, month):
    yb, mb = str(year), str(month)
    wy = d.textlength(yb, font=font14) / S
    wm = d.textlength(mb, font=font14) / S
    gap = 3
    x = (160 - (wy + gap + 16 + gap + wm + gap + 16)) / 2
    text(yb, x + wy / 2, 22)
    blit("年", int(x + wy + gap) * S, 14 * S, TXT)
    x2 = x + wy + gap + 16 + gap
    text(mb, x2 + wm / 2, 22)
    blit("月", int(x2 + wm + gap) * S, 14 * S, TXT)

d.line([20 * S, 30 * S, 140 * S, 30 * S], fill=LINE, width=S)
title(2026, 9)
wd = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
import datetime
wdn = ["一", "二", "三", "四", "五", "六", "日"]
cw, gx0, gy0, rh = 22, 3, 46, 14
for i, w in enumerate(wd):
    text(w, gx0 + cw * i + cw / 2, 38, DIM)
d.line([0, gy0 * S, 160 * S, gy0 * S], fill=LINE, width=S)
for i in range(1, 7):
    d.line([int(gx0 + cw * i) * S, gy0 * S, int(gx0 + cw * i) * S, 128 * S], fill=LINE, width=S)
fd = (datetime.date(2026, 9, 1).weekday())  # Monday-first offset
total, today = 30, 9
row, col = 0, fd
for day in range(1, total + 1):
    cx, cy = gx0 + cw * col + cw / 2, gy0 + rh * row + rh / 2
    if day == today:
        d.ellipse([(cx - 5) * S, (cy - 5) * S, (cx + 5) * S, (cy + 5) * S], fill=ACC)
        text(str(day), cx, cy, BG)
    else:
        text(str(day), cx, cy, DIM if col >= 5 else TXT)
    col += 1
    if col > 6: col, row = 0, row + 1
img.save(OUT)
print("saved:", OUT)
