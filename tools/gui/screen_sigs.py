#!/usr/bin/env python3
"""畫面像素特徵與分類（純函式、純標準函式庫，不 import winenv，不碰遊戲）。

從 quest.py / netwatch.py / heal.py 搬出的共用特徵；quest.read_screen、netwatch、（之後的）watch 都用同一份。
特徵 = 清單，每點 tuple (x, y, r, g, b, tol)：座標是 2880×1659 版面的截圖座標（1440×830 縮圖座標），
tol 是該特徵原本使用的容差（搬移時逐一保留，不要統一）。
classify(px) 與搬出前的 quest.read_screen 判定逐點相同（fixtures/screen_px.json 驗證）。
"""
import battleguard

# ---- 容差原值 ----
TOL = 40                             # quest 預設：對話框 / 獲得物品 / 切換面板 / 選擇對象 / HUD / VS 牌
TOL_BATTLE = 25
TOL_CMD = 25
TOL_AUTO_OFF = 20
TOL_CLOSE_ROW = 22
NET_TOL = 25                         # netwatch waitpix
ENC_TOL = 50                         # heal 遇敵鈕（紅龍頭）


def close(c, ref, tol=TOL):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def _t(points, tol):
    """5 元素 (x,y,r,g,b) 清單 → 6 元素 (x,y,r,g,b,tol)"""
    return [(x, y, r, g, b, tol) for x, y, r, g, b in points]


# ---- quest 特徵（說明與實測紀錄見 quest.py 原註解 / ui/*.md）----
# 對話框：棕底 2 點 + 兩顆米色鈕（主畫面沙地很像米色，所以一定要配棕底）
SIG_DIALOG = _t([(1360, 300, 107, 70, 44), (1100, 350, 107, 70, 44), (948, 445, 229, 197, 155), (1220, 445, 229, 197, 155)], TOL)
SIG_REWARD = _t([(720, 572, 62, 106, 158), (680, 560, 82, 125, 178), (560, 620, 233, 203, 161), (720, 640, 104, 72, 46)], TOL)
SIG_PANEL = _t([(1064, 208, 197, 69, 41), (880, 590, 55, 67, 13)], TOL)    # 切換角色面板：右上紅 ✕ + 刷新鈕深綠
SIG_HUD = _t([(1300, 745, 254, 0, 0)], TOL)                                  # 外掛鈕 ASS 紅字（對話框開著時整個 UI 隱藏）
# 「選擇對象」面板（點 NPC 後右側跳出的米色面板）
SIG_SELECT = _t([(1112, 300, 104, 79, 48), (1112, 400, 104, 79, 48), (1112, 470, 104, 79, 48), (1416, 300, 93, 68, 36), (1416, 470, 93, 68, 36),
                 (1120, 470, 247, 216, 177), (1250, 490, 245, 229, 191), (1410, 470, 246, 219, 182)], TOL)
# 完整戰鬥畫面上方中央棕框外框 9 點（定義在 battleguard.py，ass.py 共用，這裡再匯出並加上容差）；VS 牌 = 快速戰鬥
SIG_BATTLE = _t(battleguard.SIG_BATTLE, TOL_BATTLE)
VS_PROBE = battleguard.VS_PROBE
VS_COLOR = battleguard.VS_COLOR
VS_TOL = TOL
# 下指令階段（右上指令框 + 上方「N回合 / 剩餘時間」）
SIG_CMD = _t([(1283, 168, 143, 119, 102), (1100, 170, 139, 117, 98), (1100, 60, 187, 161, 131), (1250, 60, 187, 161, 131), (1060, 200, 133, 100, 72)], TOL_CMD)
# 自動戰鬥鈕「關」= 靜止紅色圖示（「開」是擺動的刀劍動畫，顏色不固定 → 只判斷「是不是關」）
SIG_AUTO_OFF = _t([(1380, 600, 75, 29, 16), (1375, 605, 249, 181, 100)], TOL_AUTO_OFF)
# 戰鬥中底部「關閉」直式鈕（左側 4 點米灰；右側頭像列 2 點很暗，另判 max < 95，不在這裡）
SIG_CLOSE_ROW = _t([(480, 745, 188, 162, 134), (500, 710, 188, 162, 134), (490, 800, 182, 158, 130), (520, 745, 188, 162, 135)], TOL_CLOSE_ROW)
# 「Auto Walking」金黃字：畫面中央 550～1000 × 500～540 取樣，金黃點（r>225, 150<g<205, b<50）≥ AW_MIN 個
AW_POINTS = [(x, y) for y in range(500, 541, 8) for x in range(552, 1000, 12)]
AW_MIN = 10

