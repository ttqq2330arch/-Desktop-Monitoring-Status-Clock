# -*- coding: utf-8 -*-
"""
天气页「状态页 + 时钟页」融合设计稿渲染器（5 版）
================================================
思路：把第1页（J 总览：深蓝黑底 + 环仪表 + 蓝/红两色极简）与第2页
（C 时钟：无框近黑底 + 糖果彩虹数字）的设计语言合并，重做天气页。

这一轮彻底放弃上一版「柔雾玻璃 / 浅色糖果」的浅底方案 —— 因为浅底与
另外三页（总览/时钟/日历全是深色）观感割裂。新方向统一为：

  · 无框近黑底（C 的 C_BG #0E0E13）—— 四页一致
  · 环/弧仪表承载数值（J 的 fillArc 环语言）—— 温度在当日高低区间里的位置
  · 糖果彩虹大号温度（C 的 Candy Rainbow 数字）
  · 极简排版 + 单强调蓝（J 的 J_ACC）—— 顶栏/分页点/副指标

160x128 逻辑分辨率，每版放大 3x 横向拼图。同一组数据：
北京 / 14:40 / 多云 / 23° / 最高27 最低18 / 湿度56% / 风速12 / 体感24
布局遵守固件防撕裂约束：y=0..2 与 y=124..127 留纯背景，内容收在 3..123。
"""
from PIL import Image, ImageDraw, ImageFont
import os, math

OUT = os.path.dirname(os.path.abspath(__file__))
MSYH   = 'C:/Windows/Fonts/msyh.ttc'     # 常规
MSYH_B = 'C:/Windows/Fonts/msyhbd.ttc'   # 粗体

S = 3
CW, CH = 160, 128
SCW, SCH = CW * S, CH * S

# ---- 配色（与固件 J / C 页同源）------------------------------------------
C_BG    = (14, 14, 19)        # C 页无框近黑底
J_ACC   = (61, 139, 253)      # J 页正常蓝 #3D8BFD
J_TRACK = (35, 42, 50)        # J 页环轨道 #232A32
WHITE   = (232, 237, 242)     # J_INK 近白
DIM     = (138, 149, 161)     # J_LABEL 灰
DIM2    = (88, 98, 110)       # 更暗
CANDY   = [(255, 79, 129), (255, 176, 0), (255, 244, 92),
           (92, 255, 138), (79, 195, 255), (179, 136, 255)]  # C 页糖果色序

def fontobj(size, bold):
    return ImageFont.truetype(MSYH_B if bold else MSYH, size * S)

def text_c(d, s, cx, cy, size, color, bold=False):
    """水平+垂直居中（cx,cy 为逻辑坐标中心）"""
    f = fontobj(size, bold)
    w = d.textlength(s, font=f)
    bb = f.getbbox(s)
    h = bb[3] - bb[1]
    d.text((cx * S - w / 2, cy * S - h / 2), s, font=f, fill=color)

def text_l(d, s, x_left, y_top, size, color, bold=False):
    f = fontobj(size, bold)
    d.text((x_left * S, y_top * S), s, font=f, fill=color)

def text_r(d, s, x_right, cy, size, color, bold=False):
    f = fontobj(size, bold)
    w = d.textlength(s, font=f)
    bb = f.getbbox(s)
    h = bb[3] - bb[1]
    d.text(((x_right * S) - w, cy * S - h / 2), s, font=f, fill=color)

def candy_width(d, s, size):
    f = fontobj(size, True)
    return sum(d.textlength(c, font=f) for c in s)

def text_c_candy(d, s, cx, cy, size):
    """糖果彩虹：每个字符轮流取 CANDY 色（与时钟页同序）。返回右缘 x（逻辑 px）"""
    f = fontobj(size, True)
    widths = [d.textlength(c, font=f) for c in s]
    total = sum(widths)
    bb = f.getbbox(s)
    h = bb[3] - bb[1]
    x = cx * S - total / 2
    y = cy * S - h / 2
    for i, c in enumerate(s):
        d.text((x, y), c, font=f, fill=CANDY[i % len(CANDY)])
        x += widths[i]
    return x / S

