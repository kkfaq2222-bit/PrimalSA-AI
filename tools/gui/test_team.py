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
import team  # noqa: E402
import uikit  # noqa: E402

errlog.LOG = Path(tempfile.mkdtemp()) / 'errlog.jsonl'
fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1


BLUE, GREEN = (29, 175, 195), (8, 187, 36)
BEIGE, BROWN = (249, 231, 203), (169, 127, 84)
RED, YEL, NORMAL = (255, 0, 7), (255, 210, 0), (41, 255, 0)
NAMES = ['DKB0', 'DKB02', 'DKB03', 'DKB04', 'DKB05']
# OCR 假資料（P-I1 實測：Zooms 2~6 合併結果）
OCR_REAL = {'DKB0': ['DKBO'], 'DKB02': ['DKB02', 'D02', '02'], 'DKB03': ['03', '003'], 'DKB04': ['DKB04', 'B04'], 'DKB05': ['05']}


class Game:
    """cards = [{'name','status','label'}]（照面板順序；數量 = 在線人數）。painted 由 color_at 即時算"""

    def __init__(self, cards, hud=True, ocr=None):
        self.cards, self.hud, self.panel = cards, hud, False
        self.clicks, self.keys, self.ocr_boxes = [], [], []
        self.ocr_map = OCR_REAL if ocr is None else ocr
        self.vanish_after_label = False
        self.on_disband = None

    def color_at(self, x, y):
        if self.hud and (x, y) == (1300, 745):
            return (254, 0, 0)
        if self.panel:
            for px, py, r, g, b, _ in screen_sigs.SIG_PANEL:
                if (x, y) == (px, py):
                    return (r, g, b)
        for i, (x0, cy) in enumerate(team.SLOTS):
            if (x, y) == (x0, cy):
                return BEIGE if self.panel and i < len(self.cards) else BROWN
            if self.panel and i < len(self.cards):
                c = self.cards[i]
                if (x, y) in ((x0 + 6, cy), (x0 + 30, cy)):
                    return BLUE if c['status'] == 'current' else GREEN
                lx, ly = x0 + team.LABEL_DX, cy + team.LABEL_DY
                if c['label'] != 'other' and ly + 10 <= y <= ly + 12 and lx + 10 <= x <= lx + 14:
                    return RED if c['label'] == 'leader' else YEL
                if ly + 20 <= y <= ly + 22 and lx + 10 <= x <= lx + 20:
                    return NORMAL
        return (0, 0, 0)

    def gui(self, *args, note=''):
        if args[0] == 'pixel':
            pts = [tuple(int(v) for v in p.split(',')) for p in args[1].split()]
            out = ' '.join('%d,%d,%d' % self.color_at(*p) for p in pts)
            if self.vanish_after_label and len(pts) > 500:
                self.panel = False
            return out
        if args[0] == 'seq':
            for part in args[1].split(';'):
                w = part.split()
                if w and w[0] == 'click':
                    xy = (int(w[1]), int(w[2]))
                    self.clicks.append(xy)
                    if xy == uikit.SWITCH.open_xy and self.hud:
                        self.panel = True
                    elif xy == uikit.SWITCH.close_xy:
                        self.panel = False
                elif w and w[0] == 'key':
                    self.keys.append(w[1])
                    if w[1] == '{ESC}':
                        self.panel = False
        return ''

    def ocr(self, box, *opts):
        self.ocr_boxes.append((box, opts))
        for i, (x0, cy) in enumerate(team.SLOTS):
            if box[0] == x0 + team.NAME_BOX_DX and box[1] == cy + team.NAME_BOX_DY and i < len(self.cards):
                nm = self.cards[i]['name']
                return list(self.ocr_map.get(nm, []))
        return []

    def inner_clicks(self):
        return [c for c in self.clicks if c not in (uikit.SWITCH.open_xy, uikit.SWITCH.close_xy)]


def mk(labels=('leader', 'member', 'member', 'member', 'member'), names=NAMES, current=0):
    return [{'name': n, 'status': 'current' if i == current else 'online', 'label': lb} for i, (n, lb) in enumerate(zip(names, labels))]


def install(g):
    uikit.gui = g.gui
    uikit.ocr = g.ocr
    uikit.sleep = lambda s: None
    uikit.preflight = lambda src: 0
    uikit.snap = lambda tag: None
    return g


