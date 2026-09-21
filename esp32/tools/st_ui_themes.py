# -*- coding: utf-8 -*-
"""
状态页 UI 风格候选设计稿（简约方向）
====================================
三套简约方案 + 当前 MC 版对照，全部按固件 src/main.cpp 的**真实逻辑坐标**
160x128 逐像素渲染（1:1 可验收）。逻辑坐标 = 用户视角（倒装外壳 + 软件翻转抵消）。

硬约束（改版不得违反）：
  · y=0..2     纯背景（EDGE_TOP=3）—— 动态内容严禁进入，静态线可
  · y=3..16    时钟带（时钟 2x 占 3..16，日期/uptime 1x 底对齐 16）
  · y=18       顶部分隔发丝线（静态，落在撕裂带也不闪）
  · y=19..123  指标区（末行内容不得越过 y=123）
  · y=124..127 纯背景（EDGE_BOT=4）—— 动态内容严禁进入

字体现实：src/clock_font.h 只有数字 0-9（无字母），状态页只能用 5x7 像素字表，
所以三套方案的差异全部体现在**布局 / 线条 / 灰度层级 / 用色纪律**上。

三套方案的语言差异：
  A BRAUN      发丝线 + 行底基线量规；颜色只承载"异常"语义（正常=中性白灰）
  B NOTHING    纯黑底 + 点阵条 + 零分隔线；全屏唯一红色，仅危险时出现
  C HIERARCHY  CPU/RAM 双大字主轴 + NET/GPU/DSK 降级紧凑行；蓝色常态填充

输出：st_theme_a_braun_4x.png / st_theme_b_nothing_4x.png /
      st_theme_c_hierarchy_4x.png / st_themes_compare_4x.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_ui_preview import (  # noqa: E402
    Canvas, text, text_w, save_png, C,
)
from st_layout_preview import draw_full as draw_current, DEMO as DEMO_MC  # noqa: E402

SCR_W, SCR_H = 160, 128
OUT = os.path.dirname(os.path.abspath(__file__))

EDGE_TOP, EDGE_BOT = 3, 4


# ============================================================ 通用绘制原语
def hline(cv, x, y, w, c):
    cv.rect(x, y, w, 1, c)


def bar(cv, x, y, w, h, pct, track, fill):
    """实心细条（发丝量规）：整条轨道 + 按比例填充"""
    cv.rect(x, y, w, h, track)
    if pct > 0:
        fw = int(round(w * min(100, pct) / 100.0))
        if fw > 0:
            cv.rect(x, y, fw, h, fill)


def dotbar(cv, x, y, w, pct, off, on, dot=2, step=4):
    """点阵条：一排小方点，点亮 = 已占用（Nothing 的点阵语言）"""
    n = (w + step - dot) // step
    onn = 0 if pct < 0 else int(round(n * min(100, max(0, pct)) / 100.0))
    for j in range(n):
        cv.rect(x + j * step, y, dot, dot, on if j < onn else off)


# ============================================================ 方案 A：Braun / 功能主义
# 语言：发丝线、无图标、无凹槽、无阴影；颜色只承载"异常"语义（正常=中性白灰）
# 排布：每行 = 标签行 → 副值行 → 行底基线量规（条天然充当行分隔 + 刻度）
A_BG    = C("121212")
A_HAIR  = C("2B2B2B")
A_LABEL = C("8C8C8C")
A_VALUE = C("F2F2F2")
A_AUX   = C("6E6E6E")
A_TRACK = C("2B2B2B")
A_FILL  = C("8A8A8A")   # 正常态：中性灰（不发亮 —— 只有异常才亮）
A_WARN  = C("FFB000")
A_CRIT  = C("FF4D4D")


def a_color(pct):
    if pct >= 85:
        return A_CRIT
    if pct >= 60:
        return A_WARN
    return A_FILL


def draw_A(st):
    cv = Canvas(SCR_W, SCR_H, A_BG)
    text(cv, st['time'], 4, 3, 2, A_VALUE)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, A_AUX)
    hline(cv, 4, 18, 152, A_HAIR)

    for i, m in enumerate(st['rows']):
        top = 19 + i * 21
        text(cv, m['label'], 4, top + 2, 1, A_LABEL)
        text(cv, m['aux'], 27, top + 2, 1, A_AUX)        # 副值跟标签同行
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, top + 2, 1, A_VALUE, bold=True)
        # 行底量规：文字行下方 5px 处，一条线承担「刻度 + 行分隔」两个职能
        bar(cv, 4, top + 14, 152, 2, m['pct'], A_TRACK, a_color(m['pct']))
    return cv


# ============================================================ 方案 B：Nothing / 纯黑白点阵
# 语言：纯黑底、无任何分隔线与边框、元素点阵化、全屏唯一红色（仅 ≥85% 时出现）
B_BG    = C("000000")
B_TEXT  = C("FFFFFF")
B_DIM   = C("6E6E6E")
B_OFF   = C("161616")
B_ACC   = C("FF3B30")


def b_color(pct):
    return B_ACC if pct >= 85 else B_TEXT


def draw_B(st):
    cv = Canvas(SCR_W, SCR_H, B_BG)
    text(cv, st['time'], 4, 3, 2, B_TEXT)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, B_DIM)

    for i, m in enumerate(st['rows']):
        top = 24 + i * 20
        text(cv, m['label'], 4, top, 1, B_TEXT)
        text(cv, m['aux'], 27, top, 1, B_DIM)
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, top, 1, b_color(m['pct']), bold=True)
        dotbar(cv, 4, top + 10, 152, m['pct'], B_OFF, b_color(m['pct']))
    return cv


# ============================================================ 方案 C：主次分层 / Less but better
# 语言：CPU+RAM 双大字主轴，NET/GPU/DSK 降级为紧凑行（标签左/主值中/副值右 + 行底条）
C_BG    = C("0F1419")
C_LINE  = C("262D36")
C_LABEL = C("8B98A5")
C_VALUE = C("E6EDF3")
C_AUX   = C("5C6773")
C_TRACK = C("21262D")
C_ACC   = C("58A6FF")
C_WARN  = C("D29922")
C_CRIT  = C("F85149")


def c_color(pct):
    if pct >= 85:
        return C_CRIT
    if pct >= 60:
        return C_WARN
    return C_ACC


def draw_C(st):
    cv = Canvas(SCR_W, SCR_H, C_BG)
    text(cv, st['time'], 4, 3, 2, C_VALUE)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, C_AUX)
    hline(cv, 4, 18, 152, C_LINE)

    # ---- 主区：CPU / RAM 双大字
    for k, idx in enumerate((0, 1)):
        m = st['rows'][idx]
        colx = 4 + k * 80
        text(cv, m['label'], colx, 21, 1, C_LABEL)
        text(cv, m['value'], colx, 30, 2, C_VALUE)          # 2x 大字 y=30..43
        text(cv, m['aux'], colx + text_w(m['value'], 2) + 5, 37, 1, C_AUX)
        bar(cv, colx, 47, 72, 2, m['pct'], C_TRACK, c_color(m['pct']))

    hline(cv, 4, 53, 152, C_LINE)

    # ---- 次区：NET / GPU / DSK（水平三段：标签左 / 主值中 / 副值右）
    for k, idx in enumerate((2, 3, 4)):
        m = st['rows'][idx]
        top = 58 + k * 22
        text(cv, m['label'], 4, top, 1, C_LABEL)
        text(cv, m['value'], 34, top, 1, C_VALUE, bold=True)
        text(cv, m['aux'], 156 - text_w(m['aux'], 1), top, 1, C_AUX)
        bar(cv, 4, top + 11, 152, 2, m['pct'], C_TRACK, c_color(m['pct']))
    return cv


# ============================================================ 工具
def selfcheck(name, cv):
    """校验：防撕裂边距是否被侵入 + 内容实际行范围"""
    bg = cv.px[0][0]
    bad_top = [y for y in range(EDGE_TOP)
               if any(cv.px[y][x] != bg for x in range(cv.w))]
    bad_bot = [y for y in range(cv.h - EDGE_BOT, cv.h)
               if any(cv.px[y][x] != bg for x in range(cv.w))]
    first = last = -1
    for y in range(cv.h):
        if any(cv.px[y][x] != bg for x in range(cv.w)):
            if first < 0:
                first = y
            last = y
    ok = (not bad_top) and (not bad_bot) and last <= 123
    print('  %-12s 内容 y=%d..%d  上边距侵入=%s 下边距侵入=%s  %s'
          % (name, first, last, bad_top or '无', bad_bot or '无',
             'OK' if ok else '★不合格'))
    return ok


def paste(dst, src, ox, oy):
    for y in range(src.h):
        for x in range(src.w):
            dst.px[oy + y][ox + x] = src.px[y][x]


def compare(cols, gap=10, title_h=16):
    """cols = [(标题, 画布), ...] 横排对比"""
    w = sum(c[1].w for c in cols) + gap * (len(cols) + 1)
    h = title_h + SCR_H + 6
    cv = Canvas(w, h, C("0A0A0A"))
    x = gap
    for title, c in cols:
        text(cv, title, x + 4, 5, 1, C("E8E8E8"))
        paste(cv, c, x, title_h)
        x += c.w + gap
    return cv


# ============================================================ 入口
DEMO_ST = {
    'time': '13:12', 'date': '09-18', 'uptime': '5H07M',
    'page': 0, 'stale': False,
    'rows': [
        {'icon': 'CPU', 'label': 'CPU', 'pct': 45, 'value': '45%',  'aux': '52C'},
        {'icon': 'RAM', 'label': 'RAM', 'pct': 62, 'value': '62%',  'aux': '9.8G'},
        {'icon': 'NET', 'label': 'NET', 'pct': -1, 'value': '1.2M', 'aux': '^340K'},
        {'icon': 'GPU', 'label': 'GPU', 'pct': 88, 'value': '88%',  'aux': '74C'},
        {'icon': 'DSK', 'label': 'DSK', 'pct': 71, 'value': '71%',  'aux': '120G'},
    ],
}

# 当前 MC 版对照（直接复用正式设计稿的固件版绘制函数 draw_full）
MC_ST = dict(DEMO_MC)
MC_ST['date'] = DEMO_ST['date']
MC_ST['uptime'] = DEMO_ST['uptime']
MC_ST['time'] = DEMO_ST['time']

if __name__ == '__main__':
    jobs = [
        ('A_BRAUN', draw_A),
        ('B_NOTHING', draw_B),
        ('C_HIERARCHY', draw_C),
    ]
    made = [('NOW_MC', draw_current(MC_ST))]
    for tag, fn in jobs:
        cv = fn(DEMO_ST)
        p = os.path.join(OUT, 'st_theme_%s_4x.png' % tag.lower())
        n = save_png(p, cv, 4)
        print('%-12s %s -> %d bytes' % (tag, p, n))
        made.append((tag, cv))

    print('--- 自检（防撕裂边距 + 末行不得越过 y=123）---')
    allok = True
    for tag, cv in made:
        allok &= selfcheck(tag, cv)

    pc = os.path.join(OUT, 'st_themes_compare_4x.png')
    save_png(pc, compare(made), 3)
    print('compare ->', pc)
    print('总体自检:', 'OK' if allok else '★不合格')
