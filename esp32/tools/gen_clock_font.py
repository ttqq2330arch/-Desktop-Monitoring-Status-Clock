# -*- coding: utf-8 -*-
"""
翻页时钟数字掩码生成器 —— 多字体版。

输出 src/clock_fonts.h：N 套字体的 4-bit alpha 掩码表 + 字体名表。
固件长按按键循环切换，便于在设备上现场比对字形（挑定后可把 FONTS 精简为 1 项）。

每套字体的 (size, BOLD_R) 经实测定标流程得出，约束：
  - 墨迹高度 inkH ≈ 23~24px（与原先单字体方案一致，换字体不改数字大小）；
  - 所有数字左右各留 >=1px（20px 数列内不裁边）；
  - BOLD_R 取「仍满足上式」的最大膨胀半径。
本脚本生成时会**再次自检**这些约束，任何数字触边即报错提醒调整参数。

管线（与设计稿 render_clock_candy.py、固件 blitHalf 的 alpha 混合一致）：
    超采样(SS=4) 渲染 -> 形态学膨胀加粗(BOLD_R) -> LANCZOS 降采样 -> 4bit 量化
加粗做在超采样大图上，所以加粗后边缘依然是抗锯齿的（不是把小图涂满）。

历史坑（2026-09-15）：
  - 1-bit 二值化会把所有曲线变阶梯锯齿 -> 必须用连续覆盖度 + 4bit alpha；
  - 字体若横向超框（如 Baloo 2 这类圆胖宽体），定标时须先满足余量约束再谈墨迹高度。
"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import os

TOOLS = _TOOLS_DIR
OUT_H = _SRC_DIR + "clock_fonts.h"
OUT_PNG = TOOLS + "clock_font_preview.png"

FC_GW, FC_H = 20, 42
SS = 4
ALPHA_MAX = 15
COV_CUT = 0.06

# 启用的字体集：顺序 = 设备上长按切换的顺序。
# (显示名, 字体路径, 可变字体实例名, 字号, 加粗半径)
FONTS = [
    ("Fredoka",   TOOLS + "fonts/Fredoka_wdth_wght.ttf", "Bold", 30, 2),
    ("Nunito",    TOOLS + "fonts/Nunito_wght.ttf",       "Bold", 29, 3),
    ("Poppins",   TOOLS + "fonts/Poppins-Bold.ttf",      None,   28, 2),
    # Trebuchet MS 是 Microsoft 商业字体，无再分发授权，仓库不收录（见 THIRD_PARTY.md）。
    # 本机装了就读，没装就跳过。
    ("Trebuchet", "C:/Windows/Fonts/trebucbd.ttf",       None,   30, 3),
]

# 字体文件缺失即跳过 —— 保证在没装 Trebuchet MS 的机器（Linux / macOS / 干净 Windows）上也能生成
_missing = [f[0] for f in FONTS if not os.path.exists(f[1])]
if _missing:
    print("  [skip] 下列字体不存在，已跳过：%s" % ", ".join(_missing))
FONTS = [f for f in FONTS if os.path.exists(f[1])]
if not FONTS:
    raise SystemExit("没有可用字体，无法生成 clock_fonts.h（见 THIRD_PARTY.md）")

_FC = {}


def load_font(path, size, var=None):
    key = (path, size, var)
    if key in _FC:
        return _FC[key]
    f = ImageFont.truetype(path, size)
    if var:
        try:
            f.set_variation_by_name(var)
        except Exception as e:
            print("  [warn] set_variation_by_name(%s) 失败: %s" % (var, e))
    _FC[key] = f
    return f


def render_alpha(digit, path, size, bold_r, var=None):
    """返回 4-bit alpha 掩码 [FC_H][FC_GW]，与固件读取布局一致（行优先）。"""
    W, H = FC_GW * SS, FC_H * SS
    img = Image.new("L", (W, H), 255)
    f = load_font(path, size * SS, var)
    ImageDraw.Draw(img).text((W / 2, H / 2), digit, font=f, fill=0, anchor="mm")
    if bold_r > 0:
        img = ImageOps.invert(ImageOps.invert(img).filter(ImageFilter.MaxFilter(2 * bold_r + 1)))
    small = img.resize((FC_GW, FC_H), Image.LANCZOS)
    out = []
    for y in range(FC_H):
        row = []
        for x in range(FC_GW):
            c = (255 - small.getpixel((x, y))) / 255.0
            row.append(0 if c < COV_CUT else max(1, min(ALPHA_MAX, int(round(c * ALPHA_MAX)))))
        out.append(row)
    return out


def bbox(m):
    pts = [(x, y) for y in range(FC_H) for x in range(FC_GW) if m[y][x]]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def main():
    sheets = []
    problems = []
    for name, path, var, size, bold in FONTS:
        if not os.path.exists(path):
            problems.append("%s: 字体文件不存在 %s" % (name, path))
            continue
        masks = [render_alpha(str(d), path, size, bold, var) for d in range(10)]
        # 自检：墨迹范围与左右余量
        hs, lx, rx, dens = [], 99, 99, []
        for d in range(10):
            b = bbox(masks[d])
            if b is None:
                problems.append("%s: 数字 %d 无墨迹" % (name, d))
                continue
            x0, x1, y0, y1 = b
            hs.append(y1 - y0 + 1)
            lx, rx = min(lx, x0), min(rx, FC_GW - 1 - x1)
            dens.append(sum(1 for y in range(FC_H) for x in range(FC_GW) if masks[d][y][x])
                        / float(FC_GW * FC_H))
        ink = sum(dens) / max(1, len(dens))
        tag = ""
        if lx < 1 or rx < 1:
            tag = "  ⚠⚠ 触边会被裁"
            problems.append("%s: 左右余量 L=%d R=%d，会裁边（请调小 size 或 BOLD_R）" % (name, lx, rx))
        print("  %-10s size=%2d BOLD_R=%d  inkH=%2d  L=%d R=%d  ink=%4.1f%%%s"
              % (name, size, bold, max(hs) if hs else 0, lx, rx, ink * 100, tag))
        sheets.append((name, path, var, size, bold, masks, ink, lx, rx, max(hs) if hs else 0))

    lines = [
        "// 自动生成：翻页时钟数字掩码（多字体 · 4-bit alpha 抗锯齿）。",
        "// 由 tools/gen_clock_font.py 生成，请勿手改。",
        "// 值域 0..15：0=纯背景，15=纯墨迹，中间为边缘覆盖度。",
        "// 固件：短按按键切页，长按按键循环切换字体（CLOCK_FONT_COUNT 套）。",
        "// 每套字体的 (size, BOLD_R) 经实测定标流程确定：",
        "//   约束 = 墨迹高度≈23~24px 且所有数字左右各留 >=1px（20px 数列内不裁边）。",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "#define CLOCK_FONT_W %d" % FC_GW,
        "#define CLOCK_FONT_H %d" % FC_H,
        "#define CLOCK_FONT_A_MAX %d" % ALPHA_MAX,
        "#define CLOCK_FONT_COUNT %d" % len(sheets),
        "",
        "// 字体名（切换时显示在屏幕上，便于辨认当前用的是哪一套）",
        "static const char* const CLOCK_FONT_NAME[CLOCK_FONT_COUNT] = {",
        "  " + ", ".join('"%s"' % s[0] for s in sheets),
        "};",
        "",
        "// [字体][数字][行][列]，行优先。",
        "static const uint8_t CLOCK_FONTS[CLOCK_FONT_COUNT][10][%d][%d] PROGMEM = {" % (FC_H, FC_GW),
    ]
    for i, (name, path, var, size, bold, masks, ink, lx, rx, ih) in enumerate(sheets):
        lines.append("  {  // [%d] %s  size=%d BOLD_R=%d inkH=%d ink=%.1f%%"
                     % (i, name, size, bold, ih, ink * 100))
        for d in range(10):
            lines.append("    {  // digit %d" % d)
            for y in range(FC_H):
                row = "      {" + ", ".join(str(masks[d][y][x]) for x in range(FC_GW)) + "}"
                lines.append(row + ("," if y < FC_H - 1 else ""))
            lines.append("    }" + ("," if d < 9 else ""))
        lines.append("  }" + ("," if i < len(sheets) - 1 else ""))
    lines.append("};")
    lines.append("")

    with open(OUT_H, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("written:", OUT_H, os.path.getsize(OUT_H), "bytes")

    # 预览：每套字体一行，0-9 顺序
    if sheets:
        sc, gap = 5, 2
        cw, ch = FC_GW * sc, FC_H * sc
        img = Image.new("RGB", (10 * cw + 9 * gap, (ch + gap) * len(sheets)), (16, 16, 20))
        for i, (name, path, var, size, bold, masks, *rest) in enumerate(sheets):
            for d in range(10):
                cell = Image.new("RGB", (FC_GW, FC_H), (0x24, 0x24, 0x2E))
                dc = ImageDraw.Draw(cell)
                for y in range(FC_H):
                    for x in range(FC_GW):
                        a = masks[d][y][x]
                        if a:
                            g = int(a * 255 / ALPHA_MAX)
                            dc.point((x, y), fill=(g, g, g))
                img.paste(cell.resize((cw, ch), Image.NEAREST), (d * (cw + gap), i * (ch + gap)))
        img.save(OUT_PNG)
        print("preview ->", OUT_PNG, img.size)

    if problems:
        print("\n[!] 存在问题：")
        for p in problems:
            print("   ", p)
        raise SystemExit(1)
    print("self-check: OK（无数字触边）")


if __name__ == "__main__":
    main()
