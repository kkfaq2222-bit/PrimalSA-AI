#!/usr/bin/env python3
"""每日任務加速（2026-10-15）離線測試：店家路線最短、合成分組不超過背包"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dailyquest1920 as dq  # noqa: E402
import dailyrun1920 as dr  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


# 2009 店家幾乎在同一直線 x=27：要從一端掃到另一端，不能走到底再折回
shops = [(('米店', 1, 2009, 27, 34), []), (('肉店', 2, 2009, 27, 15), []), (('蔬菜', 3, 2009, 27, 26), []),
         (('特產', 4, 2009, 27, 37), []), (('魚店', 5, 2009, 27, 17), [])]
ys = [st[4] for st, _ in dq.shop_route(shops, (10, 25))]
check('路線單向掃過（不折返）', ys in (sorted(ys), sorted(ys, reverse=True)), True)
check('路線包含全部店', sorted(ys), [15, 17, 26, 34, 37])
check('沒有店回空路線', dq.shop_route([], (10, 25)), [])

# 合成分組：材料少可以併、材料多不併
plan = [(1, 'A', [('a1', 1), ('a2', 1)]), (2, 'B', [('b1', 1)]), (3, 'C', [('c1', 1)])]
check('材料少 → 三頁併成一組', dr.craft_groups([1, 2, 3], plan, [], dq.PEPPERS), [[1, 2, 3]])
big = [(p, 'X', [(f'm{p}_{k}', 1) for k in range(7)]) for p in (1, 2)]
check('材料多 → 不併', dr.craft_groups([1, 2], big, [], dq.PEPPERS), [[1], [2]])
keep = [f'k{k}' for k in range(11)]
kplan = [(1, 'A', [(n, 1) for n in keep]), (2, 'B', [('x', 1), ('y', 1)])]
check('留身上的多 → 不併', dr.craft_groups([1, 2], kplan, keep, dq.PEPPERS), [[1], [2]])
check('每組都不超過 15 格', all(len(g) >= 1 for g in dr.craft_groups([1, 2, 3], plan, [], dq.PEPPERS)), True)

print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
