#!/usr/bin/env python3
"""解任務監測：任務靠遊戲內建自動巡路（Auto Walking），這支腳本每 2.5 秒截圖判斷狀態，只處理「對話要按確認」與「戰鬥按刷新角色加速」。

用法（專案根目錄；WSL / Windows 原生指令相同）：
  uv run --no-project python tools/gui/quest.py --task 黃金羚羊之謎   # 一直監測，最長 15 分鐘（--task = 追蹤列表上的任務名，必填）
  uv run --no-project python tools/gui/quest.py --once          # 只看一次、做一個動作就結束（除錯用）
  uv run --no-project python tools/gui/quest.py --max-seconds 600 --stop-after-rewards 2
  選項：--task 任務名（要點追蹤時，先用 OCR 認出追蹤列表每一格的標題，名稱相符才點；不符就捲動列表再找，找不到退出碼 5，絕不點其他任務。
          沒給 --task 又沒給 --no-track 會直接拒絕執行）、--no-marker（不找 NPC 頭上的黃色問號）、
        --every 2.5（輪詢秒數）、--no-track（不主動點任務追蹤，只處理對話 / 戰鬥）、--no-refresh（戰鬥不按刷新角色）、
        --no-clef（不用 Clef 加速層；也可設環境變數 PSA_NO_CLEF=1。預設有 token 就用，失敗 / 額度用完自動退回 OCR 與規則，見 ui/quest.md「Clef 加速層」）、
        --stop-after-rewards N（領到第 N 次「獲得物品」確認窗後停；避免自動接下一個任務。成人儀式 = 2）
  --solo   單人逃跑風格（/psa-quest-solo）：遇怪進完整戰鬥畫面 → 按右上角「逃跑」1283,168（失敗下一輪再按）；到 NPC 跳出對話框 → ESC 關掉（不按任何選項）後停下，退出碼 20；
           被打飛（回到薩姆吉爾村 1000 儲存點附近）→ 退出碼 21。要先確認快速戰鬥 / 自動戰鬥 / 原地遇敵 / 自動逃跑都關（完整戰鬥畫面才有逃跑鈕）。
  --stop-after-dialog  對話步（組隊後單步）：按完對話框、閒置 2 次就結束退出碼 0（有獲得物品視窗的步驟改用 --stop-after-rewards 1）
  --fight  戰鬥步（假設已站在 NPC 旁，**不點追蹤、不巡路**）：--npc X,Y（NPC 地圖座標）或 --npc auto（--task 的任務步驟找戰鬥步 NPC）→ 依自己座標算畫面位置點 NPC（--at X,Y 可手動給自己座標）
           → 對話框按左鈕 → 開打。戰鬥分類：開始時距離最後一次點 NPC / 按對話框 <= QUEST_BATTLE_WINDOW(15) 秒 = BOSS 戰（確保自動戰鬥開，打完連續閒置 2 次印「BOSS 戰結束」退出碼 0，不繼續巡路）；
           否則 = 小怪（自動戰鬥開著就先關，下指令階段按逃跑）。已手動點過 NPC 用 --no-click。
           點 NPC 後 12 秒沒對話框也沒戰鬥 → 退出碼 22（沒點到 NPC）；對話後 15 秒沒開打 → 23；被打飛 21。
           範例：quest.py --fight --task 英雄島前傳 --npc auto --max-seconds 300
  模擬測試：uv run --no-project python tools/gui/test_quest_fight.py
  事件記錄：notes/quest-events.log（每行一筆，附截圖路徑 tools/.cache/quest-log/）。

狀態判斷（都是背景截圖讀像素，座標為 2880×1659 → 截圖 1440×830；細節與實測見 .claude/skills/psa-game-ui/ui/quest.md）：
  對話框   右側棕底 + 兩顆米色鈕 → 點左鈕 948,461（接受 / 完成 / 成人勾玉 等推進鈕；右鈕 1220,461 是「再見」不點）
  獲得物品 藍色「確認」鈕 720,572 + 米色底 → 點它
  戰鬥     角色頭上綠色 VS 牌（快速戰鬥沒有戰鬥畫面）→ 切換 763,760 → 刷新角色 910,578（按完面板自己關）
  巡路中   畫面中央金黃色「Auto Walking」字樣
  主畫面   外掛鈕紅字 ASS（沒對話框 / 巡路 / 戰鬥時）→ 檢測方針（使用者指定）：
           1. 場景裡有黃色「?」「!」任務標記 → 優先點它（findmark.ps1 找黃色色塊，點標記下方的 NPC）
           2. 沒有 → 在追蹤列表先用標題圖片樣板比對（titlematch，0.7 秒）、沒樣板 / 沒找到才用 OCR（ocr.ps1，成功會存樣板）找 --task 那一格，必要時捲動列表，確認標題相符才點 → 開始（繼續）巡路
  不認得   連續 3 次都不是以上任何狀態（答題 / 驗證視窗、讀取中卡住…）→ 存圖、印警告、退出碼 2（鐵則 5：交給使用者）
  追蹤沒反應 點了任務追蹤連續 2 次都沒進入巡路 / 對話 / 戰鬥 → 退出碼 3，改手動（walk.py + 點 NPC）
退出碼：20 --solo 到達 NPC（已 ESC 關對話框）、21 被打飛回村（--solo / --fight）、22 --fight 沒點到 NPC、23 --fight 對話後沒開打、0 正常結束（任務完成〔領過獎勵後整個追蹤列表掃完沒有 --task，印「任務完成」〕/ 時間到 / 做完對話或領獎後連續 2 次閒置提前結束 / --once / 達到 --stop-after-rewards）、2 不認得的畫面、3 追蹤沒反應、4 版面不支援、5 追蹤列表掃完（到頂 + 到底）找不到 --task 的任務且沒領過獎勵（沒點任何東西）。
只透過 gui.ps1 背景截圖 / 點擊，不碰遊戲記憶體。
"""
import argparse
import os
import difflib
import json
import sys
import time
from pathlib import Path

import clef
import layout
import netwatch
import winenv
import walk
from walk import ROOT, gui, log, PRIMER, stat
import re

EXIT_AT_NPC = 20                     # --solo：到達 NPC（對話框已 ESC 關閉）
EXIT_KNOCKED = 21                    # 被打飛回薩姆吉爾儲存點
EXIT_NO_NPC = 22                     # --fight：點 NPC 後 NPC_WAIT 秒內沒對話框也沒戰鬥（沒點到 NPC / 被小怪打斷）
EXIT_NO_BATTLE = 23                  # --fight：有對話但 QUEST_BATTLE_WINDOW 秒內沒開打（這步其實不戰鬥？）
NPC_WAIT = 12.0                      # --fight 點 NPC 後最多等幾秒看有沒有反應（走過去 + 開對話框）
LOG_FILE = ROOT / 'notes' / 'quest-events.log'
SHOT_DIR = ROOT / 'tools' / '.cache' / 'quest-log'