def run(fn, *a, **k):
    import io
    import contextlib
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


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
check('cross_check 讀不出 → unknown', team.cross_check('DKB03', []) == 'unknown')
check('cross_check 讀到別人 → conflict', team.cross_check('DKB03', ['D02']) == 'conflict')
check('cross_check 同卡多名字 → unknown（雜訊）', team.cross_check('DKB03', ['03', 'D02']) == 'unknown')
check('cross_check DKB05 只讀到 DKBO（可能截斷）→ unknown 不算矛盾', team.cross_check('DKB05', ['DKBO']) == 'unknown')
check('cross_check DKB02 讀到 DKB0 單獨 → unknown', team.cross_check('DKB02', ['DKB0']) == 'unknown')
check('resolve_name 唯一尾碼', team.resolve_name(1, ['D02', '02']) == 'DKB02' and team.resolve_name(0, ['DKBO']) == 'DKB0' and team.resolve_name(2, ['DKBO']) is None)

# ---- status：5 人隊 ----
g = install(Game(mk()))
rc, out = run(team.status)
check('status 5 人隊 rc 0 + 隊長 DKB0 當前 DKB0', rc == 0 and '隊長 DKB0、當前 DKB0' in out and out.count('OCR 一致') == 5, out.strip().splitlines()[-1])
check('status 面板內 0 次點擊、面板已關', g.inner_clicks() == [] and not g.panel, str(g.clicks))
check('status OCR 用 Zooms 2,3,4,5,6', all(o[1] == ('-Zooms', '2,3,4,5,6') for o in g.ocr_boxes) and len(g.ocr_boxes) == 5)
g = install(Game(mk()))
rc, out = run(team.status, True, False)
d = json.loads(out)
check('status --json --no-ocr：無 OCR 呼叫、欄位正確', rc == 0 and g.ocr_boxes == [] and d['summary']['leader'] == 'DKB0' and [c['name'] for c in d['cards']] == NAMES
      and d['cards'][0]['status'] == 'current' and d['cards'][1]['label'] == 'member')
g = install(Game(mk(current=4)))
rc, out = run(team.status, True, False)
check('當前是 DKB05（隊員）', json.loads(out)['summary']['current'] == 'DKB05')

# ---- check ----
g = install(Game(mk()))
check('check 5 人隊 → 0', run(team.check, 5)[0] == 0 and g.inner_clicks() == [])
check('check --leader DKB0 → 0', run(team.check, 5, 'DKB0')[0] == 0)
check('check --leader DKB02 → 43', run(team.check, 5, 'DKB02')[0] == 43)
check('check --leader 不在白名單 → 1', run(team.check, 5, 'XYZ')[0] == 1)
check('check size 4（5 人隊多一人）→ 41', run(team.check, 4)[0] == 41)
g = install(Game(mk(), ocr={}))
rc, out = run(team.check, 5)
check('OCR 全讀不出 → 0（不算矛盾）', rc == 0, out.strip().splitlines()[-1])
g = install(Game(mk(), ocr={**OCR_REAL, 'DKB03': ['D02']}))
check('OCR 讀到別人名字 → 43', run(team.check, 5)[0] == 43)
g = install(Game(mk(), ocr={**OCR_REAL, 'DKB05': ['DKBO']}))
check('DKB05 只讀到 DKBO → 0', run(team.check, 5)[0] == 0)
g = install(Game(mk(labels=('leader', 'member', 'member', 'member', 'other'))))
check('4 人隊 + 1 單人，size 5 → 41', run(team.check, 5)[0] == 41)
check('同上 size 4 → 0', run(team.check, 4)[0] == 0)
g = install(Game(mk(labels=('other',) * 5)))
check('全單人 → 47', run(team.check, 5)[0] == 47)
g = install(Game(mk(labels=('leader', 'member', 'leader', 'member', 'member'))))
check('兩個隊長 → 41', run(team.check, 5)[0] == 41)
# 卡片不足
g = install(Game(mk(('leader', 'member', 'member', 'member'), names=['DKB0', 'DKB02', 'DKB04', 'DKB05'])))
rc, out = run(team.check, 5)
check('4 張卡（DKB03 離線）→ 42，名字改由 OCR 對應', rc == 42 and "'DKB0', 'DKB02', 'DKB04', 'DKB05'" in out, out.strip().splitlines()[-1])
g = install(Game(mk(('leader', 'member', 'member', 'member'), names=['DKB0', 'DKB02', 'DKB04', 'DKB05']), ocr={'DKB0': ['DKBO'], 'DKB02': [], 'DKB04': ['B04'], 'DKB05': ['05']}))
rc, out = run(team.status, True)
d = json.loads(out)
check('卡片 < 5 讀不出名字 → name None（不亂猜順序）', [c['name'] for c in d['cards']] == ['DKB0', None, 'DKB04', 'DKB05'])
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
