#!/usr/bin/env python3
"""team.py（status / check / disband）離線測試：不碰遊戲，假 gui 依設定畫切換面板像素。
用法：uv run --no-project python tools/gui/test_team.py"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import errlog  # noqa: E402
import screen_sigs  # noqa: E402
import namematch  # noqa: E402
import team  # noqa: E402
import uikit  # noqa: E402

errlog.LOG = Path(tempfile.mkdtemp()) / 'errlog.jsonl'
namematch.TPL_DIR = Path(tempfile.mkdtemp())     # 不讀真實樣板（離線測試走舊 OCR 邏輯）
fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1

from fake_switch import BLUE, GREEN, BEIGE, BROWN, RED, YEL, NORMAL, NAMES, OCR_REAL, Game, mk, install, run  # noqa: E402,F401


# ---- 純函式：fixture 真實像素 ----
fx = json.loads((HERE / 'fixtures' / 'switch_px.json').read_text(encoding='utf-8'))['px']
P = lambda x, y: tuple(fx[f'{x},{y}'])  # noqa: E731
check('fixture 卡片米色 = 存在', all(team.is_card(P(x, y)) for x, y in [(416, 300), (416, 385), (416, 470), (726, 300), (726, 385)]))
check('fixture 第 6 格棕色 = 空位', not team.is_card(P(726, 470)))
check('fixture 線上 = online（左右欄）', team.classify_status(P(422, 300), P(446, 300)) == 'online' and team.classify_status(P(732, 385), P(756, 385)) == 'online')
check('fixture 當前 = current', team.classify_status(P(422, 470), P(446, 470)) == 'current')
check('實測值（P-I1）當前 / 線上', team.classify_status((29, 175, 195), (24, 189, 211)) == 'current' and team.classify_status((8, 187, 36), (0, 201, 33)) == 'online')
check('狀態不明（棕）= unknown', team.classify_status(BROWN, BROWN) == 'unknown')
# 標籤分類
check('紅 ≥3 = leader', team.classify_label([RED] * 7 + [(0, 0, 0)] * 50) == 'leader')
check('黃 4 + 綠「正常」= member', team.classify_label([YEL] * 4 + [NORMAL] * 30 + [(77, 66, 59)] * 20) == 'member')
check('只有綠 = other', team.classify_label([NORMAL] * 30) == 'other')
check('框邊 (183,128,63) 不算', team.classify_label([(183, 128, 63)] * 100) == 'other')
check('紅 2 點（雜訊）= other', team.classify_label([RED] * 2) == 'other')

# ---- 名字 OCR ----
for nm in NAMES:
    check(f'cross_check {nm} 實測 OCR → ok', team.cross_check(nm, OCR_REAL[nm]) == 'ok', str(OCR_REAL[nm]))
check('cross_check 讀不出 → unknown', team.cross_check('DKBO3', []) == 'unknown')
check('cross_check 讀到別人 → conflict', team.cross_check('DKBO3', ['D02']) == 'conflict')
check('cross_check 同卡多名字 → unknown（雜訊）', team.cross_check('DKBO3', ['03', 'D02']) == 'unknown')
check('cross_check DKBO5 只讀到 DKBO（可能截斷）→ unknown 不算矛盾', team.cross_check('DKBO5', ['DKBO']) == 'unknown')
check('cross_check DKBO2 讀到 DKBO 單獨 → unknown', team.cross_check('DKBO2', ['DKBO']) == 'unknown')
check('resolve_name 唯一尾碼', team.resolve_name(1, ['D02', '02']) == 'DKBO2' and team.resolve_name(0, ['DKBO']) == 'DKBO' and team.resolve_name(2, ['DKBO']) is None)

# ---- status：5 人隊 ----
g = install(Game(mk()))
rc, out = run(team.status)
check('status 5 人隊 rc 0 + 隊長 DKBO 當前 DKBO', rc == 0 and '隊長 DKBO、當前 DKBO' in out and out.count('OCR 一致') == 5, out.strip().splitlines()[-1])
check('status 面板內 0 次點擊、面板已關', g.inner_clicks() == [] and not g.panel, str(g.clicks))
check('status OCR 用 Zooms 2,3,4,5,6', all(o[1] == ('-Zooms', '2,3,4,5,6') for o in g.ocr_boxes) and len(g.ocr_boxes) == 5)
g = install(Game(mk()))
rc, out = run(team.status, True, False)
d = json.loads(out)
check('status --json --no-ocr：無 OCR 呼叫、欄位正確', rc == 0 and g.ocr_boxes == [] and d['summary']['leader'] == 'DKBO' and [c['name'] for c in d['cards']] == NAMES
      and d['cards'][0]['status'] == 'current' and d['cards'][1]['label'] == 'member')
g = install(Game(mk(current=4)))
rc, out = run(team.status, True, False)
check('當前是 DKBO5（隊員）', json.loads(out)['summary']['current'] == 'DKBO5')

# ---- check ----
g = install(Game(mk()))
check('check 5 人隊 → 0', run(team.check, 5)[0] == 0 and g.inner_clicks() == [])
check('check --leader DKBO → 0', run(team.check, 5, 'DKBO')[0] == 0)
check('check --leader DKBO2 → 43', run(team.check, 5, 'DKBO2')[0] == 43)
check('check --leader 不在白名單 → 1', run(team.check, 5, 'XYZ')[0] == 1)
check('check size 4（5 人隊多一人）→ 41', run(team.check, 4)[0] == 41)
g = install(Game(mk(), ocr={}))
rc, out = run(team.check, 5)
check('OCR 全讀不出 → 0（不算矛盾）', rc == 0, out.strip().splitlines()[-1])
g = install(Game(mk(), ocr={**OCR_REAL, 'DKBO3': ['D02']}))
check('OCR 讀到別人名字 → 43', run(team.check, 5)[0] == 43)
g = install(Game(mk(), ocr={**OCR_REAL, 'DKBO5': ['DKBO']}))
check('DKBO5 只讀到 DKBO → 0', run(team.check, 5)[0] == 0)
g = install(Game(mk(labels=('leader', 'member', 'member', 'member', 'other'))))
check('4 人隊 + 1 單人，size 5 → 41', run(team.check, 5)[0] == 41)
check('同上 size 4 → 0', run(team.check, 4)[0] == 0)
g = install(Game(mk(labels=('other',) * 5)))
check('全單人 → 47', run(team.check, 5)[0] == 47)
g = install(Game(mk(labels=('leader', 'member', 'leader', 'member', 'member'))))
check('兩個隊長 → 41', run(team.check, 5)[0] == 41)
# 卡片不足
g = install(Game(mk(('leader', 'member', 'member', 'member'), names=['DKBO', 'DKBO2', 'DKBO4', 'DKBO5'])))
rc, out = run(team.check, 5)
check('4 張卡（DKBO3 離線）→ 42，名字改由 OCR 對應', rc == 42 and "'DKBO', 'DKBO2', 'DKBO4', 'DKBO5'" in out, out.strip().splitlines()[-1])
g = install(Game(mk(('leader', 'member', 'member', 'member'), names=['DKBO', 'DKBO2', 'DKBO4', 'DKBO5']), ocr={'DKBO': ['DKBO'], 'DKBO2': [], 'DKBO4': ['B04'], 'DKBO5': ['05']}))
rc, out = run(team.status, True)
d = json.loads(out)
check('卡片 < 5 讀不出名字 → name None（不亂猜順序）', [c['name'] for c in d['cards']] == ['DKBO', None, 'DKBO4', 'DKBO5'])
check('4 張卡 size 4 → 0', run(team.check, 4)[0] == 0)

# ---- 面板問題 → 40，不點面板內座標 ----
g = install(Game(mk(), hud=False))
rc, out = run(team.check, 5)
check('HUD 不在（對話框等）→ 40、0 次點擊', rc == 40 and g.clicks == [], str(g.clicks))
g = install(Game(mk()))
g.vanish_after_label = True
rc, out = run(team.check, 5)
check('讀圖後面板消失 → 40、面板內 0 次點擊', rc == 40 and g.inner_clicks() == [], f'rc={rc} {g.clicks}')

# ---- disband ----
import quest  # noqa: E402

calls = {'disband': 0, 'tab': 0}


def fake_disband(g, rc_ret=0, clear=True):
    def f():
        calls['disband'] += 1
        if clear and rc_ret == 0:
            for c in g.cards:
                c['label'] = 'other'
        return rc_ret
    return f


quest.ensure_task_tab = lambda: calls.__setitem__('tab', calls['tab'] + 1)

g = install(Game(mk()))
quest.disband_team = fake_disband(g)
calls.update(disband=0, tab=0)
rc, out = run(team.disband)
check('disband 成功 → 0、quest.disband_team 1 次、切回任務分頁', rc == 0 and calls == {'disband': 1, 'tab': 1}, f'{rc} {calls}')
check('disband 面板內 0 次點擊（點擊交給 quest）', g.inner_clicks() == [] and not g.panel)

g = install(Game(mk(labels=('other',) * 5)))
quest.disband_team = fake_disband(g)
calls.update(disband=0, tab=0)
rc, out = run(team.disband)
check('本來就沒隊伍 → 0、不呼叫 quest', rc == 0 and calls['disband'] == 0 and g.inner_clicks() == [])

g = install(Game(mk(current=2)))
quest.disband_team = fake_disband(g)
calls.update(disband=0, tab=0)
rc, out = run(team.disband)
check('當前不是隊長 → 46、不呼叫 quest', rc == 46 and calls['disband'] == 0, str(rc))

g = install(Game(mk()))
quest.disband_team = fake_disband(g, rc_ret=26)
calls.update(disband=0, tab=0)
rc, out = run(team.disband)
check('quest.disband_team 回 26 → 45', rc == 45 and calls['tab'] == 0, str(rc))

g = install(Game(mk()))
quest.disband_team = fake_disband(g, clear=False)
calls.update(disband=0, tab=0)
rc, out = run(team.disband)
check('quest 回 0 但仍有隊伍 → 45', rc == 45 and calls['tab'] == 0, str(rc))

g = install(Game(mk(), hud=False))
quest.disband_team = fake_disband(g)
calls.update(disband=0, tab=0)
rc, out = run(team.disband)
check('disband 面板打不開 → 40、不呼叫 quest', rc == 40 and calls['disband'] == 0)

# ---- 全域：errlog 有寫、team 不 import 時不碰遊戲 ----
check('失敗有寫 errlog', errlog.LOG.exists())
print('失敗', fails)
sys.exit(1 if fails else 0)