# ---- 座標與特徵色（2880×1659 版面，截圖座標；2026-10-09 實測）----
TRACKER = (205, 325)                 # 左側任務追蹤第一條：點了自動尋路到任務 NPC
SWITCH_BTN = (763, 760)              # 主畫面「切換」
REFRESH_BTN = (910, 578)             # 切換角色面板「刷新角色」（綠色，最右；按完面板自己關）
QUEST_BATTLE_WINDOW = 15.0           # 最後一次「按對話框 / 點 NPC / 點問號」後幾秒內開始的戰鬥 = 任務戰鬥（才按刷新角色）
ESCAPE_BTN = (1283, 168)             # 完整戰鬥下指令畫面右上角指令框的「逃跑」（跑步小人，第 2 排最右；2026-10-10 實測，點了出現 Escape! 泡泡）
AUTO_BTN = (1380, 600)               # 戰鬥畫面右側「自動戰鬥」鈕（點一下切換開 / 關，同外掛 ASS 的自動戰鬥；日誌「你已開啟 / 關閉自動戰鬥」）
# 下指令階段（右上指令框 + 上方「N回合 / 剩餘時間」）：播放中框會消失，用框的底色 / 邊框 + 逃跑鈕判斷（2026-10-10 實測，容差 25）
SIG_CMD = [(1283, 168, 143, 119, 102), (1100, 170, 139, 117, 98), (1100, 60, 187, 161, 131), (1250, 60, 187, 161, 131), (1060, 200, 133, 100, 72)]
# 自動戰鬥鈕「關」= 靜止的紅色圖示（兩點固定）；「開」是會擺動的刀劍動畫，顏色不固定 → 只判斷「是不是關」（容差 20）
SIG_AUTO_OFF = [(1380, 600, 75, 29, 16), (1375, 605, 249, 181, 100)]
SAVE_POINT = (1000, 93, 99)          # 薩姆吉爾的儲存點巫女 1000:94,99、復活 / 傳送落點 92,99 附近（知識庫 Npc 3014）
KO_RADIUS = 8                        # 地圖 1000 且離儲存點這麼近（格）才可能是「被打飛」
DIALOG_NEXT = (948, 461)             # NPC 對話框左鈕
REWARD_OK = (720, 572)               # 「獲得物品」視窗的藍色確認鈕
# 對話框：棕底 2 點 + 兩顆米色鈕（heal.py 同款）。主畫面沙地很像米色，所以一定要配棕底
SIG_DIALOG = [(1360, 300, 107, 70, 44), (1100, 350, 107, 70, 44), (948, 445, 229, 197, 155), (1220, 445, 229, 197, 155)]
SIG_REWARD = [(720, 572, 62, 106, 158), (680, 560, 82, 125, 178), (560, 620, 233, 203, 161), (720, 640, 104, 72, 46)]
SIG_PANEL = [(1064, 208, 197, 69, 41), (880, 590, 55, 67, 13)]    # 切換角色面板：右上紅 ✕ + 刷新鈕深綠
SIG_HUD = [(1300, 745, 254, 0, 0)]                                  # 外掛鈕 ASS 紅字（對話框開著時整個 UI 隱藏）
VS_PROBE = (706, 295)                                               # 頭上 VS 牌綠框（heal.py SIG_NO_BATTLE 反過來）
VS_COLOR = (122, 227, 0)
# 完整戰鬥畫面（2026-10-10 實測，下指令 / 播放中兩種都量過）：上方中央棕框標籤（播放中 → 米色字；下指令 → 「N回合」+ 下方「剩餘時間 90」倒數），
# 標籤文字會變，所以只取「外框」9 點（兩種畫面像素相同）；主畫面 / 對話 / 獲得物品 / 地圖載入在這些點都不同。9 點同時符合（容差 25）才算。
# 完整戰鬥時 HUD 的 ASS 紅字還在，所以要排在 idle 之前
SIG_BATTLE = [(650, 25, 99, 77, 57), (780, 38, 252, 234, 200), (645, 38, 99, 57, 31), (790, 38, 250, 227, 194), (645, 12, 244, 225, 182),
              (790, 12, 255, 230, 192), (660, 45, 200, 172, 139), (770, 45, 236, 209, 174), (643, 25, 242, 217, 181)]
# 「Auto Walking」金黃字：畫面中央 550～1000 × 500～540 取樣，金黃點（r>225, 150<g<205, b<50）≥ 10 個
AW_POINTS = [(x, y) for y in range(500, 541, 8) for x in range(552, 1000, 12)]
AW_MIN = 10
TOL = 40

# ---- 任務追蹤列表（左側，「任務 / 組隊」分頁下方；一格一個任務，標題 + 步驟說明，可上下捲動）----
LIST_BOX = (75, 270, 260, 180)       # OCR 區域 x,y,w,h（截圖座標）：標題深棕字
LIST_Y_MAX = 425                     # 標題中心 y 超過這個的格子被面板裁掉一半，不點
CARD_DY = 16                         # 點擊位置 = 標題中心往下一點（格子中心）
SCROLL_UP = (200, 420, 200, 300)     # 往上拖 120px ≈ 捲一格（列表往下走）
SCROLL_DOWN = (200, 300, 200, 420)   # 反向


def close(c, ref, tol=TOL):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def read_screen() -> dict:
    """一次 gui pixel 讀完所有特徵點 → 判斷狀態"""
    pts = [(x, y) for x, y, *_ in SIG_DIALOG + SIG_REWARD + SIG_PANEL + SIG_HUD + SIG_BATTLE + SIG_CMD + SIG_AUTO_OFF] + [VS_PROBE] + AW_POINTS
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
    cols = [tuple(int(v) for v in c.split(',')) for c in out]
    if len(cols) != len(pts):
        return {'state': 'error', 'raw': out[:3]}
    px = dict(zip(pts, cols))
    match = lambda sig: all(close(px[(x, y)], (r, g, b)) for x, y, r, g, b in sig)
    full = False
    gold = sum(1 for x, y in AW_POINTS if px[(x, y)][0] > 225 and 150 < px[(x, y)][1] < 205 and px[(x, y)][2] < 50)
    if match(SIG_DIALOG):
        st = 'dialog'
    elif match(SIG_REWARD):
        st = 'reward'
    elif all(close(px[(x, y)], (r, g, b), 25) for x, y, r, g, b in SIG_BATTLE):
        st, full = 'battle', True
    elif match(SIG_PANEL):
        st = 'panel'
    elif close(px[VS_PROBE], VS_COLOR):
        st = 'battle'
    elif gold >= AW_MIN:
        st = 'walking'
    elif match(SIG_HUD):
        st = 'idle'
    else:
        st = 'unknown'
    cmd = full and all(close(px[(x, y)], (r, g, b), 25) for x, y, r, g, b in SIG_CMD)            # 完整戰鬥且在下指令階段
    auto_off = full and all(close(px[(x, y)], (r, g, b), 20) for x, y, r, g, b in SIG_AUTO_OFF)  # 自動戰鬥鈕是關的
    return {'state': st, 'gold': gold, 'full': full, 'cmd': cmd, 'auto_off': auto_off}


