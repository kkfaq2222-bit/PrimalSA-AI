#!/usr/bin/env python3
"""petfetchimg1920 離線測試（不碰遊戲）：格子座標、取樣點、樣板比對、不明確 / 太遠的判斷。
用法：uv run --no-project python tools/gui/test_petfetchimg.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import petfetchimg1920 as pf  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


def flat(rgb):
    return [rgb] * 16


check('第 1 格中心', pf.slot_center(0), (542, 170))
check('第 5 格中心', pf.slot_center(4), (808, 170))
check('第 20 格中心', pf.slot_center(19), (808, 370))
check('取樣點 16 個', len(pf.slot_points(0)), 16)

tp = {'克邦凱斯': [flat((40, 90, 200))], '加克拉': [flat((200, 40, 40))], '空': [flat((190, 170, 130))]}
check('命中', pf.best_match(flat((42, 92, 198)), tp)[0], '克邦凱斯')
check('空格', pf.best_match(flat((188, 168, 132)), tp)[0], '空')
check('太遠', pf.best_match(flat((0, 255, 0)), tp)[2], 'far')
amb = {'甲': [flat((100, 100, 100))], '乙': [flat((104, 100, 100))]}
check('接近的兩種 → 不明確', pf.best_match(flat((102, 100, 100)), amb)[2], 'ambiguous')
same = {'甲': [flat((100, 100, 100)), flat((104, 100, 100))]}
check('同名多變體不算不明確', pf.best_match(flat((100, 100, 100)), same)[0], '甲')
check('沒樣板', pf.best_match(flat((1, 1, 1)), {})[2], 'none')
check('長度不同 → 距離極大', pf.dist([(1, 1, 1)], flat((1, 1, 1))) > 900, True)

print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
