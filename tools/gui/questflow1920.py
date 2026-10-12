#!/usr/bin/env python3
"""任務總流程（1920×1017；終端機直接跑）：照使用者排的順序一路解下去，可中斷續跑。

規則（使用者 2026-10-12）：
- 開頭從公共倉庫領「龍王的守護」到角色 1 背包；每個任務（及長任務的每一步）前讀 Buff 剩餘時間，快到期才吃。
- 全程 5 人組隊、不逃跑、自動戰鬥；點左邊任務追蹤欄導航，看不到就往下拉一點點。
- 不檢視寵物背包；接任務一律走「任務詳情 → 支線 → 最上排」。
- 順序：四大洞窟 → 漆黑（只到打完機暴，不跟守門員講話）→ 英雄島前傳 → 解救老爺爺 / 夢幻洞窟 / 亞姆的斧頭 /
  五兄弟之謎 / 強盜的洞穴 → 整理背包（刪除 + 存倉庫；角色 1 的龍王的守護留身上、其他人存公共）→
  小豬愛情故事 … 彌生和日美子 → 再整理一次背包。卡坦的願望 / 恐龍博士之後另跑（寵物流程）。
- 已在帳本標 done 的任務自動跳過；停手（Halt）就停在那個任務，再跑一次會從追蹤欄目前的步驟繼續。

用法（專案根目錄）：
  tools\\gui\\run_questflow.cmd kkfaq22222 [--dry] [--from 任務名] [--only 任務名,任務名] [--no-potion]
退出碼同 q1920.py：0 成功 / 3 隊伍 / 5 找不到任務 / 6 疑似驗證或不認得的畫面（停手通知使用者）/ 7 逾時 / 8 BOSS 後沒前進。
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import q1920 as q  # noqa: E402
import pausegate  # noqa: E402
import notifyhalt  # noqa: E402

# ---- 座標（截圖 960×508，2026-10-12 在 22222 實機量）----
BAG_BTN = (757, 462)
CLOSE_BAG = (832, 66)
TAB_BAG, TAB_DEPOT = (852, 175), (852, 275)
DEPOT_PUBLIC = (372, 118)
TAKE_BTN = (488, 400)            # 倉庫道具浮窗「取出」
USE_BTN = (417, 400)             # 背包道具浮窗「使用」
DEPOT_X, DEPOT_Y = (178, 238, 297, 357, 416), (170, 233, 296, 358)   # 倉庫格（5 欄 × 4 列）
BAG_SLOT1 = (500, 146)
BAG_NAME1 = (468, 118, 66, 36)   # 背包第 1 格上方道具名
ROLE1 = (52, 108)
BUFF_ICON = (60, 105)            # 龍王守護 Buff 圖示（點了出現「龍王守護 0天0時9分49秒」）
BUFF_SIG = (52, 98, 5, 21, 51)   # 圖示深藍底；沒有 Buff 時這裡是地圖
BUFF_TIME_BOX = (540, 228, 140, 30)
POTION = '龍王'
POTION_MIN_S = 150               # 剩餘不到這麼多秒就吃（Buff 持續 10 分鐘）
CHECK_GAP_S = 90                 # 長任務每步前檢查，但兩次檢查至少隔這麼久

FOUR_CAVES = ['琉璃洞窟', '玄黃洞窟', '碧青洞窟', '深紅洞窟']
HERO_ISLAND = ['英雄島前傳', '英雄島後傳']   # 後傳：使用者 2026-10-12 要求一併解完（含三段練寵）
GROUP_A = ['解救老爺爺', '夢幻洞窟', '亞姆的斧頭', '五兄弟之謎', '強盜的洞穴']
GROUP_B = ['小豬愛情故事', '四寶玉之謎', '馬祖快遞', '礦工的比賽', '夢德洞窟', '強恩一族', '伐木證書', '黃金羚羊之謎',
           '龍的巢穴', '彌生和日美子']
ALIAS = {'謎生和美日子': '彌生和日美子', '五兄弟隻謎': '五兄弟之謎', '五兄弟之迷': '五兄弟之謎',
         'hero2': '英雄島後傳', 'dreamcave': '夢幻洞窟', 'fiveb': '五兄弟之謎', 'fourjade': '四寶玉之謎', 'mazu': '馬祖快遞',
         # 其餘任務的英文別名（run_questflow_task.cmd 用；終端機批次檔只能放 ASCII）
         'liuli': '琉璃洞窟', 'xuanhuang': '玄黃洞窟', 'biqing': '碧青洞窟', 'shenhong': '深紅洞窟', 'hero1': '英雄島前傳',
         'rescue': '解救老爺爺', 'axe': '亞姆的斧頭', 'robber': '強盜的洞穴', 'piglove': '小豬愛情故事', 'miner': '礦工的比賽',
         'mengde': '夢德洞窟', 'qiangen': '強恩一族', 'wood': '伐木證書', 'antelope': '黃金羚羊之謎', 'dragonnest': '龍的巢穴',
         'miyo': '彌生和日美子'}   # 終端機指令只能 ASCII：--only hero2
CN_NUM = '一二三四五'
TRANSIENT_CODES = (7, 4)                # EXIT_TIMEOUT / EXIT_ASS：重試一次通常就過（傳送沒到達、外掛面板被戰鬥擋住）
SKIP_QUESTS = ['恐龍博士', '卡坦的願望']   # 排在最後做（寵物任務）：接任務時支線清單由上往下找，跳過這兩個再取最上排

_last_check = 0.0
RUN_LOG = None                   # main() 設定：tools/.cache/questflow-<client>.log（完整輸出，停手後給 Claude 看）


def log(msg: str) -> None:
    q.log(msg)
    if RUN_LOG:
        try:
            with open(RUN_LOG, 'a', encoding='utf-8') as fh:
                fh.write(time.strftime('%F %T ') + str(msg) + '\n')
        except OSError:
            pass


def snapshot(tag: str) -> None:
    """停手 / 出錯當下存一張畫面：tools/.cache/questflow-<client>-<tag>.png"""
    try:
        q.uk().gui('shot', f'questflow-{q.CLIENT}-{tag}.png')
    except Exception:
        pass


# ---- 純函式（離線測試用）----
def parse_remaining(txt: str):
    """'0天0時9分49秒' → 589；讀不到回 None（OCR 常把「時」讀成別字，所以只要抓到分 / 秒就算）"""
    t = txt.replace(' ', '')
    d = re.search(r'(\d+)天', t)
    h = re.search(r'(\d+)[時时]', t)
    m = re.search(r'(\d+)分', t)
    s = re.search(r'(\d+)秒', t)
    if not (m or s):
        return None
    return (int(d[1]) if d else 0) * 86400 + (int(h[1]) if h else 0) * 3600 + (int(m[1]) if m else 0) * 60 + (int(s[1]) if s else 0)


def last_boss_step(steps) -> int:
    """steps = q.plan_steps 回傳的 [(step, kind, desc, map)] → 最後一個戰鬥步的步號（沒有戰鬥回 0）"""
    return max([st for st, kind, _, _ in steps if kind == 'boss'] or [0])


def track_keys(name: str) -> list:
    k = q.unique_keys(name)
    if name.startswith('漆黑'):
        return ['漆黑']
    return k or [name[:2]]


# ---- 背包 / 倉庫 / 龍王的守護 ----
def open_bag() -> bool:
    for _ in range(3):
        c = q.px([(480, 56), CLOSE_BAG])
        if c and c[1][0] > 150 and c[1][1] < 120:
            return True
        q.click(BAG_BTN, right=2, wait_ms=1500, note='questflow 開背包')
    c = q.px([(480, 56), CLOSE_BAG])
    return bool(c) and c[1][0] > 150 and c[1][1] < 120


def close_bag() -> None:
    q.click(CLOSE_BAG, wait_ms=800, note='questflow 關背包')


def _ocr(box, *opts) -> str:
    return ''.join(q.uk().ocr(box, *opts)).strip()


def bag_has_potion() -> bool:
    """背包第 1 格是不是龍王的守護：先確保「顯示道具名」是開的（bag1920.ensure_names，沒開會自動按），再 OCR 名稱"""
    import bag1920
    bag1920.ensure_names()
    return POTION in _ocr(BAG_NAME1, '-Zooms', '3,4', '-Dark', '170')


def take_from_depot() -> bool:
    """公共倉庫 → 找「龍王的守護」→ 點開 → 取出（全部領到角色 1 背包）。找不到回 False"""
    if not open_bag():
        raise q.Halt(q.EXIT_HALT, '背包打不開（戰鬥 / 對話中？）')
    q.click(ROLE1, wait_ms=1000, note='questflow 選角色 1')
    q.click(TAB_DEPOT, wait_ms=1200, note='questflow 倉庫分頁')
    q.click(DEPOT_PUBLIC, wait_ms=900, note='questflow 公共倉庫')
    hit = None
    for y in DEPOT_Y[:2]:
        for x in DEPOT_X:
            if POTION in _ocr((x - 34, y - 26, 68, 20), '-Zooms', '3,4', '-Dark', '170'):
                hit = (x, y)
                break
        if hit:
            break
    if not hit:
        q.click(TAB_BAG, wait_ms=700)
        close_bag()
        return False
    q.click(hit, wait_ms=900, note='questflow 點龍王的守護')
    q.click(TAKE_BTN, wait_ms=1200, note='questflow 取出')
    q.click(TAB_BAG, wait_ms=900, note='questflow 回背包分頁')
    ok = bag_has_potion()
    close_bag()
    log('已從公共倉庫領出龍王的守護' if ok else '取出後背包第 1 格沒看到龍王的守護（請檢查）')
    return ok


def eat_potion() -> bool:
    """角色 1 背包第 1 格 → 使用。第 1 格不是龍王的守護就先從公共倉庫領"""
    for attempt in range(2):
        if not open_bag():
            raise q.Halt(q.EXIT_HALT, '背包打不開（戰鬥 / 對話中？）')
        q.click(ROLE1, wait_ms=1000, note='questflow 選角色 1')
        q.click(TAB_BAG, wait_ms=900, note='questflow 背包分頁')
        if bag_has_potion():
            q.click(BAG_SLOT1, wait_ms=900, note='questflow 選第 1 格')
            q.click(USE_BTN, wait_ms=1200, note='questflow 使用龍王的守護')
            close_bag()
            log('已吃一顆龍王的守護')
            return True
        close_bag()
        if attempt == 0 and not take_from_depot():
            break
    raise q.Halt(q.EXIT_USAGE, '背包和公共倉庫都沒有龍王的守護：停手（請補貨或加 --no-potion）')


def buff_remaining():
    """龍王守護 Buff 剩餘秒數；沒有 Buff 回 0；有圖示但讀不到時間回 None"""
    c = q.px([BUFF_SIG[:2]])
    if not c or not q.near(c[0], BUFF_SIG[2:], 40):
        return 0
    q.click(BUFF_ICON, wait_ms=800, note='questflow 看 Buff 剩餘時間')
    r = None
    for opts in (('-Zooms', '3,4'), ('-Zooms', '2,3'), ('-Zooms', '4,5')):   # 提示視窗位置 / 字體偶有差異：換倍率多讀幾次
        r = parse_remaining(_ocr(BUFF_TIME_BOX, *opts))
        if r is not None:
            break
    q.key('{ESC}')
    q.sleep(0.5)
    return r


def potion_check(force: bool = False) -> None:
    global _last_check
    if not force and q.clock() - _last_check < CHECK_GAP_S:
        return
    r = buff_remaining()
    _last_check = q.clock()
    if r is None:
        log('Buff 圖示在但剩餘時間讀不到，先不吃')
        return
    log(f'龍王的守護剩餘 {r} 秒')
    if r < POTION_MIN_S:
        eat_potion()
        _last_check = q.clock()


# ---- 追蹤欄 / 接任務 ----
TRACK_BOX = (40, 150, 190, 150)  # 左側追蹤欄可見範圍（x, y, w, h；下方被聊天按鈕列遮住）
TRACK_SCROLL = 'drag 130 255 130 215; wait 1200'     # 往下拉一點點（約 40 px）


def _track_lines():
    import json
    r = winenv_run('ocr.ps1', *map(str, TRACK_BOX), '-Zooms', '2,3')
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    return [(ln['text'], ln['y']) for ln in d.get('lines', [])] if d.get('ok') else []


def winenv_run(*a):
    import winenv
    return winenv.run_ps(*a)


TRACK_SUB_VISIBLE_Y = 238         # 任務標題 y 超過這個，副標題（約 +20）會被下方聊天按鈕列遮住（可見範圍約到 y 280）


def find_track_row(name: str, scroll: bool = True, reveal: bool = True):
    """追蹤欄 OCR 找任務名稱的實際位置（任務可能在第 2 或第 3 格，漆黑永遠佔第 1 條）。
    1) 看不到標題就「往下拉一點點」再找（最多 4 次）；
    2) 找到但標題太靠下（副標題被遮住）就繼續往下拉，直到副標題看得到（使用者 2026-10-12：沒拉就看不到「訓練魯烏到 30 級」）。
    找到就把 q.TRACK_Y_OVERRIDE 設成那一列的 y，之後點擊 / 讀副標題都用它。回 y 或 None。
    scroll=False：只 OCR 一次、不拉（每步檢查 / 完成確認用，使用者 2026-10-12 嫌拉太多次）；
    reveal=False：找到就好，不為了露出副標題再往下拉（只有要讀副標題時才需要）。"""
    if name not in TRAIN_STEPS:                  # 一次只解一個任務：只點追蹤欄，不拉（只有英雄島後傳要讀副標題才個別處理；使用者 2026-10-12）
        scroll = reveal = False
    keys = track_keys(name)
    skip = ('漆黑',) if not name.startswith('漆黑') else ()
    prev = q.TRACK_Y_OVERRIDE
    q.TRACK_Y_OVERRIDE = None

    def locate():
        for text, y in _track_lines():
            if any(k in text for k in skip):
                continue
            if any(k in text for k in keys):
                return max(y, q.TRACK[1] - 20)
        return None

    y = None
    rounds = 3 if scroll else 1
    for rnd in range(rounds):
        y = locate()
        if y is not None:
            break
        if rnd < rounds - 1:
            q.seq(TRACK_SCROLL, 'questflow 追蹤欄往下拉一點點')
    if y is None:
        q.TRACK_Y_OVERRIDE = prev
        return None
    for _ in range(4):                       # 副標題被遮住 → 往下拉到看得到
        if not reveal or y <= TRACK_SUB_VISIBLE_Y or name.startswith('漆黑'):
            break
        q.seq(TRACK_SCROLL, 'questflow 追蹤欄再往下拉（露出副標題）')
        y2 = locate()
        if y2 is None or y2 >= y:            # 拉不動（到底了）就用現有位置
            break
        y = y2
    q.TRACK_Y_OVERRIDE = y
    return y


def accept_top(name: str, side: bool = True, nth: int = 0) -> bool:
    """任務詳情 → 支線（side=False 時主線）→ **依任務名稱找那一列** → 傳送 → NPC 對話（5 人組隊狀態接受）。
    清單裡有你沒排進去的任務（例：英雄島後傳）時，絕不能無腦點最上排：對不到名稱就捲動找，找不到就停手。
    nth = 同名關鍵字出現多列時取第幾個（漆黑一～五轉都含「漆黑」，一轉 = 0）。
    主線 / 漆黑：追蹤欄永遠有漆黑，不能用追蹤欄判斷已接；改看該列下方是不是「待接取」，不是就回 False（不傳送、不對話）"""
    if not q.TRUST_TEAM:
        q.require_team()
    keys = track_keys(name)
    q.click(q.DETAIL_BTN, right=2, wait_ms=900, note='questflow 開任務詳情')
    q.click(q.TAB_SIDE if side else q.TAB_MAIN, wait_ms=800, note='questflow ' + ('支線' if side else '主線') + '分頁')
    hit, rows = [], []                           # 不再先把清單拉回頂端（使用者 2026-10-12：多餘；開面板就是從頂端開始）
    for attempt in range(8):
        rows = sorted(q._list_rows(), key=lambda r: r[1])
        hit = [r for r in rows if name in r[0] or any(k in r[0] for k in keys)]
        if len(hit) > nth:
            break
        q.seq('drag 200 400 200 170; wait 1200', 'questflow 清單往下捲')
    if len(hit) <= nth:
        q.key('{ESC}')
        raise q.Halt(q.EXIT_NOQUEST, f'任務詳情「{"支線" if side else "主線"}」清單找不到「{name}」（讀到：{[r[0] for r in rows][:6]}）：停手，不接其他任務')
    top = hit[nth]
    if not side:
        below = [r for r in rows if top[1] + 8 <= r[1] <= top[1] + 45]
        if not any('待接' in r[0] or '接取' in r[0] for r in below):
            log(f'「{name}」那一列不是「待接取」（下方文字 {[r[0] for r in below]}），視為已接，不重接')
            q.key('{ESC}')
            return False
    q.click((200, top[1]), wait_ms=900, note=f'questflow 選「{top[0]}」')
    q.click(q.GO_BTN, wait_ms=3500, note='questflow 傳送')
    s = q.wait_state(('DIALOG', 'REWARD'), timeout=15)
    if s != 'DIALOG':
        raise q.Halt(q.EXIT_TIMEOUT, '傳送後沒出現 NPC 對話窗')
    res = q.talk(allow_confirm=False)
    log(f'接任務對話結束：{res}')
    q.note(f'questflow 接「{name}」（{"支線" if side else "主線"}列 {top[0]!r}）：對話 {res}')
    return True


# ---- 練寵（英雄島後傳：魯烏 / 迪歐 30 級、加美 33 級；使用者 2026-10-12：去五兄弟洞窟練）----
TRAIN_STEPS = {'英雄島後傳': {7: ('魯烏', 30), 10: ('迪歐', 30), 14: ('加美', 33)}}
TRAIN_SPOT = '五兄弟洞窟'
PET_BTN, PET_CLOSE = (202, 40), (851, 63)
PET_ROLE_X, PET_ROLE_Y = 52, [110, 205, 290, 375, 440]
PET_SLOT_X, PET_SLOT_Y = 185, [120, 197, 275, 352, 430]
PET_BATTLE_BTN = (272, 433)
PET_REST_BTN = (452, 433)        # 「休息」（petrest1920 實測）
PET_NAME_BOX, PET_LVL_BOX = (250, 96, 220, 24), (310, 380, 110, 26)   # 名稱框 2026-10-12 縮小：舊框含鉛筆圖示，長名稱（愛麗兒隊的加美）讀不到
TRAIN_POLL_S = 60                # 第一次檢查的等待秒數（使用者：第一次沒問題）
TRAIN_POLL_NEXT_S = 20           # 之後每輪的間隔（使用者 2026-10-12：第二次起改 20 秒；讀 5 人等級本身約 20 秒）


def pet_panel_open() -> bool:
    c = q.px([PET_CLOSE])
    return bool(c) and q.near(c[0], (197, 73, 49), 35)


def open_pet_panel() -> None:
    for _ in range(6):
        if pet_panel_open():
            return
        q.click(PET_BTN, right=2, wait_ms=1500, note='questflow 開寵物面板')
    raise q.Halt(q.EXIT_HALT, '寵物面板打不開（戰鬥 / 對話中？）')


def close_pet_panel() -> None:
    """關寵物面板並驗證（第一次點偶爾被吃掉：沒關就再點，最多 4 次；還關不掉就 ESC）"""
    for i in range(4):
        if not pet_panel_open():
            return
        q.click(PET_CLOSE, wait_ms=900, note='questflow 關寵物面板')
    if pet_panel_open():
        q.key('{ESC}')
        q.sleep(0.8)
    if pet_panel_open():
        raise q.Halt(q.EXIT_HALT, '寵物面板關不掉：停手')


def pet_slot_filled(i: int) -> bool:
    c = q.px([(178, PET_SLOT_Y[i] + 22)])
    return not (bool(c) and c[0][0] > 120 and c[0][1] > 90)


def read_level_text() -> int | None:
    """面板右下「0轉133」：-Dark 170 最穩；各倍率結果分開解析（直接串接會變成 '0轉10轉1' → 10 級），取出現最多的值"""
    import collections
    vals = []
    for box in (PET_LVL_BOX, (320, 382, 90, 22)):
        for t in q.uk().ocr(box, '-Zooms', '3,4', '-Dark', '170'):
            m = re.search(r'(\d+)\s*轉\s*(\d+)', t)
            if m:
                vals.append(int(m[2]))
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def read_pet(i: int):
    """選第 i 格 → (名稱, 等級)"""
    q.click((PET_SLOT_X, PET_SLOT_Y[i]), wait_ms=800, note=f'questflow 選寵物第 {i + 1} 格')
    name = ''.join(_ocr(PET_NAME_BOX, *o) for o in (('-Zooms', '2,3'), ('-Zooms', '3,4'), ('-Zooms', '4,5'), ('-Zooms', '3,4', '-Dark', '170')))
    return name, read_level_text()


# 任務給的寵物名會帶部隊名前綴（例：「愛麗兒隊的加美」），名稱框放不下時 OCR 只讀到片段 → 別名含前綴片段（2026-10-12 實測）
PET_ALIAS = {'魯烏': ('魯烏', '魯鳥', '魯焉', '泰坦隊的', '坦隊的魯'),
             '迪歐': ('迪歐', '迪毆', '迪欧', '迪區', '米蘭達隊的', '蘭達隊的迪', '達隊的迪'),
             '加美': ('加美', '佳美', '加羙', '愛麗兒隊', '麗兒隊的', '兒隊的加', '隊的加美')}


def name_match(name: str, keyword: str) -> bool:
    """寵物名比對：只認完整名稱或已知 OCR 錯字別名。不再「中一字就算」（左迪洛斯曾因含「迪」被當成迪歐）"""
    n = re.sub(r'\s+', '', name)
    return any(a in n for a in PET_ALIAS.get(keyword, (keyword,)))


def find_pet(keyword: str):
    """目前這個角色的寵物欄找名稱含 keyword 的寵物 → (格, 等級)；找不到回 None。
    不靠「空格像素」判斷（亮色頭像會被誤當空格：魯烏曾因此被跳過）：5 格逐一點選讀名稱，新領的通常在最後所以由後往前讀。"""
    for i in (4, 3, 2, 1, 0):
        name, lvl = read_pet(i)
        if name_match(name, keyword):
            return i, lvl
    return None


def set_battle_all(keyword: str) -> None:
    open_pet_panel()
    for r in range(5):
        q.click((PET_ROLE_X, PET_ROLE_Y[r]), wait_ms=1000, note=f'questflow 寵物面板選角色 {r + 1}')
        hit = find_pet(keyword)
        if hit is None:
            close_pet_panel()
            raise q.Halt(q.EXIT_USAGE, f'角色 {r + 1} 寵物欄找不到「{keyword}」')
        i, lvl = hit
        q.click((PET_SLOT_X, PET_SLOT_Y[i]), wait_ms=800, note=f'questflow 選「{keyword}」')
        q.click(PET_BATTLE_BTN, wait_ms=1000, note=f'questflow 「{keyword}」出戰')
        log(f'角色 {r + 1}：「{keyword}」在第 {i + 1} 格（Lv{lvl}）→ 已設出戰')
    close_pet_panel()


def rest_quest_pets(keyword: str) -> None:
    """5 人把任務寵改「休息」（取消出戰）：出戰狀態下 NPC 不收（使用者 2026-10-12：你要把他取消戰鬥）"""
    open_pet_panel()
    for r in range(5):
        q.click((PET_ROLE_X, PET_ROLE_Y[r]), wait_ms=900, note=f'questflow 休息：角色 {r + 1}')
        hit = find_pet(keyword)
        if hit is None:
            close_pet_panel()
            raise q.Halt(q.EXIT_USAGE, f'角色 {r + 1} 找不到「{keyword}」，無法改休息')
        q.click((PET_SLOT_X, PET_SLOT_Y[hit[0]]), wait_ms=700, note=f'questflow 選「{keyword}」')
        q.click(PET_REST_BTN, wait_ms=900, note=f'questflow 「{keyword}」休息')
    close_pet_panel()
    log(f'5 人「{keyword}」已改休息（取消出戰）')


def levels(keyword: str) -> list:
    open_pet_panel()
    out = []
    for r in range(5):
        q.click((PET_ROLE_X, PET_ROLE_Y[r]), wait_ms=900, note=f'questflow 讀等級：角色 {r + 1}')
        hit = find_pet(keyword)
        out.append(hit[1] if hit else None)
    close_pet_panel()
    return out


AUTOSWAP_TAB, AUTOSWAP_CHK = (540, 127), (439, 270)    # 外掛「一般設置」分頁 / 自動轉換戰寵勾選框（autoswap1920 實測；純白 255,255,255 = 沒勾）
ROLE_NAMES = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']


def autoswap_off() -> None:
    """5 人外掛「自動轉換戰寵」全部取消勾選：練任務寵時不能讓它在門檻（25 級）把戰寵換掉（使用者 2026-10-12：中間會跳）"""
    import ass
    close_pet_panel()
    if not ass.open_panel(timeout=20):
        raise q.Halt(q.EXIT_ASS, '外掛面板打不開（戰鬥中？）')
    try:
        for r, nm in enumerate(ROLE_NAMES, 1):
            if not ass.select_role(nm):
                raise q.Halt(q.EXIT_ASS, f'外掛選不到角色 {r}')
            q.click(AUTOSWAP_TAB, wait_ms=800, note='questflow 外掛一般設置分頁')
            c = q.px([AUTOSWAP_CHK])
            checked = bool(c) and tuple(c[0]) != (255, 255, 255)
            if checked:
                q.click(AUTOSWAP_CHK, wait_ms=700, note=f'questflow 角色 {r} 取消自動轉換戰寵')
                c = q.px([AUTOSWAP_CHK])
                checked = bool(c) and tuple(c[0]) != (255, 255, 255)
            log(f'角色 {r} 自動轉換戰寵：{"仍勾選（取消失敗）" if checked else "關"}')
            if checked:
                raise q.Halt(q.EXIT_ASS, f'角色 {r} 自動轉換戰寵取消不掉：停手（會把任務寵換掉）')
    finally:
        ass.close_panel()


def train_pets(keyword: str, target: int) -> None:
    """5 人把「keyword」設出戰 → 傳去五兄弟洞窟（組隊、快速 + 自動戰鬥、原地遇敵開）→ 每分鐘讀等級，
    5 隻都 >= target 才收（不設時間上限）→ 關原地遇敵、等戰鬥結束。畫面連續不認得會由 q.wait_battle_end / 導航停手。"""
    log(f'--- 練寵：「{keyword}」→ {target} 級（5 人），地點 {TRAIN_SPOT} ---')
    lv0 = levels(keyword)                       # 已經練好（例如重啟續跑）就不用再傳去練
    if all(v is not None and v >= target for v in lv0):
        log(f'「{keyword}」5 隻已是 {lv0}，不用再練')
        rest_quest_pets(keyword)
        return
    set_battle_all(keyword)
    autoswap_off()
    q.grind(TRAIN_SPOT)
    t0 = q.clock()
    first = True
    while True:
        q.sleep(TRAIN_POLL_S if first else TRAIN_POLL_NEXT_S)
        first = False
        if q.state() == 'OTHER':
            q.sleep(5)
            if q.state() == 'OTHER':
                raise q.Halt(q.EXIT_HALT, '練寵中連續看到不認得的畫面（疑似驗證視窗）：停手')
        try:
            lv = levels(keyword)
        except q.Halt:
            continue                                  # 戰鬥中開不了面板：下一輪再讀
        log(f'練寵進度（{int(q.clock() - t0)} 秒）：{lv}')
        if all(v is not None and v >= target for v in lv):
            break
    q.set_ass(encounter=False)
    q.wait_battle_end()
    log(f'「{keyword}」5 隻都到 {target} 級，已關原地遇敵')
    rest_quest_pets(keyword)


# ---- 單一任務 ----
def pick_start_step(state: dict, name: str, all_steps: list, fresh: bool, given):
    """決定起始步與來源：(step 或 None, 來源說明)。
    順序：--from-step 指定 > 剛接的任務（第 1 步）> 存檔（同任務、未標完成、「上次做完第 N 步」→ N+1）> None（交給追蹤欄 OCR 猜）。"""
    if given is not None:
        return given, '--from-step 指定'
    if fresh:
        return 1, '剛接的任務'
    nums = sorted(s[0] for s in all_steps)
    try:
        done = int(state.get('step'))
    except (TypeError, ValueError):
        done = None
    if state.get('quest') == name and not state.get('done') and done is not None and nums:
        nxt = next((n for n in nums if n > done), None)
        if nxt is not None:
            return nxt, f'存檔（上次做完第 {done} 步）'
    return None, ''


def run_quest(name: str, key=None, stop_after_last_boss: bool = False, use_potion: bool = True,
              dry: bool = False, from_step=None, _retry: int = 0, to_step=None) -> None:
    key = key or name
    led = q.ledger_load().get(q.CLIENT, {}).get(name, {})
    if led.get('status') == 'done':
        log(f'「{name}」帳本已完成，跳過')
        return
    disp, steps = q.plan_steps(key, 1)
    all_steps = steps
    last = last_boss_step(steps)
    if stop_after_last_boss and not last:
        raise q.Halt(q.EXIT_USAGE, f'「{name}」沒有戰鬥步，無法決定停在哪')
    if dry:
        until = f'，只做到第 {last} 步（打完機暴）' if stop_after_last_boss else ''
        log(f'[dry] {disp}（{name}）：' + ' → '.join(f'步{st}:{"打" if k == "boss" else "談"}' for st, k, _, _ in steps) + until)
        return
    if use_potion:
        potion_check(force=True)
    q.ledger_mark(name, 'doing', 'questflow')
    if stop_after_last_boss:                     # 漆黑：永遠在追蹤欄，不能當「已接」；一律先看主線那列是不是待接取
        accept_top(name, side=False, nth=int(key) - 2004 if str(key).isdigit() else 0)
        row = find_track_row(name)
    else:
        row = find_track_row(name, reveal=name in TRAIN_STEPS)
        for _ in range(2):                       # 剛吃完藥 / 面板還沒收好時 OCR 會暫時讀不到：先重讀，不要直接去任務詳情接（2026-10-12 四寶玉之謎）
            if row is not None:
                break
            time.sleep(2)
            row = find_track_row(name, scroll=False, reveal=False)
    fresh = False
    if row is None:
        accept_top(name)
        fresh = True
        row = find_track_row(name, reveal=name in TRAIN_STEPS)
        if row is None:
            raise q.Halt(q.EXIT_NOQUEST, f'接完任務後追蹤欄找不到「{name}」')
    # 起始步：--from-step 明講就用它；否則才用追蹤欄副標題 OCR 猜（OCR 會猜錯：英雄島後傳曾把步 7 猜成步 11）
    if stop_after_last_boss and from_step is None and not fresh:
        from_step, src = None, ''
    else:
        from_step, src = pick_start_step(q.load_state(), name, all_steps, fresh and not stop_after_last_boss, from_step)
    if from_step is None:
        src = '追蹤欄副標題 OCR 猜測'
        log('提醒：沒有 --from-step，起始步由追蹤欄副標題 OCR 猜測（不一定準）')
        find_track_row(name)                     # 只有要猜起始步才需要把副標題拉到看得見
    _, steps = q.plan_steps(key, from_step)
    if to_step is not None:                      # 只做到第 to_step 步（卡坦的願望步 1 / 步 2 分兩次交）
        steps = [s for s in steps if s[0] <= to_step]
    if stop_after_last_boss:
        steps = [s for s in steps if s[0] <= last]
    log(f'「{disp}」追蹤欄第 {row} 條；起始步來源：{src or "預設（第 1 步）"}；要做 {len(steps)} 步：' + ' '.join(f'{st}:{k}' for st, k, _, _ in steps))
    t0 = q.clock()
    for j, (st, kind, desc, _) in enumerate(steps, 1):
        pausegate.wait(log)                      # 步與步之間的安全點：有暫停檔就停在這裡
        if st in TRAIN_STEPS.get(name, {}):
            kw, tgt = TRAIN_STEPS[name][st]
            try:
                train_pets(kw, tgt)
            except q.Halt as h:
                # 寵物要到這一步跟 NPC 對話時才領到（使用者 2026-10-12）：還沒有 → 先對話一次領取，再練，練完再對話交
                if h.code == q.EXIT_USAGE and '找不到' in h.msg:
                    log(f'還沒領到「{kw}」→ 先對話一次領取')
                    q.step_team(fight=False)
                    train_pets(kw, tgt)
                else:
                    raise
        if use_potion:
            potion_check()
        log(f'=== {name} 步{st}（{j}/{len(steps)}）{"BOSS" if kind == "boss" else "對話"}：{desc} ===')
        if j > 1 and find_track_row(name, scroll=False, reveal=False) is None:
            log('追蹤欄這一輪找不到任務名稱，沿用上次位置')
        for attempt in range(3):
            try:
                q.step_team(fight=(kind == 'boss'))
                break
            except q.Halt as h:
                # 上一個 BOSS 戰沒算贏（琉璃 14 樓實測）：下一步又看到「挑戰」→ 把挑戰打掉再重做這一步，最多 2 次
                if h.code == q.EXIT_BOSS and '戰鬥選項' in h.msg and attempt < 2:
                    log(f'步{st} 看到挑戰選項 = 上一場沒過 → 再挑戰一次（第 {attempt + 1} 次）')
                    if q.talk(allow_battle=True) == 'battle':
                        q.wait_battle_end()
                    continue
                raise
        if st in TRAIN_STEPS.get(name, {}):
            kw = TRAIN_STEPS[name][st][0]
            for retry in range(2):               # 交完要確認副標題「訓練X到N級」消失；沒消失 = 沒收（多半還在出戰）→ 改休息再交
                find_track_row(name)
                sub = q.tracker_text().split('|')[-1]
                if not any(c in sub for c in ('訓練',)) or kw[0] not in sub:
                    break
                log(f'交「{kw}」後追蹤欄仍是「{sub}」→ 再改休息並重新對話（第 {retry + 1} 次）')
                rest_quest_pets(kw)
                q.step_team(fight=False)
            else:
                raise q.Halt(q.EXIT_BOSS, f'「{kw}」交不出去（追蹤欄仍顯示訓練）：停手，請看畫面')
        q.save_state({'quest': name, 'step': st, 'at': time.strftime('%F %T')})
    detail = f'questflow 全程組隊；{len(steps)} 步；{q.clock() - t0:.0f} 秒'
    if to_step is not None and steps and to_step < max(s[0] for s in all_steps):
        q.ledger_mark(name, 'doing', detail + f'；已做到第 {steps[-1][0]} 步（分段做，後面還有步驟）')
        q.note(f'questflow「{name}」做到第 {steps[-1][0]} 步（分段）')
        return
    if not stop_after_last_boss:
        still = find_track_row(name, scroll=False, reveal=False)
        if still is not None:                    # 剛做完可能還在演出：隔幾秒再讀一次
            time.sleep(3)
            still = find_track_row(name, scroll=False, reveal=False)
        if still is not None and _retry < 1 and steps and steps[-1][0] < max(s[0] for s in all_steps):
            nxt = next(s[0] for s in sorted(all_steps) if s[0] > steps[-1][0])
            log(f'殘留且後面還有步驟 → 自己從第 {nxt} 步再做一次（只試一次）')
            return run_quest(name, key=key, stop_after_last_boss=stop_after_last_boss, use_potion=use_potion,
                             dry=dry, from_step=nxt, _retry=_retry + 1)
    if stop_after_last_boss:
        q.ledger_mark(name, 'done', detail + '；只解到打完機暴（使用者規定，不跟守門員講話）')
    else:
        still = find_track_row(name, scroll=False, reveal=False)
        q.ledger_mark(name, 'done' if still is None else 'paused', detail + ('' if still is None else '；追蹤欄仍有此任務'))
        if still is None:
            q.save_state({'quest': name, 'step': None, 'done': True, 'at': time.strftime('%F %T')})
        if still is not None:
            log(f'警告：做完步驟但追蹤欄仍看到「{name}」（可能還有步驟或 OCR 誤讀）')
    q.note(f'questflow「{name}」完成（{q.clock() - t0:.0f} 秒）')


def dark_cave_name(trans: int):
    """0 轉 → 漆黑洞窟(一轉)… 4 轉 → 五轉；5 轉以上回 None"""
    if trans >= 5:
        return None
    return f'漆黑洞窟({CN_NUM[trans]}轉)', 2004 + trans


def current_trans() -> int:
    import walk
    s = walk.stat()
    m = re.match(r'(\d+)轉', str(s.get('level') or ''))
    if not m:
        raise q.Halt(q.EXIT_USAGE, f'讀不到轉生數（HUD level={s.get("level")!r}），請用 --trans 指定')
    return int(m[1])


def mark_doing_paused(why: str) -> None:
    """停手 / 例外時，把這個客戶端帳本裡還是 doing 的任務標成 paused（不會自己留著 doing 讓人誤以為還在跑）。"""
    try:
        for name, v in q.ledger_load().get(q.CLIENT, {}).items():
            if v.get('status') == 'doing':
                q.ledger_mark(name, 'paused', why[:120])
                log(f'帳本：「{name}」doing → paused')
    except Exception as e:                       # 帳本寫不進去不能蓋掉原本的停手原因
        log(f'帳本標記 paused 失敗：{e}')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='任務總流程（1920×1017）')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('--dry', action='store_true', help='只印每個任務的規劃，不操作遊戲')
    ap.add_argument('--from', dest='from_name', help='從這個任務開始（前面的全部跳過）')
    ap.add_argument('--only', help='只做這些任務（逗號分隔）')
    ap.add_argument('--no-potion', action='store_true', help='不管龍王的守護（不領、不吃）')
    ap.add_argument('--trans', type=int, help='轉生數（決定漆黑洞窟是第幾轉；預設讀 HUD）')
    ap.add_argument('--skip-bag', action='store_true', help='跳過整理背包階段')
    ap.add_argument('--from-step', type=int, help='搭配 --only：該任務從第幾步開始（不用 OCR 猜）')
    ap.add_argument('--ledger', action='store_true', help='只列出這個客戶端的帳本（各任務狀態）後結束')
    ap.add_argument('--limit', type=int, default=0, help='最多實際做幾個任務就停（0 = 不限；已完成跳過的不算）')
    a = ap.parse_args(argv)
    q.CLIENT = a.client
    os.environ['PSA_EXE_MATCH'] = a.client
    if a.ledger:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        q.ledger_show(a.client)
        return 0
    global RUN_LOG
    RUN_LOG = str(q.STATE_DIR / f'questflow-{a.client}.log')
    log(f'===== questflow 開始（{a.client}{" dry" if a.dry else ""}）=====')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    only = [ALIAS.get(x.strip(), x.strip()) for x in a.only.split(',')] if a.only else None
    from_name = ALIAS.get(a.from_name, a.from_name) if a.from_name else None
    started = from_name is None
    use_potion = not a.no_potion
    try:
        q.preflight()
        if not a.dry:
            if not q.team_ok():
                q.form_team()
            q.require_team()
            q.set_ass(flee=False, auto=True)
            q.TRUST_TEAM = True
            log('開頭驗證完成：5 人隊 + 自動戰鬥開 / 自動逃跑關；之後不再逐步驗證')
        trans = a.trans if a.trans is not None else (0 if a.dry else current_trans())
        dark = dark_cave_name(trans)

        ran = 0
        plan = [(n, n, False) for n in FOUR_CAVES]
        if dark:
            plan.append((dark[0], str(dark[1]), True))
        plan += [(n, n, False) for n in HERO_ISLAND + GROUP_A] + [('__BAG__', None, False)] + [(n, n, False) for n in GROUP_B] + [('__BAG2__', None, False)]

        led = q.ledger_load().get(q.CLIENT, {})
        names = [n for n, _, _ in plan if not n.startswith('__BAG')]
        done_n = [n for n in names if led.get(n, {}).get('status') == 'done']
        todo_n = [n for n in names if n not in done_n and (not only or n in only)]
        if from_name in names:
            todo_n = todo_n[todo_n.index(from_name):] if from_name in todo_n else todo_n
        log(f'帳本摘要：已完成 {len(done_n)} 個；本輪待做 {len(todo_n)} 個：' + ('、'.join(todo_n) or '（無）')
            + (f'；paused：{"、".join(n for n in names if led.get(n, {}).get("status") == "paused")}'
               if any(led.get(n, {}).get('status') == 'paused' for n in names) else ''))
        for name, key, stop in plan:
            if not started:
                started = name == from_name
                if not started:
                    continue
            if only and name not in only and not name.startswith('__BAG'):
                continue
            if name.startswith('__BAG'):
                label = '整理背包' if name == '__BAG__' else '整理背包（彌生和日美子之後）'
                if a.skip_bag or a.dry:
                    log(f'[dry] {label}（bag1920 --do）' if a.dry else f'略過{label}')
                    continue
                if q.ledger_load().get(q.CLIENT, {}).get(label, {}).get('status') == 'done':
                    log(f'{label}帳本已完成，跳過')
                    continue
                log('=== 整理背包（刪除 + 存倉庫；角色 1 的龍王的守護留身上）===')
                import bag1920
                rc = bag1920.main(['--client', a.client, '--do'])
                if rc:
                    raise q.Halt(q.EXIT_HALT, f'bag1920 退出碼 {rc}')
                q.ledger_mark(label, 'done', 'questflow：bag1920 --do')
                continue
            pausegate.wait(log)                  # 任務與任務之間的安全點
            if a.limit and ran >= a.limit:
                log(f'已做滿 --limit {a.limit} 個任務，停止')
                break
            was_done = q.ledger_load().get(q.CLIENT, {}).get(name, {}).get('status') == 'done'
            for attempt in range(3):             # 暫時性失敗（傳送沒到 / 外掛面板打不開）最多重試 2 次，再停手
                try:
                    run_quest(name, key=key, stop_after_last_boss=stop, use_potion=use_potion, dry=a.dry,
                              from_step=a.from_step if (only and name in only and attempt == 0) else None)
                    break
                except q.Halt as h:
                    if h.code in TRANSIENT_CODES and attempt < 2 and not a.dry:
                        log(f'暫時性失敗（退出碼 {h.code}：{h.msg}）→ 重試 {attempt + 1}/2（從存檔的步驟接續）')
                        try:
                            q.wait_battle_end()
                        except Exception:
                            pass
                        time.sleep(5)
                        continue
                    raise
            if not was_done and not a.dry:
                ran += 1
            if not a.dry and q.ledger_load().get(q.CLIENT, {}).get(name, {}).get('status') == 'paused':
                # 做完步驟但追蹤欄仍有此任務（起始步 OCR 猜錯 / 還有步驟）：不要靜默跳去下一個（2026-10-12 夢幻洞窟被跳過）
                raise q.Halt(q.EXIT_BOSS, f'「{name}」做完所列步驟後追蹤欄仍有此任務（起始步可能猜錯）：停手，'
                                          f'請看畫面後用 --only {name} --from-step N 重跑')
        log('全部任務流程完成' if not a.dry else '[dry] 規劃完成')
        if not a.dry:
            notifyhalt.alert('questflow 全部任務流程完成', ok=True)
        return q.EXIT_OK
    except q.Halt as h:
        log(f'停手（退出碼 {h.code}）：{h.msg}')
        q.note(f'questflow 停手：{h.msg}')
        mark_doing_paused(f'停手（退出碼 {h.code}）：{h.msg}')
        snapshot('halt')
        notifyhalt.alert(f'questflow 退出碼 {h.code} {h.msg}'[:80])
        return h.code
    except Exception as e:                       # 腳本自己的錯：留 traceback + 畫面，方便事後修
        import traceback
        log('腳本例外：' + ''.join(traceback.format_exception(e)).strip())
        mark_doing_paused(f'腳本例外：{e}')
        snapshot('error')
        notifyhalt.alert(f'questflow 腳本例外 {e}'[:80])
        return 99


if __name__ == '__main__':
    sys.exit(main())
