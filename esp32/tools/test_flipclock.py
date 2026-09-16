# -*- coding: utf-8 -*-
"""Host-side self test + preview for the flip-clock page.

1. Assert card layout math (positions, gaps, colon dots, vertical budget).
2. Render a 4x preview PNG: static frame + mid-flip frames (p=0.25 / p=0.75),
   mirroring drawFlipCard()'s two-phase composition.
"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

from PIL import Image, ImageDraw, ImageFont

SCR_W, SCR_H = 160, 128
FC_W, FC_H, FC_HALF, FC_Y = 22, 42, 20, 26
FC_GW = FC_W - 2
FC_X = [4, 28, 57, 81, 110, 134]
S = 4

C_BG    = (0x0E, 0x0E, 0x13)
C_CARD_T= (0x26, 0x26, 0x31)
C_CARD_B= (0x1A, 0x1A, 0x22)
C_CARD_L= (0x3C, 0x3C, 0x48)
C_FOLD  = (0x08, 0x08, 0x0C)
C_TXT   = (0xEE, 0xEE, 0xF2)
C_DIM   = (0x73, 0x73, 0x82)
C_ACC   = (0x4D, 0xD0, 0xC4)

# ---------- 1. layout assertions ----------
for i, x in enumerate(FC_X):
    assert x >= 0 and x + FC_W <= SCR_W, f"card {i} out of screen: {x}"
gaps = [FC_X[i + 1] - (FC_X[i] + FC_W) for i in range(5)]
assert gaps == [2, 7, 2, 7, 2], f"unexpected gaps: {gaps}"
assert FC_Y + FC_H + 1 <= SCR_H, "cards exceed screen height"
colon_x = [FC_X[1] + FC_W + 3, FC_X[3] + FC_W + 3]
for k, cx in enumerate(colon_x):
    nxt = FC_X[2] if k == 0 else FC_X[4]
    prv_end = FC_X[1] + FC_W if k == 0 else FC_X[3] + FC_W
    assert cx > prv_end and cx + 2 < nxt, f"colon {k} overlaps card: {cx}"
print("layout OK: cards x=%s gaps=%s colon x=%s card bottom=%d"
      % (FC_X, gaps, colon_x, FC_Y + FC_H))

# ---------- 2. render ----------
font26 = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 26)
font12 = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 13)
font10 = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 10)

def glyph_half(d, bottom):
    """Render digit d into a FC_GW x FC_H card face, return its top/bottom half."""
    img = Image.new("RGB", (FC_GW, FC_H), C_CARD_B if bottom else C_CARD_T)
    dr = ImageDraw.Draw(img)
    w = dr.textlength(str(d), font=font26)
    dr.text(((FC_GW - w) / 2, (FC_H - 26) / 2 - 3), str(d), font=font26, fill=C_TXT)
    y0 = FC_HALF if bottom else 0
    return img.crop((0, y0, FC_GW, y0 + FC_HALF))

TOP = {d: glyph_half(d, False) for d in range(10)}
BOT = {d: glyph_half(d, True) for d in range(10)}

def blit_half(canvas, dx, dy, dst_h, src):
    if dst_h <= 0:
        return
    canvas.paste(src.resize((FC_GW, dst_h), Image.NEAREST), (dx, dy))

def draw_card(canvas, i, cur, prev=None, p=1.0):
    x, ix = FC_X[i], FC_X[i] + 1
    topY, botY = FC_Y + 1, FC_Y + 1 + FC_HALF
    d = canvas if isinstance(canvas, Image.Image) else canvas
    dr = ImageDraw.Draw(d)
    dr.rounded_rectangle([x, FC_Y, x + FC_W - 1, FC_Y + FC_H - 1], radius=3, fill=C_CARD_B)
    if p >= 1.0 or prev is None:
        blit_half(d, ix, topY, FC_HALF, TOP[cur])
        blit_half(d, ix, botY, FC_HALF, BOT[cur])
    elif p < 0.5:
        blit_half(d, ix, topY, FC_HALF, TOP[cur])
        blit_half(d, ix, botY, FC_HALF, BOT[prev])
        blit_half(d, ix, topY + FC_HALF - int(FC_HALF * (1 - p * 2)),
                  int(FC_HALF * (1 - p * 2)), TOP[prev])
    else:
        blit_half(d, ix, topY, FC_HALF, TOP[cur])
        blit_half(d, ix, botY, FC_HALF, BOT[prev])
        blit_half(d, ix, botY, int(FC_HALF * ((p - 0.5) * 2)), BOT[cur])
    dr.line([x + 1, botY, x + FC_W - 2, botY], fill=C_FOLD)
    dr.rounded_rectangle([x, FC_Y, x + FC_W - 1, FC_Y + FC_H - 1], radius=3, outline=C_CARD_L)

def draw_page(digits, flip_idx=None, prev=None, p=1.0):
    img = Image.new("RGB", (SCR_W, SCR_H), C_BG)
    dr = ImageDraw.Draw(img)
    dr.ellipse([SCR_W // 2 - 2, 4, SCR_W // 2 + 2, 8], fill=C_ACC)
    for i, dg in enumerate(digits):
        if flip_idx is not None and i == flip_idx:
            draw_card(img, i, dg, prev, p)
        else:
            draw_card(img, i, dg)
    cy = FC_Y + FC_H // 2
    for k in range(2):
        cx = colon_x[k]
        dr.rectangle([cx, cy - 6, cx + 1, cy - 5], fill=C_DIM)
        dr.rectangle([cx, cy + 4, cx + 1, cy + 5], fill=C_DIM)
    def ctext(s, y, font, col):
        w = dr.textlength(s, font=font)
        dr.text(((SCR_W - w) / 2, y), s, font=font, fill=col)
    ctext("THU", 82, font12, C_ACC)
    ctext("2026-09-10", 100, font12, C_DIM)
    ctext("up 3h 12m", 116, font10, C_CARD_L)
    return img

frames = [
    draw_page([1, 0, 2, 9, 3, 5]),
    draw_page([1, 0, 2, 9, 3, 5], flip_idx=5, prev=4, p=0.25),
    draw_page([1, 0, 2, 9, 3, 5], flip_idx=5, prev=4, p=0.75),
]
out = Image.new("RGB", (SCR_W * len(frames), SCR_H), C_BG)
for i, f in enumerate(frames):
    out.paste(f, (SCR_W * i, 0))
big = out.resize((SCR_W * len(frames) * S, SCR_H * S), Image.NEAREST)
OUT = _TOOLS_DIR + "flipclock_preview.png"
big.save(OUT)
print("saved:", OUT)
print("ALL HOST TESTS PASSED")
