#!/usr/bin/env python3
"""2026-10-13 新增 / 修正的純函式離線測試（不碰遊戲）。uv run --no-project python tools/gui/test_session_0913.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


import depotlvl1920 as dl  # noqa: E402
import dino1920 as dino  # noqa: E402
import fullrun1920 as fr  # noqa: E402
import fullrun_watchdog as wd  # noqa: E402
import newbiebox1920 as nb  # noqa: E402
import petrest1920 as pr  # noqa: E402
import petfetchimg1920 as pf  # noqa: E402

# 金飛 1 級門檻：真 1 級實測 0.72~0.96，133 級約 0.35
check('1 級判讀門檻 0.60', (dl.GLOBAL_MIN, dl.WINDOW_MIN), (0.60, 0.60))
check('0.72/0.64 算 1 級、0.35/0.47 不算', (0.72 >= dl.GLOBAL_MIN and 0.64 >= dl.WINDOW_MIN, 0.35 >= dl.GLOBAL_MIN and 0.47 >= dl.WINDOW_MIN), (True, False))

# 恐龍博士交付：走錯到守門人 / 精靈王時要擋
check('精靈王 / 覲見 / 守門人字樣都擋', all(any(k in t for k in dino.DANGER) for t in ('覲見精靈王', '你要進入裏面嗎', '那趕緊通過吧', '轉生的儀式')), True)
check('恐龍博士對話不被擋', any(k in '我是幫博士從事研究工作的人' for k in dino.DANGER), False)

# 人物資訊面板等級
check('人物資訊等級取轉後級前', fr.parse_info_level(['1轉131級(10000342)', '1轉131級(000342)']), 131)
check('人物資訊等級：掉位數不採信（只剩「1轉級」）', fr.parse_info_level(['1轉級']), None)

# 禮盒 / 道具名稱辨識（名稱常少讀字）
check('名稱：誘餌被讀歪', [nb.kind_of(t) for t in ('寵物誘餌', '物誘餌', '巃物誘餌')], ['bait', 'bait', 'bait'])
check('名稱：果子 / 水晶 / 安撫之素', [nb.kind_of(t) for t in ('2倍智慧果(綁定)', '2倍智慧', '離線水晶(8H)', '撫之素')], ['fruit', 'fruit', 'crystal', 'soothe'])
check('名稱：龍王的守護不是目標', nb.kind_of('龍王的守護'), None)
check('禮盒轉數：2 轉不開 3 轉', (nb.box_matches('2轉新手禮盒', 2), nb.box_matches('3轉新手禮盒', 2)), (True, False))
lines = [('寵物誘餌', 570, 130), ('10', 590, 170), ('離線水晶', 635, 131), ('(8H)', 635, 143), ('3轉新手禮盒', 500, 197)]
check('整塊 OCR 依位置分格（數量字略過、折行串起來）', nb.assign_names(lines)[:2] + [nb.assign_names(lines)[2], nb.assign_names(lines)[5]],
      ['', '寵物誘餌', '離線水晶(8H)', '3轉新手禮盒'])

# 休息 / 出戰狀態顏色
C, G = (225, 200, 167), (190, 125, 60)
check('寵物狀態顏色', [pr.pet_mode([G, C, C]), pr.pet_mode([C, G, C]), pr.pet_mode([C, C, G]), pr.pet_mode([C, C, C])], ['battle', 'ride', 'rest', None])

# 倉庫短名「WW / 11」與四圍數字名稱
check('倉庫名稱：短名與四圍數字', [pf.is_numeric_name(t) for t in ('WW', '11', '31/', '34/7/3/8', '迪基格斯')], [True, True, True, True, False])

print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
