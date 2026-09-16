# -*- coding: utf-8 -*-
"""左下角 DSK 图标对比稿：现役「石头噪点」 vs 候选「清晰圆石」。

背景：状态页左下角（逻辑 x=2..15, y=107..120）是 DSK 行的方块图标。现役图标由
      mc_ui_preview.py 的 _stone() 用固定种子程序化生成 3 级灰度随机点阵 —— 12x12 的
      随机点在 1x 屏上就是电视雪花，肉眼读不出是什么。用户多次报的「左下角乱码」很可能是它。
本脚本只出设计稿，不改固件；确认后再改 mc_ui_preview.py 的 ICONS['DSK'] 并跑 gen_mc_theme.py。

输出：dsk_icon_8x.png（细节，8 倍）、dsk_icon_1x.png（实尺，1 倍，左现役 / 右候选）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mc_ui_preview as M          # noqa: E402

C = M.C

# ---- 候选：MC 圆石。浅灰底 + 深灰石块轮廓，四大两小的石块分布，12x12 同规格。
#      与现役 CPU(熔炉)/RAM(箱子)/NET(信标)/GPU(附魔台) 同为「可辨认的 MC 方块」。
CAND_DSK = ("cccccccccccc"
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
            "cccccccccccc")
M.ICONS['DSK_CAND'] = (CAND_DSK, {'b': C("7C7C7C"), 'c': C("9B9B9B"), 'd': C("565656")})

SLOT = 14            # 凹槽外框 14x14（= mcIcon 的 MC_ICON_SZ + 2）
GAP = 6
PANEL_BG = C("0A0A0A")


def compare_canvas():
    """左=现役石头噪点，右=候选清晰圆石，各自嵌在同规格凹槽里。"""
    cv = M.Canvas(SLOT * 2 + GAP, SLOT, PANEL_BG)
    M.draw_icon(cv, 'DSK', 0, 0)                 # 现役：_stone() 噪点
    M.draw_icon(cv, 'DSK_CAND', SLOT + GAP, 0)   # 候选：清晰圆石
    return cv


if __name__ == '__main__':
    cv = compare_canvas()
    for name, scale in (('dsk_icon_8x', 8), ('dsk_icon_1x', 1)):
        p = os.path.join(HERE, name + '.png')
        n = M.save_png(p, cv, scale)
        print('%s -> %d bytes  %s' % (name + '.png', n, p))
    print('面板尺寸 %dx%d 像素（左：现役噪点 / 右：候选圆石）' % (cv.w, cv.h))
    print('候选点阵相对现役的改变：随机 3 级灰度 -> 结构性石块分布，1x 下可辨认')
