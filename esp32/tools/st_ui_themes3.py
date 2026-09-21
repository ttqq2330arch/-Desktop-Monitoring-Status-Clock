# -*- coding: utf-8 -*-
"""
状态页 UI · 第三批（G）：信息收敛到 4 项
==========================================
需求变更：只保留 **CPU / RAM / NET / GPU** 四项（删掉 DSK）。

★ 不能"只删一行"：原布局 BODY_TOP=19、ROW_H=21，5 行正好占满 19..123；
  删掉一项后 4 行只占 84px，底下会空出 21px。所以必须重排节奏：
  4 行 × 26px = 104 → 19..123 仍然占满，但每行多出 5px，可以放更大的数字。

★ NET 行不再留空轨道：monitor.py 发的是 **"u"/"d" 两个 float（KB/s）**，
  固件也已解析进 st.upKB / st.dnKB（main.cpp:1314-1315），只是画的时候
  把 pct 写死成 -1。所以网速量规是**纯固件端改动，不用碰 PC 端**。
  刻度取对数（网速动态范围 0.1KB/s ~ 100MB/s，线性刻度日常流量等于看不见）：
      pct = 100 * log10(1 + KB/s) / log10(1 + 10240)      # 满格 = 10 MB/s

三套结构上互不相同的方案（都不是换配色）：
  G1 2x2 GRID  四宫格：4 项各占一格，2x 数字 + 粗量规（信息最少、最透气）
  G2 PANEL4    仪器面板：状态点 LED（异常才亮）+ 4 段刻度轨道（TE orange）
  G3 METER     横向仪表：左「标签+副值」两行 / 中「仪表条」/ 右「值」，四行等距

硬约束（沿用，改版不得违反）：
  · y=0..2 纯背景（EDGE_TOP=3）  · y=3..16 时钟带  · y=18 分隔线（静态）
  · y=19..123 指标区（末行内容不得越过 123）  · y=124..127 纯背景（EDGE_BOT=4）
  · 5x7 像素字步进 6px，横向间距 <6px 会粘成一个词

输出：st_theme_g1_grid_4x.png / st_theme_g2_panel4_4x.png /
      st_theme_g3_meter_4x.png / st_themes3_compare_4x.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_ui_preview import Canvas, text, text_w, save_png, C  # noqa: E402
from st_ui_themes import hline, bar, selfcheck, compare, DEMO_ST  # noqa: E402
from st_layout_preview import draw_full as draw_current, DEMO as DEMO_MC  # noqa: E402

SCR_W, SCR_H = 160, 128
OUT = os.path.dirname(os.path.abspath(__file__))

BODY_TOP, BODY_BOT = 19, 123
RH4 = 26                      # 4 行行高：19 + 4*26 = 123 ✓ 正好占满


def rate_pct(kbs, full=10240.0):
    """网速 → 对数刻度百分比（满格 full KB/s，默认 10 MB/s）"""
    import math
    if kbs <= 0:
        return 0
    return min(100, int(round(100.0 * math.log10(1.0 + kbs)
                             / math.log10(1.0 + full))))


# 中性档 / 警告 / 危险 三档取色（全屏统一纪律：正常不发亮，只有异常才亮）
# ★ 阈值不能照抄常见的 60/85：Windows 上内存占用 60% 是常态、GPU 瞬时 60% 也正常，
#   阈值定低了等于"到处是警告" = 没有警告。取 80 / 90，宁可少亮，亮则必是问题。
WARN_PCT, CRIT_PCT = 80, 90


def _tier(m, fill, warn, crit):
    """m 为指标行数据；NET 无"占用率"语义，固定中性色（网速快不是故障）"""
    if m['label'] == 'NET' or m['pct'] < 0:
        return fill
    if m['pct'] >= CRIT_PCT:
        return crit
    if m['pct'] >= WARN_PCT:
        return warn
    return fill


# ============================================================ G1：2x2 四宫格
# 语言：把屏幕切成 4 个等大的模块，每格一个 2x 大数字 + 一条粗量规。
# 信息量最少、留白最多 —— 直接回应"不想显示这么多信息"。
G1_BG    = C("12151A")
G1_SEAM  = C("252C35")     # 格缝（1px 竖线 + 1px 横线）
G1_LABEL = C("8B96A3")
G1_AUX   = C("5E6874")
G1_VALUE = C("EDF2F7")
G1_TRACK = C("1E242C")
G1_FILL  = C("9AA4B0")     # 正常：冷中性灰（不发亮）
G1_WARN  = C("F0A93B")
G1_CRIT  = C("F0524B")

# 网格：左右边距 4..156 = 153px → 76 + 1(缝) + 76
G1_CW = 76
G1_CX = (4, 81)
# 上下：19..123 = 105px → 52 + 1(缝) + 52
G1_CH = 52
G1_CY = (19, 72)


def g1_fill(m):
    return _tier(m, G1_FILL, G1_WARN, G1_CRIT)


def g1_cell(cv, m, tx, ty, net_mode='single'):
    if m['label']:
        text(cv, m['label'], tx, ty + 5, 1, G1_LABEL)
        text(cv, m['aux'], tx + 26, ty + 5, 1, G1_AUX)
    vw = text_w(m['value'], 2, bold=True)
    text(cv, m['value'], tx + G1_CW - vw, ty + 20, 2, G1_VALUE, bold=True)

    # NET 无「占用率」语义，三种处理方式（详见 st_net_variants_4x.png）
    if m['label'] == 'NET':
        if net_mode == 'blank':
            return                                  # 不画量规，只留数字
        if net_mode == 'dual':
            # 下行（上线）+ 上行（下线）：两条细条，一眼看出这是"两个值"
            bar(cv, tx, ty + 41, G1_CW, 2, m['pct'], G1_TRACK, G1_FILL)
            bar(cv, tx, ty + 45, G1_CW, 2, m.get('pct2', 0), G1_TRACK, G1_AUX)
            return
    # ★ 4px 而非 6px：粗条会抢 2x 数字的视觉主角位，量规是辅助不是主体
    bar(cv, tx, ty + 42, G1_CW, 4, m['pct'], G1_TRACK, g1_fill(m))


def draw_G1(st, net_mode='single'):
    cv = Canvas(SCR_W, SCR_H, G1_BG)
    text(cv, st['time'], 4, 3, 2, G1_VALUE)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, G1_AUX)
    hline(cv, 4, 18, 152, G1_SEAM)
    # 格缝
    cv.rect(80, G1_CY[0], 1, BODY_BOT - G1_CY[0] + 1, G1_SEAM)
    cv.rect(4, 71, 152, 1, G1_SEAM)

    for i, m in enumerate(st['rows'][:4]):
        g1_cell(cv, m, G1_CX[i % 2], G1_CY[i // 2], net_mode)
    return cv


# ============================================================ G2：仪器面板（4 行）
# 语言承接 D（TE）：状态点 LED 只标异常 + 4 段刻度轨道；
# 4 行撑满后行高 26px，轨道从 3px 加粗到 4px，去掉底栏（那本就是多余信息）。
G2_BG    = C("141317")
G2_INK   = C("E5E5E5")
G2_SOFT  = C("A0A0A8")
G2_MUTED = C("6E6E76")
G2_LINE  = C("2A2930")
G2_TRACK = C("26252B")
G2_OFF   = C("33333A")     # 状态点「正常」= 几乎不亮
G2_WARN  = C("FFB000")
G2_CRIT  = C("FF5A00")     # TE orange —— 唯一强调色，只给最高一档


def g2_point(m):
    """亮点只代表问题：正常不亮，≥80% 琥珀，≥90% orange"""
    return _tier(m, G2_OFF, G2_WARN, G2_CRIT)


def g2_fill(m):
    return _tier(m, G2_SOFT, G2_WARN, G2_CRIT)


def g2_segbar(cv, x, y, w, h, pct, track, fill, segs=4):
    """4 段刻度轨道：未填充段读数格子，填充段读长度"""
    gap = 1
    sw = (w - (segs - 1) * gap) // segs
    for i in range(segs):
        cv.rect(x + i * (sw + gap), y, sw, h, track)
    if pct > 0:
        fw = int(round(w * min(100, pct) / 100.0))
        if fw > 0:
            cv.rect(x, y, fw, h, fill)


def draw_G2(st):
    cv = Canvas(SCR_W, SCR_H, G2_BG)
    text(cv, st['time'], 4, 3, 2, G2_INK)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, G2_MUTED)
    hline(cv, 0, 18, SCR_W, G2_LINE)          # 全宽接缝

    for i, m in enumerate(st['rows'][:4]):
        ty = BODY_TOP + i * RH4
        cv.rect(4, ty + 6, 3, 3, g2_point(m))                  # 状态点
        text(cv, m['label'], 12, ty + 3, 1, G2_SOFT)
        text(cv, m['aux'], 36, ty + 3, 1, G2_MUTED)             # ★离标签 ≥7px，防粘连
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, ty + 3, 1, G2_INK, bold=True)
        # 轨道贴行块底部（基线刻度）：标签在上、量规在下，行归属一眼可判
        g2_segbar(cv, 12, ty + 18, 144, 4, m['pct'], G2_TRACK, g2_fill(m))
    return cv


# ============================================================ G3：横向仪表
# 语言：真仪表读数 —— 左列「标签 + 副值」两行文字，中段一条仪表条（含刻度），
# 右端值右对齐。四行等距，没有图标、没有状态点、没有分隔线。
G3_BG    = C("111316")
G3_HAIR  = C("2E3338")
G3_LABEL = C("8C949C")
G3_VALUE = C("F2F5F7")
G3_AUX   = C("636B73")
G3_TRACK = C("23282C")
G3_FILL  = C("8A929A")
G3_WARN  = C("FFB000")
G3_CRIT  = C("FF4D4D")

G3_BAR_X, G3_BAR_W = 44, 80     # 右端 123：值最宽 5 字符("12.3M")从 127 起，留 4px 不撞


def g3_fill(m):
    return _tier(m, G3_FILL, G3_WARN, G3_CRIT)


def draw_G3(st):
    cv = Canvas(SCR_W, SCR_H, G3_BG)
    text(cv, st['time'], 4, 3, 2, G3_VALUE)
    rt = st['date'] + ' ' + st['uptime']
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, G3_AUX)
    hline(cv, 4, 18, 152, G3_HAIR)

    for i, m in enumerate(st['rows'][:4]):
        ty = BODY_TOP + i * RH4
        text(cv, m['label'], 4, ty + 3, 1, G3_LABEL)
        text(cv, m['aux'], 4, ty + 13, 1, G3_AUX)               # 副值独占左列第二行
        bar(cv, G3_BAR_X, ty + 11, G3_BAR_W, 4, m['pct'], G3_TRACK,
            g3_fill(m))
        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, ty + 5, 1, G3_VALUE, bold=True)
    return cv


# ============================================================ 入口
DEMO4 = {
    'time': '13:12', 'date': '09-18', 'uptime': '5H07M',
    'page': 0, 'stale': False,
    # ★ 演示数据的取值原则：三项正常 + 一项越线。
    #   这样才能验证"全屏只有一个亮点"的机制真的成立（旧稿 4 行里 3 行是彩的）。
    'rows': [
        {'icon': 'CPU', 'label': 'CPU', 'pct': 23, 'value': '23%',  'aux': '52C'},
        {'icon': 'RAM', 'label': 'RAM', 'pct': 58, 'value': '58%',  'aux': '9.8G'},
        # NET：pct = 下行 1.2MB/s(1228.8KB/s) 的对数刻度值 = 77（但按中性色画）
        #      pct2 = 上行 340KB/s 的对数刻度值，仅 "dual" 变体使用
        {'icon': 'NET', 'label': 'NET', 'pct': rate_pct(1228.8), 'value': '1.2M',
         'aux': '^340K', 'pct2': rate_pct(340)},
        {'icon': 'GPU', 'label': 'GPU', 'pct': 91, 'value': '91%',  'aux': '74C'},
    ],
}

MC_ST = dict(DEMO_MC)
MC_ST['date'] = DEMO4['date']
MC_ST['uptime'] = DEMO4['uptime']
MC_ST['time'] = DEMO4['time']

if __name__ == '__main__':
    print('NET 对数刻度自检：')
    for kbs in (10, 100, 340, 1228.8, 5120, 10240):
        print('   %8.1f KB/s -> %3d%%' % (kbs, rate_pct(kbs)))

    jobs = [('G1_2X2_GRID', draw_G1), ('G2_PANEL4', draw_G2),
            ('G3_METER', draw_G3)]
    made = [('NOW_MC5', draw_current(MC_ST))]
    for tag, fn in jobs:
        cv = fn(DEMO4)
        p = os.path.join(OUT, 'st_theme_%s_4x.png' % tag.lower())
        n = save_png(p, cv, 4)
        print('%-12s %s -> %d bytes' % (tag, p, n))
        made.append((tag, cv))

    print('--- 自检（防撕裂边距 + 末行不得越过 y=123）---')
    allok = True
    for tag, cv in made:
        allok &= selfcheck(tag, cv)

    pc = os.path.join(OUT, 'st_themes3_compare_4x.png')
    save_png(pc, compare(made), 3)
    print('compare ->', pc)
    print('总体自检:', 'OK' if allok else '★不合格')

    # ---- NET 行的三种处理方式（只影响 NET 那一格，用于定夺）
    variants = [
        ('NET_SINGLE', draw_G1(DEMO4, 'single')),
        ('NET_DUAL', draw_G1(DEMO4, 'dual')),
        ('NET_BLANK', draw_G1(DEMO4, 'blank')),
    ]
    pn = os.path.join(OUT, 'st_net_variants_4x.png')
    save_png(pn, compare(variants), 4)
    print('NET 变体 ->', pn)
