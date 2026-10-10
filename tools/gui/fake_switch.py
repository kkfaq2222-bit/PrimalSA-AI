#!/usr/bin/env python3
"""離線測試共用：假切換面板（Game）。team / char 的測試都用它：假 gui 依設定畫切換面板像素，不碰遊戲。"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import screen_sigs  # noqa: E402
import team  # noqa: E402
import uikit  # noqa: E402


BLUE, GREEN = (29, 175, 195), (8, 187, 36)
BEIGE, BROWN = (249, 231, 203), (169, 127, 84)
RED, YEL, NORMAL = (255, 0, 7), (255, 210, 0), (41, 255, 0)
NAMES = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']
# OCR 假資料（P-I1 實測：Zooms 2~6 合併結果）
OCR_REAL = {'DKBO': ['DKBO'], 'DKBO2': ['DKBO2', 'D02', '02'], 'DKBO3': ['03', '003'], 'DKBO4': ['DKBO4', 'B04'], 'DKBO5': ['05']}


class Game:
    """cards = [{'name','status','label'}]（照面板順序；數量 = 在線人數）。painted 由 color_at 即時算"""

    def __init__(self, cards, hud=True, ocr=None):
        self.cards, self.hud, self.panel = cards, hud, False
        self.clicks, self.keys, self.ocr_boxes = [], [], []
        self.ocr_map = OCR_REAL if ocr is None else ocr
        self.vanish_after_label = False
        self.on_disband = None
        self.loading = 0              # >0：加載畫面（SIG_HUD 不成立、SIG_LOADING 成立），每次 pixel 呼叫減 1
        self.after_load = 2           # 點卡片後加載畫面持續幾次 pixel 呼叫
        self.card_moves = True        # False = 點卡片沒反應（當前不動，測 62）
        self.stuck = False            # True = 點卡片後 HUD 一直不回來（測 65）
        self.hud_never = False

    def color_at(self, x, y):
        if self.hud and not self.loading and not self.hud_never and (x, y) == (1300, 745):
            return (254, 0, 0)
        if self.loading or self.hud_never:
            for px, py, r, g, b, _ in screen_sigs.SIG_LOADING:
                if (x, y) == (px, py):
                    return (r, g, b)
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
                    return BLUE if c['status'] == 'current' else GREEN if c['status'] == 'online' else BROWN
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
            if self.loading:
                self.loading -= 1
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
                    elif self.panel:
                        for i, (x0, cy) in enumerate(team.SLOTS):
                            if i < len(self.cards) and xy[0] in range(x0, x0 + 300) and xy[1] in range(cy - 25, cy + 25):
                                self.panel = False                       # 點卡片：面板自己關 + 加載
                                if self.card_moves:
                                    for k, c in enumerate(self.cards):
                                        c['status'] = 'current' if k == i else 'online'
                                self.loading = self.after_load
                                self.hud_never = self.stuck
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
