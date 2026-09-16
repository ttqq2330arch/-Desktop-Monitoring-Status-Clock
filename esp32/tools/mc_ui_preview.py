# -*- coding: utf-8 -*-
"""
总览页《我的世界》主题 —— 设计稿预览生成器
================================================
输出 160x128 真实像素的设计稿（1:1 与 3 倍放大各一张），
用到的 5x7 像素字体表与方块图标表可直接搬进固件当 PROGMEM 数据。

色值全部取自 Minecraft 官方调色板：
  - 16 色格式化代码（minecraft.wiki/w/Formatting_codes）
  - 材质色 material_diamond / material_redstone 等（1.21.4+）
  - GUI 灰阶 #FFFFFF/#C6C6C6/#8B8B8B/#555555/#373737/#212121
  - 经验值绿 #80FF20（common_colors.json: experience_text）

无第三方依赖（自带极简 PNG 写入器），用任意 python3 直接跑。
"""
import zlib, struct, os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================ 配色（MC 官方）
def C(h):  # "55FF55" -> (85,255,85)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

MC_BLACK   = C("000000")
MC_DGRAY   = C("555555")   # §8 dark_gray
MC_GRAY    = C("AAAAAA")   # §7 gray
MC_WHITE   = C("FFFFFF")   # §f
MC_GREEN   = C("55FF55")   # §a
MC_AQUA    = C("55FFFF")   # §b
MC_BLUE    = C("5555FF")   # §9
MC_GOLD    = C("FFAA00")   # §6
MC_RED     = C("FF5555")   # §c
MC_LPURPLE = C("FF55FF")   # §d
MC_YELLOW  = C("FFFF55")   # §e
MC_XP      = C("80FF20")   # 经验条绿
MC_DIAMOND = C("2CBAA8")   # material_diamond
MC_REDSTONE= C("971607")   # material_redstone

GUI_PANEL  = C("373737")   # GUI 灰阶：面板底
GUI_DEEP   = C("212121")   # GUI 灰阶：最深
GUI_LIGHT  = C("8B8B8B")   # GUI 灰阶：亮面
GUI_DARK   = C("555555")   # GUI 灰阶：暗面

# 屏幕底：取 MC GUI 最深的灰阶，保持"近黑省电"又属于 MC 色板
SCR_BG     = GUI_DEEP
HEAD_BG    = GUI_PANEL
HEAD_HI    = GUI_DARK      # 顶栏上/左高光
HEAD_LO    = C("151515")   # 顶栏下/右阴影

# 五行指标色（全部落在 MC 16 色板内）
ROW_COLORS = [MC_AQUA, MC_GOLD, MC_BLUE, MC_LPURPLE, MC_GREEN]

