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
one_low = {**full, 3: [25, 24, 25, 25]}
check('有一隻 24 級', kt.all_done(one_low, 25), False)
check('有讀不到', kt.all_done({**full, 2: [25, None, 25, 25]}, 25), False)
check('少一個角色', kt.all_done({r: [25] * 4 for r in range(1, 5)}, 25), False)
check('少一隻寵物', kt.all_done({**full, 4: [25, 25, 25]}, 25), False)
check('總等級忽略 None', kt.total({1: [10, None, 5, 5]}), 20)
check('有進展不算停滯', kt.stalled(100, 101, 99999, 1800), (101, False))
check('沒進展但時間未到', kt.stalled(100, 100, 600, 1800), (100, False))
check('沒進展且超過 30 分鐘', kt.stalled(100, 99, 1800, 1800), (100, True))
check('等級解析 單一數字', kt.parse_level(['25']), 25)
check('等級解析 多組取眾數', kt.parse_level(['25', '2', '25', '']), 25)
check('等級解析 雜訊', kt.parse_level(['x', '·']), None)
check('等級解析 超出範圍不算', kt.parse_level(['999', '0']), None)
check('換 3 次且 25 級 = 完成', kt.done_by_swaps(3, 25, 25), True)
check('只換 2 次且 20 級不算', kt.done_by_swaps(2, 20, 25), False)
check('換 3 次但第 4 隻 24 級不算', kt.done_by_swaps(3, 24, 25), False)
check('出戰寵物 34 級（沒看到換寵）= 完成', kt.done_by_swaps(0, 34, 25), True)
check('剛好 25 級、沒換寵不算', kt.done_by_swaps(0, 25, 25), False)
check('讀不到等級不算', kt.done_by_swaps(3, None, 25), False)
print(f'失敗 {fails}')
sys.exit(1 if fails else 0)
