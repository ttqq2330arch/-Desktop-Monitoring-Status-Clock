# -*- coding: utf-8 -*-
"""Host-side self test for cn_font.h + drawMonthTitle layout.

1. Parse cn_font.h, decode each glyph bitmap, print ASCII (round-trip check).
2. Verify all 12 glyphs are exactly 32 bytes and non-empty.
3. Simulate drawMonthTitle centering math for a 160px wide screen and
   assert the composite title stays within bounds.
"""
import os as _pathos
_HERE = _pathos.path.dirname(_pathos.path.abspath(__file__)).replace('\\', '/')
_TOOLS_DIR = _HERE + '/'
_SRC_DIR = _pathos.normpath(_HERE + '/../src').replace('\\', '/') + '/'
_BASE_DIR = _pathos.normpath(_HERE + '/..').replace('\\', '/')

import re, sys

H_PATH = _SRC_DIR + "cn_font.h"
SCR_W = 160
CH = "年月一二三四五六七八九十"
NAMES = ["CN_NIAN","CN_YUE","CN_1","CN_2","CN_3","CN_4","CN_5","CN_6","CN_7","CN_8","CN_9","CN_10"]

src = open(H_PATH, encoding="utf-8").read()
# enum sanity
m = re.search(r"enum \{([^}]*)\};", src)
enum_names = [s.strip() for s in m.group(1).split(",")]
assert enum_names == NAMES, f"enum mismatch: {enum_names}"

# glyph bodies appear as lines like: {0x00,0x00,...} following a "// 字" comment
blocks = re.findall(r"// (.)\n\s*\{([0-9A-Fx,]+)\},", src)
assert len(blocks) == 12, f"expected 12 glyphs, got {len(blocks)}"

glyphs = {}
for ch, body in blocks:
    vals = [int(v, 16) for v in body.split(",")]
    assert len(vals) == 32, f"{ch}: {len(vals)} bytes != 32"
    assert any(vals), f"{ch}: empty bitmap"
    rows = []
    for r in range(16):
        word = (vals[r*2] << 8) | vals[r*2+1]
        rows.append("".join("#" if word & (0x8000 >> c) else "." for c in range(16)))
    glyphs[ch] = rows

# digit widths: FreeSansBold-ish digits measured on device are ~9px @font14;
# use 9px as the value monitor uses (any value passes bounds test)
def digit_w(n_str): return 9 * len(n_str)

def title_layout(year, month):
    yb, mb = str(year), str(month)
    wy, wm = digit_w(yb), digit_w(mb)
    gap = 3
    total = wy + gap + 16 + gap + wm + gap + 16
    x = (SCR_W - total) // 2
    return x, total

for (y, m) in [(2026, 9), (2026, 12), (1999, 1)]:
    x, total = title_layout(y, m)
    assert x >= 0 and x + total <= SCR_W, f"out of bounds for {y}-{m}"
    print(f"title {y}年{m}月 -> x={x}, width={total}  [OK]")

print()
print("glyph round-trip (from cn_font.h):")
for ch in CH:
    print(ch + ":")
    print("\n".join(glyphs[ch]))
print()
print("ALL HOST TESTS PASSED")