def ps_json(script: str, *args) -> dict:
    """跑 tools/gui 的 PowerShell 腳本（ocr.ps1 / findmark.ps1）→ 解析輸出的 JSON；失敗回 {'ok': False}"""
    r = winenv.run_ps(script, *[str(a) for a in args])
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False, 'error': (r.stderr or r.stdout)[:200]}


def norm(t: str) -> str:
    """任務名比對前的正規化：去空白、括號 / 版本字尾（例「黃金羚羊之謎(1.82)」→「黃金羚羊之謎」）"""
    import re
    return re.sub(r'[\s\(（\[【].*$', '', t)


def match_title(want: str, got: str) -> bool:
    """OCR 讀到的標題 got 是不是任務 want：完整包含，或相似度 >= 0.75（OCR 偶爾錯 1 個字）"""
    w, g = norm(want), norm(got)
    if not w or not g:
        return False
    return w in g or (len(g) >= 3 and g in w) or difflib.SequenceMatcher(None, w, g).ratio() >= 0.75


def read_list_titles() -> list[dict]:
    """OCR 追蹤列表的標題行 → [{y, texts: [各倍數讀到的字]}]（依 y 排序）。
    Windows OCR 對同一張圖換放大倍數，結果差很多（有時整行讀不到、有時只讀到右半），
    所以一次 ocr.ps1 跑放大 2～7 倍、把 y 相近（<14px）的行併成一格，比對時只要任一種讀法符合即可。"""
    x, y, w, h = LIST_BOX
    r = ps_json('ocr.ps1', x, y, w, h, '-Zooms', '2,3,4,5,6,7', '-Dark', 150)
    rows: list[dict] = []
    for ln in sorted(r.get('lines', []), key=lambda o: o['y']):
        if len(ln['text']) < 2:
            continue
        for row in rows:
            if abs(row['y'] - ln['y']) < 14:
                row['texts'].append(ln['text'])
                break
        else:
            rows.append({'y': ln['y'], 'texts': [ln['text']]})
    return rows


def list_signature() -> list[tuple]:
    """追蹤列表區域的像素取樣（判斷捲動有沒有動、是否到盡頭用；比 OCR 穩）"""
    pts = ' '.join(f'{x},{y}' for y in range(285, 445, 14) for x in range(90, 330, 20))
    return gui('pixel', pts).split()


class _Interrupted(Exception):
    """掃描途中畫面不再是主畫面（跳出對話 / 戰鬥 / 領獎）"""


def scroll_list(drag: tuple[int, int, int, int], note: str, before: list) -> tuple[bool, list]:
    """捲動追蹤列表一格；回傳（畫面有沒有變, 捲完的像素取樣）。before = 捲動前的取樣（呼叫端沿用上一次的，省一次截圖）；沒變 = 已到盡頭"""
    gui('seq', 'drag %d %d %d %d; wait 1400' % drag, note=note)
    after = list_signature()
    return after != before, after


def _find_on_page(want: str, mode: str) -> int | None:
    """目前這一頁追蹤列表上 want 的標題中心 y（沒有回 None）；畫面不是主畫面 → _Interrupted。
    tpl = 標題圖片樣板（約 0.7 秒）；ocr = Windows OCR（3～7 秒），認出目標就存樣板。名稱不符絕不回傳。"""
    if read_screen()['state'] != 'idle':
        raise _Interrupted()
    if mode == 'tpl':
        ty = _tm_find(want)
        return ty if ty is not None and ty <= LIST_Y_MAX else None
    rows = read_list_titles()
    if not rows:                                           # 整個列表讀不到（剛換圖 / 捲動慣性中）→ 等一下再讀一次
        time.sleep(1.0)
        rows = read_list_titles()
    log(f'追蹤列表標題：{[r["texts"][0] for r in rows]}')
    for row in rows:
        if row['y'] <= LIST_Y_MAX and any(match_title(want, t) for t in row['texts']):
            _tm_learn(want, row['y'])                      # OCR 認出了 → 存標題樣板，下次不必 OCR
            return row['y']
    return None


def track_task(want: str, max_scrolls: int = 12, click: bool = True) -> bool | None:
    """掃一遍追蹤列表找標題 = want 的那一格並點它（開始巡路）。名稱不符絕不點。
    回傳：True 找到（click=True 時已點）、False 整個列表掃完沒有、None 途中畫面不再是主畫面（交回主迴圈，不算找不到）。
    一輪有明確終點：先看目前這頁 → 往上捲到頂（每頁都看）→ 再往下捲到底（已看過的頁不重看）；到頂 / 到底用像素取樣沒變判斷，不來回。
    辨識：該任務有標題樣板 → 只用樣板比對（0.7 秒 / 頁，錯配率 0，樣板沒命中 = 不在）；沒樣板 → OCR（3～7 秒 / 頁，並學樣板）。"""
    gui('seq', PRIMER)
    ensure_task_tab()
    mode = 'tpl' if _tm_has(want) else 'ocr'
    t0 = time.time()
    if mode == 'ocr' and click and clef.available():
        # Clef-flash 取代 OCR 的「第一格」快速通道：只在主畫面（呼叫端已確認 idle，非登入畫面）才上傳追蹤區裁圖；
        # 最上面一格標題 = want 且 choice / noul 機率都 >= 0.9 才直接點第一格；否則 / 失敗 → 照舊 OCR 掃描
        img = clef_shot_bytes()
        hit = clef.check_track_top(img, want, known_task_titles()) if img else None
        if hit:
            gui('seq', f'click {TRACKER[0]} {TRACKER[1]}', note=f'點追蹤「{want}」（Clef，--task {want}）')
            event(f'追蹤列表第一格由 Clef 認出「{want}」→ 點 {TRACKER[0]},{TRACKER[1]}（耗時 {time.time() - t0:.1f}s，略過 OCR）')
            return True
        log('Clef 沒認出第一格是目標（或不可用）→ 退回 OCR 掃描' if hit is not None else 'Clef 不可用 → 退回 OCR 掃描')
    try:
        sig = list_signature()
        y = _find_on_page(want, mode)
        ups = pages = 0
        if y is None:
            while ups < max_scrolls:                       # 往上到頂
                moved, sig = scroll_list(SCROLL_DOWN, f'任務追蹤列表往上捲一格找「{want}」', sig)
                if not moved:
                    break
                ups += 1
                if (y := _find_on_page(want, mode)) is not None:
                    break
        if y is None:
            for i in range(max_scrolls * 2):               # 往下到底；前 ups 格是剛看過的頁，不重看
                moved, sig = scroll_list(SCROLL_UP, f'任務追蹤列表往下捲一格找「{want}」', sig)
                if not moved:
                    break
                pages += 1
                if i + 1 > ups and (y := _find_on_page(want, mode)) is not None:
                    break
    except _Interrupted:
        return None
    log(f'追蹤列表掃描（{mode}）{"找到 y=%d" % y if y is not None else "沒找到"}，上 {ups} 格 / 下 {pages} 格，耗時 {time.time() - t0:.1f}s')
    if y is None:
        return False
    if click:
        cx, cy = 205, y + CARD_DY
        gui('seq', f'click {cx} {cy}', note=f'點追蹤「{want}」（{mode}，--task {want}）')
        event(f'追蹤列表找到「{want}」（{mode}）→ 點 {cx},{cy}')
    return True


