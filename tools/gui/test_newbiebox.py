#!/usr/bin/env python3
"""newbiebox1920 的離線測試（只驗純函式，不碰遊戲）。uv run --no-project python tools/gui/test_newbiebox.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import newbiebox1920 as nb

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


check('轉數解析', [nb.parse_trans(t) for t in ('1轉131級', '2 轉1級', '上官', '')], [1, 2, None, None])
check('禮盒：轉數相符', nb.is_box('2轉新手禮盒', 2), True)
check('禮盒：轉數不符', nb.is_box('3轉新手禮盒', 2), False)
check('禮盒：數字讀不到仍算', nb.is_box('轉新手禮盒', 2), True)
check('禮盒：別的道具不算', nb.is_box('龍王的守護', 2), False)
check('智慧果：2 倍', nb.is_fruit('2倍智慧果（綁定）'), True)
check('智慧果：豆子不算', nb.is_fruit('3倍聰明的豆子'), False)
check('離線水晶', nb.is_crystal('離線水晶（8H）'), True)
check('存共用：安撫之素 / 誘餌', [nb.is_store_item(t) for t in ('安撫之素', '寵物誘餌', '龍王的守護')], [True, True, False])
import fullrun1920 as fr
check('fullrun：gift 在 rebirth 之後、organize 之前', fr.STAGES[fr.STAGES.index('rebirth') + 1:fr.STAGES.index('organize')], ['gift'])
check('fullrun：gift 指令', Path(fr.plan('kkfaq22222', 'gift')[0][1][1]).name, 'newbiebox1920.py')
print('失敗', fails)
sys.exit(1 if fails else 0)