# ---- netwatch 特徵（waitpix 字串由 tuple 產生；容差 NET_TOL 由呼叫端帶）----
NET_DIALOG = _t([(520, 570, 245, 217, 179), (880, 570, 245, 217, 179), (600, 300, 243, 213, 175), (600, 557, 243, 213, 175),
                 (830, 557, 243, 213, 175), (640, 557, 61, 106, 167)], NET_TOL)      # 米色「提示」視窗：兩側米色 + 中間藍鈕
NET_LOGIN = _t([(500, 570, 179, 127, 63), (760, 565, 93, 137, 187), (440, 520, 243, 217, 179)], NET_TOL)   # 登錄鈕橘、註冊鈕藍、面板米色
NET_CHARSEL = _t([(640, 640, 197, 134, 70), (500, 250, 241, 213, 179), (1186, 190, 196, 72, 48), (350, 330, 169, 117, 70)], NET_TOL)  # 全登鈕橘、米色面板、紅 X、角色列棕

# ---- heal 特徵：主畫面「取消遇敵」紅龍頭（容差 50）----
ENC_ON = _t([(1380, 630, 129, 6, 0), (1360, 632, 179, 12, 0)], ENC_TOL)


def sig_str(sig, neg: bool = False) -> str:
    """tuple 清單 → gui.ps1 waitpix 字串 'x,y,r,g,b/x,y,r,g,b'；neg = 每點加 '!'（不是這個顏色）。容差由呼叫端另帶"""
    return '/'.join(f'{x},{y},{r},{g},{b}{"!" if neg else ""}' for x, y, r, g, b, _ in sig)


def match(px: dict, sig) -> bool:
    """px = {(x, y): (r, g, b)}；sig 全部點都在各自容差內"""
    return all(close(px[(x, y)], (r, g, b), tol) for x, y, r, g, b, tol in sig)


def points() -> list:
    """classify 需要的所有取樣點（順序固定，fixture 也照這個順序）"""
    return [(x, y) for x, y, *_ in SIG_DIALOG + SIG_REWARD + SIG_PANEL + SIG_SELECT + SIG_HUD + SIG_BATTLE + SIG_CMD + SIG_AUTO_OFF] + [VS_PROBE] + AW_POINTS


def classify(px: dict) -> dict:
    """px 含 points() 的所有點 → {'state', 'gold', 'full', 'cmd', 'auto_off'}。
    state：dialog / reward / battle / panel / select / walking / idle / unknown（優先序不可動：HUD 紅字在戰鬥 / 選擇面板時還在，所以 idle 排最後）"""
    full = False
    gold = sum(1 for x, y in AW_POINTS if px[(x, y)][0] > 225 and 150 < px[(x, y)][1] < 205 and px[(x, y)][2] < 50)
    if match(px, SIG_DIALOG):
        st = 'dialog'
    elif match(px, SIG_REWARD):
        st = 'reward'
    elif match(px, SIG_BATTLE):
        st, full = 'battle', True
    elif match(px, SIG_PANEL):
        st = 'panel'
    elif match(px, SIG_SELECT):
        st = 'select'
    elif close(px[VS_PROBE], VS_COLOR, VS_TOL):
        st = 'battle'
    elif gold >= AW_MIN:
        st = 'walking'
    elif match(px, SIG_HUD):
        st = 'idle'
    else:
        st = 'unknown'
    cmd = full and match(px, SIG_CMD)                 # 完整戰鬥且在下指令階段
    auto_off = full and match(px, SIG_AUTO_OFF)       # 自動戰鬥鈕是關的
    return {'state': st, 'gold': gold, 'full': full, 'cmd': cmd, 'auto_off': auto_off}


def annotate(px: dict, base: dict) -> list:
    """watch 專用附註（第 5 階段實作；沒有正例樣本的特徵不上線）。目前不產生任何附註"""
    return []