TAB_TASK = (148, 236)                # 左側面板「任務」分頁鈕
TAB_PROBE = ((130, 225), (270, 225))  # 選中的分頁底是亮米色（R>190），沒選中是深棕（R<120）：任務在左、組隊在右


def ensure_task_tab() -> None:
    """左側面板停在「組隊」分頁時追蹤列表看不到任務（OCR 只讀到「創建隊伍」→ 誤判找不到）。
    只在「組隊亮、任務暗」很明確時點「任務」分頁；讀不準就不動。"""
    try:
        out = gui('pixel', ' '.join(f'{x},{y}' for x, y in TAB_PROBE)).split()
        (tr, _, _), (gr, _, _) = [tuple(int(v) for v in c.split(',')) for c in out]
        if tr < 120 and gr > 190:
            gui('seq', f'click {TAB_TASK[0]} {TAB_TASK[1]}; wait 600', note='左側面板在「組隊」分頁 → 切回「任務」')
            event('左側面板在組隊分頁，已切回任務分頁')
    except Exception as e:
        log(f'ensure_task_tab 失敗：{e}')


def _tm_has(want: str) -> bool:
    try:
        import titlematch
        return titlematch.has_templates(want)
    except Exception as e:                                 # 樣板模組壞了 → 退回 OCR
        log(f'titlematch 不可用：{e}')
        return False


def _tm_find(want: str) -> int | None:
    try:
        import titlematch
        return titlematch.find(want)
    except Exception as e:
        log(f'titlematch.find 失敗：{e}')
        return None


def _tm_learn(want: str, y: int) -> None:
    try:
        import titlematch
        d = titlematch.learn(want, y)
        if d:
            log(f'新增標題樣板 {d.name}')
    except Exception as e:
        log(f'titlematch.learn 失敗：{e}')


# ---- 黃色「?」任務標記（NPC 頭上；findmark.ps1 找黃色連通色塊，形狀 / 位置過濾在這裡）----
# 實測（2026-10-10，庫伊老爺爺頭上）：「?」金黃色，因高光被切成 3 塊（單位 = 截圖座標）：
#   上半彎鉤 18x15 n≈117、中間竪 5x10 n≈24、下面圓點 6x7 n≈27；整體 w≈18 h≈33。
#   「!」（可接任務）是 8x15 + 7x9 兩塊、寬度 ≤ 8，與「?」的彎鉤（寬 ≥ 14）明確不同；使用者只要「?」。
#   NPC 名字黃字拆成 n≤13 的小碎塊、Auto Walking 金黃字大又寬（w > 24），都不符。
MARK_HEAD = dict(w=(14, 24), h=(11, 20), n=(70, 200))      # 「?」上半彎鉤
MARK_DOT = dict(w=(4, 9), h=(5, 10), n=(15, 45))           # 「?」下面的圓點
MARK_NPC_DYS = (96, 135)              # 連續第 1、2 次嘗試的偏移；2 次都沒反應就改走追蹤列表（精靈之木這種大樹，身體在標記下 ~270，點標記下方會點到樹冠 / 隊友）
MARK_NPC_DY = 96                      # 彎鉤中心往下 96 = NPC 身體（實測：看門者彎鉤 y=296 → 點 y=392 開對話；+90 與 +45 名字牌上都沒反應）
# 場景區外的 UI（左側任務面板 / 左上 HUD / 右上地圖鈕 / 左下聊天 / 底部按鈕列 / 右側遇敵鈕）不算
MARK_EXCLUDE = [(0, 0, 560, 140), (60, 190, 400, 470), (1060, 0, 1440, 230), (0, 550, 540, 830), (700, 700, 1440, 830), (1300, 600, 1440, 830)]


def _in(b: dict, spec: dict) -> bool:
    return all(spec[k][0] <= b[k] <= spec[k][1] for k in ('w', 'h', 'n'))


def find_marker() -> dict | None:
    """場景區有沒有黃色「?」：找得到「彎鉤 + 正下方圓點」的組合才算；回傳彎鉤色塊（含 x,y,n）或 None"""
    r = ps_json('findmark.ps1')
    bl = r.get('blobs', [])
    for b in sorted((b for b in bl if _in(b, MARK_HEAD)), key=lambda b: -b['n']):
        if any(x0 <= b['x'] <= x1 and y0 <= b['y'] <= y1 for x0, y0, x1, y1 in MARK_EXCLUDE):
            continue
        if any(_in(d, MARK_DOT) and abs(d['x'] - b['x']) <= 6 and 15 <= d['y'] - b['y'] <= 30 for d in bl):
            return b
    return None


def event(msg: str, shot: str | None = None) -> None:
    """印出並寫進 notes/quest-events.log"""
    log(msg)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}' + (f' [{shot}]' if shot else '') + '\n')
    except OSError:
        pass


def snap(tag: str) -> str:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    p = SHOT_DIR / f'{time.strftime("%H%M%S")}-{tag}.png'
    gui('shot', str(p))
    return str(p.relative_to(ROOT))


CLEF_WAIT_MAX = 20                   # Clef 判成「載入畫面 / 戰鬥中」時，最多連續幾次不算「不認得」（之後照舊 3 次停手）
CLEF_WAIT_SCENES = ('載入畫面', '戰鬥中')