# ============================================================ 5x7 像素字体
# 直接对应 MC 字体的字形骨架（全大写外观）。'#' 点亮。
# 这 44 个字形就是固件里要用的 PROGMEM 位图数据，等宽 5x7、步进 6px。
F = {
 ' ': ["     "]*7,
 '0': [".###.","#...#","#..##","#.#.#","##..#","#...#",".###."],
 '1': ["..#..",".##..","..#..","..#..","..#..","..#..",".###."],
 '2': [".###.","#...#","....#","...#.","..#..",".#...","#####"],
 '3': [".###.","#...#","....#","..##.","....#","#...#",".###."],
 '4': ["...#.","..##.",".#.#.","#..#.","#####","...#.","...#."],
 '5': ["#####","#....","####.","....#","....#","#...#",".###."],
 '6': ["..##.",".#...","#....","####.","#...#","#...#",".###."],
 '7': ["#####","....#","...#.","..#..",".#...",".#...",".#..."],
 '8': [".###.","#...#","#...#",".###.","#...#","#...#",".###."],
 '9': [".###.","#...#","#...#",".####","....#","...#.",".##.."],
 'A': [".###.","#...#","#...#","#####","#...#","#...#","#...#"],
 'B': ["####.","#...#","#...#","####.","#...#","#...#","####."],
 'C': [".###.","#...#","#....","#....","#....","#...#",".###."],
 'D': ["###..","#..#.","#...#","#...#","#...#","#..#.","###.."],
 'E': ["#####","#....","#....","####.","#....","#....","#####"],
 'F': ["#####","#....","#....","####.","#....","#....","#...."],
 'G': [".###.","#...#","#....","#..##","#...#","#...#",".###."],
 'H': ["#...#","#...#","#...#","#####","#...#","#...#","#...#"],
 'I': [".###.","..#..","..#..","..#..","..#..","..#..",".###."],
 'J': ["..###","...#.","...#.","...#.","...#.","#..#.",".##.."],
 'K': ["#...#","#..#.","#.#..","##...","#.#..","#..#.","#...#"],
 'L': ["#....","#....","#....","#....","#....","#....","#####"],
 'M': ["#...#","##.##","#.#.#","#...#","#...#","#...#","#...#"],
 'N': ["#...#","##..#","#.#.#","#..##","#...#","#...#","#...#"],
 'O': [".###.","#...#","#...#","#...#","#...#","#...#",".###."],
 'P': ["####.","#...#","#...#","####.","#....","#....","#...."],
 'Q': [".###.","#...#","#...#","#...#","#.#.#","#..#.",".##.#"],
 'R': ["####.","#...#","#...#","####.","#.#..","#..#.","#...#"],
 'S': [".####","#....","#....",".###.","....#","....#","####."],
 'T': ["#####","..#..","..#..","..#..","..#..","..#..","..#.."],
 'U': ["#...#","#...#","#...#","#...#","#...#","#...#",".###."],
 'V': ["#...#","#...#","#...#","#...#","#...#",".#.#.","..#.."],
 'W': ["#...#","#...#","#...#","#...#","#.#.#","##.##","#...#"],
 'X': ["#...#","#...#",".#.#.","..#..",".#.#.","#...#","#...#"],
 'Y': ["#...#","#...#",".#.#.","..#..","..#..","..#..","..#.."],
 'Z': ["#####","....#","...#.","..#..",".#...","#....","#####"],
 '%': ["##..#","##.#.","..#..",".#...","#....","#..##","...##"],
 ':': [".....","..#..","..#..",".....","..#..","..#..","....."],
 '.': [".....",".....",".....",".....",".....","..#..","..#.."],
 '-': [".....",".....",".....",".###.",".....",".....","....."],
 '/': ["....#","....#","...#.","..#..",".#...","#....","#...."],
 '#': [".#.#.",".#.#.","#####",".#.#.","#####",".#.#.",".#.#."],
 'DEG':[".##..","#..#.",".##..",".....",".....",".....","....."],
 # 上下行方向箭头（NET 行用）：用 ^ / ~ 两个字符索引
 '^': ["..#..",".###.","#####","..#..","..#..","..#..","..#.."],
 '~': ["..#..","..#..","..#..","..#..","#####",".###.","..#.."],
}
GLYPH_W, GLYPH_H, ADV = 5, 7, 6   # 字宽 / 字高 / 步进


