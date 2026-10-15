#!/usr/bin/env python3
"""每日任務加速 3（2026-10-15）離線測試：背包整塊 OCR 分格、商店點位順序"""
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dailyquest1920 as dq  # noqa: E402
import uikit  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


slots = [(400 + 80 * c, 200 + 70 * r) for r in range(3) for c in range(5)]


def fake(lines, ok=True):
    out = json.dumps({'ok': ok, 'lines': lines}, ensure_ascii=False)
    uikit.winenv.run_ps = lambda *a, **k: types.SimpleNamespace(stdout=out)


# 格子 0：名稱折兩行（zoom 2 / 3 各讀一次，不能兩種縮放拼在一起）；格子 6：一行；其他空
fake([{'text': '水分多', 'x': 400, 'y': 180, 'zoom': 2}, {'text': '的蘋果', 'x': 400, 'y': 190, 'zoom': 2},
      {'text': '水分多的', 'x': 401, 'y': 181, 'zoom': 3}, {'text': '蘋果', 'x': 400, 'y': 191, 'zoom': 3},
      {'text': '炭', 'x': 480, 'y': 254, 'zoom': 2},
      {'text': '雜訊', 'x': 700, 'y': 400, 'zoom': 2}])          # 超出所有格子範圍 → 丟掉
t = dq._grid_texts(slots)
check('折兩行依 y 串起來', t[0], '水分多的蘋果')
check('第 2 列第 2 格', t[6], '炭')
check('空格是空字串', t[1], '')
check('15 格都有回', len(t), 15)
fake([], ok=False)
check('OCR 失敗回 None（改逐格讀）', dq._grid_texts(slots), None)

check('商店先點正中', dq.SHOP_JITTER[0], (0, 0))
check('商店點位和一般點位同一組', sorted(dq.SHOP_JITTER), sorted(dq.CLICK_JITTER))

print('全部通過' if not fails else f'{fails} 項失敗')
sys.exit(1 if fails else 0)