def clef_shot_bytes() -> bytes | None:
    """背景截一張遊戲視窗（PrintWindow，只含遊戲客戶區，不含桌面）→ bytes；截完立刻刪檔。
    上傳前先用本地規則排除登入畫面 / 網路異常提示（netwatch.detect），這兩種不上傳。"""
    try:
        if netwatch.detect() is not None:
            return None
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        p = SHOT_DIR / 'clef-tmp.png'
        gui('shot', str(p))
        data = p.read_bytes()
        p.unlink(missing_ok=True)
        return data
    except Exception as e:
        log(f'Clef 截圖失敗（{type(e).__name__}），退回原流程')
        return None


def known_task_titles() -> list[str]:
    """已有標題樣板的任務名（titlematch 的樣板檔名「任務@N.png」），給 Clef 當 choice 候選"""
    d = ROOT / 'tools' / '.cache' / 'task-titles'
    try:
        return sorted({f.name.split('@')[0] for f in d.glob('*.png')})
    except OSError:
        return []


def is_quest_battle(last_action: float, now: float, window: float = QUEST_BATTLE_WINDOW) -> bool:
    """戰鬥開始時離最後一次任務互動（按對話框 / 點 NPC / 點問號）夠近 → 任務戰鬥。巡路途中的隨機遇敵不算"""
    return last_action > 0 and now - last_action <= window


def plan_battle_action(s: dict, boss: bool, since_click: float) -> str | None:
    """完整戰鬥畫面該做什麼（純函式，方便模擬測試）：
    BOSS 戰 → 自動戰鬥鈕是「關」才點（'auto_on'）；小怪 → 下指令階段按逃跑（'escape'），
    自動戰鬥是開著（鈕不是靜止紅圖示、也沒有指令框）就先關（'auto_off'，指令框下一回合才會出現）。
    沒有完整戰鬥畫面（快速戰鬥）或點擊間隔不夠 → None。"""
    if not s.get('full'):
        return None
    if boss:
        return 'auto_on' if s.get('auto_off') and since_click >= 3.0 else None
    if s.get('cmd'):
        return 'escape' if since_click >= 1.2 else None
    if not s.get('auto_off') and since_click >= 3.0:
        return 'auto_off'
    return None


def refresh_characters() -> None:
    """戰鬥中按「刷新角色」加速：切換 → 等面板 → 刷新角色；面板還開著就 ESC"""
    sig = '/'.join(f'{x},{y},{r},{g},{b}' for x, y, r, g, b in SIG_PANEL)
    gui('seq', f'click {SWITCH_BTN[0]} {SWITCH_BTN[1]}; waitpix 1500 {sig} 40; ifok click {REFRESH_BTN[0]} {REFRESH_BTN[1]}; wait 500')
    if read_screen()['state'] == 'panel':
        gui('key', '{ESC}')


def read_pos() -> tuple[int, int, int] | None:
    """stat.ps1 OCR 讀右上角「地圖ID:x,y」→ (地圖, x, y)；讀不到回 None"""
    m = re.match(r'(\d+):(\d+),(\d+)', stat().get('pos') or '')
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_knocked(last: tuple[int, int, int] | None, cur: tuple[int, int, int] | None) -> bool:
    """被打飛 = 現在在薩姆吉爾村 1000 的儲存點附近，而且「上次不在那裡」（換了地圖，或位置突然跳了 > KO_RADIUS 以上）。
    任務本來就在儲存點附近開始時，last 也在附近 → 不算（要真的被傳走才算）；不知道上次位置（last=None）也不算。"""
    if not cur or cur[0] != SAVE_POINT[0]:
        return False
    near = lambda p: p[0] == SAVE_POINT[0] and max(abs(p[1] - SAVE_POINT[1]), abs(p[2] - SAVE_POINT[2])) <= KO_RADIUS
    if not near(cur):
        return False
    return last is not None and not near(last)


def resolve_npc(a) -> tuple[int, int] | None:
    """--fight 的 NPC 地圖座標：--npc X,Y，或 --npc auto（--task 的任務步驟中第一個戰鬥步的 endNpc）；失敗印原因回 None"""
    if a.npc.lower() == 'auto':
        if not a.task:
            log('--npc auto 需要 --task（用任務步驟找戰鬥步的 NPC）')
            return None
        g, ts, _ = walk.psa.task_steps(a.task)
        for t in ts:
            if walk.psa.classify_step(t)[0] == 'battle':
                n = walk.psa.by_id('Npc').get(t.get('endNpc'))
                if n:
                    log(f'--npc auto：第 {t.get("step")} 步 {walk.psa.nm(n)} @ 地圖 {n.get("map")}:{n.get("x")},{n.get("y")}')
                    a.npc_map = n.get('map')
                    return (n['x'], n['y'])
        log(f'任務「{a.task}」找不到戰鬥步的 NPC，請改用 --npc X,Y')
        return None
    m = re.fullmatch(r'(\d+)[,:](\d+)', a.npc.strip())
    if not m:
        log('--fight 要給 --npc X,Y（NPC 地圖座標）/ --npc auto（用 --task 查），或加 --no-click（已自己點過 NPC）')
        return None
    return (int(m[1]), int(m[2]))


