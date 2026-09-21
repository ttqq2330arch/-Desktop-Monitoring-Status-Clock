# -*- coding: utf-8 -*-
"""
固件级模拟渲染（第1页 · 四环）
================================
目的：烧录**之前**确认 main.cpp 的 drawOverview()/jCell()/jRing() 会画出什么。
      设计稿（st_ui_themes4.draw_J）用的是它自己的 ring() 数学；固件走的是
      LovyanGFX 的 fill_arc_helper —— 两者角度一致但像素边界判据不同
      （`ir*(ir-1)` vs `ri²<=d²<=ro²`），环壁会差 ~1px。
      所以这里用【移植自 LovyanGFX 的 fill_arc_helper】+【与固件同公式的字宽】
      重画一遍，再与设计稿逐像素比对，把「固件 = 设计稿」这件事验证掉。

参数来源：main.cpp 第1页段（J_BG/J_INK/J_LABEL/J_DIM/J_TRACK/J_ACC/J_WARN/J_CRIT、
         J_RO=22/J_RI、J_CX/J_CY、jColor()、jRing()、jCell()）。

用法：python sim_firmware_j.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mc_ui_preview import Canvas, text, text_w, save_png, C  # noqa: E402
from _lgfx_arc import lgfx_fill_arc                           # noqa: E402
from st_ui_themes3 import DEMO4                           # noqa: E402

SCR_W, SCR_H = 160, 128
OUT = os.path.dirname(os.path.abspath(__file__))

# ---- main.cpp 的常量（逐值抄；改 main.cpp 记得同步这里） ----
J_BG    = C("0E1116")
J_INK   = C("E8EDF2")
J_LABEL = C("8A95A1")   # 环内标签
J_DIM   = C("5A646F")   # 顶栏日期（比标签更暗）
J_TRACK = C("232A32")
J_ACC   = C("3D8BFD")
J_CRIT  = C("FF2A2A")   # ★必须与固件 J_CRIT 同值
J_HOT_PCT = 80      # ★ 只有两档：>=80% 转红（80..89 的琥珀档已按用户要求删除）
J_RO, J_RI = 22, 17
J_CX = (48, 112, 48, 112)
J_CY = (47, 47, 97, 97)


def j_color(label, pct):
    """只有两档：正常蓝 / 过高红（与 main.cpp 的 jColor 逐条对应）"""
    if label[0] == 'N' or pct < 0:
        return J_ACC
    if pct >= J_HOT_PCT:
        return J_CRIT
    return J_ACC


def j_ring(cv, cx, cy, pct, col):
    """固件 jRing()：fillArc(0,360) 轨道 + fillArc(270, 270+3.6p) 进度"""
    clip = (0, 0, SCR_W - 1, SCR_H - 1)
    for (x, y) in lgfx_fill_arc(cx, cy, J_RO, J_RI, 0, 360, clip):
        cv.pix(x, y, J_TRACK)
    if pct <= 0:
        return
    p = min(100, pct)
    for (x, y) in lgfx_fill_arc(cx, cy, J_RO, J_RI, 270.0, 270.0 + 3.6 * p, clip):
        cv.pix(x, y, col)


def j_cell(cv, i, label, val, pct):
    cx, cy = J_CX[i], J_CY[i]
    j_ring(cv, cx, cy, pct, j_color(label, pct))
    text(cv, label, cx - text_w(label, 1, False) // 2, cy - 10, 1, J_LABEL)
    text(cv, val,   cx - text_w(val,   1, True ) // 2, cy +  2, 1, J_INK, bold=True)


def draw_fw(st):
    cv = Canvas(SCR_W, SCR_H, J_BG)
    # 时钟带：mcStr(time,4,3,J_INK,2,0,false) / mcStrRight(dt,156,10,J_DIM,1,0,false)
    text(cv, st['time'], 4, 3, 2, J_INK)
    rt = '%s %s' % (st['date'], st['uptime'])
    text(cv, rt, 156 - text_w(rt, 1), 10, 1, J_DIM)
    for i, m in enumerate(st['rows'][:4]):
        j_cell(cv, i, m['label'], m['value'], m['pct'])
    return cv


def diff_vs_design(fw, ds):
    n = 0
    for y in range(SCR_H):
        for x in range(SCR_W):
            if fw.px[y][x] != ds.px[y][x]:
                n += 1
    return n


if __name__ == '__main__':
    from st_ui_themes4 import draw_J
    ds = draw_J(DEMO4)

    fw = draw_fw(DEMO4)
    p = os.path.join(OUT, 'st_fw_j_ring_4x.png')
    n = save_png(p, fw, 4)
    print('固件模拟 -> %s  (%d bytes)' % (p, n))

    total = SCR_W * SCR_H
    d = diff_vs_design(fw, ds)
    print('与设计稿差异像素: %d / %d  (%.2f%%)' % (d, total, 100.0 * d / total))

    print()
    print('--- 内半径扫描（找壁厚最接近设计稿的 J_RI）---')
    for ri in (17, 18, 19):
        J_RI = ri
        fw2 = draw_fw(DEMO4)
        d2 = diff_vs_design(fw2, ds)
        ring_px = len(lgfx_fill_arc(48, 47, J_RO, ri, 0, 360, (0, 0, 159, 127)))
        print('  J_RI=%d  环满圈像素=%-4d  与设计稿差异=%d (%.2f%%)'
              % (ri, ring_px, d2, 100.0 * d2 / total))

    # 设计稿满圈的像素数（作对照）
    from st_ui_themes4 import ring as ds_ring
    cv_tmp = Canvas(SCR_W, SCR_H, J_BG)
    ds_ring(cv_tmp, 48, 47, J_RO, J_RI, 100, C("000000"), C("FFFFFF"))
    n_ds = sum(1 for y in range(SCR_H) for x in range(SCR_W)
               if cv_tmp.px[y][x] == C("FFFFFF"))
    print('  设计稿 ring(ro=22,ri=%d) 满圈像素=%d  ← 目标' % (J_RI, n_ds))

    J_RI = 17   # 恢复被扫描循环改掉的值（扫描只用于选型）
    from st_ui_themes import selfcheck
    selfcheck('FW_J', draw_fw(DEMO4))
