#!/usr/bin/env python3
"""1920×1017 版面的任務執行器（只用標準函式庫）：把「接任務 / 單人逃跑跑路 / 組隊 / BOSS / 解散」寫成腳本。

2026-10-11 依使用者規則寫成（見記憶 psa-accept-quest-via-detail、psa-solo-escape-for-long-route、psa-layout-1920-primary）：
- 接任務一律走左邊「任務詳情」→ 支線 / 主線 → 任務 → 傳送 → NPC 對話。
- 路途遠、會遇野怪的步驟 = 單人 + 外掛「自動逃跑」：先解散，點追蹤欄自動導航，每 5 秒偵測畫面；
  遊戲到點自動跟 NPC 對話 = 已抵達 → ESC → 一鍵組隊 5 人並驗證 → 再點追蹤欄 → 選任務選項。
- BOSS 步也先單人 + 自動逃跑導航（路上有野怪），到點對話前才取消自動逃跑、組隊打。每步前用 team1920 讀隊伍（1 隊長 + 4 隊員）。
- 換圖後第一下點擊常被吃：面板鈕 / 追蹤欄一律「右鍵 2 次 + 左鍵 1 次」；橫幅會擋點擊 → 點完驗證狀態、沒變再點。

用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1 較快）：
  uv run --no-project python tools/gui/q1920.py --client kkfaq11111 status
  uv run --no-project python tools/gui/q1920.py --client kkfaq11111 accept 深紅洞窟
  uv run --no-project python tools/gui/q1920.py --client kkfaq11111 run --steps solo,solo,boss,boss,talk
  uv run --no-project python tools/gui/q1920.py --client kkfaq11111 team | disband
步驟種類：fight = 組隊直接導航 + 對話 + 打 BOSS（不解散、不逃跑）；solo = 單人 + 自動逃跑跑到 NPC → 組隊 → 對話；boss = 同 solo，但到點先取消自動逃跑、開自動戰鬥再組隊對話開打（路上一樣逃跑）；talk = 已組隊、近距離的對話步。
退出碼：0 成功 / 1 參數 / 2 版面不是 1920×1017 / 3 隊伍問題 / 4 外掛設定失敗 / 5 找不到任務 / 6 疑似驗證或不認得的畫面（停手通知使用者）
        7 逾時 / 8 BOSS 戰後任務沒前進（可能輸了，不重打）
座標 = 截圖座標（客戶區 1920×1017 → 960×508）。
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TRACK_ROW_DY = 57                # 追蹤欄每一條的間距（截圖座標，960×508）
TRACK_N = 1                      # 目標任務在追蹤欄第幾條（--track N；預設 1）
TRACK = (130, 200)               # 左側追蹤欄第一條（實際點擊用 track_xy()）
DETAIL_BTN = (230, 205)          # 追蹤欄右側「詳情」
TAB_SIDE = (237, 129)            # 任務詳情「支線」分頁
TAB_MAIN = (160, 129)            # 「主線」分頁（2026-10-12 從任務詳情截圖量：主線 x≈162、支線 x≈237）
GO_BTN = (420, 414)              # 任務詳情「傳送」
GO_TXT_OCR = (340, 390, 170, 50)  # 那顆鈕的文字：待接取 =「傳送」（-Dark 200 才讀得到）、進行中 =「重置任務」（花 50000 石幣，絕不按）
OPT1 = (650, 283)                # NPC 對話框第一個選項
OK_BTN = (480, 352)              # 「獲得物品」確認
TEAM_BTN = (598, 465)            # 主畫面「組隊」
TEAM_X = (812, 42)               # 組隊面板 ✕
TEAM_ACT = (480, 413)            # 組隊面板：紅 = 解散隊伍、藍 = 創建隊伍
SW_QUICK = (355, 357)            # 切換面板「快速組隊」
SW_TIP_X = (688, 100)            # 快速組隊「提示」視窗 ✕
SW_LEADER = (377, 190)
SW_MEMBERS = ((377, 320), (461, 320), (545, 320), (628, 320))
SW_GO = (480, 410)               # 提示視窗「組隊」
TRACK_OCR_1 = (45, 172, 170, 70)   # 追蹤欄第一條文字（任務名 + 副標題兩行；OCR 偶爾只讀到任務名）
TRACK_SUB_OCR_1 = (50, 198, 160, 32)   # 副標題那一行（BOSS 戰前後比對用）


TRACK_Y_OVERRIDE = None          # questflow 依 OCR 找到任務所在列的實際 y（設了就不用 TRACK_N；任務在第 2 或第 3 格、或已上滑都適用）


def track_xy() -> tuple:
    if TRACK_Y_OVERRIDE is not None:
        return (TRACK[0], TRACK_Y_OVERRIDE)
    return (TRACK[0], TRACK[1] + TRACK_ROW_DY * (TRACK_N - 1))


def _shift(box):
    dy = (TRACK_Y_OVERRIDE - TRACK[1]) if TRACK_Y_OVERRIDE is not None else TRACK_ROW_DY * (TRACK_N - 1)
    return (box[0], box[1] + dy, box[2], box[3])
LIST_OCR = (40, 140, 300, 330)   # 任務詳情清單

POLL_S = 5.0                     # 導航中檢查「位置有沒有變」的間隔（使用者要求 5 秒）
FAST_S = 1.0                     # 對話窗 / 戰鬥偵測間隔（地圖很近時快點抓到，使用者 2026-10-11）
HALT_OTHER_S = 90                # 連續不認得的畫面超過這麼久 → 停手（鐵則 5）
NAV_TIMEOUT_S = 900
EXIT_OK, EXIT_USAGE, EXIT_LAYOUT, EXIT_TEAM, EXIT_ASS, EXIT_NOQUEST, EXIT_HALT, EXIT_TIMEOUT, EXIT_BOSS = 0, 1, 2, 3, 4, 5, 6, 7, 8

sleep = time.sleep
clock = time.time
_uikit = None
ROOT = HERE.parents[1]
STATE_DIR = ROOT / 'tools' / '.cache'
NOTES = ROOT / 'notes' / 'quest-log.md'
CLIENT = ''                      # main() 設定；進度檔 / 記錄用


def state_path() -> Path:
    return STATE_DIR / f'q1920-{CLIENT}.json'


def load_state() -> dict:
    import json
    try:
        return json.loads(state_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_state(d: dict) -> None:
    """原子寫入進度檔（不進 git：tools/.cache）"""
    import json
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = state_path().with_suffix('.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, state_path())


LEDGER = ROOT / 'notes' / 'quest-ledger.json'    # 任務帳本（notes/ 不進 git；比 tools/.cache 不會被清掉）


def ledger_load() -> dict:
    import json
    try:
        return json.loads(LEDGER.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def ledger_mark(quest: str, status: str, detail: str = '', client: str | None = None) -> None:
    """記一筆：status = done / paused / doing / todo；detail = 做到哪一步 / 注意事項。原子寫入"""
    import json
    c = client or CLIENT or '?'
    d = ledger_load()
    d.setdefault(c, {})[quest] = {'status': status, 'detail': detail, 'at': time.strftime('%F %T')}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix('.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, LEDGER)


def ledger_show(client: str | None = None) -> None:
    d = ledger_load()
    for c, qs in d.items():
        if client and c != client:
            continue
        print(f'[{c}]')
        for q, v in qs.items():
            print(f'  {v["status"]:6} {q}  {v.get("detail", "")}  ({v.get("at", "")})')


# ---- 任務順序（2026-10-12 11111 任務詳情實測：支線清單由上而下，解完的會往下沉）----
SIDE_ORDER = [
    '琉璃洞窟', '玄黃洞窟', '碧青洞窟', '深紅洞窟', '英雄島前傳', '英雄島後傳', '解救老爺爺', '恐龍博士', '夢幻洞窟',
    '亞姆的斧頭', '五兄弟之謎', '卡坦的願望', '強盜的洞穴', '小豬愛情故事', '四寶玉之謎', '馬祖快遞', '礦工的比賽',
    '夢德洞窟', '強恩一族', '伐木證書', '黃金羚羊之謎', '龍的巢穴', '猜謎三兄弟', '彌生和日美子', '精靈少女', '天空之島',
]
# 主線（任務詳情「主線」分頁，2026-10-12 實測）：成人儀式是支線的前置；漆黑洞窟 二～四轉要 131 級 + 先完成 4 大洞窟任務
# （琉璃 / 玄黃 / 碧青 / 深紅），五轉要 140 級；每個最後一步都是轉生。轉生會重置任務，所以只排二轉在最後，三～五轉留給轉生後。
# 使用者說明：成人儀式解完後遊戲會自動把漆黑洞窟帶入追蹤欄（第 1 條，所以 batch 的 --track 預設 2），不用另外接。
MAIN_FIRST = ['成人儀式']
CAVES = ['琉璃洞窟', '玄黃洞窟', '碧青洞窟', '深紅洞窟']      # 4 大洞窟：先全部解完（漆黑二轉的條件）
AFTER_CAVES = ['漆黑洞窟(二轉)', '英雄島前傳']              # 使用者做法：4 洞窟後 → 漆黑解到打完機暴就停 → 紅暴（英雄島前傳）
QUEST_UNTIL = {'漆黑洞窟(二轉)': 4}                       # 只做到第 N 步（含）：第 4 步 = 帖拉所伊朵（機暴）戰；不接守衛 / 精靈王轉生
MAIN_LATER = ['漆黑洞窟(三轉)', '漆黑洞窟(四轉)', '漆黑洞窟(五轉)']   # 這一輪不排（要先轉生；五轉另需 140 級）
MAIN_QUESTS = set(MAIN_FIRST + ['漆黑洞窟(二轉)'] + MAIN_LATER + ['初入石器', '漆黑洞窟(一轉)'])
SKIP_QUESTS = ['英雄島後傳', '精靈少女', '天空之島']      # 使用者規則：不解（精靈少女要 3 轉 120、天空之島要 5 轉 135）
LAST_QUESTS = ['猜謎三兄弟', '卡坦的願望', '恐龍博士']   # 使用者規則：排最後解，順序 = 猜謎三兄弟 → 卡坦的願望 → 恐龍博士（寵物任務，見 psa-pet-quest-plan）


# 寵物任務：不走一般對話流程，改呼叫 katan1920.py（抓寵 → 存 / 分寵 → 練到達標 → 接任務逐一交），全自動不停下來（使用者 2026-10-12）。
# 每個系別各自完整走一遍：卡坦的願望 = 鯊魚（步 1）→ 火雞（步 2，不再做 setup）；恐龍博士 = dino。--resume：中斷後接續已完成階段。
# 要練寵的一般任務：改走 questflow1920.run_quest（TRAIN_STEPS 在步 2 前練金布衣到 77；批次一律不吃龍王的守護）
QF_QUESTS = {'猜謎三兄弟'}


PET_QUESTS = {
    '卡坦的願望': [('shark', []), ('bird', ['--no-setup'])],
    '恐龍博士': [('dino', [])],
}


def run_pet_quest(name: str, client: str) -> int:
    """依序執行該寵物任務的各系別；任何一個退出碼不是 0 就回傳（呼叫端停手）"""
    import subprocess
    for fam, extra in PET_QUESTS[name]:
        cmd = [sys.executable, str(HERE / 'katan1920.py'), '--client', client, '--family', fam,
               '--phase', 'all', '--do', '--resume', *extra]
        log(f'寵物任務「{name}」→ {fam}：{" ".join(cmd[2:])}')
        rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
        if rc:
            return rc
    return 0


def build_queue(client: str | None = None, use_ledger: bool = False) -> list:
    """支線解題順序：清單由上而下，扣掉不解，排最後的接在尾端；use_ledger 才再扣帳本 done 的
    （預設不扣：轉生 / 封印書後任務會重置，帳本會過期；accept 在清單找不到才會退出碼 5）"""
    done = {q for q, v in ledger_load().get(client or CLIENT or '?', {}).items() if v.get('status') == 'done'} if use_ledger else set()
    early = CAVES + AFTER_CAVES
    head = [q for q in SIDE_ORDER if q not in SKIP_QUESTS and q not in LAST_QUESTS and q not in early and q not in done]
    early = [q for q in early if q not in done]
    tail = [q for q in LAST_QUESTS if q not in done]
    return MAIN_FIRST + early + head + tail


def note(line: str) -> None:
    """append 一行到 notes/quest-log.md（遊玩紀錄；notes/ 不進 git）"""
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    with NOTES.open('a', encoding='utf-8') as f:
        f.write(f'- {time.strftime("%m-%d %H:%M")} [{CLIENT}] {line}\n')


class Halt(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg
        # 所有停手 / 暫時性失敗都在丟出當下存一張圖（tools/.cache/fail/，failshot 保留規則）；
        # 要先 ESC 復原畫面的地方在 ESC 前呼叫 failshot.pre()，這裡會沿用那張
        try:
            import failshot
            self.shot = failshot.shot(Path(sys.argv[0]).stem or 'q1920', f'退出碼 {code}：{msg}')
        except Exception:
            self.shot = None


def log(msg: str) -> None:
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def uk():
    global _uikit
    if _uikit is None:
        import uikit
        _uikit = uikit
    return _uikit


# ---- 純函式（離線測試用）----
def near(c, ref, tol=25) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


PROBES = {'hud': (874, 455), 'dlg_a': (600, 245), 'dlg_b': (900, 245), 'rw_t': (480, 120), 'rw_b': (480, 352),
          'banner': (478, 14), 'avatar': (75, 47), 'tab': (92, 147),
          'rw_t2': (350, 245), 'rw_b2': (432, 352),     # 獲得物品視窗的備用探針：畫面上方 NEW 圖示的星星柱（x≈445~520）會蓋住 (480,120)（2026-10-13 實測 136,121,89）
          'fam': (697, 458)}   # 下方按鈕列：主畫面此處是「家族」鈕（紅 166,71,44）；戰鬥中沒有家族鈕、按鈕左移，此處變成排行榜獎盃（金 232,192,71）
PROBE_KEYS = list(PROBES)


def classify(cols: dict) -> str:
    """像素 → 'REWARD' 獲得物品 / 'DIALOG' NPC 對話窗 / 'BATTLE' / 'MAIN' / 'OTHER'（載入、面板、不認得）"""
    hud_red = near(cols['hud'], (255, 0, 0), 40)
    rw_top = near(cols['rw_t'], (242, 214, 160), 20) or (cols.get('rw_t2') is not None and near(cols['rw_t2'], (241, 215, 182), 25))
    rw_bot = near(cols['rw_b'], (46, 86, 134), 30) or (cols.get('rw_b2') is not None and near(cols['rw_b2'], (53, 98, 156), 30))
    if rw_top and rw_bot and not hud_red:
        return 'REWARD'
    if not hud_red and near(cols['dlg_a'], (107, 70, 44), 14) and near(cols['dlg_b'], (107, 70, 44), 14):
        return 'DIALOG'
    fam = cols.get('fam')
    in_battle_ui = fam is not None and near(fam, (232, 192, 71), 40)
    av = cols['avatar']
    # 頭像探針：原本只認 (151,70,43)（深髮色角色）。333 的角色頭像探針是膚色 (241,193,151) → 永遠判 OTHER，
    # wait131 / 練寵 / 任務全部靜默空轉（2026-10-14）。再接受暖色（紅 - 藍 >= 40、紅 >= 140，亮度不是白 / 灰面板）
    avatar_ok = near(av, (151, 70, 43), 30) or (av is not None and av[0] >= 140 and av[0] - av[2] >= 40 and av[0] >= av[1] >= av[2])
    main_like = hud_red and avatar_ok and near(cols['tab'], (145, 135, 108), 40)
    # 橫幅探針只有 1 個點：沙地地圖（薩伊那斯）背景色 (237,209,139) 與橫幅 (226,199,148) 幾乎一樣 → 誤判戰鬥而卡住
    # （2026-10-12 卡坦步 1）。HUD 頭像 / 分頁都像主畫面時，不能只憑橫幅那一點判戰鬥。
    if hud_red and (in_battle_ui or (near(cols['banner'], (226, 199, 148), 22) and not main_like)):
        return 'BATTLE'      # 播放中橫幅，或（含快速戰鬥）下方按鈕列沒有家族鈕
    if main_like:
        return 'MAIN'
    return 'OTHER'


# ---- 遊戲存取 ----
def px(points, tries=3):
    pts = list(points)
    for _ in range(tries):
        r = uk().px(pts)
        if r and len(r) == len(pts):
            return r
        sleep(0.5)
    return None


def state() -> str:
    cols = px([PROBES[k] for k in PROBE_KEYS])
    return classify(dict(zip(PROBE_KEYS, cols))) if cols else 'OTHER'


def seq(cmd: str, note: str = '') -> None:
    uk().gui('seq', cmd, note=note)


def click(xy, right: int = 0, wait_ms: int = 600, note: str = '') -> None:
    x, y = xy
    parts = [f'click {x} {y} right'] * right + [f'click {x} {y}', f'wait {wait_ms}']
    seq('; '.join(parts), note)


def key(k: str) -> None:
    uk().gui('key', k)


def pos():
    import walk
    return walk.pos()


def tracker_text() -> str:
    """追蹤欄第一條：任務名 + 副標題。OCR 整塊常只讀到任務名，所以副標題另讀一次接在後面（BOSS 戰判輸贏要靠副標題變化）"""
    head = ''.join(uk().ocr(_shift(TRACK_OCR_1), '-Zooms', '2,3'))
    sub = ''.join(uk().ocr(_shift(TRACK_SUB_OCR_1), '-Zooms', '3,4', '-Dark', '160'))
    if not sub.strip() and TRACK_N > 1:      # 小幅上滑後副標題位置會偏（實測第 2 條在 y≈235~250）：換大框再讀
        b = _shift(TRACK_SUB_OCR_1)
        sub = ''.join(uk().ocr((b[0], b[1] - 30, b[2], 70), '-Zooms', '3,4', '-Dark', '160'))
    return head + '|' + sub


def wait_state(want, timeout=30.0, gap=1.0) -> str:
    end = clock() + timeout
    s = state()
    while s not in want and clock() < end:
        sleep(gap)
        s = state()
    return s


def scroll_tracker(max_tries: int = 3) -> None:
    """目標任務在追蹤欄第 N 條 (N > 1) 時：副標題常被下方聊天視窗蓋住 → 欄內小幅上滑（約 40 px，使用者規則），
    每滑一次就讀副標題，讀得到字就停；連滑都沒變 = 到底。只在 TRACK_N > 1 時做"""
    if TRACK_N <= 1:
        return
    for _ in range(max_tries):
        if ''.join(uk().ocr(_shift(TRACK_SUB_OCR_1), '-Zooms', '3,4', '-Dark', '160')).strip():
            return
        seq('drag 130 255 130 215; wait 1500', 'q1920 追蹤欄小幅上滑')
    log('追蹤欄上滑後副標題仍讀不到（任務在更下面或被蓋住）')


def preflight() -> None:
    import layout
    cur = None
    for _ in range(4):                       # gui info 偶爾逾時回 None（對話窗 / 面板切換瞬間），重試幾次再下結論
        layout._cache.clear()
        cur = layout.current()
        if cur:
            break
        sleep(1.5)
    if cur != '1920x1017':
        raise Halt(EXIT_LAYOUT, f'版面是 {cur}，這支只量過 1920x1017')


# ---- 隊伍 ----
def team_summary() -> dict | None:
    import team1920
    for _ in range(3):
        r = team1920.read_state()
        if r['ok'] and r['summary'].get('n', 0) > 0:     # 0 張卡片 = 面板沒真的開 / 讀失敗（換圖後常見），重讀
            return r['summary']
        sleep(1.5)
    return None


TEAM_OK_AT = 0.0                 # 最近一次驗證「1 隊長 + 4 隊員」的時間；talk() 只在這之後 TEAM_FRESH_S 秒內才准點對話選項
TEAM_FRESH_S = 150.0
TRUST_TEAM = False               # batch --trust-team：開頭驗證一次後，不再逐步驗證隊伍 / 外掛（使用者 2026-10-11）


TEAM_CARD_CX = (237, 355, 480, 604, 729)      # 組隊面板 5 張卡片中心 x（960×508 截圖座標；2026-10-13 11111 實機量）
TEAM_LABEL_Y, TEAM_NAME_Y = 287, 248


def team_panel_summary():
    """下方「組隊」面板判斷（使用者 2026-10-13：全部組隊都看這裡；只有抓寵要單人才用切換面板）。
    開面板 → 紅色「解散隊伍」鈕 = 在隊中；5 張卡片名牌 / 標籤 OCR（隊長 / 隊員）→ {'n','leaders','members','in_team'}；面板打不開回 None"""
    for attempt in range(3):
        click(TEAM_BTN, right=2, wait_ms=1400, note='q1920 開組隊面板（判斷隊伍）')
        cols = px([TEAM_X, TEAM_ACT])
        if cols and near(cols[0], (197, 73, 49), 40):
            break
        key('{ESC}')                                 # 沒開成：ESC ×1 再開（最多 3 輪）
        sleep(1.0)
    else:
        return None
    in_team = near(cols[1], (135, 40, 19), 50)
    # 卡片在不在：看每張卡片兩側底色（米色 ≈ (221~233,185~201,143~163)；空格是深褐 (120,88,63)）一次取 10 個點；
    # 不靠文字（畫面上方「NEW」圖示的閃亮星星會蓋住中間那張卡）
    side = px([(cx + dx, 230) for cx in TEAM_CARD_CX for dx in (-52, 52)]) or []
    n = 0
    for k in range(len(TEAM_CARD_CX)):
        pair = side[2 * k:2 * k + 2]
        if any(c[0] > 195 and c[1] > 160 for c in pair):
            n += 1
    # 隊長 / 隊員標籤：5 張卡的標籤列整條 OCR 一次（舊版每張卡 4 次、共 20 次，兩個客戶端同時跑時一次判斷要 1 分鐘以上，
    # form_team 連判斷好幾次 → 組隊面板開著 4~6 分鐘，2026-10-13）
    txt = ''
    for z in ('3,4', '4,5'):
        try:
            txt += ''.join(uk().ocr((TEAM_CARD_CX[0] - 40, TEAM_LABEL_Y - 2, TEAM_CARD_CX[-1] - TEAM_CARD_CX[0] + 80, 24), '-Zooms', z)) + '|'
        except Exception:
            pass
        if txt.count('長') + txt.count('員') >= 4 or z == '4,5':
            break
    first = txt.split('|')[0]
    leaders = 1 if '長' in txt else 0
    members = min(4, max(first.count('員'), txt.count('員') // (txt.count('|') or 1)))
    if n == 0 and (leaders or members):
        n = leaders + members
    click(TEAM_X, wait_ms=800, note='q1920 關組隊面板')
    return {'n': n, 'leaders': leaders, 'members': members, 'in_team': in_team}


def team_ok() -> bool:
    """隊伍 = 1 隊長 + 4 隊員：看下方「組隊」面板（卡片 5 張 + 恰 1 個隊長 + 紅色解散鈕）；中間那張標籤 OCR 偶爾漏讀，所以不強求讀滿 4 個隊員"""
    global TEAM_OK_AT
    s = team_panel_summary()
    ok = bool(s) and s['in_team'] and s['n'] == 5 and s['leaders'] == 1 and s['members'] >= 3
    TEAM_OK_AT = clock() if ok else 0.0
    return ok


def no_team() -> bool:
    s = team_summary()
    return bool(s) and s['leaders'] + s['members'] == 0


def form_team() -> None:
    """一鍵組隊 5 人並驗證；已經 5 人隊就不動"""
    import team1920
    if team_ok():
        log('隊伍已是 1 隊長 + 4 隊員')
        return
    for attempt in range(3):
        if attempt > 0 or state() != 'MAIN':           # 使用者 2026-10-13：沒成功就先按一次 ESC（背包 / 面板沒關會擋住一鍵組隊）再重試
            seq('key {ESC}; wait 700', note='q1920 組隊前 ESC 關面板')
            if state() != 'MAIN':
                click((832, 66), wait_ms=700, note='q1920 組隊前關背包 ✕')
        if not team1920.open_panel():
            sleep(2)
            continue
        click(SW_QUICK, wait_ms=2500, note='q1920 快速組隊')
        cols = px([SW_TIP_X, SW_GO])
        if not (cols and near(cols[0], (184, 62, 38), 45) and near(cols[1], (44, 83, 131), 40)):
            log('快速組隊提示視窗沒出現（可能被橫幅吃掉）→ 重試')
            team1920.close_panel()
            continue
        click(SW_LEADER, wait_ms=700, note='q1920 選隊長')
        for m in SW_MEMBERS:
            click(m, wait_ms=250, note='q1920 選隊員')
        click(SW_GO, wait_ms=2000, note='q1920 組隊')
        team1920.close_panel()
        if team_ok():
            log('組隊完成並驗證（1 隊長 + 4 隊員）')
            return
        log('組隊後驗證不符 → 重試')
    raise Halt(EXIT_TEAM, '一鍵組隊 3 次都沒成功（有人離線 / 地圖禁止組隊？）')


def disband() -> None:
    """解散隊伍並驗證；本來就沒隊伍就不點"""
    import team1920
    if no_team():
        log('本來就是單人')
        return
    global TEAM_OK_AT
    TEAM_OK_AT = 0.0
    for attempt in range(3):
        click(TEAM_BTN, right=2, wait_ms=1300, note='q1920 開組隊面板')
        cols = px([TEAM_X, TEAM_ACT])
        if not (cols and near(cols[0], (197, 73, 49), 35)):
            # 沒開成：先 ESC 關掉可能擋住的視窗 / 面板（背包、外掛面板、獲得物品）再重開（使用者 2026-10-14：
            # 11111 解散隊伍 3 次都沒開成，因為重試之間沒按 ESC）；仍是別的畫面就再點一下關閉 ✕
            log('組隊面板沒開 → ESC 後重試')
            key('{ESC}')
            sleep(1.0)
            if state() != 'MAIN':
                click((832, 66), wait_ms=700, note='q1920 解散前關背包 / 面板 ✕')
                key('{ESC}')
                sleep(0.8)
            continue
        if near(cols[1], (135, 40, 19), 45):               # 紅 = 解散隊伍
            click(TEAM_ACT, wait_ms=1200, note='q1920 解散隊伍')
        click(TEAM_X, wait_ms=900, note='q1920 關組隊面板')
        if no_team():
            log('已解散（切換面板全員單人）')
            return
    raise Halt(EXIT_TEAM, '解散隊伍 3 次都沒成功')


def require_team() -> None:
    if not team_ok():
        raise Halt(EXIT_TEAM, '隊伍不是 1 隊長 + 4 隊員，停手（不對 NPC 做事）')


# ---- 外掛設定 ----
def set_ass(**flags) -> None:
    """flee / fast / encounter / auto = True / False；用 ass.set_states 勾選並讀回確認"""
    import ass
    names = {'flee': '自動逃跑', 'fast': '快速戰鬥', 'encounter': '原地遇敵', 'auto': '自動戰鬥'}
    want = {names[k]: v for k, v in flags.items()}
    for attempt in range(3):
        rc, st, msg = ass.set_states('DKBO', want)
        if rc == 0 and st and all(st[i] == v for i, v in want.items()):
            log('外掛：' + ass.fmt(st))
            return
        log(f'外掛設定未成功（退出碼 {rc}：{msg}）→ 重試')
        sleep(3)
    raise Halt(EXIT_ASS, f'外掛設定 {want} 3 次都沒成功')


# ---- 導航 / 對話 ----
# 導航時判斷「有沒有在走」：在地圖區取一格取樣點，前後兩次像素有變 = 畫面在捲動 = 角色在走（便宜、不用 OCR 座標）
MOVE_PTS = [(x, y) for x in range(340, 900, 80) for y in range(110, 430, 70)]
MOVE_TOL = 12                    # 單點 RGB 各通道差超過這個才算「變了」
MOVE_MIN_CHANGED = 2             # 至少幾個取樣點變了才算在移動（避免水面 / 動畫 NPC 的單點閃爍）
RECLICK_BEFORE_ADJUST = 3        # 使用者 2026-10-12：導覽中既不是「戰鬥 / 任務導覽 / NPC 對話」→ 重點追蹤欄任務，連續 3 次都沒有 → 把追蹤欄往下拉看怎麼調整
NAV_ADJUST = None                # 往下拉重新定位的 hook（questflow1920.run_quest 設：lambda: find_track_row(name, scroll=True, reveal=False) is not None）
TRACK_NUDGE = 'drag 130 255 130 215; wait 1200'   # hook 沒設時的備案：追蹤欄往下拉一點點（約 40 px）
STILL_POLLS = 2                  # 連續幾次（每次 FAST_S）畫面沒動 → 重新點追蹤欄（使用者 2026-10-12：第一次點沒反應，過 2 秒再點一次）


def scan():
    """一次像素讀取（同一個行程）→ (畫面狀態, 取樣點顏色)；讀不到回 ('OTHER', None)"""
    keys = PROBE_KEYS
    cols = px([PROBES[k] for k in keys] + MOVE_PTS)
    if not cols:
        return 'OTHER', None
    return classify(dict(zip(keys, cols[:len(keys)]))), cols[len(keys):]


def moved(a, b) -> bool:
    if not a or not b:
        return True
    n = sum(1 for x, y in zip(a, b) if not near(x, y, MOVE_TOL))
    return n >= MOVE_MIN_CHANGED


def nav_decision(still: int, fails: int, adjusted: bool) -> str:
    """導覽中「沒有戰鬥 / 任務導覽（畫面在捲動）/ NPC 對話」時怎麼做（純函式，離線測試用）。
    still = 連續幾次輪詢都沒有這三種；fails = 目前這一輪已重點追蹤欄幾次都沒用；adjusted = 是否已往下拉調整過。
    回傳 'wait' / 'reclick' / 'adjust'（往下拉看怎麼調整）/ 'halt'（無解，停手）"""
    if still < STILL_POLLS:
        return 'wait'
    if fails < RECLICK_BEFORE_ADJUST:
        return 'reclick'
    return 'halt' if adjusted else 'adjust'


def adjust_tracker() -> bool:
    """重點 3 次都沒反應：先存一張圖（事後看），再把追蹤欄往下拉重新找任務那一列。回傳是否有找到 / 動作"""
    try:
        uk().gui('shot', f'nav-stuck-{time.strftime("%H%M%S")}.png')
    except Exception:
        pass
    if NAV_ADJUST is not None:
        try:
            return bool(NAV_ADJUST())
        except Exception as e:     # hook 出錯不能讓導覽當掉，改用備案
            log(f'追蹤欄重新定位出錯：{e}')
    seq(TRACK_NUDGE, 'q1920 追蹤欄往下拉看怎麼調整')
    return True


TRACK_GUARD = None               # questflow 設：點追蹤欄前檢查那一列不是漆黑（回 False = 會點錯）；None = 不檢查


def track_click(right: int = 0, note: str = 'q1920 點追蹤欄') -> None:
    """點追蹤欄前先確認不會點到漆黑（使用者 2026-10-15：解其他任務時漆黑本來在第 2 格只露一半，
    登出再登入後漆黑跑回第 1 格，照舊位置點就點到漆黑 → 導航去守門人）。會點錯 → 先依任務名稱重新定位再檢查，還是不對就停手、絕不點。"""
    if TRACK_GUARD is not None and not TRACK_GUARD():
        log(f'追蹤欄要點的那一列是漆黑（y={track_xy()[1]}，可能登出後順序變了）→ 不點，依任務名稱重新定位')
        ok = False
        if NAV_ADJUST is not None:
            try:
                ok = bool(NAV_ADJUST()) and TRACK_GUARD()
            except Exception as e:
                log(f'重新定位出錯：{e}')
        if not ok:
            raise Halt(EXIT_TIMEOUT, '追蹤欄重新定位後要點的還是漆黑（或找不到任務）：不點、停手，避免導航去守門人')
        log(f'重新定位完成 → 改點 y={track_xy()[1]}')
    x, y = track_xy()
    parts = [primer()] + [f'click {x} {y} right'] * right + [f'click {x} {y}', 'wait 500']
    seq('; '.join(parts), note)


def primer() -> str:
    """換地圖後第一下左鍵會被遊戲吃掉 → 點追蹤欄前先點引子（walk.PRIMER，1920 版面是右上狀態列 822,11；
    平常點它沒作用）。不點的話第一下常沒反應，要等 STILL_POLLS 秒才「畫面沒在動 → 重新點追蹤欄」"""
    import walk
    return walk.PRIMER


def navigate(max_s: float = NAV_TIMEOUT_S) -> str:
    """點追蹤欄自動導航；每 FAST_S 秒一次像素讀取：DIALOG / REWARD → 立刻回傳；戰鬥 / 畫面在捲動（導覽中）→ 等；
    以上都不是（連續 STILL_POLLS 次）→ 重點追蹤欄任務，連續 3 次都沒用 → 追蹤欄往下拉重新定位，再 3 次還是沒用 → 停手（使用者規則）。
    連續不認得的畫面超過 HALT_OTHER_S → Halt（疑似驗證視窗）"""
    t0, other_since, clicks, still, prev = clock(), None, 0, 0, None
    fails, adjusted = 0, False
    track_click(right=2, note='q1920 點追蹤欄導航')
    sleep(FAST_S)
    _, prev = scan()                                   # 點完先取一張基準，之後每秒比較：2 秒內沒導航 / 對話 / 戰鬥 → 再點一次
    while clock() - t0 < max_s:
        sleep(FAST_S)
        s, cur = scan()
        if s in ('DIALOG', 'REWARD'):
            return s
        if s == 'OTHER':
            other_since = other_since or clock()
            if clock() - other_since > HALT_OTHER_S:
                raise Halt(EXIT_HALT, f'連續 {HALT_OTHER_S} 秒不認得的畫面（疑似驗證視窗或卡住）：停手，請使用者看畫面')
            continue
        other_since = None
        if s == 'BATTLE':
            still, prev = 0, None
            continue
        # MAIN
        if moved(prev, cur):
            still, fails, adjusted = 0, 0, False     # 在導覽（畫面捲動）：一切歸零
        else:
            still += 1
            act = nav_decision(still, fails, adjusted)
            if act == 'reclick':
                fails += 1
                clicks += 1
                log(f'畫面沒在動（沒有導覽 / 戰鬥 / 對話）→ 重新點追蹤欄（本輪第 {fails}/{RECLICK_BEFORE_ADJUST} 次）')
                seq('key {ESC}; wait 600', note='q1920 重點前先 ESC（使用者 2026-10-13：沒反應 → ESC ×1 再點，最多 3 輪）')
                track_click(note='q1920 重點追蹤欄')
                still = 0
            elif act == 'adjust':
                log(f'重點 {RECLICK_BEFORE_ADJUST} 次都沒反應 → 追蹤欄往下拉重新定位')
                adjusted = adjust_tracker()
                fails, still = 0, 0
                if adjusted:
                    track_click(right=2, note='q1920 調整後點追蹤欄')
                else:
                    raise Halt(EXIT_TIMEOUT, '導覽沒反應，追蹤欄往下拉也找不到任務：停手（請看畫面；可能是道具滿了漏道具）')
            elif act == 'halt':
                raise Halt(EXIT_TIMEOUT, f'調整追蹤欄後再重點 {RECLICK_BEFORE_ADJUST} 次仍沒有導覽 / 對話 / 戰鬥：停手（請看畫面；可能是道具滿了漏道具）')
        prev = cur
    raise Halt(EXIT_TIMEOUT, f'導航 {max_s:.0f} 秒內沒到點')


def talk(max_clicks: int = 8, allow_confirm: bool = True, allow_battle: bool = False) -> str:
    # 防呆（使用者 2026-10-11）：單人時點接任務 / 交任務選項，其他角色會漏掉 → 隊伍沒在近期驗證過 5 人就不准點選項
    if not TRUST_TEAM and clock() - TEAM_OK_AT > TEAM_FRESH_S:
        raise Halt(EXIT_TEAM, '對話前隊伍沒在 %d 秒內驗證過 5 人（單人點選項會讓其他角色漏掉任務）：停手' % TEAM_FRESH_S)
    """對話迴圈：DIALOG → 點第一個選項；REWARD → 確認；回傳 'battle' / 'main' / 'timeout'。
    出現「進入裏面嗎」之類的二次確認（猜謎樓層傳送）不會自動按接受：ESC 後回傳 'confirm'。"""
    for _ in range(max_clicks):
        s = state()
        if s == 'DIALOG':
            txt = ''.join(uk().ocr((555, 160, 350, 95), '-Zooms', '2,3'))
            log(f'對話：{txt[:40]}')
            opt = ''.join(uk().ocr((565, 262, 175, 42), '-Zooms', '2,3'))
            if '挑戰' in opt and not allow_battle:        # 使用者 2026-10-11：選項寫「挑戰○○」才會進戰鬥；非 BOSS 步不准點
                raise Halt(EXIT_BOSS, f'非 BOSS 步看到戰鬥選項「{opt}」：停手（不點）')
            log(f'對話選項：{opt}')
            if '進入裏面' in txt and not allow_confirm:
                key('{ESC}')
                return 'confirm'
            click(OPT1, wait_ms=2200, note='q1920 對話選項' + ('（接受進入）' if '進入裏面' in txt else ''))
        elif s == 'REWARD':
            click(OK_BTN, wait_ms=1500, note='q1920 獲得物品確認')
        elif s == 'BATTLE':
            return 'battle'
        elif s == 'MAIN':
            return 'main'
        else:
            sleep(1.5)
    return 'timeout'


def wait_battle_end(max_s: float = 420) -> None:
    t0, other_since = clock(), None
    while clock() - t0 < max_s:
        s = state()
        if s == 'MAIN':
            return
        if s in ('REWARD', 'DIALOG'):
            talk()
            continue
        if s == 'OTHER':
            other_since = other_since or clock()
            if clock() - other_since > HALT_OTHER_S:
                raise Halt(EXIT_HALT, '戰鬥後連續不認得的畫面，停手')
        else:
            other_since = None
        sleep(POLL_S)
    raise Halt(EXIT_TIMEOUT, '戰鬥 / 導覽超過時間仍沒回到主畫面')


BYE_BTN = (822, 283)             # NPC 對話框第二個選項「再見」


def close_dialog() -> None:
    """關掉 NPC 對話窗但不回答任何選項：ESC → 還在就點「再見」；每次都驗證回到主畫面（HUD 紅字出現），3 輪都不行 → Halt"""
    for attempt in range(3):
        if state() == 'MAIN':
            return
        key('{ESC}')
        sleep(1.2)
        if state() == 'MAIN':
            return
        if state() == 'DIALOG':
            click(BYE_BTN, wait_ms=1200, note='q1920 對話窗點「再見」')
            if state() == 'MAIN':
                return
    raise Halt(EXIT_HALT, '對話窗關不掉（ESC 與「再見」都沒用），停手請使用者看畫面')


# ---- 步驟 ----
def step_solo(boss: bool = False) -> None:
    """路途遠、有野怪：單人 + 自動逃跑 → 導航到點 → （boss：取消自動逃跑 + 開自動戰鬥）→ 組隊 → 再點追蹤欄對話。
    使用者 2026-10-11：BOSS 步（深紅 7 樓 / 9 樓守護獸）路上也有野怪，一樣先單人逃跑導航，跟 NPC 對話前才取消逃跑。"""
    before = tracker_text()
    disband()
    set_ass(flee=True, fast=False, encounter=False)
    s = navigate()
    log(f'已抵達（{s}）→ ESC 關對話、' + ('取消自動逃跑、' if boss else '') + '組隊後再對話')
    close_dialog()
    if boss:
        set_ass(flee=False, auto=True)          # 到點才取消逃跑；BOSS 戰不能逃
    form_team()
    require_team()
    navigate()                       # 組隊後再點追蹤欄：同樣監測（導覽 / 對話 / 戰鬥，都不是 = 卡住 → 重點，見 navigate）
    res = talk(allow_battle=boss)
    log(f'對話結束：{res}')
    if res == 'battle':
        wait_battle_end()
    after = tracker_text()
    log(f'追蹤欄：{before!r} → {after!r}')
    if boss and before and after == before:
        raise Halt(EXIT_BOSS, 'BOSS 戰後追蹤欄沒變（可能沒打贏）：停手，不重打')


def step_team(fight: bool = False) -> None:
    """已組隊、同圖或很近的對話步（例：深紅步 5 伊拉）：驗證隊伍 → 導航 → 對話。
    fight = 組隊直接打 BOSS（不解散、不逃跑；使用者指定「直接組隊不用逃跑」的任務，例：五兄弟之謎步 7）"""
    before = tracker_text()
    if not TRUST_TEAM:
        require_team()
        set_ass(flee=False, auto=True)
    s = navigate()
    log(f'已抵達（{s}）')
    # 長導航（迷宮 / 洞窟）超過 TEAM_FRESH_S 後隊伍驗證會過期：對話窗開著時切換面板打不開，所以先 ESC 關窗 → 重驗隊伍 → 再點追蹤欄重開對話
    if not TRUST_TEAM and clock() - TEAM_OK_AT > TEAM_FRESH_S - 20:
        close_dialog()
        require_team()
        navigate()                   # 重驗隊伍後再點追蹤欄：同樣監測（導覽 / 對話 / 戰鬥，都不是 = 卡住 → 重點）
    res = talk(allow_battle=fight)
    log(f'對話結束：{res}')
    if res == 'battle':
        wait_battle_end()
    after = tracker_text()
    log(f'追蹤欄：{before!r} → {after!r}')
    if fight and res == 'battle' and before and after == before and not TRUST_TEAM:   # 信任模式：追蹤欄 OCR 兩行文字常讀成一樣會誤判；打輸時下一步對話會看到「挑戰」選項而停手
        raise Halt(EXIT_BOSS, 'BOSS 戰後追蹤欄沒變（可能沒打贏）：停手，不重打')


# ---- 接任務 ----
def unique_keys(name: str) -> list:
    """任務名 → 在全部任務名裡「不重複」的 2 字片段（任務詳情清單 OCR 常讀錯個別字，命中任一個就算認得）。
    同系列（漆黑洞窟一～五轉）本來就沒有共同的唯一 2 字，會回傳括號內的字（例：(一、一轉）。對照表見 notes/quest-detect-keys.md"""
    import re
    names = []
    for ln in (ROOT / 'knowledge' / 'quests' / 'guides.md').read_text(encoding='utf-8').splitlines():
        m = re.match(r'\| \d+ \| ([^|]+) \|', ln)
        if m:
            names.append(re.sub(r'\((1\.82|2\.5)\)|（必做）', '', m.group(1).strip()))
    if name not in names:
        return []
    others = [n for n in names if n != name]
    return [name[k:k + 2] for k in range(len(name) - 1) if not any(name[k:k + 2] in o for o in others)]


def is_reset_text(txt: str) -> bool:
    """按鈕 / 提示窗文字是不是「重置任務 / 花費石幣」類（這類絕不按；實測「重置任務」常讀成「重倕務」）"""
    return any(k in txt for k in ('重', '花費', '花费'))


def is_go_text(txt: str) -> bool:
    """白名單：按鈕要讀到「傳 / 送」才按（讀不到 / 讀到別的一律不按）"""
    return ('傳' in txt or '送' in txt) and not is_reset_text(txt)


def go_button_text() -> str:
    """任務詳情下方大按鈕文字：一般讀法（讀得到「重倕務」）+ -Dark 200（讀得到「傳送」）合起來（2026-10-15 22222 實測）"""
    return ''.join(uk().ocr(GO_TXT_OCR, '-Zooms', '3,4')) + '|' + ''.join(uk().ocr(GO_TXT_OCR, '-Zooms', '3,4', '-Dark', '200'))


# ---- 任務詳情下方大按鈕：顏色判（OCR 只當第二道確認）----
# 2026-10-15 從我們自己的 960×508 截圖量（tools/.cache detail_main / detail_side / qd1 / qd2 / fail/*）：
#   傳送鈕 = 藍底 ≈ (64,96,160)：按鈕格點約 82% 符合 b-r>=60 且 b>=140；
#   重置任務鈕 = 金底 ≈ (192,128,64)：約 70% 符合 r>g>b、r-b>=80、r>=150；
#   按鈕左右兩側面板底色 ≈ (208~223,160~175,128~143)；被「提示」窗壓暗時變 (96,80,64) → 不判；
#   地圖畫面（fail/20261015-103949 河流有 40% 藍點）兩側面板點不符 → 不判。
GO_BTN_PTS = [(x, y) for y in range(398, 432, 3) for x in range(370, 472, 3)]          # 按鈕本體格點（12 × 34 = 408 點）
GO_PANEL_PTS = [(300, 405), (320, 415), (340, 425), (500, 405), (525, 415), (550, 425)]   # 按鈕兩側面板底色
GO_BLUE_MIN, GO_GOLD_MIN, GO_OTHER_MAX = 0.6, 0.5, 0.05


def _is_blue(c) -> bool:
    return c[2] - c[0] >= 60 and c[2] >= 140


def _is_gold(c) -> bool:
    return c[0] > c[1] > c[2] and c[0] - c[2] >= 80 and c[0] >= 150


def _is_panel(c) -> bool:
    r, g, b = c
    return 195 <= r <= 235 and 145 <= g <= 190 and 110 <= b <= 160 and r > g > b


def classify_go_button(cols) -> str | None:
    """cols = GO_BTN_PTS + GO_PANEL_PTS 的顏色 → 'transfer'（藍）/ 'reset'（金）/ None（面板不在、被壓暗、判不出）"""
    if not cols or len(cols) != len(GO_BTN_PTS) + len(GO_PANEL_PTS):
        return None
    btn, panel = cols[:len(GO_BTN_PTS)], cols[len(GO_BTN_PTS):]
    if not all(_is_panel(c) for c in panel):
        return None
    n = len(btn)
    blue = sum(map(_is_blue, btn)) / n
    gold = sum(map(_is_gold, btn)) / n
    if blue >= GO_BLUE_MIN and gold <= GO_OTHER_MAX:
        return 'transfer'
    if gold >= GO_GOLD_MIN and blue <= GO_OTHER_MAX:
        return 'reset'
    return None


def go_button_decide(color: str | None, text: str | None) -> str | None:
    """顏色 + OCR 合判：顏色是藍（傳送）且 OCR 白名單也放行（讀到傳 / 送、沒有重 / 花費）才回 'transfer'；
    金色回 'reset'；其他（判不出、顏色與文字矛盾）回 None。比舊的只看 is_go_text 更嚴：兩道都要過。"""
    if color == 'reset':
        return 'reset'
    if color == 'transfer' and text is not None and is_go_text(text):
        return 'transfer'
    return None


def go_button_kind() -> tuple:
    """任務詳情下方大按鈕 → (kind, 說明)；kind == 'transfer' 才可以按（2026-10-15 22222 誤按重置任務花 50000 石幣的事故後加嚴）。
    先讀像素（便宜）；不是藍色就不 OCR 直接回；藍色才讀文字確認。"""
    color = classify_go_button(px(GO_BTN_PTS + GO_PANEL_PTS))
    if color != 'transfer':
        return go_button_decide(color, None), f'顏色 {color or "判不出"}'
    text = go_button_text()
    return go_button_decide(color, text), f'顏色 藍、文字 {text!r}'


def accept(name: str, side: bool = True) -> None:
    """左邊「詳情」→ 分頁 → 清單 OCR 找任務名 → 點 → 傳送 → 對話選項（組隊狀態 5 人一起領）"""
    if not TRUST_TEAM:
        require_team()
    click(DETAIL_BTN, right=2, wait_ms=900, note='q1920 開任務詳情')
    click(TAB_SIDE if side else TAB_MAIN, wait_ms=800, note='q1920 切分頁')
    found = None
    keys = unique_keys(name)
    for attempt in range(2):
        if attempt:    # 往下捲到底沒找到：不往上拉，直接關掉重開（清單回到頂端）再往下找一次
            key('{ESC}')
            click(DETAIL_BTN, right=2, wait_ms=900, note='q1920 重開任務詳情')
            click(TAB_SIDE if side else TAB_MAIN, wait_ms=800, note='q1920 切分頁')
        for i in range(10):
            for ln in _list_rows():
                if name in ln[0] or any(k in ln[0] for k in keys):
                    found = ln
                    break
            if found:
                break
            seq('drag 200 400 200 170; wait 1500', 'q1920 捲任務清單')
        if found:
            break
    if not found:
        raise Halt(EXIT_NOQUEST, f'任務詳情清單找不到「{name}」（可能已接 / 分頁不對）')
    click((200, found[1]), wait_ms=900, note=f'q1920 選任務 {name}')
    kind, why = go_button_kind()
    if kind != 'transfer':
        key('{ESC}')
        raise Halt(EXIT_HALT, f'「{name}」下方按鈕不是傳送（{why}；任務已在進行中？）：不按、停手，避免花石幣重置任務')
    click(GO_BTN, wait_ms=3500, note='q1920 傳送')
    s = wait_state(('DIALOG', 'REWARD'), timeout=15)
    if s != 'DIALOG':
        raise Halt(EXIT_TIMEOUT, '傳送後沒出現 NPC 對話窗')
    res = talk(allow_confirm=False)
    log(f'接任務對話結束：{res}；追蹤欄：{tracker_text()!r}')
    note(f'接任務「{name}」：對話 {res}；追蹤欄 {tracker_text()!r}')


# ---- 公告橫幅過濾（使用者 2026-10-13：公告固定在畫面中間一帶，常見「儲值公告」「抽獎翻倍公告」，不要判斷那裡的內容）----
ANNOUNCE_KEYS = ['儲值', '抽獎', '翻倍', '恭喜玩家', '恭喜', '稱號', 'LuckyCard', 'Lucky', '連翻', '幸運達人', '公告', '星球']
ANNOUNCE_LEARN = ROOT / 'tools' / '.cache' / 'announce-learned.json'


def is_announcement(text: str) -> bool:
    return any(k in text for k in ANNOUNCE_KEYS)


def _learn_announcement(x, y, text) -> None:
    """把偵測到的公告位置記下來（只記不判斷）：{'n': 次數, 'x': [..], 'y': [..], 'samples': [最近 5 句]}"""
    import json
    try:
        d = json.loads(ANNOUNCE_LEARN.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        d = {'n': 0, 'x': [], 'y': [], 'samples': []}
    d['n'] += 1
    d['x'] = (d['x'] + [x])[-50:]
    d['y'] = (d['y'] + [y])[-50:]
    d['samples'] = (d['samples'] + [text[:30]])[-5:]
    try:
        ANNOUNCE_LEARN.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def _list_rows():
    """任務詳情清單 OCR → [(文字, y)]；公告橫幅的行（關鍵字比對）一律丟掉，位置記進 announce-learned.json"""
    import json
    import winenv
    r = winenv.run_ps('ocr.ps1', *map(str, LIST_OCR), '-Zooms', '2,3')
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    if not d.get('ok'):
        return []
    out = []
    for ln in d.get('lines', []):
        if is_announcement(ln['text']):
            _learn_announcement(ln.get('x'), ln.get('y'), ln['text'])
            continue
        out.append((ln['text'], ln['y']))
    return out


# ---- 任務規劃（從知識庫自動算每一步的類型；任何任務都能用）----
def plan_steps(key: str, from_step: int | None = None) -> tuple[str, list]:
    """任務名 / 任務組 ID → (任務名, [(step, kind, 說明, npc 地圖)])；kind = solo / boss / talk。
    規則：戰鬥步 = boss；對話步 = solo；與前一步 NPC 同地圖 = talk（已組隊、近距離）；打怪步 / 非一般對話 → Halt 請人工規劃。
    from_step = 從第幾步開始（None = 用追蹤欄 OCR 對 explandTn 找；找不到就從第 1 步）"""
    sys.path.insert(0, str(ROOT / 'tools' / 'query'))
    import psa
    g, ts, _ = psa.task_steps(key)
    if not ts:
        raise Halt(EXIT_NOQUEST, f'知識庫找不到任務「{key}」')
    if from_step is None:
        txt = tracker_text()
        best, from_step = 0, 1
        for t in ts:
            ex = psa.clean(t.get('explandTn') or t.get('explandCn') or '')
            hit = sum(1 for ch in set(ex) if ch in txt)
            if ex and hit > best:
                best, from_step = hit, t.get('step', 1)
    out, prev_map = [], None
    # 追蹤欄有快速傳送的步驟：路上沒野怪，不必單人逃跑（使用者 2026-10-11：深紅步 2 守人）。key = 任務組 ID，value = 步號集合
    fast_travel = {2015: {1, 2}, 2023: {2}, 2003: {2}, 2004: {1}, 2005: {1}, 2006: {1}, 2007: {1}, 2008: {1}}   # 漆黑各轉步 1 守門人：使用者 2026-10-11 確認會快速傳送到附近
    for t in ts:
        c, why = psa.classify_step(t)
        n = psa.by_id('Npc').get(t.get('endNpc')) or {}
        mp = n.get('map')
        desc = f'{psa.clean(t.get("explandTn") or "")} @ {mp}:{n.get("x")},{n.get("y")}'
        if t.get('step', 0) >= from_step:
            if c == 'monster':
                raise Halt(EXIT_USAGE, f'步 {t.get("step")} 是打怪步（不能逃），需人工規劃：{desc}')
            kind = 'boss' if c == 'battle' else 'solo'
            if c != 'battle' and ((mp is not None and mp == prev_map) or t.get('step') in fast_travel.get(g, ())):
                kind = 'talk'
            out.append((t.get('step'), kind, desc, mp))
        prev_map = mp
    return psa.nm(ts[0]), out


def current_step(name: str, last_done: int = 0):
    """依追蹤欄副標題（-Dark 160 OCR）對 Task 表的 explandTn 找「現在是第幾步」；多步同文字（玄黃 8F / 14F）取 > last_done 的最小步。
    回 (step, kind) 或 (None, None)"""
    sys.path.insert(0, str(ROOT / 'tools' / 'query'))
    import psa
    g, ts, _ = psa.task_steps(name)
    sub = tracker_text().split('|')[-1]
    if not sub:
        return None, None
    _, plan = plan_steps(name, 1)
    kinds = {st: kind for st, kind, _, _ in plan}
    best = None
    for t in ts:
        ex = psa.clean(t.get('explandTn') or t.get('explandCn') or '')
        if not ex:
            continue
        hit = sum(1 for ch in set(ex) if ch in sub) / max(len(set(ex)), 1)
        if hit >= 0.6 and t.get('step', 0) > last_done:
            if best is None or hit > best[0] + 1e-9 or (abs(hit - best[0]) < 1e-9 and t['step'] < best[1]):
                best = (hit, t['step'])
    return (best[1], kinds.get(best[1])) if best else (None, None)


def cmd_plan(a) -> int:
    scroll_tracker()
    name, steps = plan_steps(a.name, 1)
    until = a.until or max(st for st, _, _, _ in steps)
    print(f'任務「{name}」共 {len(steps)} 步，做到第 {until} 步為止：')
    for st, kind, desc, mp in steps:
        print(f'  步 {st} {kind:5} {desc}')
    if a.dry:
        return EXIT_OK
    if a.accept:
        accept(a.name, side=not a.main)
    note(f'「{name}」開始（到第 {until} 步）')
    last_done, repeat, prev = (a.from_step or 1) - 1, 0, None
    done_any, finished, t_start, per_step = False, False, clock(), []
    while True:
        cur, kind = current_step(a.name, last_done)
        if cur is None and done_any:
            head = tracker_text().split('|')[0]
            key_chars = [ch for ch in set(name) if ch not in '()（）一二三四五轉洞窟']   # 「洞窟」各任務都有，不能拿來比
            if key_chars and not any(ch in head for ch in key_chars):
                log(f'追蹤欄第一條已不是「{name}」→ 任務完成')
                finished = True
                break
        if cur is None:
            raise Halt(EXIT_NOQUEST, '追蹤欄副標題對不到任何步驟（任務已完成 / 沒接 / OCR 讀不到）：停手請人看畫面')
        if cur > until:
            log(f'已到第 {cur} 步，超過 --until {until}，停下')
            break
        repeat = repeat + 1 if cur == prev else 0
        if repeat >= 3:
            raise Halt(EXIT_BOSS, f'步 {cur} 連做 3 次追蹤欄都沒前進：停手，請人看畫面')
        prev = cur
        desc = next((d for st, _, d, _ in steps if st == cur), '')
        log(f'=== {name} 步 {cur}（現在）{kind}：{desc} ===')
        t_step = clock()
        step_solo(boss=(kind == 'boss')) if kind in ('solo', 'boss') else step_team()
        done_any = True
        per_step.append(f'步{cur}:{kind}:{clock() - t_step:.0f}s')
        save_state({'quest': name, 'last': cur, 'at': time.strftime('%F %T')})
        ledger_mark(name, 'doing', f'步 {cur}（{kind}）做完一輪；追蹤欄 {tracker_text().split("|")[-1]!r}')
        note(f'「{name}」步 {cur}（{kind}）做完一輪；追蹤欄 {tracker_text()!r}')
        last_done = cur - 1 if cur == prev else cur     # 同一步沒前進就不往前推，下一輪再判斷
        cur2, _ = current_step(a.name, 0)
        last_done = (cur2 - 1) if cur2 else last_done
    total = clock() - t_start
    plan_txt = ' → '.join(f'步{st}:{k}' for st, k, _, _ in steps)
    note(f'「{name}」' + ('完成' if finished else f'做到第 {until} 步') + f'；共 {total:.0f} 秒；{" ".join(per_step)}')
    ledger_mark(name, 'done' if (finished or until >= max(st for st, _, _, _ in steps)) else 'paused',
                f'規劃 {plan_txt}；實際 {" ".join(per_step)}；共 {total:.0f} 秒')
    if a.grind:
        grind(a.spot)
    return EXIT_OK


# ---- 連續作業（一行指令跑多個任務）----
def cmd_batch(a) -> int:
    """依序做多個任務：每個任務 accept → 步驟（全程組隊，BOSS 步 fight、其他 talk）→ 帳本 / 日誌。
    任務清單用逗號分隔；任務間不停頓（龍王的守護有時效）；任何一個 Halt 就停在那個任務，回報後面還沒做的。
    用 --potion 在第一個任務前吃一顆龍王的守護（背包第 1 格），--potion-each 每個任務前都吃。"""
    names = [x.strip() for x in (a.names or '').split(',') if x.strip()]
    if a.auto:
        names = build_queue(a.client, a.use_ledger)
    if not names:
        log('沒有要做的任務（給任務名或 --auto）')
        return EXIT_USAGE
    done, t0 = [], clock()
    global TRUST_TEAM
    if a.trust_team:
        require_team()
        set_ass(flee=False, auto=True)
        log('開頭驗證一次完成：5 人隊 + 自動戰鬥開 / 自動逃跑關；之後不再逐步驗證')
        TRUST_TEAM = True
    for i, name in enumerate(names):
        try:
            if a.potion_each:
                use_potion()
            elif a.potion and i == 0:
                for _ in range(max(1, a.potions)):
                    use_potion()
            note(f'連續作業 {i + 1}/{len(names)}：開始「{name}」')
            ledger_mark(name, 'doing', f'連續作業第 {i + 1}/{len(names)} 個')
            if name in QF_QUESTS:
                import questflow1920 as qf
                qf.run_quest(name, use_potion=False)
                done.append(name)
                continue
            if name in PET_QUESTS:
                rc = run_pet_quest(name, a.client)
                if rc:
                    raise Halt(EXIT_HALT, f'寵物任務「{name}」katan1920 退出碼 {rc}（已通知；修好後同一行再跑會從中斷的階段接續）')
                ledger_mark(name, 'done', f'連續作業完成（katan1920）；{clock() - t0:.0f} 秒（累計）')
                note(f'連續作業：寵物任務「{name}」完成（累計 {clock() - t0:.0f} 秒）')
                done.append(name)
                continue
            _, steps = plan_steps(name, 1)
            kinds = ['fight' if k == 'boss' else 'talk' for _, k, _, _ in steps]
            partial = name in QUEST_UNTIL
            if partial:
                kinds = kinds[:QUEST_UNTIL[name]]
            accept(name, side=not (a.main or name in MAIN_QUESTS))
            global TRACK_N
            TRACK_N = a.track
            for j, kd in enumerate(kinds, 1):
                log(f'=== {name} 步 {j}/{len(kinds)} {kd} ===')
                step_team(fight=(kd == 'fight'))
                save_state({'batch': names, 'quest': name, 'step': j, 'at': time.strftime('%F %T')})
            ledger_mark(name, 'partial' if partial else 'done', f'連續作業{"做到第 %d 步停手（使用者規則）" % len(kinds) if partial else "完成"}；步驟 {",".join(kinds)}；{clock() - t0:.0f} 秒（累計）')
            note(f'連續作業：「{name}」完成（累計 {clock() - t0:.0f} 秒）')
            done.append(name)
        except Halt as h:
            ledger_mark(name, 'paused', f'連續作業停手：{h.msg}')
            note(f'連續作業停手於「{name}」：{h.msg}；已完成 {done}；未做 {names[i + 1:]}')
            log(f'停手於「{name}」（退出碼 {h.code}）：{h.msg}；已完成 {done}；未做 {names[i + 1:]}')
            return h.code
    log(f'連續作業全部完成：{done}（共 {clock() - t0:.0f} 秒）')
    if getattr(a, 'auto', False) and not getattr(a, 'no_finish', False):
        return cmd_finish(a.client)
    return EXIT_OK


def use_potion() -> None:
    """背包第 1 格（龍王的守護）→ 使用。前提：道具在第 1 格；之後確認左上 Buff 圖示出現（藍色閃電 ≈60,105）"""
    click((757, 462), right=2, wait_ms=1500, note='q1920 開背包')
    click((500, 145), wait_ms=1000, note='q1920 選第 1 格')
    click((417, 400), wait_ms=1200, note='q1920 使用')
    click((832, 66), wait_ms=900, note='q1920 關背包')
    log('已使用第 1 格道具（龍王的守護）')


# ---- 恢復練功 ----
SPOTS = {'地雷區': (760, 245, 60049), '地雷區2': (760, 288, 60050), '波拉島': (718, 138, 500),
         '五兄弟洞窟': (469, 272, 31706)}   # 五兄弟洞窟：座標取 heal.py 的 1920 傳送面板量測（練級傳送分頁）   # 練級傳送分頁點擊位置 + 抵達地圖


# 地圖名 OCR 會缺字（「五兄弟的山寨地下 6 樓」讀成「兄丨的寨地下」）：任一組關鍵字全部出現就算（2026-10-12 實測）
SPOT_NAME_KEY = {'五兄弟洞窟': [('五兄弟',), ('兄', '寨'), ('兄', '地下'), ('寨', '地下')]}


def grind(spot: str = '地雷區') -> None:
    """傳送到練功點 → 驗證地圖 → 組隊驗證 → 5 人 快速 + 自動戰鬥補勾（自動逃跑關）→ 開原地遇敵並讀回"""
    import ass
    if spot not in SPOTS:
        raise Halt(EXIT_USAGE, f'練功點只能是 {" / ".join(SPOTS)}')
    x, y, mp = SPOTS[spot]
    require_team()
    set_ass(flee=False, encounter=False)
    for attempt in range(3):
        click((905, 38), right=2, wait_ms=1200, note='q1920 開傳送面板')
        click((192, 190), wait_ms=900, note='q1920 練級傳送分頁')
        click((x, y), wait_ms=4500, note=f'q1920 傳送 {spot}')
        p = None
        arrived = False
        for _ in range(6):
            p = pos()
            if p and p[0] == mp:
                arrived = True
                break
            # 地圖名折兩行（例：五兄弟的山寨地下 6 樓）時座標 OCR 讀不到：改讀地圖名文字，含關鍵字就算抵達
            groups = SPOT_NAME_KEY.get(spot) or []
            nm = ''.join(uk().ocr((745, 22, 165, 55), '-Zooms', '2,3')) if groups else ''
            if any(all(k in nm for k in g) for g in groups):
                arrived = True
                break
            sleep(1.5)
        if arrived:
            log(f'已抵達 {spot}（{p[0]}:{p[1]},{p[2]}）' if p else f'已抵達 {spot}（地圖名確認，座標讀不到）')
            break
        log('傳送沒成功（被橫幅吃掉 / 戰鬥中 / 等級不足）→ 重試')
        key('{ESC}')
    else:
        raise Halt(EXIT_TIMEOUT, f'傳送 {spot} 3 次都沒到達')
    sleep(2)
    require_team()
    rc, res, msgs = ass.all_session({'快速戰鬥': True, '自動戰鬥': True})
    bad = [r for r, st in res.items() if not st or not (st['快速戰鬥'] and st['自動戰鬥'])]
    if rc or bad or len(res) != 5:
        raise Halt(EXIT_ASS, f'5 人快速 / 自動戰鬥補勾沒完成：{bad or msgs}')
    log('5 人快速戰鬥 + 自動戰鬥已確認')
    set_ass(encounter=True)
    note(f'恢復練功：{spot} 抵達、組隊 5 人、5 人快速 + 自動戰鬥確認、原地遇敵已開')


# ---- 收尾檢驗（使用者 2026-10-12）：恐龍博士做完 → 檢驗任務詳情裡沒做的只剩「不解」那幾個 → 有就去解 → 漆黑洞窟後續解到精靈王 → 轉生（不需另外確認）----
ALLOWED_LEFT = set(SKIP_QUESTS) | set(MAIN_LATER) | {'漆黑洞窟(二轉)'}      # 允許還沒完成的（漆黑二轉是要接著解的那一個）
KNOWN_NAMES = ['成人儀式', '初入石器', '漆黑洞窟(一轉)', '漆黑洞窟(二轉)', '漆黑洞窟(三轉)', '漆黑洞窟(四轉)', '漆黑洞窟(五轉)'] + SIDE_ORDER
DARK_KEYS = {'漆黑洞窟(一轉)': '一轉', '漆黑洞窟(二轉)': '二轉', '漆黑洞窟(三轉)': '三轉', '漆黑洞窟(四轉)': '四轉', '漆黑洞窟(五轉)': '五轉'}
STATUS_DY = 21                   # 任務卡「標題」到「狀態列（待接取 / 已完成）」的 y 距離（任務詳情截圖量測）
STATUS_XS = list(range(178, 226, 6))


def match_known(text: str):
    """任務詳情清單的一行 OCR 文字 → 已知任務名（認不出回 None）"""
    t = text.replace(' ', '')
    if '漆黑' in t:
        for n, k in DARK_KEYS.items():
            if k in t:
                return n
        return None
    for n in KNOWN_NAMES:
        if n in t:
            return n
    for n in SIDE_ORDER:
        if any(k in t for k in unique_keys(n)):
            return n
    return None


def is_done_card(cols) -> bool:
    """狀態列取樣點：「已完成」是亮綠字（約 11,229,7）、待接取是白字 → 綠點 >= 2 算已完成"""
    return sum(1 for c in cols if c[0] < 70 and c[1] > 170 and c[2] < 70) >= 2


def judge_remaining(status: dict, allowed=None) -> list:
    """status = {任務名: 是否已完成} → 還沒完成、又不在允許名單內的任務（依解題順序）"""
    allowed = ALLOWED_LEFT if allowed is None else allowed
    order = MAIN_FIRST + CAVES + AFTER_CAVES + [n for n in SIDE_ORDER if n not in CAVES + AFTER_CAVES]
    left = [n for n, d in status.items() if not d and n not in allowed]
    return sorted(left, key=lambda n: order.index(n) if n in order else 999)


def scan_detail_tab(side: bool, max_pages: int = 9) -> dict:
    """任務詳情已開著：切到主線 / 支線分頁 → 一頁一頁讀「任務名 + 狀態列顏色」→ {任務名: 是否已完成}"""
    click(TAB_SIDE if side else TAB_MAIN, wait_ms=800, note='q1920 檢驗：切分頁')
    out, stale = {}, 0
    for _ in range(max_pages):
        before = len(out)
        for text, y in _list_rows():
            n = match_known(text)
            if n is None or n in out:
                continue
            cols = px([(x, y + STATUS_DY) for x in STATUS_XS])
            if cols:
                out[n] = is_done_card(cols)
        stale = stale + 1 if len(out) == before else 0
        if stale >= 2:
            break
        seq('drag 200 400 200 300; wait 1200', 'q1920 檢驗：清單往下捲')
    return out


def scan_all_quests() -> dict:
    click(DETAIL_BTN, right=2, wait_ms=900, note='q1920 檢驗：開任務詳情')
    try:
        st = {}
        st.update(scan_detail_tab(side=False))
        st.update(scan_detail_tab(side=True))
    finally:
        key('{ESC}')
        sleep(0.8)
    return st


def cmd_finish(client: str) -> int:
    """檢驗 → 還有沒解的（不在不解名單）就去解 → 全部解完後漆黑洞窟接著解（守衛 → 精靈王）→ 轉生。轉生不另外確認（使用者規定）"""
    import types
    import questflow1920 as qf
    for rnd in range(3):
        st = scan_all_quests()
        if len(st) < 20:
            raise Halt(EXIT_HALT, f'任務詳情只讀到 {len(st)} 個任務（應有 30 個左右）：檢驗讀不完整，停手請看畫面')
        todo = judge_remaining(st)
        log(f'檢驗第 {rnd + 1} 輪：沒完成且該解的 = {todo or "無"}；不解 / 之後再解的 = ' +
            '、'.join(n for n, d in st.items() if not d and n in ALLOWED_LEFT))
        note(f'收尾檢驗第 {rnd + 1} 輪：該解沒解的 {todo or "無"}')
        if not todo:
            break
        a = types.SimpleNamespace(names=','.join(todo), auto=False, use_ledger=False, potion=False, potion_each=False,
                                  potions=1, trust_team=False, main=False, track=2, client=client, no_finish=True)
        rc = cmd_batch(a)
        if rc:
            return rc
    else:
        raise Halt(EXIT_HALT, '檢驗 3 輪後仍有沒解完的任務：停手，請看畫面')
    trans = qf.current_trans()
    cave = qf.dark_cave_name(trans)
    if cave is None:
        log('已是 5 轉以上，沒有下一個漆黑洞窟')
        return EXIT_OK
    name, key_id = cave
    log(f'=== 收尾：{name} 接著解（守衛 → 精靈王）→ 轉生（目前 {trans} 轉）===')
    note(f'收尾：{name} 從第 5 步接著解到精靈王並轉生（使用者規定，不另外確認）')
    qf.run_quest(name, key=key_id, from_step=5, use_potion=False)
    sleep(15)
    now = qf.current_trans()
    if now <= trans:
        raise Halt(EXIT_HALT, f'做完漆黑對話後轉生數沒增加（{trans} → {now}）：停手，請看畫面確認是否已轉生')
    log(f'轉生完成：{trans} 轉 → {now} 轉')
    note(f'轉生完成：{trans} → {now} 轉')
    return EXIT_OK


# ---- 入口 ----
def cmd_status() -> int:
    s = state()
    print(f'畫面 {s}；位置 {pos()}；追蹤欄 {tracker_text()!r}')
    ts = team_summary()
    print(f'隊伍：{ts}')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--track', type=int, default=1, help='目標任務在左側追蹤欄第幾條（預設 1；追蹤欄需先小幅上滑才看得到下面幾條時才用）')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    sub.add_parser('team')
    sub.add_parser('disband')
    p = sub.add_parser('accept')
    p.add_argument('name')
    p.add_argument('--main', action='store_true', help='任務在「主線」分頁（預設支線）')
    p = sub.add_parser('run')
    p.add_argument('--steps', required=True, help='solo,solo,boss,boss,talk')
    p.add_argument('--resume', action='store_true', help='steps 與進度檔相同就從上次做到的下一步繼續')
    p.add_argument('--grind', action='store_true', help='做完後接著恢復練功（傳送 + 5 人設定檢查 + 開原地遇敵）')
    p.add_argument('--spot', default='地雷區', help='練功點（地雷區 / 地雷區2）')
    p = sub.add_parser('plan', help='依知識庫自動規劃並執行一個任務（任何任務）')
    p.add_argument('name', help='任務名或任務組 ID')
    p.add_argument('--from', dest='from_step', type=int, help='從第幾步開始（預設用追蹤欄判斷）')
    p.add_argument('--dry', action='store_true', help='只印規劃，不碰遊戲操作')
    p.add_argument('--until', type=int, help='做到第 N 步為止（含）')
    p.add_argument('--accept', action='store_true', help='先走任務詳情接任務')
    p.add_argument('--main', action='store_true', help='任務在主線分頁')
    p.add_argument('--grind', action='store_true')
    p.add_argument('--spot', default='地雷區')
    p = sub.add_parser('batch', help='連續作業：依序做多個任務（全程組隊）')
    p.add_argument('names', nargs='?', default='', help='任務名，逗號分隔，例：強盜的洞穴,小豬愛情故事,四寶玉之謎')
    p.add_argument('--use-ledger', action='store_true', help='--auto 時扣掉帳本 done 的（帳本可能過期）')
    p.add_argument('--no-finish', action='store_true', help='--auto 做完後不要接著做收尾檢驗 + 漆黑後續 + 轉生')
    p.add_argument('--auto', action='store_true', help='依 SIDE_ORDER 排序（跳過不解、排最後的放尾端、帳本 done 的略過）')
    p.add_argument('--potion', action='store_true', help='第一個任務前吃一顆龍王的守護（背包第 1 格）')
    p.add_argument('--potion-each', action='store_true', help='每個任務前都吃一顆')
    p.add_argument('--potions', type=int, default=1, help='--potion 時第一個任務前吃幾顆（預設 1）')
    p.add_argument('--trust-team', action='store_true', help='開頭驗證一次隊伍 + 外掛，之後逐步不再驗證')
    p.add_argument('--main', action='store_true')
    p.add_argument('--track', type=int, default=2, help='任務接完後在追蹤欄第幾條（預設 2；漆黑暫停佔第一條）')
    sub.add_parser('finish', help='收尾：檢驗任務是否全做完 → 補做 → 漆黑後續解到精靈王 → 轉生')
    p = sub.add_parser('queue', help='印出支線解題順序（不碰遊戲）')
    p.add_argument('--use-ledger', action='store_true')
    p = sub.add_parser('ledger', help='顯示 / 標記任務帳本')
    p.add_argument('--mark', nargs=2, metavar=('任務', '狀態'), help='狀態 = done / paused / doing / todo')
    p.add_argument('--detail', default='')
    p = sub.add_parser('grind', help='恢復練功')
    p.add_argument('--spot', default='地雷區')
    a = ap.parse_args(argv)
    global CLIENT, TRACK_N
    CLIENT = a.client
    TRACK_N = max(1, a.track)
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if a.cmd == 'queue':
        for i, q in enumerate(build_queue(a.client, a.use_ledger), 1):
            print(f'{i:2} {q}')
        return EXIT_OK
    import winenv
    winenv.enable_server()
    try:
        preflight()
        if a.cmd == 'status':
            return cmd_status()
        if a.cmd == 'team':
            form_team()
        elif a.cmd == 'disband':
            disband()
        elif a.cmd == 'batch':
            return cmd_batch(a)
        elif a.cmd == 'finish':
            return cmd_finish(a.client)
        elif a.cmd == 'ledger':
            if a.mark:
                ledger_mark(a.mark[0], a.mark[1], a.detail)
            ledger_show(a.client)
        elif a.cmd == 'plan':
            return cmd_plan(a)
        elif a.cmd == 'grind':
            grind(a.spot)
        elif a.cmd == 'accept':
            accept(a.name, side=not a.main)
        elif a.cmd == 'run':
            steps = [x.strip() for x in a.steps.split(',') if x.strip()]
            if any(x not in ('solo', 'boss', 'talk', 'fight') for x in steps):
                print('steps 只能是 solo / boss / talk / fight')
                return EXIT_USAGE
            sv = load_state()
            start = sv.get('next', 0) if sv.get('steps') == steps and a.resume else 0
            for i, st in enumerate(steps, 1):
                if i - 1 < start:
                    continue
                log(f'=== 步驟 {i}/{len(steps)}：{st} ===')
                save_state({'steps': steps, 'next': i - 1, 'running': st, 'at': time.strftime('%F %T')})
                step_solo(boss=(st == 'boss')) if st in ('solo', 'boss') else step_team(fight=(st == 'fight'))
                save_state({'steps': steps, 'next': i, 'done': st, 'at': time.strftime('%F %T')})
                note(f'步驟 {i}/{len(steps)}（{st}）完成；追蹤欄 {tracker_text()!r}')
            if a.grind:
                grind(a.spot)
        return EXIT_OK
    except Halt as h:
        log(f'停手（退出碼 {h.code}）：{h.msg}')
        try:
            if a.cmd == 'plan':
                ledger_mark(a.name, 'paused', f'停手：{h.msg}')
        except Exception:
            pass
        return h.code


if __name__ == '__main__':
    sys.exit(main())
