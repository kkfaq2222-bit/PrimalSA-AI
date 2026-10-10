#!/usr/bin/env python3
"""解任務監測：任務靠遊戲內建自動巡路（Auto Walking），這支腳本每 2.5 秒截圖判斷狀態，只處理「對話要按確認」與「戰鬥按刷新角色加速」。

用法（專案根目錄；WSL / Windows 原生指令相同）：
  uv run --no-project python tools/gui/quest.py --task 黃金羚羊之謎   # 一直監測，最長 15 分鐘（--task = 追蹤列表上的任務名，必填）
  uv run --no-project python tools/gui/quest.py --once          # 只看一次、做一個動作就結束（除錯用）
  uv run --no-project python tools/gui/quest.py --max-seconds 600 --stop-after-rewards 2
  選項：--task 任務名（要點追蹤時，先用 OCR 認出追蹤列表每一格的標題，名稱相符才點；不符就捲動列表再找，找不到退出碼 5，絕不點其他任務。
          沒給 --task 又沒給 --no-track 會直接拒絕執行）、--no-marker（不找 NPC 頭上的黃色問號）、
        --every 2.5（輪詢秒數）、--no-track（不主動點任務追蹤，只處理對話 / 戰鬥）、--no-refresh（戰鬥不按刷新角色）、
        --stop-after-rewards N（領到第 N 次「獲得物品」確認窗後停；避免自動接下一個任務。成人儀式 = 2）
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
退出碼：0 正常結束（任務完成〔領過獎勵後整個追蹤列表掃完沒有 --task，印「任務完成」〕/ 時間到 / 做完對話或領獎後連續 2 次閒置提前結束 / --once / 達到 --stop-after-rewards）、2 不認得的畫面、3 追蹤沒反應、4 版面不支援、5 追蹤列表掃完（到頂 + 到底）找不到 --task 的任務且沒領過獎勵（沒點任何東西）。
只透過 gui.ps1 背景截圖 / 點擊，不碰遊戲記憶體。
"""
import argparse
import difflib
import json
import sys
import time
from pathlib import Path

import layout
import netwatch
import winenv
from walk import ROOT, gui, log, PRIMER

LOG_FILE = ROOT / 'notes' / 'quest-events.log'
SHOT_DIR = ROOT / 'tools' / '.cache' / 'quest-log'

# ---- 座標與特徵色（2880×1659 版面，截圖座標；2026-10-09 實測）----
TRACKER = (205, 325)                 # 左側任務追蹤第一條：點了自動尋路到任務 NPC
SWITCH_BTN = (763, 760)              # 主畫面「切換」
REFRESH_BTN = (910, 578)             # 切換角色面板「刷新角色」（綠色，最右；按完面板自己關）
DIALOG_NEXT = (948, 461)             # NPC 對話框左鈕
REWARD_OK = (720, 572)               # 「獲得物品」視窗的藍色確認鈕
# 對話框：棕底 2 點 + 兩顆米色鈕（heal.py 同款）。主畫面沙地很像米色，所以一定要配棕底
SIG_DIALOG = [(1360, 300, 107, 70, 44), (1100, 350, 107, 70, 44), (948, 445, 229, 197, 155), (1220, 445, 229, 197, 155)]
SIG_REWARD = [(720, 572, 62, 106, 158), (680, 560, 82, 125, 178), (560, 620, 233, 203, 161), (720, 640, 104, 72, 46)]
SIG_PANEL = [(1064, 208, 197, 69, 41), (880, 590, 55, 67, 13)]    # 切換角色面板：右上紅 ✕ + 刷新鈕深綠
SIG_HUD = [(1300, 745, 254, 0, 0)]                                  # 外掛鈕 ASS 紅字（對話框開著時整個 UI 隱藏）
VS_PROBE = (706, 295)                                               # 頭上 VS 牌綠框（heal.py SIG_NO_BATTLE 反過來）
VS_COLOR = (122, 227, 0)
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
    pts = [(x, y) for x, y, *_ in SIG_DIALOG + SIG_REWARD + SIG_PANEL + SIG_HUD] + [VS_PROBE] + AW_POINTS
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
    cols = [tuple(int(v) for v in c.split(',')) for c in out]
    if len(cols) != len(pts):
        return {'state': 'error', 'raw': out[:3]}
    px = dict(zip(pts, cols))
    match = lambda sig: all(close(px[(x, y)], (r, g, b)) for x, y, r, g, b in sig)
    gold = sum(1 for x, y in AW_POINTS if px[(x, y)][0] > 225 and 150 < px[(x, y)][1] < 205 and px[(x, y)][2] < 50)
    if match(SIG_DIALOG):
        st = 'dialog'
    elif match(SIG_REWARD):
        st = 'reward'
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
    return {'state': st, 'gold': gold}


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


