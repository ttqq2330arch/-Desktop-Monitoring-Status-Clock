# -*- coding: utf-8 -*-
"""
状态页 UI 风格候选设计稿 · 第二批（D/E/F）
==========================================
承接 st_ui_themes.py（A/B/C）。三套新方向，按固件真实逻辑坐标 160x128 渲染。

新增的三条设计语言（检索所得）：
  · Teenage Engineering —— "真仪器上到处都是小号大写标签"；恰好一个强调色；
    允许一套编码状态点（LED）系统；模块之间有接缝；底栏放 dry 元数据。
  · Swiss / 国际主义排版 —— 层级只靠「大小 / 粗细 / 位置」，不靠颜色和装饰
    （"Information hierarchy is purely structural"）；单一强调色只做信号。
  · 数显读数（工业巡检仪 / 万用表）—— 数字是主角，图形降级为极短量规。

三套方案：
  D TE PANEL   仪器面板：状态点 LED + 4 段刻度轨道 + 接缝 + 底栏元数据（TE orange 强调）
  E LINE ICON  极简线性图标：8x8 单色 1px 描边图标 + 1px 发丝量规（解决"没图标不好找"）
  F READOUT    数显读数：5 个 2x 大数字 + 通道号 + 微型量规（无长条形）

硬约束同 st_ui_themes.py：y=0..2 / y=124..127 为防撕裂纯背景带，末行内容 <= y=123。

输出：st_theme_d_tepanel_4x.png / st_theme_e_lineicon_4x.png /
      st_theme_f_readout_4x.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_ui_preview import Canvas, text, text_w, save_png, C  # noqa: E402
from st_ui_themes import hline, bar, selfcheck, compare, DEMO_ST  # noqa: E402

SCR_W, SCR_H = 160, 128
OUT = os.path.dirname(os.path.abspath(__file__))


# ============================================================ D：TE 仪器面板
# 语言：外壳接缝 + 状态点 LED（亮点只代表异常）+ 4 段刻度轨道 + 底栏 dry 元数据
# 用色纪律：恰好一个强调色（TE orange），且只出现在「危险」这一档
D_BG    = C("141317")
D_INK   = C("E5E5E5")
D_SOFT  = C("A0A0A8")
D_MUTED = C("6E6E76")
D_LINE  = C("2A2930")
D_TRACK = C("26252B")
D_OFF   = C("33333A")     # 状态点「正常」= 几乎不亮
D_WARN  = C("FFB000")
D_CRIT  = C("FF5A00")     # TE orange —— 唯一的强调色，只给最高一档

D_BODY_TOP, D_ROW_H = 20, 19


def d_point(pct):
    """状态点 LED：★正常不亮（几乎不可见），只有异常才亮 —— 屏幕上亮着的点就是问题"""
    if pct >= 85:
        return D_CRIT
    if pct >= 60:
        return D_WARN
    return D_OFF


def d_fill(pct):
    """轨道填充色：正常为中性白，异常才染色"""
    if pct >= 85:
        return D_CRIT
    if pct >= 60:
        return D_WARN
    return D_INK


def d_seg_bar(cv, x, y, w, h, pct, track, fill, segs=4):
    """4 段刻度轨道（暗）+ 连续填充（亮）—— 已填充段读长度，未填充段读数格子"""
    gap = 1
    sw = (w - (segs - 1) * gap) // segs
    for i in range(segs):
        cv.rect(x + i * (sw + gap), y, sw, h, track)
    if pct > 0:
        fw = int(round(w * min(100, pct) / 100.0))
        if fw > 0:
            cv.rect(x, y, fw, h, fill)


def draw_D(st):
    cv = Canvas(SCR_W, SCR_H, D_BG)
    # ---- 时钟带
    text(cv, st['time'], 4, 3, 2, D_INK)
    rt = st['date']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, D_MUTED)
    hline(cv, 0, 18, SCR_W, D_LINE)          # 外壳接缝（全宽）

    # ---- 5 个模块
    for i, m in enumerate(st['rows']):
        top = D_BODY_TOP + i * D_ROW_H
        cv.rect(4, top + 3, 3, 3, d_point(m['pct']))          # 状态点
        text(cv, m['label'], 12, top + 1, 1, D_SOFT)          # 大写字标签
        text(cv, m['aux'], 34, top + 1, 1, D_MUTED)           # 单位/副值
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, top + 1, 1, D_INK, bold=True)
        d_seg_bar(cv, 12, top + 11, 144, 3, m['pct'], D_TRACK,
                  d_fill(m['pct']))

    # ---- 底栏（dry 元数据）
    hline(cv, 0, 114, SCR_W, D_LINE)
    text(cv, 'UP ' + st['uptime'], 4, 117, 1, D_MUTED)
    link = '115200'
    text(cv, link, 156 - text_w(link, 1), 117, 1, D_MUTED)
    return cv


# ============================================================ E：极简线性图标
# 语言：8x8 单色 1px 描边图标（不是彩色方块）+ 1px 发丝量规 + 无凹槽无阴影
# 这是「A 去掉了图标」的回应：保留定位功能，但把图标压成最轻的单色符号
E_BG    = C("0D0D0F")
E_INK   = C("ECECEC")
E_SOFT  = C("9A9AA2")
E_DIM   = C("5F5F68")
E_LINE  = C("32323A")     # 轨道/发丝线（太暗会看不出「满格在哪」）
E_ICON  = C("8E8E96")
E_WARN  = C("FFB020")
E_CRIT  = C("FF4D4D")

E_BODY_TOP, E_ROW_H = 19, 21


def stroke_rect(cv, x, y, w, h, c):
    cv.rect(x, y, w, 1, c)
    cv.rect(x, y + h - 1, w, 1, c)
    cv.rect(x, y, 1, h, c)
    cv.rect(x + w - 1, y, 1, h, c)


def glyph(cv, key, x, y, c):
    """8x8 单色 1px 线性图标（五者结构互不相同，1x 下可辨）"""
    if key == 'CPU':                       # 芯片：方框 + 内芯
        stroke_rect(cv, x, y, 8, 8, c)
        cv.rect(x + 2, y + 2, 4, 4, c)
    elif key == 'RAM':                     # 内存条：扁框 + 3 条竖线
        stroke_rect(cv, x, y + 1, 8, 6, c)
        for dx in (2, 4, 6):
            cv.rect(x + dx, y + 2, 1, 4, c)
    elif key == 'NET':                     # 信号：上窄下宽三条横线
        for k, wd in enumerate((3, 5, 7)):
            cv.rect(x + (8 - wd) // 2, y + 1 + k * 3, wd, 1, c)
    elif key == 'GPU':                     # 散热片：方框 + 两条横翅
        stroke_rect(cv, x, y, 8, 8, c)
        cv.rect(x + 2, y + 3, 4, 1, c)
        cv.rect(x + 2, y + 5, 4, 1, c)
    elif key == 'DSK':                     # 盘片：圆环（方形近似）+ 轴心
        stroke_rect(cv, x + 1, y + 1, 6, 6, c)
        cv.rect(x + 3, y + 3, 2, 2, c)


def e_fill(pct):
    if pct >= 85:
        return E_CRIT
    if pct >= 60:
        return E_WARN
    return E_INK


def draw_E(st):
    cv = Canvas(SCR_W, SCR_H, E_BG)
    text(cv, st['time'], 4, 3, 2, E_INK)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, E_DIM)
    hline(cv, 4, 18, 152, E_LINE)

    for i, m in enumerate(st['rows']):
        top = E_BODY_TOP + i * E_ROW_H
        glyph(cv, m['icon'], 4, top + 2, E_ICON)
        text(cv, m['label'], 16, top + 3, 1, E_SOFT)
        text(cv, m['aux'], 40, top + 3, 1, E_DIM)     # ★与标签拉开 6px，否则粘成一个词
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, top + 3, 1, E_INK, bold=True)
        bar(cv, 4, top + 15, 152, 1, m['pct'], E_LINE, e_fill(m['pct']))
    return cv


# ============================================================ F：数显读数
# 语言：数字是主角（2x 大数字右对齐成一栏）+ 通道号 + 微型量规（无长条形）
F_BG    = C("11151A")
F_INK   = C("F0F4F8")
F_SOFT  = C("98A2AE")
F_DIM   = C("5D6672")
F_CH    = C("3E4753")
F_TRACK = C("1D232B")
F_WARN  = C("F0A93B")
F_CRIT  = C("F0524B")

F_BODY_TOP, F_ROW_H = 19, 21
F_MICRO_W = 70


def f_fill(pct):
    """量规填充：三档"""
    if pct >= 85:
        return F_CRIT
    if pct >= 60:
        return F_WARN
    return F_INK


def f_text(pct):
    """大数字：★默认白，只有危险档才染色 —— 否则满屏彩字，正是要摆脱的东西"""
    return F_CRIT if pct >= 85 else F_INK


def draw_F(st):
    cv = Canvas(SCR_W, SCR_H, F_BG)
    text(cv, st['time'], 4, 3, 2, F_INK)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, F_DIM)
    hline(cv, 4, 18, 152, F_TRACK)

    for i, m in enumerate(st['rows']):
        top = F_BODY_TOP + i * F_ROW_H
        text(cv, '%02d' % (i + 1), 4, top + 4, 1, F_CH)       # 通道号
        text(cv, m['label'], 19, top + 4, 1, F_SOFT)
        vw = text_w(m['value'], 2)
        vx = 156 - vw
        text(cv, m['value'], vx, top + 1, 2, f_text(m['pct']))  # 2x 大数字
        aw = text_w(m['aux'], 1)
        text(cv, m['aux'], vx - 7 - aw, top + 5, 1, F_DIM)
        # 微型量规（右对齐大数字栏；离数字 2px，避免读成下划线）
        my = top + 17
        cv.rect(156 - F_MICRO_W, my, F_MICRO_W, 2, F_TRACK)
        if m['pct'] > 0:
            fw = int(round(F_MICRO_W * min(100, m['pct']) / 100.0))
            if fw > 0:
                cv.rect(156 - F_MICRO_W, my, fw, 2, f_fill(m['pct']))
    return cv


# ============================================================ 入口
if __name__ == '__main__':
    jobs = [('D_TEPANEL', draw_D), ('E_LINEICON', draw_E),
            ('F_READOUT', draw_F)]
    made = []
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
    print('总体自检:', 'OK' if allok else '★不合格')

    cmp3 = os.path.join(OUT, 'st_themes2_compare_4x.png')
    save_png(cmp3, compare(made), 3)
    print('compare ->', cmp3)
