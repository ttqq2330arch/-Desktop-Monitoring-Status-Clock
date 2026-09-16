# -*- coding: utf-8 -*-
"""字节序问题的可视化诊断：模拟「修复前」与「修复后」设备屏幕实际显示什么。

原理（已由设备自检证实 [DIAG] fill=0x1234 buf=0x3412 swap=1）：
  sprite 缓冲是 rgb565_2Byte(swap565)，缓冲里存的是 swap16(逻辑色值)；
  屏幕最终显示 = swap16(直接写进缓冲的 uint16)。

  · 修复前：blitHalf 裸写逻辑色  -> 屏上显示 swap16(逻辑色)  -> 数字区域整块"红蓝互换"
  · 修复后：blitHalf 写 swap16(逻辑色) -> 屏上显示逻辑色      -> 与设计稿一致

只对 blitHalf 覆盖的矩形（每张卡的 20x20 数字区上下两块）做交换，
卡片圆角/背景/日期仍由 LovyanGFX API 绘制，颜色本来就正确。
"""
import os
import sys

from PIL import Image, ImageDraw

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import predict_clock_render as P  # 复用掩码解析 / 切片 / q565

SCR_W, SCR_H = 160, 128
FC_W, FC_H, FC_HALF, FC_GW = 22, 42, 20, 20
FC_Y = 26
FC_X = [4, 28, 57, 81, 110, 134]


def sw565(c):
    """逻辑 RGB888 →（按 swap565 缓冲裸写后）屏上实际显示的 RGB888"""
    r, g, b = c
    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    v = ((v & 0xFF) << 8) | (v >> 8)          # swap16
    return ((v >> 11) & 0x1F) * 255 // 31, ((v >> 5) & 0x3F) * 255 // 63, (v & 0x1F) * 255 // 31


def render(mask, swap_digit_zone):
    gTop, gBot = P.build_glyphs(mask)
    img = Image.new('RGB', (SCR_W, SCR_H), P.C_BG_W)
    d = ImageDraw.Draw(img)
    sample = "123456"
    for i in range(6):
        x = FC_X[i]
        dig = int(sample[i])
        cTop, cBot = P.C_TOP, P.C_BOT
        d.rounded_rectangle([x, FC_Y, x + FC_W - 1, FC_Y + FC_HALF - 1], radius=3, fill=cTop)
        d.rounded_rectangle([x, FC_Y + FC_HALF, x + FC_W - 1, FC_Y + FC_H - 1], radius=3, fill=cBot)
        d.rectangle([x, FC_Y + FC_HALF - 3, x + FC_W - 1, FC_Y + FC_HALF - 1], fill=cTop)
        ix = x + 1
        dc = P.DIG[i]
        bgT, bgB = cTop, cBot
        if swap_digit_zone:                   # 修复前：裸写，屏上红蓝互换
            dc, bgT, bgB = sw565(P.DIG[i]), sw565(cTop), sw565(cBot)
        for yy in range(FC_HALF):
            for xx in range(FC_GW):
                if gTop[dig][yy][xx]:
                    d.point((ix + xx, FC_Y + yy), fill=dc)
                else:
                    d.point((ix + xx, FC_Y + yy), fill=bgT)
                if gBot[dig][yy][xx]:
                    d.point((ix + xx, FC_Y + FC_HALF + 2 + yy), fill=dc)
                else:
                    d.point((ix + xx, FC_Y + FC_HALF + 2 + yy), fill=bgB)
        d.line([x + 1, FC_Y + FC_HALF, x + FC_W - 2, FC_Y + FC_HALF], fill=P.C_FOLD)
    cy = FC_Y + FC_H // 2
    for k in range(2):
        cx = (FC_X[1] + FC_W + 3) if k == 0 else (FC_X[3] + FC_W + 3)
        d.rectangle([cx, cy - 6, cx + 1, cy - 5], fill=P.C_COLON)
        d.rectangle([cx, cy + 4, cx + 1, cy + 5], fill=P.C_COLON)
    return img


def main():
    mask = P.load_mask()
    before = render(mask, swap_digit_zone=True)    # 修复前（设备实际曾显示）
    after = render(mask, swap_digit_zone=False)    # 修复后（应显示）

    S = 3
    b3 = before.resize((SCR_W * S, SCR_H * S), Image.NEAREST)
    a3 = after.resize((SCR_W * S, SCR_H * S), Image.NEAREST)
    b3.save(os.path.join(TOOLS, 'clock_swap_before.png'))
    a3.save(os.path.join(TOOLS, 'clock_swap_after.png'))

    gap, top = 16, 34
    W = b3.width + a3.width + gap * 3
    H = b3.height + top + 16
    cmp_img = Image.new('RGB', (W, H), (0x18, 0x18, 0x1E))
    d = ImageDraw.Draw(cmp_img)
    cmp_img.paste(b3, (gap, top))
    cmp_img.paste(a3, (gap * 2 + b3.width, top))
    try:
        from PIL import ImageFont
        f = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 16)
    except Exception:
        f = None
    d.text((gap, 10), 'BEFORE  (raw write -> red/blue swapped)', fill=(255, 120, 120), font=f)
    d.text((gap * 2 + b3.width, 10), 'AFTER  (swap16 applied -> correct)', fill=(140, 255, 160), font=f)
    out = os.path.join(TOOLS, 'clock_swap_compare.png')
    cmp_img.save(out)
    print('before ->', os.path.join(TOOLS, 'clock_swap_before.png'))
    print('after  ->', os.path.join(TOOLS, 'clock_swap_after.png'))
    print('compare ->', out, cmp_img.size)


if __name__ == '__main__':
    main()