def rrect(d, x, y, w, h, r, fill, outline=None, width=1):
    box = [x * S, y * S, (x + w) * S, (y + h) * S]
    d.rounded_rectangle(box, radius=r * S, fill=fill, outline=outline,
                        width=(width * S if outline else 0))

def hline(d, x, y, w, color, width=1):
    d.line([(x * S, y * S), ((x + w) * S, y * S)], fill=color, width=width * S)

def thick_arc(d, cx, cy, rmid, halfw, a0, a1, color, steps=140):
    """屏幕坐标（y 向下）的粗弧：a0->a1 角度增加 = 顺时针（0=3点）"""
    a0r, a1r = math.radians(a0), math.radians(a1)
    pts = []
    for i in range(steps + 1):
        a = a0r + (a1r - a0r) * i / steps
        x = cx + rmid * math.cos(a)
        y = cy + rmid * math.sin(a)
        pts.append((x * S, y * S))
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=color, width=int(2 * halfw * S))

def arc_rainbow(d, cx, cy, rmid, halfw, a0, a1, steps=160):
    a0r, a1r = math.radians(a0), math.radians(a1)
    prev = None
    for i in range(steps + 1):
        a = a0r + (a1r - a0r) * i / steps
        x = cx + rmid * math.cos(a)
        y = cy + rmid * math.sin(a)
        p = (x * S, y * S)
        if prev is not None:
            t = i / steps
            c = CANDY[min(int(t * len(CANDY)), len(CANDY) - 1)]
            d.line([prev, p], fill=c, width=int(2 * halfw * S))
        prev = p

def ring(d, cx, cy, r_out, w, frac, prog_col, track=J_TRACK, rainbow=False):
    """环仪表：轨道整圈 + 12点起顺时针填充（与固件 fillArc 语义一致）"""
    rmid = r_out - w / 2.0
    halfw = w / 2.0
    thick_arc(d, cx, cy, rmid, halfw, 0, 360, track)
    if frac <= 0.001:
        return
    if rainbow:
        arc_rainbow(d, cx, cy, rmid, halfw, 270, 270 + frac * 360)
    else:
        thick_arc(d, cx, cy, rmid, halfw, 270, 270 + frac * 360, prog_col)

# ---- 简易天气图标（白/灰，极简矢量）--------------------------------------
def icon_cloud(d, cx, cy, r, col):
    d.ellipse([(cx - r * 0.9) * S, (cy - r * 0.5) * S, (cx + r * 0.9) * S, (cy + r * 0.7) * S], fill=col)
    d.ellipse([(cx - r * 0.6) * S, (cy - r * 0.7) * S, (cx + r * 0.2) * S, (cy + r * 0.3) * S], fill=col)
    d.ellipse([(cx - r * 0.1) * S, (cy - r * 0.9) * S, (cx + r * 0.8) * S, (cy + r * 0.1) * S], fill=col)
    d.rectangle([(cx - r * 0.9) * S, (cy + r * 0.1) * S, (cx + r * 0.9) * S, (cy + r * 0.55) * S], fill=col)

# ---- 顶部栏（与其它页一致：城市 / 时间 / 分页点）-------------------------
def header(d, city, time, cur=3, n=4):
    text_l(d, city, 6, 4, 14, WHITE, bold=True)
    text_r(d, time, 154, 10, 12, DIM)
    cx = 80
    for i in range(n):
        x = cx + (i - (n - 1) / 2.0) * 9
        if i == cur:
            d.ellipse([(x - 2) * S, (6 - 2) * S, (x + 2) * S, (6 + 2) * S], fill=J_ACC)
        else:
            d.ellipse([(x - 1) * S, (6 - 1) * S, (x + 1) * S, (6 + 1) * S], fill=DIM2)

