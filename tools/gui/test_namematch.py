#!/usr/bin/env python3
"""namematch.py 離線測試：fixtures/name_tpl.json 是 2026-10-11 實機 5 張卡片名字圖（二值化後的整名樣板）。
不碰遊戲。用法：uv run --no-project python tools/gui/test_namematch.py"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import namematch as nm  # noqa: E402
import team  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1


nm.TPL_DIR = Path(tempfile.mkdtemp())
TPL = json.loads((HERE / 'fixtures' / 'name_tpl.json').read_text(encoding='utf-8'))
NAMES = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']
IMG = {n: int(TPL[n][0], 16) for n in NAMES}
ROWS = {n: nm.int_to_rows(v) for n, v in IMG.items()}
EMPTY = ['0' * nm.CW_] * nm.CH_


def shifted(rows, dx, dy):
    out = []
    for y in range(nm.CH_):
        sy = y - dy
        src = rows[sy] if 0 <= sy < nm.CH_ else '0' * nm.CW_
        out.append(('0' * dx + src)[:nm.CW_] if dx >= 0 else (src[-dx:] + '0' * -dx))
    return out


def hits(rows_by_slot, tpl=TPL):
    return {s: r['name'] for s, r in nm.match_rows(rows_by_slot, tpl).items()}


check('bitmask 轉換可逆', all(nm.rows_to_int(ROWS[n]) == IMG[n] for n in NAMES))
check('墨點夠多（真實字）', all(IMG[n].bit_count() > 1000 for n in NAMES), str({n: IMG[n].bit_count() for n in NAMES}))
check('5 張原圖全中', hits({i: ROWS[n] for i, n in enumerate(NAMES)}) == dict(enumerate(NAMES)))
# 名字之間的相似度：最像的一對仍低於門檻（同名 = 1.0）
worst = max(nm.iou(IMG[a], IMG[b]) for a in NAMES for b in NAMES if a != b)
check('不同名字 IoU 都低於 HIT_MIN - MARGIN', worst < nm.HIT_MIN - nm.MARGIN, f'最高 {worst:.3f}')
check('同名 IoU = 1', nm.iou(IMG['DKBO2'], IMG['DKBO2']) == 1.0)
# 平移
for dx, dy in [(1, 0), (-2, 0), (0, 2), (2, -2), (-1, 1)]:
    r = hits({0: shifted(ROWS['DKBO4'], dx, dy), 1: shifted(ROWS['DKBO'], dx, dy)})
    check(f'平移 ({dx},{dy}) 仍命中', r == {0: 'DKBO4', 1: 'DKBO'}, str(r))
r = hits({0: shifted(ROWS['DKBO3'], 5, 0)})
check('平移 5 px 超出容許 → 不誤判成別人', r[0] in (None, 'DKBO3'), str(r))
# 空卡位 / 垃圾
check('空白 = None', hits({0: EMPTY}) == {0: None})
junk = [('10' * (nm.CW_ // 2)) if y % 2 else EMPTY[0] for y in range(nm.CH_)]
check('雜訊圖 = None', hits({0: junk}) == {0: None})
# 保守：沒有該名字的樣板 → 不能硬套最像的
tpl2 = {k: v for k, v in TPL.items() if k != 'DKBO3'}
check('缺 DKBO3 樣板時，DKBO3 的圖 = None（不誤判 DKBO5）', hits({0: ROWS['DKBO3']}, tpl2) == {0: None})
check('沒有任何樣板 = None', hits({0: ROWS['DKBO3']}, {}) == {0: None})
# 差距太小：兩個名字各放一份同圖的變體 → 分數相同 → None
tpl3 = {'DKBO2': TPL['DKBO2'], 'DKBO3': TPL['DKBO2']}
check('兩名字樣板相同（差距 0）= None', hits({0: ROWS['DKBO2']}, tpl3) == {0: None})
# 白名單：樣板檔裡不在白名單的名字被忽略
(nm.TPL_DIR / f'{nm.LAYOUT}.json').write_text(json.dumps({**TPL, 'ZZZ9': TPL['DKBO2']}), encoding='utf-8')
loaded = nm.load_tpl()
check('load_tpl 濾掉白名單外名字', 'ZZZ9' not in loaded and set(NAMES) <= set(loaded))
# 學習
t = {}
lab = {i: n for i, n in enumerate(NAMES)}
rows5 = {i: ROWS[n] for i, n in enumerate(NAMES)}
logs = []
check('learn_from 空樣板 → 新增 5', nm.learn_from(rows5, lab, t, logs.append) == 5 and all(len(v) == 1 for v in t.values()))
check('重複學不新增（重複圖）', nm.learn_from(rows5, lab, t, logs.append) == 0 and all(len(v) == 1 for v in t.values()))
sh = {i: shifted(ROWS[n], 1, 0) for i, n in enumerate(NAMES)}
n_before = sum(len(v) for v in t.values())
nm.learn_from(sh, lab, t, logs.append)
check('平移 1px 的圖算新變體（IoU < DUP_IOU）且不超過上限', sum(len(v) for v in t.values()) >= n_before and all(len(v) <= nm.MAX_VARIANTS for v in t.values()))
bad = dict(lab)
bad[1], bad[2] = 'DKBO3', 'DKBO2'                       # 標籤對調：與既有樣板矛盾
t2 = {k: list(v) for k, v in TPL.items()}
check('標籤對調 → 0 個新增', nm.learn_from(rows5, bad, t2, logs.append) == 0 and t2 == TPL)
check('空白圖不學', nm.learn_from({0: EMPTY}, {0: 'DKBO'}, {}, logs.append) == 0)
# 檔案往返
nm.save_tpl(t)
check('save / load 往返', nm.load_tpl() == t)

# ---- read_detail / read_names（假 capture）----
nm.save_tpl(TPL)
calls = []
nm.capture = lambda: calls.append(1) or {i: ROWS[n] for i, n in enumerate(NAMES)}
check('read_names 5 張', nm.read_names() == dict(enumerate(NAMES)))
nm.capture = lambda: None
check('截圖失敗 = {}', nm.read_names() == {})
(nm.TPL_DIR / f'{nm.LAYOUT}.json').unlink()
nm.capture = lambda: calls.append('X') or {}
calls.clear()
check('沒樣板檔 = {} 且不截圖', nm.read_names() == {} and not calls)

# ---- team.build_cards 接 matched ----
px = ([(249, 231, 203), (29, 175, 195), (29, 175, 195)] + [(0, 0, 0)] * (len(team.LABEL_SCAN) ** 2))
per = len(px)
cols5 = px * 5 + [(169, 127, 84)] + [(0, 0, 0)] * (per - 1)
full = team.build_cards(cols5, {}, {i: n for i, n in enumerate(NAMES)})
check('5 張 + 樣板全中 → via tpl / ok', [c.name for c in full] == NAMES and all(c.via == 'tpl' and c.check == 'ok' for c in full))
conf = team.build_cards(cols5, {}, {0: 'DKBO', 1: 'DKBO3'})
check('5 張樣板與順序矛盾 → conflict', conf[1].check == 'conflict' and conf[1].name == 'DKBO3')
mix = team.build_cards(cols5, {2: ['03']}, {0: 'DKBO'})
check('樣板 None 的卡退回順序 + OCR', mix[2].name == 'DKBO3' and mix[2].check == 'ok' and mix[2].via == '')
cols3 = px * 3 + [(169, 127, 84)] + [(0, 0, 0)] * (per - 1)
cols3 += [(169, 127, 84)] + [(0, 0, 0)] * (per - 1) + [(169, 127, 84)] + [(0, 0, 0)] * (per - 1)
three = team.build_cards(cols3, {0: [], 1: [], 2: []}, {0: 'DKBO', 1: 'DKBO3', 2: 'DKBO5'})
check('卡片 < 5：樣板命中即採用（補位後順序不同）', [c.name for c in three] == ['DKBO', 'DKBO3', 'DKBO5'] and all(c.check == 'ok' for c in three))
none3 = team.build_cards(cols3, {0: [], 1: [], 2: []}, {})
check('卡片 < 5 且樣板 / OCR 都沒有 → name None', none3[1].name is None)
# 舊樣板檔鍵 DKB0 / DKB02（數字 0）→ 讀入時對應到白名單真名
import tempfile as _tf  # noqa: E402
_d = Path(_tf.mkdtemp())
_old = nm.TPL_DIR
nm.TPL_DIR = _d
(_d / f'{nm.LAYOUT}.json').write_text(json.dumps({'DKB0': ['ff'], 'DKB02': ['0f'], 'XYZ': ['1']}), encoding='utf-8')
_t = nm.load_tpl()
nm.TPL_DIR = _old
check('舊樣板鍵 DKB0 / DKB02 → 真名 DKBO / DKBO2，非白名單忽略', set(_t) == {'DKBO', 'DKBO2'} and _t['DKBO'] == ['ff'])

print('失敗', fails)
sys.exit(1 if fails else 0)
