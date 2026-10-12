#!/usr/bin/env python3
"""katantrain1920 離線測試（不碰遊戲）：達標判斷、總等級、停滯判斷。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import katantrain1920 as kt  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


full = {r: [25, 26, 25, 30] for r in range(1, 6)}
check('全部達標', kt.all_done(full, 25), True)
one_low = dict(full, **{3: [25, 24, 25, 25]})
check('有一隻 24 級', kt.all_done(one_low, 25), False)
check('有讀不到', kt.all_done(dict(full, **{2: [25, None, 25, 25]}), 25), False)
check('少一個角色', kt.all_done({r: [25] * 4 for r in range(1, 5)}, 25), False)
check('少一隻寵物', kt.all_done(dict(full, **{4: [25, 25, 25]}), 25), False)
check('總等級忽略 None', kt.total({1: [10, None, 5, 5]}), 20)
check('有進展不算停滯', kt.stalled(100, 101, 99999, 1800), (101, False))
check('沒進展但時間未到', kt.stalled(100, 100, 600, 1800), (100, False))
check('沒進展且超過 30 分鐘', kt.stalled(100, 99, 1800, 1800), (100, True))
print(f'失敗 {fails}')
sys.exit(1 if fails else 0)
