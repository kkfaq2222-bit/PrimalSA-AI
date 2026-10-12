#!/usr/bin/env python3
"""team.py 的 1920×1017 版面唯讀讀取器（只用標準函式庫）：開切換面板 → 一次 pixel 讀 6 張卡片 → 關面板。

2026-10-11 在 11111 實機量（截圖 960×508）：只讀像素、不點任何面板內座標（只點開啟鈕與 ✕）。
- 卡片：左欄 x0=308、右欄 x0=502；列 y0=164 / 218 / 272（間距 54）。slot = 欄 + 2×列（同 team.SLOTS 的順序）。
- 存在：(x0+157, y0+6) 米色 (251,229,199) vs 空位棕 (169,127,84)。
- 狀態框（卡片左側）：(x0-8, y0+8)：藍 = 當前、綠 = 線上。
- 隊伍標籤：框 (x0, y0) 起 26×26、間隔 2 的 13×13 掃描：紅 (255,0,7)=隊長、黃 (255,210,0)=隊員（判斷同 team.classify_label）。
- 開啟鈕 533,465（換圖後第一下常被吃 → 右鍵 2 次 + 左鍵 1 次）；面板開著 = ✕ 698,125 紅 (183,65,41)；關閉 = 點 ✕。
名字依卡片順序（5 張時）；1920 版面沒有名字樣板 / OCR，所以只回順序名（DKBO、DKBO2…）。
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import team  # noqa: E402  純函式：classify_label 等
import uikit  # noqa: E402

OPEN_BTN = (533, 465)
CLOSE_BTN = (698, 125)
CLOSE_SIG = (183, 65, 41)
HUD_PROBE = (874, 455, 255, 0, 0)
COL_X = (308, 502)
ROW_Y = (164, 218, 272)
SLOTS = [(COL_X[i % 2], ROW_Y[i // 2]) for i in range(6)]
SCAN = range(0, 26, 2)
BEIGE = (251, 229, 199)
BEIGE_TOL = 30

sleep = time.sleep


def _near(c, ref, tol):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


# 面板開著的特徵（2026-10-11 在紅地面的深紅 8 樓實測：單點 ✕ 會被紅地面誤判，所以多點一起比對）
PANEL_SIG = [((698, 125), (183, 65, 41), 35), ((355, 357), (99, 66, 31), 35), ((480, 357), (39, 63, 92), 35),
             ((600, 357), (86, 108, 21), 35), ((300, 160), (253, 237, 211), 30)]   # 值 = gui pixel 實測（比 shot 的圖暗一階）


def panel_open() -> bool:
    cols = uikit.px([p for p, _, _ in PANEL_SIG])
    return bool(cols) and len(cols) == len(PANEL_SIG) and all(_near(c, ref, tol) for c, (_, ref, tol) in zip(cols, PANEL_SIG))


def hud_visible() -> bool:
    cols = uikit.px([HUD_PROBE[:2]])
    return bool(cols) and _near(cols[0], HUD_PROBE[2:], 40)


def open_panel() -> bool:
    """開切換面板並驗證。第 1 輪照規則「右鍵 2 次 + 左鍵 1 次」；沒開就等 2 秒再單點左鍵（換圖載入中 / 橫幅會吃點擊），最多 4 輪"""
    if panel_open():
        return True
    if not hud_visible():
        return False
    x, y = OPEN_BTN
    for i in range(4):
        cmd = (f'click {x} {y} right; click {x} {y} right; click {x} {y}; wait 1200' if i == 0
               else f'wait 2000; click {x} {y}; wait 1500')
        uikit.gui('seq', cmd, note='team1920 開切換面板')
        if panel_open():
            return True
    return False


def close_panel() -> bool:
    for _ in range(3):
        if not panel_open():
            return True
        uikit.gui('seq', f'click {CLOSE_BTN[0]} {CLOSE_BTN[1]}; wait 700', note='team1920 關切換面板')
    return not panel_open()


def parse(cols: list) -> list:
    """純函式：pixel 讀值（每 slot：存在、狀態、13×13 標籤掃描）→ Card 清單；空位以前（連續）才算"""
    per = 2 + len(SCAN) ** 2
    order = team.charstate.chars()
    cards = []
    for i in range(len(SLOTS)):
        seg = cols[i * per:(i + 1) * per]
        if not _near(seg[0], BEIGE, BEIGE_TOL):
            break
        r, g, b = seg[1]
        status = 'current' if (b > 200 and b > g + 30 and r < 170) else ('online' if g > b + 20 else 'unknown')
        cards.append(team.Card(i, status=status, label=team.classify_label(seg[2:])))
    if len(cards) == len(order):
        for c in cards:
            c.name = order[c.slot]
    return cards


def read_state(keep_open: bool = False) -> dict:
    """回 {'ok','cards','summary','err'}（同 team.read_state 的形狀，沒有 ms）"""
    res = {'ok': False, 'cards': [], 'summary': {}, 'err': '', 'ms': {}}
    was_open = panel_open()
    if not open_panel():
        res['err'] = '切換面板打不開（主畫面外掛鈕紅字不在 = 戰鬥 / 對話 / 載入中，或特徵沒出現）'
        return res
    try:
        pts = []
        for x0, y0 in SLOTS:
            pts += [(x0 + 157, y0 + 6), (x0 - 8, y0 + 8)]
            pts += [(x0 + dx, y0 + dy) for dy in SCAN for dx in SCAN]
        cols = uikit.px(pts)
        if cols is None or len(cols) != len(pts):
            res['err'] = '讀不到面板像素'
            return res
        if not panel_open():
            res['err'] = '讀圖中面板消失'
            return res
        cards = parse(cols)
        res.update(ok=True, cards=cards, summary=team.summarize(cards))
        return res
    finally:
        if not was_open and not (keep_open and res['ok']):
            close_panel()