def bottom_band(d, hi, lo, hum, wind):
    """底部副指标带：两行两列（列 x=20 / x=88），收在 y<=123"""
    hline(d, 14, 94, 132, (40, 46, 54), width=1)
    text_l(d, '最高', 20, 99, 10, DIM)
    text_l(d, str(hi), 20 + 21, 97, 13, WHITE, bold=True)
    text_l(d, '最低', 88, 99, 10, DIM)
    text_l(d, str(lo), 88 + 21, 97, 13, WHITE, bold=True)
    text_l(d, '湿度', 20, 112, 10, DIM)
    text_l(d, '%d%%' % hum, 20 + 21, 110, 13, WHITE, bold=True)
    text_l(d, '风速', 88, 112, 10, DIM)
    text_l(d, '%d' % wind, 88 + 21, 110, 13, WHITE, bold=True)

# ====================== 5 个融合版本 =======================================
CITY, TIME = '北京', '14:40'
TEMP, HI, LO, HUM, WIND, FEEL = 23, 27, 18, 56, 12, 24
COND = '多云'
FRAC = (TEMP - LO) / (HI - LO)   # 温度在当日区间里的位置 → 环填充比例

def cond_line(d, cy, txt_col=DIM, ic_col=DIM):
    """多云 + 小云图标（图标在文字左侧）"""
    text_c(d, COND, 84, cy, 13, txt_col, bold=True)
    icon_cloud(d, 60, cy, 6, ic_col)

def ver_a(d):   # A 环温中枢：单英雄环（蓝）+ 环内糖果温度（最平衡的 J+C 融合）
    d.rectangle([0, 0, SCW, SCH], fill=C_BG)
    header(d, CITY, TIME)
    cond_line(d, 25)
    ring(d, 80, 63, 30, 5, FRAC, J_ACC)
    xr = text_c_candy(d, '%d' % TEMP, 78, 61, 30)
    d.ellipse([(xr + 1) * S, (61 - 13) * S, (xr + 6) * S, (61 - 8) * S], fill=WHITE)  # °
    bottom_band(d, HI, LO, HUM, WIND)

def ver_b(d):   # B 彩虹巨温：糖果巨温为主 + 背后仪表弧（开口朝下，多云坐开口里）
    d.rectangle([0, 0, SCW, SCH], fill=C_BG)
    header(d, CITY, TIME)
    rmid, halfw = 44 - 2.5, 2.5
    arc_rainbow(d, 80, 58, rmid, halfw, 135, 135 + 270 * FRAC)   # 仪表弧：开口在底部
    xr = text_c_candy(d, '%d' % TEMP, 78, 54, 42)
    d.ellipse([(xr + 1) * S, (54 - 18) * S, (xr + 8) * S, (54 - 11) * S], fill=WHITE)
    text_c(d, COND, 80, 88, 12, DIM, bold=True)                  # 坐在弧开口里
    bottom_band(d, HI, LO, HUM, WIND)

def ver_c(d):   # C 主环三联：左英雄环(白净温) + 右三联小弧（J 主导，纯净无糖果）
    d.rectangle([0, 0, SCW, SCH], fill=C_BG)
    header(d, CITY, TIME)
    ring(d, 44, 54, 26, 5, FRAC, J_ACC)
    text_c(d, '%d' % TEMP, 44, 54, 26, WHITE, bold=True)
    d.ellipse([(44 + 16) * S, (54 - 11) * S, (44 + 20) * S, (54 - 7) * S], fill=WHITE)
    # 右侧三联小弧指标（y=28/52/76，收在 hairline 94 之上）
    rows = [('湿度', '%d%%' % HUM, HUM / 100.0),
            ('风速', '%d' % WIND, min(1.0, WIND / 40.0)),
            ('体感', '%d' % FEEL, (FEEL - LO) / (HI - LO))]
    y = 28
    for lab, val, fr in rows:
        ring(d, 106, y, 10, 3, fr, J_ACC)
        text_l(d, lab, 122, y - 6, 10, DIM)
        text_l(d, val, 122, y + 4, 13, WHITE, bold=True)
        y += 24
    bottom_band(d, HI, LO, HUM, WIND)