def click_npc(npc: tuple[int, int], a) -> bool:
    """依自己的座標算 NPC 的畫面位置並點一下（走路函式 walk.npc_screen；不巡路、不亂走）。座標讀不到 / 太遠 / 地圖不符 → False"""
    if a.at:
        m = re.fullmatch(r'(\d+),(\d+)', a.at.strip())
        cur = (getattr(a, 'npc_map', None), int(m[1]), int(m[2])) if m else None
    else:
        cur = None
        for _ in range(3):
            if (cur := read_pos()):
                break
            time.sleep(1.0)
    if not cur:
        log('讀不到自己的座標（--at X,Y 可手動給）')
        return False
    want_map = getattr(a, 'npc_map', None)
    if want_map and cur[0] and cur[0] != want_map:
        log(f'目前在地圖 {cur[0]}，NPC 在地圖 {want_map}：不在同一張圖，先傳送 / 走過去（--fight 不巡路）')
        return False
    at = (cur[1], cur[2])
    dx, dy = npc[0] - at[0], npc[1] - at[1]
    if not walk.reachable(dx, dy):
        log(f'NPC {npc} 離我 {at} 太遠或點擊位置落在 UI 上（dx={dx}, dy={dy}）→ 先走近一點再跑 --fight')
        return False
    nx, ny = walk.npc_screen(npc, at)
    gui('seq', f'{PRIMER}; click {nx} {ny}', note=f'--fight 點 NPC {npc}（我在 {at}）')
    event(f'--fight 點 NPC {npc}（我在 {at}）→ 畫面 {nx},{ny}')
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description='解任務監測：對話按確認、戰鬥按刷新角色、巡路停了重點任務追蹤')
    ap.add_argument('--once', action='store_true', help='只判斷一次、做一個動作就結束')
    ap.add_argument('--every', type=float, default=None, help='輪詢間隔秒數（預設 2.5；--solo / --fight 預設 1.5）')
    ap.add_argument('--solo', action='store_true', help='單人逃跑風格：完整戰鬥按逃跑；到 NPC 出對話框 → ESC 後停下（退出碼 20）；被打飛退出碼 21')
    ap.add_argument('--stop-after-dialog', action='store_true', help='對話框按完、回主畫面連續閒置 2 次就結束（沒有獲得物品視窗的對話步用；組隊後單步對話用，避免自動點下一步追蹤開始巡路）')
    ap.add_argument('--fight', action='store_true', help='戰鬥步（要先站在 NPC 附近；不巡路）：點 NPC → 對話左鈕 → 開打；只有點 NPC / 按對話框後 %d 秒內開始的才是 BOSS 戰（開自動戰鬥、打完退出碼 0）；其他戰鬥是小怪（關自動戰鬥、按逃跑）；沒反應退出碼 22、對話後沒開打 23、被打飛 21' % QUEST_BATTLE_WINDOW)
    ap.add_argument('--npc', default='', help='--fight 用：NPC 的地圖座標 X,Y，或 auto（用 --task 的任務步驟找第一個戰鬥步的 NPC，同 psa.py steps）；不給 = 必須加 --no-click')
    ap.add_argument('--at', default='', help='--fight 用：自己目前的座標 X,Y（不給就 OCR 讀右上角）')
    ap.add_argument('--no-click', action='store_true', help='--fight 用：不點 NPC（已手動點過 / 對話已開），從現在起算開打時間窗')
    ap.add_argument('--max-seconds', type=int, default=900, help='最長執行秒數（預設 900）')
    ap.add_argument('--task', default='', help='追蹤列表上的任務名（例：黃金羚羊之謎）；點追蹤前先 OCR 核對標題，名稱不符絕不點')
    ap.add_argument('--no-marker', action='store_true', help='不找 NPC 頭上的黃色問號')
    ap.add_argument('--no-track', action='store_true', help='不主動點任務追蹤')
    ap.add_argument('--no-clef', action='store_true', help='不用 Clef（Cloudflare Workers AI）加速層，全走原本的規則 / OCR（也可設環境變數 PSA_NO_CLEF=1）')
    ap.add_argument('--no-refresh', action='store_true', help='戰鬥不按刷新角色')
    ap.add_argument('--stop-after-rewards', type=int, default=0, help='領到第 N 次獲得物品視窗後停（0 = 不停）')
    a = ap.parse_args()
    if layout.current() != '2880x1659':
        log('quest.py 只量過 2880×1659 版面，先跑 gui.sh max；見 ui/layout-1920x1017.md')
        return 4
    if a.solo and a.fight:
        log('--solo（逃跑）與 --fight（打）互斥')
        return 4
    if a.every is None:
        a.every = 1.5 if (a.solo or a.fight) else 2.5
    npc_xy = None                        # --fight：要點的 NPC 地圖座標
    if a.fight:
        a.no_track = True                # --fight 假設已站在 NPC 旁，絕不點任務追蹤巡路
        if not a.no_click:
            npc_xy = resolve_npc(a)
            if npc_xy is None:
                return 4
    guard_ko = a.solo or a.fight         # 只有這兩種風格才會被打飛後要停手
    if not a.no_track and not a.task:
        log('沒給 --task：不知道要點哪個任務追蹤（點錯任務是之前的老問題）。請加 --task 任務名，或用 --no-track（只處理對話 / 戰鬥）')
        return 4
    clef.set_logger(event)
    if a.no_clef:
        clef.set_enabled(False)
    else:
        clef.available()         # 啟動時檢查一次：沒 token 會在 stderr 醒目提示並寫事件 log
    end = time.time() + a.max_seconds
    clef_wait = 0                # 連續被 Clef 解釋成「載入 / 戰鬥」的 unknown 次數
    marker_fail = 0              # 連續點黃色問號沒反應的次數
    task_miss = 0
    event(f'開始監測（每 {a.every}s，最長 {a.max_seconds}s）')
    unknown = 0
    track_fail = 0
    tracked = False              # 剛點過任務追蹤，還沒看到任何反應
    rewards = 0
    checked_rewards = 0          # 已做過「領獎後完整列表檢查」的獎勵次數
    last = ''
    battles = dialogs = 0
    last_full_log = 0.0
    last_action = 0.0            # 最後一次對話框 / 點 NPC / 點問號的時間（time.time()）
    quest_battle = False         # 目前這場戰鬥是不是任務戰鬥（戰鬥開始那一刻決定）
    prev_st = ''
    idle_streak = 0
    last_pos = None                              # 上一次讀到的 (地圖, x, y)；對戰鬥畫面 OCR 會讀不到，起點最多試 3 次
    for _ in range(3 if guard_ko else 0):
        if (last_pos := read_pos()) or read_screen()['state'] == 'battle':
            break
        time.sleep(1.0)
    last_pos_t = time.time()
    ko_pending = False           # 剛打完一場 / 讀圖中 → 下次閒置時查一次位置
    last_click_t = 0.0           # 逃跑 / 自動戰鬥鈕最後一次點擊時間（避免連點）
    in_battle = False            # 戰鬥中（直到看到主畫面 / 對話 / 領獎 / 巡路才算結束；中間 unknown / panel 不重新分類）
    boss = False                 # 目前這場是不是 BOSS 戰（戰鬥開始那一刻決定，打完才重設）
    boss_seen = False            # --fight：已打過 BOSS 戰
    npc_click_t = 0.0            # --fight：點 NPC 的時間
    warned_quick = False
    if guard_ko:
        event(f'模式：{"單人逃跑 --solo" if a.solo else "戰鬥步 --fight"}；起點 {last_pos}')
    if a.fight:
        if npc_xy:
            if not click_npc(npc_xy, a):
                return 4
            npc_click_t = last_action = time.time()
        elif a.no_click:
            last_action = time.time()
            event('--fight --no-click：不點 NPC，從現在起算 BOSS 戰時間窗')
    while True:
        s = read_screen()
        st = s['state']
        if st in ('idle', 'walking', 'dialog', 'reward'):
            in_battle = False
        if st == 'battle' and not in_battle:
            in_battle = True
            quest_battle = is_quest_battle(last_action, time.time())
            boss = quest_battle
            boss_seen = boss_seen or boss
            log(f'戰鬥開始：{"任務戰鬥（對話 / 點 NPC 後 %ds 內）" % QUEST_BATTLE_WINDOW if quest_battle else "一般遇敵（只等，不按刷新角色）"}')
            if a.fight:
                event(f'--fight 戰鬥開始：{"BOSS 戰（點 NPC / 對話後 %.0f 秒）→ 自動戰鬥" % (time.time() - last_action) if boss else "小怪 → 關自動戰鬥並逃跑"}')
        if guard_ko and prev_st == 'battle' and st != 'battle':
            ko_pending = True
        prev_st = st
        if st in ('unknown', 'error'):
            # 先給 netwatch 看：「網路異常，是否重連?」提示 / 登入畫面（自動按登錄重登；失敗才 halt exit 10，不輸入帳密）
            nr = netwatch.guard('quest')
            if nr['status'] == 'reconnected':
                event('網路斷線後已恢復（netwatch），重新判斷畫面')
                tracked, track_fail, marker_fail, last, unknown = False, 0, 0, '', 0
                continue
            if nr.get('failed'):
                continue
        if st != last:
            log(f'狀態 {last or "-"} → {st}' + (f'（金黃點 {s["gold"]}）' if st in ('walking', 'idle') else ''))
        last = st
        if st != 'unknown':
            unknown = 0
            clef_wait = 0
        idle_streak = idle_streak + 1 if st == 'idle' else 0
        if st in ('dialog', 'reward', 'battle'):
            marker_fail = 0
        if st in ('walking', 'dialog', 'reward', 'battle'):
            if tracked:
                tracked, track_fail = False, 0
        if st == 'dialog' and a.solo:
            shot = snap('npc-dialog')
            gui('key', '{ESC}', note='到達 NPC：ESC 關閉對話框（不回答任何選項）')
            event(f'--solo 到達 NPC：對話框已 ESC 關閉，停下交給組隊（退出碼 {EXIT_AT_NPC}）', shot)
            print('到達 NPC（對話框已 ESC 關閉）', flush=True)
            return EXIT_AT_NPC
        if st == 'dialog':
            dialogs += 1
            shot = snap('dialog')
            gui('seq', f'click {DIALOG_NEXT[0]} {DIALOG_NEXT[1]}')
            last_action = time.time()
            event(f'對話框 #{dialogs}：按左鈕 {DIALOG_NEXT}', shot)
        elif st == 'reward':
            rewards += 1
            shot = snap('reward')
            gui('seq', f'click {REWARD_OK[0]} {REWARD_OK[1]}')
            event(f'獲得物品視窗 #{rewards}：按確認', shot)
            if a.stop_after_rewards and rewards >= a.stop_after_rewards:
                event(f'已領 {rewards} 次獎勵視窗，停止（--stop-after-rewards）')
                return 0
        elif st == 'battle' and (a.solo or a.fight):
            if not s.get('full'):
                if not warned_quick:
                    event(f'--{"solo" if a.solo else "fight"}：遇敵但沒有完整戰鬥畫面（只看到 VS 牌 = 快速戰鬥還開著？）→ 無法逃跑 / 開自動戰鬥，只能等；請先關快速戰鬥')
                    warned_quick = True
            else:
                act = plan_battle_action(s, a.fight and boss, time.time() - last_click_t)
                if act:
                    xy = {'escape': ESCAPE_BTN, 'auto_off': AUTO_BTN, 'auto_on': AUTO_BTN}[act]
                    gui('seq', f'click {xy[0]} {xy[1]}', note={'escape': '完整戰鬥小怪 → 逃跑', 'auto_off': '小怪戰 → 先關自動戰鬥', 'auto_on': 'BOSS 戰 → 開自動戰鬥'}[act])
                    last_click_t = time.time()
                    battles += 1
                    event({'escape': f'{"--solo" if a.solo else "--fight 小怪"} 戰鬥中：按逃跑（第 {battles} 次）',
                           'auto_off': '--solo / 小怪戰：自動戰鬥是開的 → 先按一下關掉，下一回合再逃',
                           'auto_on': f'--fight BOSS 戰：自動戰鬥鈕是關的 → 按一下（第 {battles} 次）'}[act])
                elif a.fight and boss and time.time() - last_full_log > 20:
                    event('--fight BOSS 戰中（自動戰鬥已開，等打完）')
                    last_full_log = time.time()
        elif st == 'battle':
            if s.get('full') or not quest_battle:
                # 完整戰鬥畫面（上方「播放中」）：戰鬥中的切換是「換角色下指令」面板，沒有刷新角色 → 只等；一般遇敵（非任務戰鬥）也只等
                if time.time() - last_full_log > 20:
                    event('完整戰鬥畫面' if s.get('full') else '一般遇敵戰鬥：等待戰鬥結束')
                    last_full_log = time.time()
            elif not a.no_refresh:
                battles += 1
                refresh_characters()
                event(f'戰鬥中：按刷新角色（第 {battles} 次）')
        elif st == 'panel':
            gui('key', '{ESC}')
            event('切換角色面板殘留，ESC 關閉')
        elif st == 'idle' and guard_ko and (ko_pending or time.time() - last_pos_t >= 12) and not (ko_pending and idle_streak < 2):
            # 打完一場後（或每 12 秒）查位置：被打飛回村 → 退出碼 21。剛打完的第一次閒置先略過一輪（畫面轉場中 OCR 讀不準）
            ko_pending = False
            cur = read_pos()
            last_pos_t = time.time()
            if is_knocked(last_pos, cur):
                shot = snap('KNOCKED')
                event(f'偵測到被打飛：{last_pos} → {cur}（薩姆吉爾儲存點附近）→ 停下（退出碼 {EXIT_KNOCKED}）', shot)
                print(f'被打飛回村：{cur}', flush=True)
                return EXIT_KNOCKED
            if cur:
                last_pos = cur
        elif st == 'idle' and a.fight:
            now = time.time()
            if boss_seen:
                if idle_streak >= 2:
                    event(f'--fight BOSS 戰結束（對話 {dialogs}、獎勵 {rewards}），連續閒置 {idle_streak} 次 → 結束，不巡路')
                    print('BOSS 戰結束', flush=True)
                    return 0
            elif npc_click_t and not dialogs and now - npc_click_t >= NPC_WAIT:
                shot = snap('no-npc')
                event(f'--fight 點 NPC 後 {NPC_WAIT:.0f} 秒內沒對話框也沒戰鬥 → 沒點到 NPC（或被小怪打斷）→ 不亂走，退出碼 {EXIT_NO_NPC}', shot)
                print('沒點到 NPC', flush=True)
                return EXIT_NO_NPC
            elif dialogs and now - last_action >= QUEST_BATTLE_WINDOW:
                shot = snap('no-battle')
                event(f'--fight 對話後 {QUEST_BATTLE_WINDOW:.0f} 秒沒開打（這步可能不戰鬥）→ 退出碼 {EXIT_NO_BATTLE}', shot)
                print('對話後沒開打', flush=True)
                return EXIT_NO_BATTLE
        elif st == 'idle':
            # 做完事（對話 / 領獎）後連續 2 次閒置 = 這一步結束，馬上結束不空等（有領過獎勵，或 --no-track 時對話過）
            if idle_streak >= 2 and not (rewards and not a.no_track and a.task and not tracked and checked_rewards < rewards) and (rewards or (a.no_track and dialogs) or (a.stop_after_dialog and dialogs)):
                event(f'步驟結束（對話 {dialogs}、獎勵 {rewards}、戰鬥 {battles}），連續閒置 {idle_streak} 次，提前結束')
                return 0
            if tracked:
                track_fail += 1
                if track_fail >= 2:
                    shot = snap('no-autowalk')
                    event('點了任務追蹤兩次都沒進入巡路 / 對話 / 戰鬥 → 這個任務步驟不能自動巡路或已完成，請改手動（walk.py + 點 NPC）', shot)
                    return 3
            if rewards > checked_rewards and not a.no_track and a.task:
                # 領過獎勵後第一次回到主畫面：立刻掃整個追蹤列表。目標任務不在列表 = 任務完成（不空轉）；還在 = 下一步，順便點它
                checked_rewards = rewards
                time.sleep(1.0)                              # 等獲得物品視窗收掉、列表刷新
                res = track_task(a.task)
                if res is None:
                    checked_rewards = rewards - 1            # 被打斷，下次回主畫面再查
                elif res:
                    tracked = True
                    task_miss = 0
                else:
                    shot = snap('task-done')
                    event(f'領過 {rewards} 次獎勵後追蹤列表整個掃完沒有「{a.task}」→ 任務完成（對話 {dialogs}、獎勵 {rewards}、戰鬥 {battles}）', shot)
                    print(f'任務完成：{a.task}', flush=True)
                    return 0
            elif not a.no_track:
                # 檢測方針：1. 場景有黃色問號 → 優先點它；2. 沒有 → 追蹤列表核對任務名再點
                mk = None if a.no_marker else find_marker()
                log('找黃色問號：' + (f'{mk["x"]},{mk["y"]} n={mk["n"]}' if mk else '沒有'))
                if mk and marker_fail < len(MARK_NPC_DYS):
                    dy = MARK_NPC_DYS[marker_fail]
                    tx, ty = mk['x'], mk['y'] + dy
                    gui('seq', f'{PRIMER}; click {tx} {ty}', note=f'點 NPC 頭上黃色標記下方（標記 {mk["x"]},{mk["y"]} n={mk["n"]}）')
                    last_action = time.time()
                    event(f'閒置：場景有黃色標記 {mk["x"]},{mk["y"]}（{mk["w"]}x{mk["h"]} n={mk["n"]}）→ 點 {tx},{ty}')
                    # 點 NPC = 隊伍自己走過去再開對話框，途中不會出現 Auto Walking 字樣 → 等最多 8 秒看有沒有對話 / 戰鬥 / 領獎 / 巡路
                    reacted = False
                    for _ in range(8):
                        time.sleep(1.0)
                        if read_screen()['state'] != 'idle':
                            reacted = True
                            break
                    marker_fail = 0 if reacted else marker_fail + 1       # 連續沒反應 2 次 → 這個問號點不到，改走追蹤列表
                    tracked = False
                elif (res := track_task(a.task)) is None:
                    log('找追蹤時畫面變了（對話 / 戰鬥 / 領獎），交回主迴圈')
                elif res:
                    tracked = True
                    task_miss = 0
                else:
                    if rewards:                      # 領過獎勵又找不到 = 完成
                        shot = snap('task-done')
                        event(f'追蹤列表整個掃完沒有「{a.task}」，且已領過獎勵 → 任務完成', shot)
                        print(f'任務完成：{a.task}', flush=True)
                        return 0
                    task_miss += 1
                    if task_miss < 2:        # 可能剛好剛換圖 / 捲動慣性 / 標記剛出現：下一輪再來一次（會先重找黃色問號）
                        log(f'追蹤列表找不到「{a.task}」（第 {task_miss} 次），下一輪重試')
                    else:
                        shot = snap('task-not-found')
                        event(f'追蹤列表掃完（到頂 + 到底）都找不到「{a.task}」（連續 {task_miss} 次，沒領過獎勵）→ 沒點任何東西，退出', shot)
                        return 5
        elif st == 'unknown' or st == 'error':
            if st == 'unknown' and clef_wait < CLEF_WAIT_MAX and clef.available() and (img := clef_shot_bytes()):
                cr = clef.classify_scene(img)
                if cr:
                    log(f'Clef 場景：{cr["scene"] or "信心不足"} p={cr["p"]:.2f}（{cr["model"]}）驗證窗機率 {cr["verify_p"]:.3f}')
                    if cr['alarm']:          # 只多一道警報：verify > 0.05 或場景判驗證窗 → 馬上停手（鐵則 5）；模型說沒有不會放行任何事
                        shot = snap('UNKNOWN')
                        event(f'警告：Clef 判斷可能是答題 / 驗證視窗（verify p={cr["verify_p"]:.3f}，場景 {cr["scene"]}）→ 停止自動操作，請使用者處理', shot)
                        print('!!! 請人工檢查畫面（鐵則 5：驗證視窗不可亂猜答案）', flush=True)
                        return 2
                    if cr['scene'] in CLEF_WAIT_SCENES and clef_wait < CLEF_WAIT_MAX:
                        clef_wait += 1
                        if clef_wait == 1:
                            event(f'Clef 判斷為「{cr["scene"]}」（p={cr["p"]:.2f}），不算不認得（最多連續 {CLEF_WAIT_MAX} 次）')
                        if a.once:
                            return 0
                        time.sleep(a.every)
                        continue
            unknown += 1
            log(f'不認得的畫面 {unknown}/3 {s}')
            if unknown >= 3:
                shot = snap('UNKNOWN')
                event('警告：連續 3 次遇到不認得的畫面（可能是答題 / 防腳本驗證視窗）→ 停止自動操作，請使用者處理', shot)
                print('!!! 請人工檢查畫面（鐵則 5：驗證視窗不可亂猜答案）', flush=True)
                return 2
        if a.once:
            return 0
        if time.time() >= end:
            event(f'時間到，結束（對話 {dialogs}、獎勵 {rewards}、戰鬥 {battles}）')
            return 0
        time.sleep(a.every)


if __name__ == '__main__':
    sys.exit(main())