# ============================================================ 极简画布
class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = [[bg] * w for _ in range(h)]

    def rect(self, x, y, w, h, c):
        if c is None: return
        for yy in range(max(0, y), min(self.h, y + h)):
            row = self.px[yy]
            for xx in range(max(0, x), min(self.w, x + w)):
                row[xx] = c

    def pix(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h: self.px[y][x] = c

    def bevel(self, x, y, w, h, hi, lo, fill):
        """MC 招牌立体边框：上/左=hi，下/右=lo（1px）"""
        self.rect(x, y, w, h, fill)
        self.rect(x, y, w, 1, hi);            self.rect(x, y, 1, h, hi)
        self.rect(x, y + h - 1, w, 1, lo);    self.rect(x + w - 1, y, 1, h, lo)


def text(cv, s, x, y, scale, color, bold=False, shadow=None):
    """在 (x,y) 左上角画 5x7 像素字。shadow 传入即画 MC 招牌右下 1px 投影。"""
    s = s.upper()
    if shadow:
        cx = x
        for ch in s:
            g = F.get(ch, F[' '])
            for r in range(GLYPH_H):
                for c in range(GLYPH_W):
                    if g[r][c] == '#':
                        cv.rect(cx + c * scale + scale, y + r * scale + scale, scale, scale, shadow)
            cx += ADV * scale
    cx = x
    for ch in s:
        g = F.get(ch, F[' '])
        for r in range(GLYPH_H):
            for c in range(GLYPH_W):
                if g[r][c] == '#':
                    cv.rect(cx + c * scale, y + r * scale, scale, scale, color)
                    if bold:
                        cv.rect(cx + c * scale + scale, y + r * scale, scale, scale, color)
        cx += ADV * scale


def text_w(s, scale, bold=False):
    return len(s) * ADV * scale - scale + (scale if bold else 0)


# ============================================================ 12x12 MC 方块图标
ICONS = {
 # 熔炉（石框 + 炉口 + 火焰）—— CPU
 'CPU': ("cccccccccccc" "cbbbbbbbbbbc" "cbbbbbbbbbbc" "cbbaaaaaabbc"
         "cbbaddddabbc" "cbbaddddabbc" "cbbaddddabbc" "cbbaffffabbc"
         "cbbafggfabbc" "cbbaffffabbc" "cbbaaaaaabbc" "cccccccccccc",
         {'a': C("565656"), 'b': C("7C7C7C"), 'c': C("9B9B9B"),
          'd': C("1A1A1A"), 'f': C("FF8C00"), 'g': C("FFE05A")}),
 # 箱子（木纹 + 锁扣）—— RAM
 'RAM': ("pppppppppppp" "prrrrrrrrrrp" "prqqqqqqqqrp" "prqqqqqqqqrp"
         "prrrrrrrrrrp" "prqqssssqqrp" "prqqssssqqrp" "prqqqqqqqqrp"
         "prqqqqqqqqrp" "prqqqqqqqqrp" "prqqqqqqqqrp" "pppppppppppp",
         {'p': C("4A2F1A"), 'q': C("8C5A32"), 'r': C("B07C48"), 's': C("1E140E")}),
 # 信标（青色宝石）—— NET
 'NET': ("tttttttttttt" "tttuuuuuuutt" "ttuuvvvvuutt" "tuuvwwwwvuut"
         "tuuvwwwwvuut" "tuuuvvvvuuut" "ttuuuvvuuutt" "tttuuuuuuutt"
         "ttttuuuutttt" "tttttttttttt" "tttttttttttt" "tttttttttttt",
         {'t': C("0A465A"), 'u': C("3CA0C8"), 'v': MC_AQUA, 'w': C("E6FFFF")}),
 # 附魔台（黑曜石紫 + 符文）—— GPU
 'GPU': ("oooooooooooo" "ozzzzzzzzzzo" "ozoooooooozo" "ozonnnnnnozo"
         "ozonnnnnnozo" "ozoooooooozo" "ozzzzzzzzzzo" "ozmmmmmmmmzo"
         "ozzzzzzzzzzo" "oooooooooooo" "oooooooooooo" "oooooooooooo",
         {'o': C("1C1026"), 'z': C("5A2882"), 'm': C("AA00AA"), 'n': MC_AQUA}),
}

# 圆石（浅灰底 + 深灰石块轮廓）—— DSK
# 历史：曾用 _stone() 固定种子生成「3 级灰度随机点阵」。12x12 的随机点在 1x 屏上等于电视雪花，
#       位置又正在状态页左下角，肉眼读不出是图标 —— 用户多次报的「左下角乱码」即含此项。
#       改为结构性石块分布后，与 CPU(熔炉)/RAM(箱子)/NET(信标)/GPU(附魔台) 同为可辨认方块。
ICONS['DSK'] = (
    "cccccccccccc"
    "cbbbbbbbbbbc"
    "cbddbbbbddbc"
    "cbddbbbbddbc"
    "cbbbbbbbbbbc"
    "cbbbbddbbbbc"
    "cbbbbddbbbbc"
    "cbbbbbbbbbbc"
    "cbddbbbbddbc"
    "cbddbbbbddbc"
    "cbbbbbbbbbbc"
    "cccccccccccc",
    {'b': C("7C7C7C"), 'c': C("9B9B9B"), 'd': C("565656")})


def draw_icon(cv, key, x, y, size=12):
    """把方块图标嵌进 MC 物品栏式凹槽（上/左暗、下/右亮的凹陷边框）"""
    cv.bevel(x, y, size + 2, size + 2, C("141414"), C("565656"), C("2A2A2A"))
    art, pal = ICONS[key]
    for r in range(size):
        for c in range(size):
            cv.pix(x + 1 + c, y + 1 + r, pal[art[r * size + c]])


# ============================================================ 分段经验条
def draw_xp_bar(cv, x, y, w, h, pct, fill):
    """MC 经验条式：凹陷槽（上/左暗、下/右亮）+ 分段填充"""
    cv.bevel(x, y, w, h, GUI_DARK, GUI_LIGHT, MC_BLACK)
    iw, ih = w - 2, h - 2
    cell = 3          # 每格宽
    gap = 1           # 格间隔
    total = (iw + gap) // (cell + gap)          # 总格数
    on = 0 if pct < 0 else int(total * max(0, min(100, pct)) / 100.0 + 0.5)
    for i in range(on):
        cv.rect(x + 1 + i * (cell + gap), y + 1, cell, ih, fill)


# ============================================================ 主界面绘制
SCR_W, SCR_H = 160, 128
HEAD_H = 17
ROW_H = 21
ROW_TOP = HEAD_H + 2
N_ROWS = 5

def draw_screen(st):
    cv = Canvas(SCR_W, SCR_H, SCR_BG)

    # ---------------- 顶栏：MC 深色面板 + 立体边框
    cv.rect(0, 0, SCR_W, HEAD_H, HEAD_BG)
    # 刻意不画 y=0 上高光：屏幕第 0 行是推屏写入与面板扫描冲突最重的位置，
    # 高对比 1px 亮线在实机上会显形为「闪跳的横线」。顶栏贴屏幕物理边缘，
    # 不需要上高光；立体感由下阴影 + 黑缝承担。
    cv.rect(0, HEAD_H - 1, SCR_W, 1, HEAD_LO)     # 下阴影
    cv.rect(0, HEAD_H, SCR_W, 1, MC_BLACK)

    # 时间（2 倍字 + MC 投影）
    text(cv, st['time'], 3, 1, 2, MC_WHITE, shadow=C("3F3F3F"))

    # 页码指示：MC 方块代替圆点
    n = 4
    bw, gap = 4, 3
    total = n * bw + (n - 1) * gap
    dx = (SCR_W - total) // 2
    for i in range(n):
        bx = dx + i * (bw + gap)
        if i == st['page']:
            cv.bevel(bx, 5, bw, bw, MC_AQUA, C("0F6E56"), MC_AQUA)
        else:
            cv.bevel(bx, 5, bw, bw, GUI_DARK, C("151515"), C("2A2A2A"))

    # 日期 / 开机时长（1 倍字，右对齐）
    rt = st['date'] + " " + st['uptime']
    text(cv, rt, SCR_W - 4 - text_w(rt, 1), 5, 1,
         MC_RED if st['stale'] else MC_GRAY)

    # ---------------- 五行指标
    for i, m in enumerate(st['rows']):
        top = ROW_TOP + i * ROW_H
        c1 = top + 8      # 主行中心（标签 / 条 / 主值）
        c2 = top + 16     # 副行中心（副值）

        draw_icon(cv, m['icon'], 2, top + 2)

        text(cv, m['label'], 18, c1 - 3, 1, MC_GRAY, shadow=C("1A1A1A"))

        vc = m['color']
        if m['pct'] >= 85:   vc = MC_RED
        elif m['pct'] >= 60: vc = MC_YELLOW
        elif m['pct'] < 0:   vc = MC_GRAY

        draw_xp_bar(cv, 52, c1 - 3, 76, 6, m['pct'], vc)

        vw = text_w(m['value'], 1, bold=True)
        text(cv, m['value'], 156 - vw, c1 - 3, 1, MC_WHITE, bold=True,
             shadow=C("3F3F3F"))

        text(cv, m['aux'], 52, c2 - 3, 1, MC_DGRAY)

    return cv


# ============================================================ PNG 输出（无依赖）
def save_png(path, cv, scale=1):
    w, h = cv.w * scale, cv.h * scale
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        row = cv.px[y // scale]
        for x in range(w):
            raw += bytes(row[x // scale])
    def chunk(t, d):
        return (struct.pack('>I', len(d)) + t + d +
                struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)
    return len(png)


# ============================================================ 示例数据
DEMO = {
    'time': '14:40', 'date': '09-14', 'uptime': '2D3H',
    'page': 0, 'stale': False,
    'rows': [
        {'icon': 'CPU', 'label': 'CPU', 'pct': 45,  'value': '45%',  'aux': '52C',    'color': ROW_COLORS[0]},
        {'icon': 'RAM', 'label': 'RAM', 'pct': 62,  'value': '62%',  'aux': '9.8G',   'color': ROW_COLORS[1]},
        {'icon': 'NET', 'label': 'NET', 'pct': -1,  'value': '1.2M', 'aux': '^340K',  'color': ROW_COLORS[2]},
        {'icon': 'GPU', 'label': 'GPU', 'pct': 88,  'value': '88%',  'aux': '74C',    'color': ROW_COLORS[3]},
        {'icon': 'DSK', 'label': 'DSK', 'pct': 71,  'value': '71%',  'aux': '120G',   'color': ROW_COLORS[4]},
    ],
}


if __name__ == '__main__':
    cv = draw_screen(DEMO)
    p1 = os.path.join(OUT_DIR, 'mc_overview_1x.png')
    p3 = os.path.join(OUT_DIR, 'mc_overview_3x.png')
    a = save_png(p1, cv, 1)
    b = save_png(p3, cv, 3)
    print('1x ->', p1, a, 'bytes')
    print('3x ->', p3, b, 'bytes')

    # 字形总表（校对 5x7 点阵用）
    keys = [k for k in F if len(k) == 1 and k != ' ']
    cols = 15
    rows = (len(keys) + cols - 1) // cols
    sheet = Canvas(cols * 8 + 4, rows * 12 + 4, C("202020"))
    for i, k in enumerate(keys):
        gx = 2 + (i % cols) * 8
        gy = 2 + (i // cols) * 12
        text(sheet, k, gx, gy, 1, MC_WHITE)
    ps = os.path.join(OUT_DIR, 'mc_glyph_sheet.png')
    save_png(ps, sheet, 3)
    print('glyph sheet ->', ps, '(%d glyphs)' % len(keys))

    # 局部放大：图标列 + 进度条（校对凹槽与分段效果）
    zx, zy, zw, zh = 0, ROW_TOP - 2, 60, 66
    zc = Canvas(zw, zh, SCR_BG)
    for y in range(zh):
        for x in range(zw):
            zc.px[y][x] = cv.px[zy + y][zx + x]
    pz = os.path.join(OUT_DIR, 'mc_overview_zoom.png')
    save_png(pz, zc, 6)
    print('zoom ->', pz)

    print('逻辑分辨率 %dx%d，字形 %dx%d 步进 %dpx' % (SCR_W, SCR_H, GLYPH_W, GLYPH_H, ADV))
