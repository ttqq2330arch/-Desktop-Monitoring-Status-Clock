# -*- coding: utf-8 -*-
"""
状态页 UI · 第四批（H/I/J）：引入「形状语言」
==============================================
前三批（A..G，共 9 套）全部是**横线条 + 直角 + 深灰底**，本质上都是"表格"——
这是用户连说三次"再找找"的真正原因：问题不在配色和排版，在于**完全没有形状**。

本轮检索到两条真正可用的语言：
  · TRMNL（ESP32 电子墨水信息盘，成熟商业产品）：1-bit、无边框、每屏只做一件事、
    "glanceable"（一眼可读）。→ 不做装饰，但容器要成"块"。
  · watchOS complications：小屏表达百分比的标准做法是 **`fillFraction` 环形 gauge**
    （Apple 活动圆环那套），不是横条。→ 形状本身就能承载数值。

固件侧能力已查证（`main.cpp` 已在用）：`fillCircle` / `drawCircle` /
`fillRoundRect` / `drawRoundRect` / `fillTriangle` → 圆角与圆环都能落地。

三套方案（形状各异，都不是改配色）：
  H CARD   圆角卡片 2x2：深色卡 + 大数字 + 卡内圆角量规
  I PILL   内嵌胶囊 4 行：一条圆头胶囊就是进度条，标签与值压在条上
  J RING   双列四环 2x2：环形进度（watchOS 那套），环内「标签 + 2x 数字」

硬约束沿用：y=0..2 / y=124..127 纯背景带，y=19..123 内容区，末行内容 <= 123。
用色纪律：**四项共用同一个正常色**（不是四种颜色），只有越线才换琥珀/红。

输出：st_theme_h_card_4x.png / st_theme_i_pill_4x.png /
      st_theme_j_ring_4x.png / st_themes4_compare_4x.png
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_ui_preview import Canvas, text, text_w, save_png, C  # noqa: E402
from st_ui_themes import hline, selfcheck, compare  # noqa: E402
from st_ui_themes3 import DEMO4  # noqa: E402
from st_layout_preview import draw_full as draw_current, DEMO as DEMO_MC  # noqa: E402

SCR_W, SCR_H = 160, 128
OUT = os.path.dirname(os.path.abspath(__file__))
BODY_TOP, BODY_BOT = 19, 123


# ============================================================ 形状原语
def rrect(cv, x, y, w, h, r, c):
    """填充圆角矩形（逐行算左右内缩；KiCad 无、但 LovyanGFX 有 fillRoundRect）"""
    if w <= 0 or h <= 0:
        return
    r = min(r, w // 2, h // 2)
    for yy in range(h):
        if r > 0 and yy < r:
            d = r - yy - 0.5
        elif r > 0 and yy >= h - r:
            d = yy - (h - r) + 0.5
        else:
            d = 0.0
        dx = 0 if d <= 0 else int(math.ceil(r - math.sqrt(max(0.0, r * r - d * d))))
        cv.rect(x + dx, y + yy, max(0, w - 2 * dx), 1, c)


def ring(cv, cx, cy, ro, ri, pct, track, fill, start=-90):
    """环形进度（12 点起顺时针）；pct<0 则整圈只画轨道"""
    ro2, ri2 = ro * ro, ri * ri
    sweep = 0.0 if pct < 0 else pct * 3.6
    for yy in range(int(cy - ro), int(cy + ro) + 1):
        for xx in range(int(cx - ro), int(cx + ro) + 1):
            dx, dy = xx - cx, yy - cy
            d2 = dx * dx + dy * dy
            if not (ri2 <= d2 <= ro2):
                continue
            ang = (math.degrees(math.atan2(dy, dx)) - start) % 360.0
            cv.pix(xx, yy, fill if ang <= sweep else track)


# ============================================================ 统一配色
BG    = C("0E1116")      # 深蓝黑底
CARD  = C("1B222B")      # 卡片 / 容器（比底色亮两档，否则卡边界看不出来）
CARD2 = C("232B35")      # 胶囊轨道
INK   = C("E8EDF2")      # 主文字
LABEL = C("8A95A1")      # 标签
DIM   = C("5A646F")      # 副值
TRACK = C("232A32")      # 轨道
ACC   = C("3D8BFD")      # 正常：四项**共用**一个柔蓝（不是四种颜色）
CRIT  = C("FF2A2A")      # 过高：整环转红（★必须与固件 J_CRIT 同值）

# ★ 只有两个颜色（与固件 jColor 逐条对应）：蓝 = 正常，红 = 数值过高。
#   曾经有过一档 80..89% 的琥珀色，被用户否掉 —— 原话"UI 设计是蓝色为正常数值，
#   数值过高就是红色圆环"。多一个中间色只会让"偏高"和"过高"长得像，反而分不出。
HOT_PCT = 80


def color_of(m):
    """只有两档：正常蓝 / 过高红；NET 不参与变色（网速快不是故障）"""
    if m['label'] == 'NET' or m['pct'] < 0:
        return ACC
    if m['pct'] >= HOT_PCT:
        return CRIT
    return ACC


def rate_pct(kbs, full=10240.0):
    return 0 if kbs <= 0 else min(
        100, int(round(100.0 * math.log10(1.0 + kbs) / math.log10(1.0 + full))))


def header(cv):
    """时钟带（三套共用）"""
    text(cv, '13:12', 4, 3, 2, INK)
    rt = '09-18 5H07M'
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, DIM)


# ============================================================ H：圆角卡片 2x2
# 卡片 74x49，间隙 5px；卡内有底色（比背景亮一档）→ 读起来是"模块"不是"表格行"
H_CW, H_CH, H_GAP = 74, 49, 5
H_CX = (4, 4 + H_CW + H_GAP)          # 4, 83
H_CY = (20, 20 + H_CH + H_GAP)        # 20, 74


def draw_H(st):
    cv = Canvas(SCR_W, SCR_H, BG)
    header(cv)
    for i, m in enumerate(st['rows'][:4]):
        cx, cy = H_CX[i % 2], H_CY[i // 2]
        rrect(cv, cx, cy, H_CW, H_CH, 6, CARD)
        text(cv, m['label'], cx + 7, cy + 6, 1, LABEL)
        text(cv, m['aux'], cx + 30, cy + 6, 1, DIM)
        vw = text_w(m['value'], 2, bold=True)
        text(cv, m['value'], cx + H_CW - 7 - vw, cy + 17, 2, INK, bold=True)
        # 卡内圆角量规
        bw = H_CW - 14
        rrect(cv, cx + 7, cy + 38, bw, 5, 2, TRACK)
        if m['pct'] > 0:
            fw = int(round(bw * min(100, m['pct']) / 100.0))
            if fw > 0:
                rrect(cv, cx + 7, cy + 38, fw, 5, min(2, fw // 2), color_of(m))
    return cv


# ============================================================ I：内嵌胶囊 4 行
# 每行就是一条圆头胶囊：轨道色是胶囊底，进度从左填充，标签与值**压在条上**
I_RH = 26
I_PH = 20                              # 胶囊高（行高 26 → 上下各留 3px）


def draw_I(st):
    cv = Canvas(SCR_W, SCR_H, BG)
    header(cv)
    hline(cv, 4, 18, 152, C("222932"))
    for i, m in enumerate(st['rows'][:4]):
        ty = BODY_TOP + i * I_RH
        px, py, pw = 4, ty + 3, 152
        rrect(cv, px, py, pw, I_PH, I_PH // 2, CARD2)
        if m['pct'] > 0:
            fw = int(round(pw * min(100, m['pct']) / 100.0))
            if fw > 0:
                # 填充也要圆头；宽度小于高度时圆角半径跟着收，否则胶囊会缺角
                rrect(cv, px, py, fw, I_PH, min(I_PH // 2, fw // 2), color_of(m))
        text(cv, m['label'], px + 9, py + 7, 1, INK)
        # ★ 副值必须紧邻主值放在**右端**：填充总是从最左开始，左端放副值时
        #   低占用（23%）会让副值正好卡在填充边界上（半蓝半灰），观感很脏。
        vw = text_w(m['value'], 1, bold=True)
        vx = px + pw - 9 - vw
        text(cv, m['value'], vx, py + 7, 1, INK, bold=True)
        aw = text_w(m['aux'], 1)
        text(cv, m['aux'], vx - 8 - aw, py + 7, 1, C("DCE3EA"))
    return cv


# ============================================================ J：双列四环 2x2
# 环外径 50 / 线宽 6 → 内径 38 → **内接正方形只有 26px**。
# ★ 这里放不下 2x 数字：2x 三字符（"23%"）= 36px、"1.2M" = 46px，都会顶穿环壁。
#   所以环内用 1x（最宽的 "1.2M" 也只有 23px，需内接 >=24px → 外径 >=44）。
#   环径随之收到 44：50 的阿环里塞 7px 小字会显得"环大内容空"，比例不协调。
J_RO, J_RI = 22, 17
J_C = ((48, 47), (112, 47), (48, 97), (112, 97))


def draw_J(st):
    cv = Canvas(SCR_W, SCR_H, BG)
    header(cv)
    for i, m in enumerate(st['rows'][:4]):
        cx, cy = J_C[i]
        ring(cv, cx, cy, J_RO, J_RI, m['pct'], TRACK, color_of(m))
        text(cv, m['label'], cx - text_w(m['label'], 1) // 2, cy - 10, 1, LABEL)
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], cx - vw // 2, cy + 2, 1, INK, bold=True)
    return cv


# ============================================================ 入口
MC_ST = dict(DEMO_MC)
MC_ST['date'] = DEMO4['date']
MC_ST['uptime'] = DEMO4['uptime']
MC_ST['time'] = DEMO4['time']

if __name__ == '__main__':
    jobs = [('H_CARD', draw_H), ('I_PILL', draw_I), ('J_RING', draw_J)]
    made = [('NOW_MC5', draw_current(MC_ST))]
    for tag, fn in jobs:
        cv = fn(DEMO4)
        p = os.path.join(OUT, 'st_theme_%s_4x.png' % tag.lower())
        n = save_png(p, cv, 4)
        print('%-10s %s -> %d bytes' % (tag, p, n))
        made.append((tag, cv))

    print('--- 自检（防撕裂边距 + 末行不得越过 y=123）---')
    allok = True
    for tag, cv in made:
        allok &= selfcheck(tag, cv)

    pc = os.path.join(OUT, 'st_themes4_compare_4x.png')
    save_png(pc, compare(made), 3)
    print('compare ->', pc)
    print('总体自检:', 'OK' if allok else '★不合格')