def ver_d(d):   # D 极简栅格：Apple 风大净温 + 横向温度弧 + 发丝栅格（最克制）
    d.rectangle([0, 0, SCW, SCH], fill=C_BG)
    header(d, CITY, TIME)
    text_l(d, '%d' % TEMP, 12, 30, 40, WHITE, bold=True)
    d.ellipse([(12 + 47) * S, (30 - 5) * S, (12 + 54) * S, (30 + 2) * S], fill=WHITE)
    text_c(d, COND, 134, 46, 14, DIM, bold=True)
    icon_cloud(d, 110, 46, 7, DIM)
    # 横向温度弧（环展开成横条）
    hline(d, 14, 74, 132, J_TRACK, width=6)
    xa = 14 + (146 - 14) * FRAC
    d.line([(14 * S, 74 * S), (xa * S, 74 * S)], fill=J_ACC, width=int(6 * S))
    # 发丝栅格副指标
    hline(d, 14, 88, 132, (40, 46, 54), width=1)
    text_l(d, '最高', 20, 94, 10, DIM); text_l(d, str(HI), 20 + 21, 92, 13, WHITE, bold=True)
    text_l(d, '最低', 88, 94, 10, DIM); text_l(d, str(LO), 88 + 21, 92, 13, WHITE, bold=True)
    text_l(d, '湿度', 20, 110, 10, DIM); text_l(d, '%d%%' % HUM, 20 + 21, 108, 13, WHITE, bold=True)
    text_l(d, '风速', 88, 110, 10, DIM); text_l(d, '%d' % WIND, 88 + 21, 108, 13, WHITE, bold=True)

def ver_e(d):   # E 霓虹环温：彩虹环 + 环内糖果温（更张扬的融合）
    d.rectangle([0, 0, SCW, SCH], fill=C_BG)
    header(d, CITY, TIME)
    cond_line(d, 25)
    ring(d, 80, 63, 30, 5, FRAC, None, rainbow=True)
    xr = text_c_candy(d, '%d' % TEMP, 78, 61, 30)
    d.ellipse([(xr + 1) * S, (61 - 13) * S, (xr + 6) * S, (61 - 8) * S], fill=WHITE)
    bottom_band(d, HI, LO, HUM, WIND)

# ====================== 拼图 ===============================================
TITLES = [('A', '环温中枢', '单英雄环+糖果温度', J_ACC),
          ('B', '彩虹巨温', '糖果巨温+细彩虹弧', CANDY[4]),
          ('C', '主环三联', '英雄环+三联小弧', J_ACC),
          ('D', '极简栅格', '大净温+横弧+发丝栅格', WHITE),
          ('E', '霓虹环温', '彩虹环+糖果温度', CANDY[1])]

def render():
    gap, top = 10, 128
    total_w = 5 * SCW + 6 * gap
    total_h = top + SCH
    sheet = Image.new('RGB', (total_w, total_h), (30, 30, 34))
    sd = ImageDraw.Draw(sheet)
    sd.text((gap, 6), u'天气页 · 状态页(J)+时钟页(C) 融合方案 · 深底无框 · 同一组数据',
            font=fontobj(12, True), fill=(220, 220, 225))

    vers = [ver_a, ver_b, ver_c, ver_d, ver_e]
    for i, (vf, (lab, name, sub, col)) in enumerate(zip(vers, TITLES)):
        img = Image.new('RGB', (SCW, SCH), C_BG)
        d = ImageDraw.Draw(img)
        vf(d)
        x0 = gap + i * (SCW + gap)
        sheet.paste(img, (x0, top))
        sd.text((x0 + 4, 50), lab, font=fontobj(16, True), fill=col)
        sd.text((x0 + 30, 54), name, font=fontobj(12, True), fill=(235, 235, 240))
        sd.text((x0 + 30, 98), sub, font=fontobj(8, False), fill=(150, 150, 158))
        sd.rounded_rectangle([x0, top, x0 + SCW, top + SCH], radius=8,
                             outline=(70, 70, 80), width=2)

    out = os.path.join(OUT, 'weather_jc_combo_5x.png')
    sheet.save(out)
    print('saved', out, sheet.size)

if __name__ == '__main__':
    render()
