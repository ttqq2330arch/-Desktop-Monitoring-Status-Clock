# -*- coding: utf-8 -*-
"""PC 仿真：验证翻页时钟「middle_center 画 -> 量真实墨迹 -> 平移修正」鲁棒算法。

与固件 buildFlipGlyphs() 同一套逻辑（字体用系统黑体做代理，仅验证算法，
ESP32 端用 LovyanGFX 真实像素跑同一流程，结果必然居中）。

PIL 的 anchor='mm' 等价于 LovyanGFX 的 middle_center；
其余「扫描真实墨迹 -> 计算 shift -> 平移重画」与固件逐行一致。
"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

from PIL import Image, ImageDraw, ImageFont

FC_GW, FC_H, FC_HALF, FOLD = 20, 42, 20, 2
C_BG     = (0x0E, 0x0E, 0x13)
C_CARD_T = (0x26, 0x26, 0x31)
C_CARD_B = (0x1A, 0x1A, 0x22)
C_CARD_L = (0x3C, 0x3C, 0x48)
C_FOLD   = (0x08, 0x08, 0x0C)
C_DIG    = (0xFF, 0xB3, 0x3D)

font = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 26)

def build_glyph(d, up):
    cyTarget = (FC_H // 2) - up              # 墨迹中心目标行；正 up=上移
    # 第一遍：画在卡片中心，量真实墨迹
    img = Image.new("RGB", (FC_GW, FC_H), C_CARD_T)
    dr = ImageDraw.Draw(img)
    dr.text((FC_GW / 2, FC_H / 2), str(d), font=font, fill=C_DIG, anchor="mm")
    bbox = img.getbbox()
    minY, maxY = bbox[1], bbox[3] - 1
    inkC = (minY + maxY) // 2
    shift = (FC_H // 2) - inkC
    finalY = cyTarget + shift
    # 第二遍（亮底上半）
    top = Image.new("RGB", (FC_GW, FC_H), C_CARD_T)
    ImageDraw.Draw(top).text((FC_GW / 2, finalY), str(d), font=font, fill=C_DIG, anchor="mm")
    gTop = top.crop((0, 0, FC_GW, FC_HALF))
    # 第二遍（暗底下半）
    bot = Image.new("RGB", (FC_GW, FC_H), C_CARD_B)
    ImageDraw.Draw(bot).text((FC_GW / 2, finalY), str(d), font=font, fill=C_DIG, anchor="mm")
    gBot = bot.crop((0, FC_HALF + FOLD, FC_GW, FC_H))
    return gTop, gBot

def compose_card(gTop, gBot):
    card = Image.new("RGB", (FC_GW, FC_H), C_CARD_B)
    card.paste(gTop, (0, 0))
    card.paste(gBot, (0, FC_HALF + FOLD))
    dr = ImageDraw.Draw(card)
    dr.line([0, FC_HALF, FC_GW - 1, FC_HALF], fill=C_FOLD)
    dr.rectangle([0, 0, FC_GW - 1, FC_H - 1], outline=C_CARD_L)
    return card

digits = [0, 1, 2, 3, 8]
ups = [0, 5, -5]
labels = {0: "up=0 居中", 5: "up=+5 上移", -5: "up=-5 下移"}

scale = 5
pad = 6
cellW, cellH = FC_GW * scale, FC_H * scale
colW = cellW + 4
rowH = cellH + 18
W = pad * 2 + len(ups) * colW
H = pad * 2 + len(digits) * rowH + 16
out = Image.new("RGB", (W, H), C_BG)
dr = ImageDraw.Draw(out)
fontLbl = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 13)
for ci, up in enumerate(ups):
    cx = pad + ci * colW
    dr.text((cx, pad), labels[up], font=fontLbl, fill=C_CARD_L)
    for ri, d in enumerate(digits):
        gTop, gBot = build_glyph(d, up)
        card = compose_card(gTop, gBot).resize((cellW, cellH), Image.NEAREST)
        cy = pad + 16 + ri * rowH
        out.paste(card, (cx, cy))
OUT = _TOOLS_DIR + "sim_flipclock_preview.png"
out.save(OUT)
print("saved:", OUT)
print("ALGO SIM PASSED (up=0/5/-5, digits 0,1,2,3,8)")
