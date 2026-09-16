# -*- coding: utf-8 -*-
"""
翻页时钟 · 彩虹糖果色方案对比
按 main.cpp 的真实布局常量 1:1 绘制（FC_W/FC_H/FC_X/FC_Y），放大输出。

色值来源（一手权威色板，非自拟）：
  colordesigner.io "Candy Rainbow"  #ff4f81 #ffb000 #fff45c #5cff8a #4fc3ff #b388ff
  ilovehue.co      "Pastel Macaron" #ffb7b2 #ffdac1 #e2f0cb #b9e5d7 #c7ceea
"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

from PIL import Image, ImageDraw, ImageFont

SCR_W, SCR_H = 160, 128
FC_W, FC_H, FC_HALF = 22, 42, 20
FC_X = [4, 28, 57, 81, 110, 134]   # HH : MM : SS 六张卡
FC_Y = 26
SCALE = 2
OUT = _TOOLS_DIR

def font_of(p, s):
    try:
        return ImageFont.truetype(p, s)
    except Exception:
        return ImageFont.load_default()

# 大数字改用 Trebuchet MS Bold（humanist 圆体，零字是整圆、1 带圆角，比 Arial 更圆润）
F_DIG  = font_of("C:/Windows/Fonts/trebucbd.ttf", 30)
F_DATE = font_of("C:/Windows/Fonts/arialbd.ttf", 13)
F_UP   = font_of("C:/Windows/Fonts/arial.ttf", 8)

def mul(c, k):
    return tuple(min(255, max(0, int(v * k))) for v in c)

def hx(s):
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))

# ---- 权威色板 -------------------------------------------------------------
CANDY6 = [hx("FF4F81"), hx("FFB000"), hx("FFF45C"),
          hx("5CFF8A"), hx("4FC3FF"), hx("B388FF")]   # colordesigner Candy Rainbow
MACARON6 = [hx("FFB7B2"), hx("FFDAC1"), hx("FDF2A8"),
            hx("B9E5D7"), hx("C7CEEA"), hx("E1B7E1")]  # 马卡龙柔色（黄位替换为更亮的 #FDF2A8）

DIGITS = "105243"
DATE = "2026-09-15"
UP = "UP 3D 07:12"

# 3 色分组（HH / MM / SS 各一色）：粉 → 橙 → 蓝
CANDY3 = [CANDY6[0], CANDY6[0], CANDY6[1], CANDY6[1], CANDY6[4], CANDY6[4]]

SCHEMES = [
    dict(
        name="A  彩虹 6 色（推荐）",
        bg=hx("14101C"),
        card_top=CANDY6,
        card_bot=[mul(c, 0.72) for c in CANDY6],
        fold=hx("1A1224"),
        line=[mul(c, 1.14) for c in CANDY6],
        dig=hx("1E1526"),          # 深墨紫（比纯黑柔和，仍是糖果调）
        date=hx("9A8CB4"),
        up=hx("4E4460"),
        colon=hx("FF7FA8"),
        gloss=True,
    ),
    dict(
        name="A2 彩虹 3 色分组",
        bg=hx("14101C"),
        card_top=CANDY3,
        card_bot=[mul(c, 0.72) for c in CANDY3],
        fold=hx("1A1224"),
        line=[mul(c, 1.14) for c in CANDY3],
        dig=hx("1E1526"),
        date=hx("9A8CB4"),
        up=hx("4E4460"),
        colon=hx("FF7FA8"),
        gloss=True,
    ),
    dict(
        name="B  糖果店 · 奶油",
        bg=hx("FFF6EC"),
        card_top=MACARON6,
        card_bot=[mul(c, 0.90) for c in MACARON6],
        fold=hx("E8D8CC"),
        line=[mul(c, 0.86) for c in MACARON6],
        dig=hx("5A4A5E"),
        date=hx("A895A8"),
        up=hx("C9BCC9"),
        colon=hx("C0A2B4"),
        gloss=True,
    ),
    dict(
        # 本次选定：卡片底色 + 全部字符色沿用 B，仅把背景换成实机时钟页的纯黑
        # （main.cpp: C_BG_W = RGB(0,0,0)，与其它三页的 #0E0E13 不同）
        name="B2 奶油糖 · 黑底（无框）",
        bg=hx("000000"),
        card_top=MACARON6,
        card_bot=[mul(c, 0.90) for c in MACARON6],
        fold=hx("E8D8CC"),
        line=None,                 # 去掉卡片 1px 描边框线，让糖果色块更干净
        dig=hx("5A4A5E"),
        date=hx("A895A8"),
        up=hx("C9BCC9"),
        colon=hx("C0A2B4"),
        gloss=True,
    ),
    dict(
        # 已落固件：clock_candy_main_3x.png，奶油底 + 6 色马卡龙卡 + 无框
        name="B3 糖果店 · 奶油（无框·实机）",
        bg=hx("FFF6EC"),
        card_top=MACARON6,
        card_bot=[mul(c, 0.90) for c in MACARON6],
        fold=hx("E8D8CC"),
        line=None,
        dig=hx("5A4A5E"),
        date=hx("A895A8"),
        up=hx("C9BCC9"),
        colon=hx("C0A2B4"),
        gloss=True,
    ),
    dict(
        name="C  彩虹电子（改动最小·无框）",
        bg=hx("0E0E13"),
        card_top=hx("24242E"),
        card_bot=hx("17171E"),
        fold=hx("08080C"),
        line=None,
        dig=CANDY6,                # 数字本身就是彩虹
        date=hx("8E8E93"),
        up=hx("48484A"),
        colon=hx("8E8E93"),
        gloss=False,
    ),
]


def draw_panel(s):
    img = Image.new("RGB", (SCR_W, SCR_H), s["bg"])
    d = ImageDraw.Draw(img)

    for i, x in enumerate(FC_X):
        ct = s["card_top"][i] if isinstance(s["card_top"], list) else s["card_top"]
        cb = s["card_bot"][i] if isinstance(s["card_bot"], list) else s["card_bot"]
        cl = s["line"][i]     if isinstance(s["line"], list)     else s["line"]
        cd = s["dig"][i]      if isinstance(s["dig"], list)      else s["dig"]

        # 上下半卡面（圆角矩形，各只在中缝一侧留直角感）
        d.rounded_rectangle([x, FC_Y, x + FC_W - 1, FC_Y + FC_HALF - 1], radius=3, fill=ct)
        d.rounded_rectangle([x, FC_Y + FC_HALF, x + FC_W - 1, FC_Y + FC_H - 1], radius=3, fill=cb)
        # 抹平中缝两侧的圆角缺口
        d.rectangle([x, FC_Y + FC_HALF - 4, x + FC_W - 1, FC_Y + FC_HALF - 1], fill=ct)

        # 糖衣高光：上半卡顶边 1px 提亮
        if s["gloss"]:
            d.rectangle([x + 2, FC_Y + 1, x + FC_W - 3, FC_Y + 1], fill=mul(ct, 1.28))

        # 数字（跨中缝居中，1:1 对齐实机 Font4 26px 布局）
        d.text((x + FC_W / 2, FC_Y + FC_H / 2), DIGITS[i],
               font=F_DIG, fill=cd, anchor="mm")

        # 中缝
        d.line([x + 1, FC_Y + FC_HALF, x + FC_W - 2, FC_Y + FC_HALF], fill=s["fold"])
        # 描边（最后画，压住圆角毛边）
        if cl is not None:
            d.rounded_rectangle([x, FC_Y, x + FC_W - 1, FC_Y + FC_H - 1],
                                radius=3, outline=cl, width=1)

    # 组间冒号点（2x2 两个）
    cy = FC_Y + FC_H // 2
    for k in (0, 1):
        cxx = (FC_X[1] + FC_W + 3) if k == 0 else (FC_X[3] + FC_W + 3)
        d.rectangle([cxx, cy - 6, cxx + 1, cy - 5], fill=s["colon"])
        d.rectangle([cxx, cy + 4, cxx + 1, cy + 5], fill=s["colon"])

    # 日期 / 开机时长
    d.text((SCR_W / 2, 92),  DATE, font=F_DATE, fill=s["date"], anchor="mm")
    d.text((SCR_W / 2, 112), UP,   font=F_UP,   fill=s["up"],   anchor="mm")
    return img


GAP = 10
panels = [draw_panel(s) for s in SCHEMES]

def strip_bg(w, h):
    return Image.new("RGB", (w, h), (0x22, 0x22, 0x28))

def save_strip(scale, path):
    W = SCR_W * len(panels) + GAP * (len(panels) - 1)
    out = strip_bg(W, SCR_H)
    for i, p in enumerate(panels):
        out.paste(p, (i * (SCR_W + GAP), 0))
    out = out.resize((W * scale, SCR_H * scale), Image.NEAREST)
    out.save(path)
    return out.size

print("1x ->", save_strip(1, OUT + "clock_candy_1x.png"))
print("2x ->", save_strip(2, OUT + "clock_candy_themes.png"))

# 候选方案单张放大（B2 / B3 / C，用于最终确认）
for MAIN_KEY in ("B2", "B3", "C"):
    a = panels[next(i for i, s in enumerate(SCHEMES) if s["name"].startswith(MAIN_KEY))]
    W, H = SCR_W * 3, SCR_H * 3
    big = Image.new("RGB", (W, H), (0x22, 0x22, 0x28))
    big.paste(a.resize((SCR_W * 3, SCR_H * 3), Image.NEAREST), (0, 0))
    big.save(OUT + "clock_candy_%s_3x.png" % MAIN_KEY)
    print("%s 3x ->" % MAIN_KEY, big.size)

# 局部 6x：看糖衣高光 / 中缝 / 数字边缘（用最后一张 C）
zx, zy, zw, zh = 4, FC_Y - 4, 50, FC_H + 10
crop = a.crop((zx, zy, zx + zw, zy + zh)).resize((zw * 6, zh * 6), Image.NEAREST)
crop.save(OUT + "clock_candy_zoom.png")
print("zoom ->", crop.size)