def refresh_characters() -> None:
    """戰鬥中按「刷新角色」加速：切換 → 等面板 → 刷新角色；面板還開著就 ESC"""
    sig = '/'.join(f'{x},{y},{r},{g},{b}' for x, y, r, g, b in SIG_PANEL)
    gui('seq', f'click {SWITCH_BTN[0]} {SWITCH_BTN[1]}; waitpix 1500 {sig} 40; ifok click {REFRESH_BTN[0]} {REFRESH_BTN[1]}; wait 500')
    if read_screen()['state'] == 'panel':
        gui('key', '{ESC}')


def main() -> int:
    ap = argparse.ArgumentParser(description='解任務監測：對話按確認、戰鬥按刷新角色、巡路停了重點任務追蹤')
    ap.add_argument('--once', action='store_true', help='只判斷一次、做一個動作就結束')
    ap.add_argument('--every', type=float, default=2.5, help='輪詢間隔秒數（預設 2.5）')
    ap.add_argument('--max-seconds', type=int, default=900, help='最長執行秒數（預設 900）')
    ap.add_argument('--task', default='', help='追蹤列表上的任務名（例：黃金羚羊之謎）；點追蹤前先 OCR 核對標題，名稱不符絕不點')
    ap.add_argument('--no-marker', action='store_true', help='不找 NPC 頭上的黃色問號')
    ap.add_argument('--no-track', action='store_true', help='不主動點任務追蹤')
    ap.add_argument('--no-refresh', action='store_true', help='戰鬥不按刷新角色')
    ap.add_argument('--stop-after-rewards', type=int, default=0, help='領到第 N 次獲得物品視窗後停（0 = 不停）')
    a = ap.parse_args()
    if layout.current() != '2880x1659':
        log('quest.py 只量過 2880×1659 版面，先跑 gui.sh max；見 ui/layout-1920x1017.md')
        return 4
    if not a.no_track and not a.task:
        log('沒給 --task：不知道要點哪個任務追蹤（點錯任務是之前的老問題）。請加 --task 任務名，或用 --no-track（只處理對話 / 戰鬥）')
        return 4
    end = time.time() + a.max_seconds
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
    idle_streak = 0
    while True:
        s = read_screen()
        st = s['state']
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
        idle_streak = idle_streak + 1 if st == 'idle' else 0
        if st in ('dialog', 'reward', 'battle'):
            marker_fail = 0
        if st in ('walking', 'dialog', 'reward', 'battle'):
            if tracked:
                tracked, track_fail = False, 0
        if st == 'dialog':
            dialogs += 1
            shot = snap('dialog')
            gui('seq', f'click {DIALOG_NEXT[0]} {DIALOG_NEXT[1]}')
            event(f'對話框 #{dialogs}：按左鈕 {DIALOG_NEXT}', shot)
        elif st == 'reward':
            rewards += 1
            shot = snap('reward')
            gui('seq', f'click {REWARD_OK[0]} {REWARD_OK[1]}')
            event(f'獲得物品視窗 #{rewards}：按確認', shot)
            if a.stop_after_rewards and rewards >= a.stop_after_rewards:
                event(f'已領 {rewards} 次獎勵視窗，停止（--stop-after-rewards）')
                return 0
        elif st == 'battle':
            battles += 1
            if a.no_refresh:
                pass
            else:
                refresh_characters()
                event(f'戰鬥中：按刷新角色（第 {battles} 次）')
        elif st == 'panel':
            gui('key', '{ESC}')
            event('切換角色面板殘留，ESC 關閉')
        elif st == 'idle':
            # 做完事（對話 / 領獎）後連續 2 次閒置 = 這一步結束，馬上結束不空等（有領過獎勵，或 --no-track 時對話過）
            if idle_streak >= 2 and not (rewards and not a.no_track and a.task and not tracked and checked_rewards < rewards) and (rewards or (a.no_track and dialogs)):
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
