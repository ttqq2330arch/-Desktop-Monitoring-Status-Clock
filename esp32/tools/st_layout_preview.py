# -*- coding: utf-8 -*-
"""
状态页排版设计稿（当前版 vs 铺满整屏版）
=====================================
用 tools/mc_ui_preview.py 里同一套 5x7 字形 / 12x12 图标 / MC 凹槽 / 分段经验条，
按固件 src/main.cpp 的**真实逻辑坐标**逐像素渲染，1:1 还原屏上效果。

坐标说明：这里的坐标系 = 固件的逻辑坐标系。因为设备是「倒装外壳 + 软件 180° 翻转」，
两层旋转互相抵消 → **用户看到的画面 = 逻辑坐标正序**（逻辑 y 小 = 视觉上方）。
所以本体输出＝用户视角，直接可验收。

输出：st_current_4x.png / st_full_4x.png / st_compare_4x.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_ui_preview import (  # noqa: E402
    Canvas, text, text_w, draw_icon, draw_xp_bar, save_png, C,
    SCR_BG, MC_BLACK, MC_DGRAY, MC_GRAY, MC_WHITE, MC_RED, MC_YELLOW,
    HEAD_LO, GUI_DARK,
)

SCR_W, SCR_H = 160, 128
OUT = os.path.dirname(os.path.abspath(__file__))

# 与固件 mc_theme.h / main.cpp 对齐的常量
MCUI_BG     = C("212121")
MCUI_LO     = C("151515")
MCUI_SHADOW = C("3F3F3F")
MCUI_LBL_SH = C("1A1A1A")

# 固件常量（main.cpp 顶部）
EDGE_TOP = 3       # 逻辑顶部纯背景带行数（y=0..2）：撕裂不可免疫，动态内容不得进入
EDGE_BOT = 4       # 逻辑底部纯背景带行数（y=124..127）：同上
BODY_TOP = 19      # 指标行起始
ROW_H    = 21      # 指标行高：5 × 21 = 105 → 19..123，末行内容收在 y=123

# ---------------------------------------------------------------- 示例数据
DEMO = {
    'time': '13:12', 'date': '09-16', 'uptime': '5h07m', 'stale': False,
    'rows': [
        {'icon': 'CPU', 'label': 'CPU', 'pct': 45, 'value': '45%',  'aux': '52C'},
        {'icon': 'RAM', 'label': 'RAM', 'pct': 62, 'value': '62%',  'aux': '9.8G'},
        {'icon': 'NET', 'label': 'NET', 'pct': -1, 'value': '1.2M', 'aux': '^340K'},
        {'icon': 'GPU', 'label': 'GPU', 'pct': 88, 'value': '88%',  'aux': '74C'},
        {'icon': 'DSK', 'label': 'DSK', 'pct': 71, 'value': '71%',  'aux': '120G'},
    ],
}
ROW_COLORS = [C("55FFFF"), C("FFAA00"), C("5555FF"), C("FF55FF"), C("55FF55")]


def load_color(pct, base):
    """对应固件 mcLoadColor()：高负载转黄/红"""
    if pct < 0:
        return MC_GRAY
    if pct >= 85:
        return MC_RED
    if pct >= 60:
        return MC_YELLOW
    return base


def draw_row(cv, m, base, top, c1, c2):
    """一行指标（横向几何与固件一致：图标 x=2 / 标签 x=18 / 条 x=52 / 主值右对齐 156 / 副值 x=52）"""
    draw_icon(cv, m['icon'], 2, top + 4)
    text(cv, m['label'], 18, c1, 1, MC_GRAY, shadow=MCUI_LBL_SH)
    draw_xp_bar(cv, 52, c1 + 1, 76, 6, m['pct'], load_color(m['pct'], base))
    vw = text_w(m['value'], 1, bold=True)
    text(cv, m['value'], 156 - vw, c1, 1, MC_WHITE, bold=True, shadow=MCUI_SHADOW)
    text(cv, m['aux'], 52, c2, 1, MC_DGRAY)


# ================================================================ 当前版（固件现状）
def draw_current(st):
    """严格按当前 main.cpp：mcStr(time,2,37,s2) / mcStr(dt,61,44,s1)
       drawMcRow: BODY_TOP=52, rh=15, c1=top+2, c2=top+10
       → 顶部空 37px、指标区挤在下方且末行溢出被裁"""
    cv = Canvas(SCR_W, SCR_H, MCUI_BG)
    text(cv, st['time'], 2, 37, 2, MC_WHITE, shadow=MCUI_SHADOW)
    rt = st['date'] + " " + st['uptime']
    text(cv, rt, 61, 44, 1, MC_GRAY)
    for i, m in enumerate(st['rows']):
        top = 52 + i * 15
        draw_row(cv, m, ROW_COLORS[i], top, top + 2, top + 10)
    return cv


# ================================================================ 铺满整屏版（新方案）
def draw_full(st):
    """铺满整屏（含防撕裂边距）：
       · y=0..2   纯背景带（EDGE_TOP=3）—— 动态内容严禁进入
       · y=3..16  时钟带：时钟 2x @ y=3（占 3..16），日期 1x @ y=10（占 10..16）→ 底边同为 y=16
       · y=17/18  凹槽分隔线（暗线 + 黑缝）—— 静态内容，落在撕裂带也不闪
       · y=19..123 指标区 BODY_TOP=19，行高 21，5 行 → 末行内容收在 y=123
       · y=124..127 纯背景带（EDGE_BOT=4）—— 动态内容严禁进入
    """
    cv = Canvas(SCR_W, SCR_H, MCUI_BG)

    # ---- 时钟带
    text(cv, st['time'], 2, 3, 2, MC_WHITE, shadow=MCUI_SHADOW)      # 2 倍字，y=3..16
    rt = st['date'] + " " + st['uptime']
    text(cv, rt, 66, 10, 1, MC_GRAY)                                 # 1 倍字，底对齐 y=16

    # ---- 凹槽分隔线（暗线 + 黑缝）
    cv.rect(0, 17, SCR_W, 1, MCUI_LO)
    cv.rect(0, 18, SCR_W, 1, MC_BLACK)

    # ---- 指标区：19..123
    for i, m in enumerate(st['rows']):
        top = BODY_TOP + i * ROW_H
        draw_row(cv, m, ROW_COLORS[i], top, top + 4, top + 14)
    return cv


def side_by_side(a, b, gap=8, bg=C("0A0A0A")):
    cv = Canvas(a.w + gap + b.w, max(a.h, b.h), bg)
    for y in range(a.h):
        for x in range(a.w):
            cv.px[y][x] = a.px[y][x]
    for y in range(b.h):
        for x in range(b.w):
            cv.px[y][x + a.w + gap] = b.px[y][x]
    return cv


def usage_report(cv):
    """统计内容实际占用的行范围（末行有非背景像素即算占用）"""
    bg = cv.px[0][0]
    last, first = -1, -1
    for y in range(cv.h):
        if any(cv.px[y][x] != bg for x in range(cv.w)):
            if first < 0:
                first = y
            last = y
    return first, last


if __name__ == '__main__':
    cur = draw_current(DEMO)
    full = draw_full(DEMO)
    for name, cv in (('st_current', cur), ('st_full', full)):
        p = os.path.join(OUT, name + '_4x.png')
        print(name + '_4x ->', save_png(p, cv, 4), 'bytes', p)
    p = os.path.join(OUT, 'st_compare_4x.png')
    print('compare ->', save_png(p, side_by_side(cur, full), 3), 'bytes', p)

    f0, f1 = usage_report(full)
    c0, c1 = usage_report(cur)
    print('当前版 内容行范围 y=%d..%d（空顶 %d 行 / 底部近边 %d 行）' % (c0, c1, c0, SCR_H - 1 - c1))
    print('铺满版 内容行范围 y=%d..%d（空顶 %d 行 / 底部近边 %d 行）' % (f0, f1, f0, SCR_H - 1 - f1))
    print('逻辑分辨率 %dx%d' % (SCR_W, SCR_H))
