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
import failshot  # noqa: E402

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
HEAL_BEFORE_DARK = True           # 設定：第一次漆黑任務前先回醫院補血一次（使用者 2026-10-14）；--no-dark-heal 單次關閉
POTION = '龍王'
POTION_PARTS = ('龍王', '王的守')   # 道具名在格子上方被截斷（實測讀到「王的守護」「王的守王的守」）


def is_potion(t: str) -> bool:
    return any(k in t for k in POTION_PARTS)
POTION_MIN_S = 150               # 剩餘不到這麼多秒就吃（Buff 持續 10 分鐘）
CHECK_GAP_S = 90                 # 長任務每步前檢查，但兩次檢查至少隔這麼久

ADULT = ['成人儀式']                     # 主線第一個；轉生後追蹤欄會自動出現，完成才能接支線（儀的玉 ×15 會疊在一格，只要 1 格背包空位；背包滿 15 格獎勵會寄信箱，使用者 2026-10-12）
FOUR_CAVES = ['琉璃洞窟', '玄黃洞窟', '碧青洞窟', '深紅洞窟']
HERO_ISLAND = ['英雄島前傳']                 # 後傳不解（使用者 2026-10-12：腳本還處理不好、會錯亂）
HERO_ISLAND_AFTER = ['英雄島後傳']          # 不在 plan 裡，--only 也不會跑（要解請自行加回 HERO_ISLAND）
# 遊戲實際的對話次數比知識庫任務表多（表把「接任務」併進步 1）：成人儀式 = 接受(14,6) → 差使領勾玉(188,13) → 護送交(14,6) = 3 次
# 值 = 步 1 要多做幾次（使用者 2026-10-13；彌生和日美子的接受由 accept_top 處理，不在這裡）
STEP_REPEAT_FIRST = {'成人儀式': 1}
NO_POTION_QUESTS = ('彌生和日美子', '猜謎三兄弟')   # 這兩個任務起不用吃龍王的守護（使用者 2026-10-13）
CONFIRM_ACCEPT = ('猜謎三兄弟',)               # 接任務時「進入裏面嗎？」確認要按接受的任務
RIDDLE = ['猜謎三兄弟']                    # 不在預設 plan；--only riddle 才做（fullrun 的 riddle 階段，排在卡坦的願望前面；要先練金布伊 77 級）
GROUP_A = ['解救老爺爺', '夢幻洞窟', '亞姆的斧頭', '五兄弟之謎', '強盜的洞穴']
GROUP_B = ['小豬愛情故事', '四寶玉之謎', '馬祖快遞', '礦工的比賽', '夢德洞窟', '強恩一族', '伐木證書', '黃金羚羊之謎',
           '龍的巢穴', '彌生和日美子']
ALIAS = {'謎生和美日子': '彌生和日美子', '五兄弟隻謎': '五兄弟之謎', '五兄弟之迷': '五兄弟之謎',
         'hero2': '英雄島後傳', 'adult': '成人儀式', 'riddle': '猜謎三兄弟', 'dreamcave': '夢幻洞窟', 'fiveb': '五兄弟之謎', 'fourjade': '四寶玉之謎', 'mazu': '馬祖快遞',
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


TIP_OCR = (345, 190, 270, 80)      # 「提示」視窗內文（例：你是否願意花費 50000 重置此任務？）
is_reset_text, is_go_text, go_button_text = q.is_reset_text, q.is_go_text, q.go_button_text   # 任務詳情下方大按鈕白名單（q1920）


def is_in_progress(txt: str) -> bool:
    """任務詳情某列下方狀態文字是不是「進行中」（OCR 常只讀到一半）"""
    return '進行' in txt or '行中' in txt


def is_pending(txt: str) -> bool:
    return '待接' in txt or '接取' in txt


def row_status(y: int) -> str:
    """任務詳情某列（名稱 y）下方狀態格單獨 OCR：清單整塊 OCR 常漏掉黃色「進行中」/ 部分「待接取」（2026-10-15 22222 實測）"""
    return ''.join(q.uk().ocr((135, y + 10, 130, 24), '-Zooms', '3,4'))


def bag_in_only(bag: str, only) -> bool:
    """--only 時這次整理背包要不要做：點名 'bag'，或它前面那組（__BAG__ ← GROUP_A、__BAG2__ ← GROUP_B）有任務被點名"""
    if 'bag' in only:
        return True
    return any(n in only for n in (GROUP_A if bag == '__BAG__' else GROUP_B))


def track_keys(name: str) -> list:
    k = q.unique_keys(name)
    if name.startswith('漆黑'):
        return ['漆黑']
    return k or [name[:2]]


# ---- 背包 / 倉庫 / 龍王的守護 ----
def open_bag() -> bool:
    for k in range(3):
        c = q.px([(480, 56), CLOSE_BAG])
        if c and c[1][0] > 150 and c[1][1] < 120:
            return True
        if k > 0:      # 使用者 2026-10-14：沒開成先 ESC 復原再重點（別的面板 / 視窗擋住時重點也沒用；22222 gate 吃龍王的守護停手）
            q.key('{ESC}')
            q.sleep(0.9)
        q.click(BAG_BTN, right=2, wait_ms=1500, note=f'questflow 開背包（第 {k + 1}/3 次）')
    c = q.px([(480, 56), CLOSE_BAG])
    return bool(c) and c[1][0] > 150 and c[1][1] < 120


def close_bag() -> None:
    q.click(CLOSE_BAG, wait_ms=800, note='questflow 關背包')


def _ocr(box, *opts) -> str:
    return ''.join(q.uk().ocr(box, *opts)).strip()


def potion_slot():
    """背包 15 格（3 列 × 5 欄）哪一格是龍王的守護：先確保「顯示道具名」是開的，再整頁 OCR 名稱（使用者 2026-10-14：不只看第 1 格）。
    回格序 0~14，沒有回 None"""
    import bag1920
    bag1920.ensure_names()
    for j, t in enumerate(bag1920.read_names()):
        if is_potion(t):
            return j
    return None


def bag_has_potion() -> bool:
    return potion_slot() is not None


def take_from_depot() -> bool:
    """公共倉庫 → 找「龍王的守護」→ 點開 → 取出（全部領到角色 1 背包）。找不到回 False"""
    if not open_bag():
        raise q.Halt(q.EXIT_HALT, '背包打不開（戰鬥 / 對話中？）')
    q.click(ROLE1, wait_ms=1000, note='questflow 選角色 1')
    hit = None
    # 遊戲會吃掉分頁點擊（使用者 2026-10-14：11111 倉庫明明有龍王的守護卻沒領）：倉庫分頁 + 公共倉庫最多重試 3 次；
    # 倉庫 5 欄 × 4 列全部掃（原本只掃前 2 列），沒找到就印出讀到的名稱方便對照
    for k in range(3):
        q.click(TAB_DEPOT, wait_ms=1200, note=f'questflow 倉庫分頁（第 {k + 1}/3 次）')
        q.click(DEPOT_PUBLIC, wait_ms=900, note='questflow 公共倉庫')
        seen = []
        for y in DEPOT_Y:
            for x in DEPOT_X:
                t = _ocr((x - 34, y - 26, 68, 20), '-Zooms', '3,4', '-Dark', '170')
                seen.append(t)
                if is_potion(t):
                    hit = (x, y)
                    break
            if hit:
                break
        if hit:
            break
        log(f'公共倉庫第 {k + 1}/3 次沒看到龍王的守護；讀到：{[t for t in seen if t]}')
        q.key('{ESC}')
        q.sleep(0.6)
        if not open_bag():
            break
        q.click(ROLE1, wait_ms=900, note='questflow 選角色 1')
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
        j = potion_slot()
        if j is not None:
            import bag1920
            q.click((bag1920.SLOT_X[j % 5], bag1920.SLOT_Y[j // 5]), wait_ms=900, note=f'questflow 選龍王的守護（背包第 {j + 1} 格）')
            q.click(USE_BTN, wait_ms=1200, note='questflow 使用龍王的守護')
            close_bag()
            log('已吃一顆龍王的守護')
            return True
        close_bag()
        if attempt == 0 and not take_from_depot():
            break
    # 沒有龍王的守護不停手（使用者 2026-10-13）：照樣往下跑，只是路上會遇到野怪、比較花時間。30 分鐘內不再重找（避免每步都開背包 / 倉庫）
    global _POTION_EMPTY_AT
    _POTION_EMPTY_AT = time.time()
    log('警告：背包和公共倉庫都沒有龍王的守護 → 不停手，沒有 Buff 繼續跑（會遇到野怪、較慢）；30 分鐘內不再重找')
    return False


_POTION_EMPTY_AT = 0.0


POTION_COOLDOWN_S = 480         # 上次吃之後這麼久內一律視為還有效（Buff 持續 10 分鐘），不重讀也不再吃（使用者 2026-10-13：有經驗加倍等其他 Buff，圖示位置 / 時間會讀錯 → 一直吃）
POTION_HARD_GAP_S = 120         # 就算讀到剩餘時間很短，兩次吃之間至少隔這麼久
POTION_MAX_PER_30MIN = 4        # 30 分鐘內最多吃幾顆，超過就不吃並提醒（異常保險絲）
POTION_STATE_NAME = 'potion-{client}.json'


def _potion_state_path():
    return q.STATE_DIR / POTION_STATE_NAME.format(client=q.CLIENT)


def _potion_eats() -> list:
    """這個帳號最近吃藥的時間戳（epoch 秒，只留 2 小時內）；存檔，重啟腳本也記得"""
    import json
    try:
        d = json.loads(_potion_state_path().read_text(encoding='utf-8'))
        return [t for t in d.get('eats', []) if time.time() - t < 7200]
    except (OSError, ValueError):
        return []


def _potion_record() -> None:
    import json
    eats = _potion_eats() + [time.time()]
    try:
        _potion_state_path().write_text(json.dumps({'eats': eats}), encoding='utf-8')
    except OSError:
        pass


q.LIST_OCR = (120, 140, 160, 330)       # 任務詳情只讀左邊清單欄（2026-10-13：右邊任務描述被當成任務名稱列，進行中的任務被誤判已完成）
BUFF_PANEL = (270, 120, 440, 300)   # 點開 Buff 圖示後的清單區（2026-10-13 實機：每個 Buff 一列，名稱 x≈390、剩餘時間 x≈607，列距約 62）
BUFF_SCROLL = 'drag 480 290 480 215; wait 900'   # 清單看不到時在中間往下滑


def _buff_lines(zoom_pairs=('2,3', '3,4')) -> list:
    import json
    out = []
    for z in zoom_pairs:
        r = winenv_run('ocr.ps1', *map(str, BUFF_PANEL), '-Zooms', z)
        try:
            d = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            continue
        if d.get('ok'):
            out += [(ln['text'], ln['x'], ln['y']) for ln in d.get('lines', [])]
    return out


def parse_buff_rows(lines):
    """OCR 行 [(text, x, y)] → ('ok', 秒) / ('absent', 0) / ('unknown', None)
    每個 Buff 一列：時間在右側（x >= 540），名稱在左側同一列（y 差 <= 12）。
    - 找到名稱含「龍王 / 守護」的列 → 取該列時間（多組 OCR 取中位數）
    - 沒找到龍王列：只有「所有列的名稱都明確是別的 Buff（智慧果 / 經驗 / 倍）」才算確定沒有（absent）；
      有任何一列名稱讀不出來就是 unknown（不能當成沒有 Buff，2026-10-13 曾因此多吃一顆）"""
    times = sorted(((y, t) for t, x, y in lines if x >= 540 and any(c in t for c in '時分秒')))
    rows = []                                   # [(y, [time texts])]
    for y, t in times:
        if rows and abs(rows[-1][0] - y) <= 10:
            rows[-1][1].append(t)
        else:
            rows.append((y, [t]))
    if not rows:
        return 'unknown', None
    dragon, others, unknown = [], 0, 0
    for y, ts in rows:
        name = ''.join(t for t, x, yy in lines if x < 540 and abs(yy - y) <= 12)
        if any(k in name for k in ('龍王', '守護', '守护', '龍', '護')):
            vals = sorted(v for v in (parse_remaining(t) for t in ts) if v is not None)
            if vals:
                dragon.append(vals[len(vals) // 2])
        elif any(k in name for k in ('智慧', '經驗', '经验', '果', 'EXP', '倍')):
            others += 1
        else:
            unknown += 1
    if dragon:
        return 'ok', dragon[0]
    if unknown == 0 and others == len(rows):
        return 'absent', 0
    return 'unknown', None


def buff_remaining():
    """龍王守護（圖示是深藍色人形「不遇敵」，清單裡名稱「龍王守護」）剩餘秒數。
    點 Buff 圖示（HUD 左上，第一格是 2倍智慧果、龍王守護在第二格；點哪一格都會跳同一份清單，約 x300~660 的半透明視窗）→
    OCR 整份清單（範圍 2026-10-13 放大：有第三個 Buff 時視窗會變長 / 要在中間往下滑）→ parse_buff_rows。
    清單沒開成（完全沒有時間列）就 ESC ×1 再點，最多 3 輪；看不到龍王列就往下滑再找（最多 2 次）。
    回傳：秒數 / 0（確定沒有）/ None（讀不準，不能判斷）"""
    res = ('unknown', None)
    for open_try in range(3):
        q.click(BUFF_ICON, wait_ms=1200, note=f'questflow 開 Buff 清單（第 {open_try + 1}/3 次）')
        try:
            for attempt in range(3):
                lines = _buff_lines()
                res = parse_buff_rows(lines)
                if res[0] == 'ok':
                    break
                has_time = any(x >= 540 and any(c in t for c in '時分秒') for t, x, y in lines)
                if not has_time:
                    break                       # 清單根本沒開：不要拖曳，交給外層 ESC 重開
                if attempt < 2:
                    q.seq(BUFF_SCROLL, note='questflow Buff 清單往下滑')
        finally:
            q.key('{ESC}')
            q.sleep(0.8)
        if res[0] in ('ok', 'absent'):
            break
    return res[1]


def potion_check(force: bool = False) -> None:
    """不會無限吃：①上次吃後 POTION_COOLDOWN_S 內直接略過（存檔，重啟也記得）②讀不到 / 讀到別的 Buff 時只看時間戳
    ③兩次吃間隔 >= POTION_HARD_GAP_S ④30 分鐘最多 POTION_MAX_PER_30MIN 顆"""
    global _last_check
    now = time.time()
    if _POTION_EMPTY_AT and now - _POTION_EMPTY_AT < 1800:
        return                                   # 剛確認過背包與公共倉庫都沒有：30 分鐘內不再找
    eats = _potion_eats()
    last = max(eats) if eats else 0
    since = now - last if last else None
    if since is not None and since < POTION_COOLDOWN_S:
        if force:
            log(f'龍王的守護：上次吃在 {int(since)} 秒前（< {POTION_COOLDOWN_S}），視為還有效，略過')
        return
    if not force and q.clock() - _last_check < CHECK_GAP_S:
        return
    r = buff_remaining()
    _last_check = q.clock()
    if r is not None and r >= POTION_MIN_S:
        log(f'龍王的守護剩餘 {r} 秒，夠用')
        return
    if r is None:
        # 讀不準（例：畫面上方 NEW 圖示的星星柱蓋住 Buff 名稱）：距離上次吃已久才補一顆，避免 Buff 過期後永遠不補（使用者 2026-10-13）
        if since is not None and since < 1200:
            log(f'Buff 清單讀不準 → 這次不吃（上次吃在 {int(since)} 秒前，未滿 1200 秒）')
            return
        log('Buff 清單讀不準，且距離上次吃已超過 20 分鐘（或沒有紀錄）→ 保險補吃一顆')
    recent = [t for t in eats if now - t < 1800]
    if len(recent) >= POTION_MAX_PER_30MIN:
        log(f'龍王的守護：30 分鐘內已吃 {len(recent)} 顆（上限 {POTION_MAX_PER_30MIN}）→ 不吃，請檢查 Buff 偵測')
        return
    if since is not None and since < POTION_HARD_GAP_S:
        return
    log(f'龍王的守護剩餘 {r} 秒 → 吃一顆')
    if eat_potion():
        _potion_record()
        _last_check = q.clock()


# ---- 追蹤欄 / 接任務 ----
TRACK_BOX = (40, 150, 190, 150)  # 左側追蹤欄可見範圍（x, y, w, h；下方被聊天按鈕列遮住）
TRACK_SCROLL = 'drag 130 255 130 215; wait 1200'     # 往下拉一點點（約 40 px）
TRACK_SCROLL_UP = 'drag 130 215 130 255; wait 1200'   # 往上滑一點點（猜謎三兄弟接完後追蹤欄要「小幅往上滑」才出現：2026-10-11 22222 實測）


def _track_lines():
    import json
    r = winenv_run('ocr.ps1', *map(str, TRACK_BOX), '-Zooms', '2,3')
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    return [(ln['text'], ln['y']) for ln in d.get('lines', [])] if d.get('ok') else []


def track_row_is_dark(y: int) -> bool:
    """追蹤欄 y 那一列（±14px）的字含「漆黑」→ True。OCR 讀不到字 → False（不擋；讀不到不代表是漆黑）"""
    near = [t for t, ly in _track_lines() if abs(ly - y) <= 14]
    return any('漆黑' in t or '漆' in t and '黑' in t for t in near)


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
        lines = _track_lines()
        for text, y in lines:
            if any(k in text for k in skip):
                continue
            if any(k in text for k in keys):
                return max(y, q.TRACK[1] - 20)
        # 保底（2026-10-13 猜謎三兄弟：標題在深色橫幅上，OCR 讀成 '4--0' / '兄' 這種碎字，完整名稱和關鍵字都比對不到）：
        # 剛接的新任務會排在追蹤欄最上面那一格；那一格有字、不是漆黑、且含任務名稱的任一個字 → 當作它
        first_y = q.TRACK[1]
        if not name.startswith('漆黑'):
            for text, y in lines:
                if abs(y - first_y) <= 14 and not any(k in text for k in skip) and any(ch in text for ch in set(name) if ch not in '之的'):
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
    if y is None and scroll:                 # 往下拉都找不到：追蹤欄可能被拉過頭 / 新任務排在上面 → 往上滑再找（最多 4 次）
        for k in range(4):
            q.seq(TRACK_SCROLL_UP, 'questflow 追蹤欄往上滑一點點')
            y = locate()
            if y is not None:
                break
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


def detail_status(name: str, side: bool = True):
    """任務詳情清單判斷任務狀態（使用者 2026-10-13 教的規則；不往下拉，只看第一頁）：
    每列有標籤「進行中」（黃字＋箭頭）/「待接取」（灰）/「已完成」（綠＋勾，OCR 讀不到）；
    排序 = 進行中在最上、待接取在其下、已完成在最下。
    - 找得到名稱那一列：讀它正下方標籤；標籤讀不到 → 它下面沒有進行中 / 待接取 = 已完成
    - 支線找不到名稱：待接取依固定順序（SIDE_ORDER），排在「最後一個可見待接取」之前卻沒出現 = 已完成；
      排在後面 = None（第一頁看不到，不判斷）
    回傳 '進行中' / '待接取' / '已完成' / None。讀完 ESC 關閉。"""
    keys = track_keys(name)
    result = None
    rows = []
    try:
        if open_detail(side):
            rows = sorted(q._list_rows(), key=lambda r: r[1])
    finally:
        q.key('{ESC}')
        q.sleep(0.6)
    LAB = ('進行', '待接', '接取', '完成')
    names = [(t, y) for t, y in rows if not any(k in t for k in LAB)]       # 任務名稱列

    def status_of(ny):
        lab = ''.join(r[0] for r in rows if ny + 4 <= r[1] <= ny + 40)
        for key_, st in (('完成', '已完成'), ('進行', '進行中'), ('待接', '待接取'), ('接取', '待接取')):
            if key_ in lab:
                return st
        return None

    # 名稱比對：先要求完整名稱（漆黑洞窟(二轉) / (三轉) 都含「漆黑」，不能用短關鍵字）；完整名稱讀不到才退到關鍵字
    exact = [(t, y) for t, y in names if name in t]
    if name.startswith('漆黑') and not side and names:
        exact = [names[0]]                       # 任務詳情主線的漆黑只看最上面那格（使用者 2026-10-14），不比對 N 轉
    target = exact[0] if exact else next(((t, y) for t, y in names if any(k in t for k in keys) and not name.startswith('漆黑')), None)
    if target:
        y = target[1]
        result = status_of(y)
        if not result:
            above_active = [ny for _, ny in names if ny < y - 10 and status_of(ny) in ('進行中', '待接取')]
            below_active = [ny for _, ny in names if ny > y + 10 and status_of(ny) in ('進行中', '待接取')]
            if above_active and not below_active:
                result = '已完成'
            elif y <= min(ny for _, ny in names) + 6:
                result = '進行中'                  # 最上面那列標籤讀不到 = 進行中（排序規則）
        return result
    if side and name in q.SIDE_ORDER:
        pend = [n for n in q.SIDE_ORDER if any(n in t and status_of(y) == '待接取' for t, y in names)]
        if pend and q.SIDE_ORDER.index(name) < max(q.SIDE_ORDER.index(n) for n in pend):
            return '已完成'
    return None


DETAIL_X = (882, 45)               # 任務詳情面板右上角 ✕（開著 ≈ (192,75,51)，關著是地圖 / 米色）


def detail_panel_open() -> bool:
    c = q.px([DETAIL_X])
    return bool(c) and q.near(c[0], (192, 75, 51), 30)


TAB_LIT_PTS = [(150, 122), (225, 122)]      # 主線 / 支線分頁底色取樣點（960 座標）；選中的分頁亮橘、沒選的暗褐


def tab_lit():
    """回傳目前亮燈的分頁 'main' / 'side'；兩邊亮度差不到 25% 讀不準回 None（使用者 2026-10-14：只要偵測分頁亮燈）"""
    c = q.px(TAB_LIT_PTS)
    if not c:
        return None
    m, s = sum(c[0][:2]), sum(c[1][:2])
    if max(m, s) < 1.25 * max(1, min(m, s)):
        return None
    return 'main' if m > s else 'side'


def open_detail(side: bool = True) -> bool:
    """開任務詳情並切到支線 / 主線分頁，用像素確認面板真的開了（使用者 2026-10-13：沒開成時往下拖會拖到聊天室）。
    沒開成：ESC ×1 → 再點「詳情」，最多 3 輪；仍沒開回 False（呼叫端不得拖曳、不得讀清單）"""
    for k in range(3):
        if not detail_panel_open():
            q.click(q.DETAIL_BTN, right=2, wait_ms=1000, note=f'questflow 開任務詳情（第 {k + 1}/3 次）')
        if detail_panel_open():
            want = 'side' if side else 'main'
            for _ in range(2):
                q.click(q.TAB_SIDE if side else q.TAB_MAIN, wait_ms=800, note='questflow ' + ('支線' if side else '主線') + '分頁')
                if tab_lit() in (want, None):        # 亮的是要的分頁（或讀不準）才算數；亮在另一邊就再點一次
                    break
            return True
        q.key('{ESC}')
        q.sleep(1.2)
    return False


def side_snapshot() -> dict:
    """只看任務詳情「支線」第一頁（不往下拉），用排序規則推出各任務狀態（使用者 2026-10-13）：
    進行中在最上、待接取在其下、已完成沉到最下。待接取保持遊戲固定順序（q.SIDE_ORDER），
    所以「排在最後一個可見待接取之前、卻沒出現在畫面上」的任務 = 已完成。
    回傳 {'active': [...], 'pending': [...], 'done': [...]}；沒有可見的待接取就不推定 done（保守）。"""
    rows = []
    if open_detail(True):
        rows = sorted(q._list_rows(), key=lambda r: r[1])
    q.key('{ESC}')
    q.sleep(0.6)
    LAB = ('進行', '待接', '接取', '完成')
    names = [(t, y) for t, y in rows if not any(k in t for k in LAB)]

    def lab_of(ny):
        return ''.join(r[0] for r in rows if ny + 4 <= r[1] <= ny + 40)

    active, pending, visible = [], [], []
    for n in q.SIDE_ORDER:
        hit = next(((t, y) for t, y in names if n in t), None)
        if not hit:
            continue
        visible.append(n)                        # 名稱在畫面上 = 一定還沒完成（已完成的會沉到最下面、第一頁看不到）
        lab = lab_of(hit[1])
        if '進行' in lab:
            active.append(n)
        elif '待接' in lab or '接取' in lab:
            pending.append(n)
        elif hit[1] <= min(y for _, y in names) + 6:
            active.append(n)                     # 最上面那列、標籤（黃字壓在橫幅上）讀不到：進行中排最上
    done = []
    if pending and len(names) >= 3:              # 名稱列太少（OCR 沒讀好）不推定，寧可不判斷
        last = max(q.SIDE_ORDER.index(n) for n in pending)
        done = [n for i, n in enumerate(q.SIDE_ORDER) if i < last and n not in visible]
    return {'active': active, 'pending': pending, 'done': done, 'visible': visible}


def sync_ledger_with_game(snap: dict) -> None:
    """帳本以遊戲畫面為準：推定已完成 → 補標 done；畫面上還看得到（進行中 / 待接取）卻標 done → 改回 todo（轉生重置後的舊紀錄）"""
    led = q.ledger_load().get(q.CLIENT, {})
    for n in snap['done']:
        if n in snap.get('visible', []) or led.get(n, {}).get('status') == 'doing':
            continue                             # 畫面上看得到 / 正在做的不補標 done
        # paused 且任務詳情第一頁完全看不到：進行中的一定排在最上面看得到，所以是已完成（使用者 2026-10-14：11111 強盜的洞穴
        # 帳本 paused、遊戲其實做完了，每次都在清單找不到而停手、看門狗空轉）
        if led.get(n, {}).get('status') != 'done':
            q.ledger_mark(n, 'done', 'questflow：任務詳情第一頁推定已完成（排序規則）')
            log(f'帳本補標 done：{n}')
    # 使用者 2026-10-14：22222 / 11111 的琉璃 / 玄黃 / 碧青洞窟被改回 todo（名字出現在漆黑洞窟的說明文字「已完成 4 大洞窟任務」裡，
    # 並不是清單裡的任務）→ 只有標籤是進行中 / 待接取的才算還沒完成。
    for n in snap['active'] + snap['pending']:
        if led.get(n, {}).get('status') == 'done':
            q.ledger_mark(n, 'todo', 'questflow：任務詳情顯示尚未完成，帳本舊紀錄更正')
            log(f'帳本更正 todo：{n}（任務詳情顯示還沒完成）')


def presume_adult_done(snap: dict) -> None:
    """成人儀式是主線，不在「支線」快照裡。判斷順序（2026-10-15 改）：
    1) 先看任務詳情「主線」分頁：成人儀式那一列是「待接取 / 進行中」→ 一定還沒做（帳本是 done 也更正回 todo）；
       （333 轉生後支線本來就有待接取，舊規則「支線有待接取 → 成人儀式做完了」把它誤標 done → 漆黑接了不算數、一直停手）
    2) 主線讀得到名稱、卻沒有「成人儀式」→ 已完成；
    3) 主線讀不到才退回舊規則：支線第一頁有進行中 / 待接取 → 推定已完成。"""
    name = ADULT[0]
    st = q.ledger_load().get(q.CLIENT, {}).get(name, {}).get('status')
    rows = []
    if open_detail(False):
        rows = sorted(q._list_rows(), key=lambda r: r[1])
    q.key('{ESC}')
    q.sleep(0.6)
    adult = [(t, y) for t, y in rows if name in t or '成人' in t]
    if adult:
        y = adult[0][1]
        lab = ''.join(t for t, ry in rows if y + 4 <= ry <= y + 40)
        if any(k in lab for k in ('待接', '接取', '進行')):
            if st == 'done':
                q.ledger_mark(name, 'todo', 'questflow：任務詳情主線顯示成人儀式待接取 / 進行中 → 帳本更正')
                log(f'帳本更正 todo：{name}（主線顯示「{lab}」，還沒做）')
            return
    if st in ('done', 'doing'):
        return
    if len(rows) >= 2 and not adult:
        q.ledger_mark(name, 'done', 'questflow：任務詳情主線清單沒有成人儀式 → 推定已完成')
        log(f'帳本補標 done：{name}（任務詳情主線清單看不到它）')
        return
    if not rows and (snap.get('active') or snap.get('pending')):
        q.ledger_mark(name, 'done', 'questflow：主線讀不到、支線已有進行中 / 待接取 → 成人儀式推定已完成')
        log(f'帳本補標 done：{name}（主線讀不到，支線已有進行中 / 待接取）')


def presume_dark_progress(dark_name: str) -> str:
    """漆黑洞窟先偵測追蹤欄再判讀（使用者 2026-10-14）：漆黑永遠在追蹤欄，副標題就是目前步驟。
    副標題「通過守護人」= 步 5（步 1~4 已打完）、「覲見精靈王」= 步 6 → 帳本補標 done（只代表步 1~4 完成；
    步 5 守門人留到最後任務都做完才回頭，由 gate 階段處理）。不倒退：副標題讀不出來 / 還在前面的步驟就不動帳本。
    回傳 'gate' / 'rebirth' / ''。"""
    try:
        lines = sorted(_track_lines(), key=lambda r: r[1])
    except Exception:
        return ''
    for i, (text, y) in enumerate(lines):
        if '漆黑' not in text:
            continue
        sub = ''.join(t for t, yy in lines if y + 6 <= yy <= y + 48)
        if not sub:    # 副標題在深色橫幅上，一般二值化讀不到（2026-10-14 333 實測：-Dark 200 讀得到「通過守護人」）
            try:
                for opts in (('-Zooms', '3,4', '-Dark', '200'), ('-Zooms', '2,3', '-Dark', '200')):
                    sub += ''.join(q.uk().ocr((45, y + 1, 175, 32), *opts))
            except Exception:
                pass
        if '覲見' in sub or '精靈王' in sub:
            stage = 'rebirth'
        elif '守護人' in sub or '守門人' in sub or '護人' in sub:
            stage = 'gate'
        else:
            continue
        st = q.ledger_load().get(q.CLIENT, {}).get(dark_name, {}).get('status')
        if st != 'done':
            q.ledger_mark(dark_name, 'done', f'questflow：追蹤欄副標題「{sub[:12]}」→ 步 1~4 已完成；步 5 守門人留到 gate 階段')
            log(f'帳本補標 done：{dark_name}（追蹤欄副標題「{sub[:12]}」＝步 1~4 已打完，守門人留到最後）')
        return stage
    return ''


def accept_top(name: str, side: bool = True, nth: int = 0) -> bool:
    """任務詳情 → 支線（side=False 時主線）→ **依任務名稱找那一列** → 傳送 → NPC 對話（5 人組隊狀態接受）。
    清單裡有你沒排進去的任務（例：英雄島後傳）時，絕不能無腦點最上排：對不到名稱就捲動找，找不到就停手。
    nth = 同名關鍵字出現多列時取第幾個（漆黑一～五轉都含「漆黑」，一轉 = 0）。
    主線 / 漆黑：追蹤欄永遠有漆黑，不能用追蹤欄判斷已接；改看該列下方是不是「待接取」，不是就回 False（不傳送、不對話）"""
    if not q.TRUST_TEAM:
        q.require_team()
    keys = track_keys(name)
    if not open_detail(side):
        failshot.pre('questflow')                # ESC 復原前先存圖（停手訊息的 Halt 會沿用這張）
        q.key('{ESC}')
        raise q.Halt(q.EXIT_TIMEOUT, '任務詳情面板開不起來（3 輪 ESC 重開都失敗）：不拖曳、停手，等看門狗重啟再試')
    hit, rows = [], []
    # 任務詳情不上下拉（使用者 2026-10-13：沒有就是沒有了）：只讀第一頁一次；找不到就視為這個任務不在（已完成 / 還沒解鎖）
    rows = sorted(q._list_rows(), key=lambda r: r[1])
    hit = [r for r in rows if name in r[0] or any(k in r[0] for k in keys)]
    if len(hit) <= nth:
        failshot.pre('questflow')
        q.key('{ESC}')
        raise q.Halt(q.EXIT_NOQUEST, f'任務詳情「{"支線" if side else "主線"}」清單找不到「{name}」（讀到：{[r[0] for r in rows][:6]}）：停手，不接其他任務')
    top = hit[nth]
    below = [r for r in rows if top[1] + 8 <= r[1] <= top[1] + 45]
    btxt = ''.join(r[0] for r in below) + '|' + row_status(top[1])
    if is_in_progress(btxt):
        # 「進行中」= 正在解（使用者 2026-10-15）：絕不按下方按鈕 —— 進行中的任務那顆鈕是「重置任務」（花 50000 石幣），
        # 不是傳送（2026-10-15 22222 夢德洞窟：帳本 paused → 回來重接 → 連按重置）。回 False，呼叫端去追蹤欄找來解
        log(f'「{name}」那一列是「進行中」（下方文字 {btxt!r}）：正在解的任務，不按重置 / 傳送，改去追蹤欄接著解')
        q.key('{ESC}')
        return False
    if not is_pending(btxt):
        # 白名單：要讀到「待接取」才接；讀不到就當已接（去追蹤欄找，找不到才停手），絕不盲按
        log(f'「{name}」那一列不是「待接取」（下方文字 {btxt!r}），視為已接，不重接')
        q.key('{ESC}')
        return False
    q.click((200, top[1]), wait_ms=900, note=f'questflow 選「{top[0]}」')
    go = go_button_text()
    if not is_go_text(go):
        failshot.pre('questflow')
        q.key('{ESC}')
        raise q.Halt(q.EXIT_HALT, f'「{name}」下方按鈕是「{go}」不是傳送（任務已在進行中？）：不按、停手，避免花石幣重置任務')
    q.click(q.GO_BTN, wait_ms=3500, note='questflow 傳送')
    s = q.wait_state(('DIALOG', 'REWARD'), timeout=15)
    if s == 'REWARD':                            # 「獲得物品」畫面擋在前面：關掉再等對話窗，不算失敗
        q.key('{ESC}')
        s = q.wait_state(('DIALOG',), timeout=10)
    if s != 'DIALOG':
        failshot.pre('questflow')                # 提示窗 / 戰鬥畫面還在時先拍，下面 ESC 復原後就看不到了
        tip = ''.join(q.uk().ocr(TIP_OCR))
        log(f'傳送後等不到對話窗：畫面狀態 {s}；提示窗文字 {tip!r}')
        # 復原只按 ESC；「確定」只在提示窗明確是「條件不達標」時才按（重置 / 花費類的提示窗絕不按確定）
        for _ in range(3):
            if not detail_panel_open():
                break
            tip = ''.join(q.uk().ocr(TIP_OCR))
            if tip and not is_reset_text(tip) and ('不達標' in tip or '條件' in tip):
                q.click((478, 343), wait_ms=700, note='questflow 提示窗「確定」（條件不達標）')
            else:
                q.key('{ESC}')
                q.sleep(0.8)
        raise q.Halt(q.EXIT_TIMEOUT, f'傳送後沒出現 NPC 對話窗（畫面 {s}；已 ESC 復原畫面）')
    # 猜謎三兄弟：點「接藍暴任務」後會跳「進入裏面嗎？」確認框，必須按「接受」任務才算接下（22222 2026-10-11 實測：按接受只是進 811:29,15、任務已承接）；
    # 先前 ESC 掉它 → 任務詳情仍是「待接取」→ 追蹤欄找不到（2026-10-13 一條龍停手原因）。其他任務維持不自動按（避免誤進副本）。
    res = q.talk(allow_confirm=name in CONFIRM_ACCEPT)
    log(f'接任務對話結束：{res}')
    q.note(f'questflow 接「{name}」（{"支線" if side else "主線"}列 {top[0]!r}）：對話 {res}')
    return True


# ---- 練寵（英雄島後傳：魯烏 / 迪歐 30 級、加美 33 級；使用者 2026-10-12：去五兄弟洞窟練）----
# 猜謎三兄弟（使用者 2026-10-12）：步 2 之前練「金布伊」（遊戲內正確名稱；任務文字寫金豬）到 77 級；寵物欄 戰寵·坐騎 / 戰寵·坐騎 / 紅暴 / 金羊 / 空 → 金布伊在第 5 格；
# 去波拉島（120 級點）練，預設 5 分鐘後第一次檢查、之後每 30 秒；先看角色 1，達標才看角色 2~5；檢查 = 點第 5 格讀中間下方「0轉N」。
TRAIN_STEPS = {'英雄島後傳': {7: ('魯烏', 30), 10: ('迪歐', 30), 14: ('加美', 33)},
               '猜謎三兄弟': {2: ('金布伊', 77, {'spot': '波拉島', 'first_s': 300, 'poll_s': 30, 'slot': 5})}}
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
    for k in range(6):
        if pet_panel_open():
            return
        if k in (2, 4):                  # 開不成多半是別的視窗（外掛的轉換設定 / 提示窗）蓋著：ESC ×1 再開（使用者 2026-10-13：卡住要按 ESC 才退得出來）
            q.key('{ESC}')
            q.sleep(0.7)
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


MODE_PTS = (('battle', (272, 423)), ('ride', (362, 423)), ('rest', (452, 423)))   # 面板下方 出戰 / 騎乘 / 休息 鈕；選中的那顆上緣內側是橘金色（約 190,125,60），沒選中是米色（225,200,167）


def pet_mode(cols=None) -> str | None:
    """目前選中的寵物是 'battle' 出戰 / 'ride' 騎乘 / 'rest' 休息；讀不到 / 沒有寵物回 None（2026-10-13 實測 3 種狀態的顏色）"""
    cols = cols if cols is not None else q.px([p for _, p in MODE_PTS])
    if not cols or len(cols) != len(MODE_PTS):
        return None
    for (name, _), (r, g, b) in zip(MODE_PTS, cols):
        if r > 150 and g < 190 and b < 100:
            return name
    return None


def ensure_battle(slot: int, tries: int = 3) -> bool:
    """寵物面板開著、角色已選：選第 slot 格（0 起算）→ 不是「出戰」就按出戰並驗證，最多 tries 次。
    使用者 2026-10-13：不明原因沒出戰到寵物 → 偵測再補出戰。空格回 False（不亂點）。"""
    for k in range(tries):
        q.click((PET_SLOT_X, PET_SLOT_Y[slot]), wait_ms=800, note=f'questflow 確認第 {slot + 1} 格出戰（第 {k + 1}/{tries} 次）')
        if pet_mode() == 'battle':
            return True
        if not pet_slot_filled(slot):
            return False
        q.click(PET_BATTLE_BTN, wait_ms=1000, note=f'questflow 第 {slot + 1} 格出戰')
    q.click((PET_SLOT_X, PET_SLOT_Y[slot]), wait_ms=800, note='questflow 最後驗證出戰')
    return pet_mode() == 'battle'


def read_level_text() -> int | None:
    """面板右下「0轉133」：-Dark 170 最穩；各倍率結果分開解析（直接串接會變成 '0轉10轉1' → 10 級），取出現最多的值"""
    import collections
    vals = []
    for box in (PET_LVL_BOX, (320, 382, 90, 22)):
        for t in q.uk().ocr(box, '-Zooms', '3,4', '-Dark', '170'):
            m = re.search(r'(\d+)\s*轉\s*(\d+)', t)
            if m:
                vals.append(int(m[2]))
    if not vals:        # 備援（2026-10-14：0轉59 在 -Dark 170 讀成「S9」→ 一直 None；換別的二值化門檻 / 不二值化就讀得到）
        for box in (PET_LVL_BOX, (320, 382, 90, 22), (PET_LVL_BOX[0] - 10, PET_LVL_BOX[1] - 6, PET_LVL_BOX[2] + 20, PET_LVL_BOX[3] + 12)):
            for opts in (('-Zooms', '3,4', '-Dark', '130'), ('-Zooms', '3,4', '-Dark', '200'), ('-Zooms', '3,4'), ('-Zooms', '2,3')):
                for t in q.uk().ocr(box, *opts):
                    m = re.search(r'[0-9OoSs]?\s*轉\s*(\d+)', t)
                    if m and 1 <= int(m[1]) <= 200:
                        vals.append(int(m[1]))
            if vals:
                break
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def read_pet(i: int):
    """選第 i 格 → (名稱, 等級)"""
    q.click((PET_SLOT_X, PET_SLOT_Y[i]), wait_ms=800, note=f'questflow 選寵物第 {i + 1} 格')
    name = ''.join(_ocr(PET_NAME_BOX, *o) for o in (('-Zooms', '2,3'), ('-Zooms', '3,4'), ('-Zooms', '4,5'), ('-Zooms', '3,4', '-Dark', '170')))
    return name, read_level_text()


# 任務給的寵物名會帶部隊名前綴（例：「愛麗兒隊的加美」），名稱框放不下時 OCR 只讀到片段 → 別名含前綴片段（2026-10-12 實測）
PET_ALIAS = {'金布伊': ('金布伊', '金布衣', '金布依', '金豬', '金布'),
             '魯烏': ('魯烏', '魯鳥', '魯焉', '泰坦隊的', '坦隊的魯'),
             '迪歐': ('迪歐', '迪毆', '迪欧', '迪區', '米蘭達隊的', '蘭達隊的迪', '達隊的迪'),
             '加美': ('加美', '佳美', '加羙', '愛麗兒隊', '麗兒隊的', '兒隊的加', '隊的加美')}


PET_SLOT_HINT = {'金布伊': 4}     # 猜謎三兄弟：寵物欄第 5 格是金布伊（使用者 2026-10-13：指定出戰金布伊）


def name_match(name: str, keyword: str) -> bool:
    """寵物名比對：只認完整名稱或已知 OCR 錯字別名。不再「中一字就算」（左迪洛斯曾因含「迪」被當成迪歐）"""
    n = re.sub(r'\s+', '', name)
    return any(a in n for a in PET_ALIAS.get(keyword, (keyword,)))


def find_pet(keyword: str):
    """目前這個角色的寵物欄找名稱含 keyword 的寵物 → (格, 等級)；找不到回 None。
    不靠「空格像素」判斷（亮色頭像會被誤當空格：魯烏曾因此被跳過）：5 格逐一點選讀名稱，新領的通常在最後所以由後往前讀。"""
    order = [4, 3, 2, 1, 0]
    hint = PET_SLOT_HINT.get(keyword)          # 已知位置先看（猜謎三兄弟：金布伊在第 5 格）
    if hint is not None:
        order = [hint] + [i for i in order if i != hint]
    for i in order:
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
        ok = ensure_battle(i)
        log(f'角色 {r + 1}：「{keyword}」在第 {i + 1} 格（Lv{lvl}）→ ' + ('已出戰（已驗證）' if ok else '警告：按了出戰仍沒看到出戰狀態'))
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


def levels(keyword: str, fix_battle: bool = False) -> list:
    open_pet_panel()
    out = []
    for r in range(5):
        q.click((PET_ROLE_X, PET_ROLE_Y[r]), wait_ms=900, note=f'questflow 讀等級：角色 {r + 1}')
        hit = find_pet(keyword)
        if fix_battle and hit and not ensure_battle(hit[0]):    # 練寵中順便確認它真的出戰（不然拿不到經驗）
            log(f'警告：角色 {r + 1}「{keyword}」不是出戰狀態，按了出戰仍沒變')
        out.append(hit[1] if hit else None)
    close_pet_panel()
    return out


AUTOSWAP_TAB, AUTOSWAP_CHK = (540, 127), (439, 270)    # 外掛「一般設置」分頁 / 自動轉換戰寵勾選框（autoswap1920 實測；純白 255,255,255 = 沒勾）
ROLE_NAMES = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']


def autoswap_off() -> None:
    """5 人外掛「自動轉換戰寵」全部取消勾選：練任務寵時不能讓它在門檻（25 級）把戰寵換掉（使用者 2026-10-12：中間會跳）。
    2026-10-13：每個角色最多重試 3 次（點 → 等 → 讀，讀到沒勾才算過）；5 人做完再整體重掃一輪，仍勾著的重關；最後還有勾才停手"""
    import ass
    close_pet_panel()
    if not ass.open_panel(timeout=20):
        raise q.Halt(q.EXIT_ASS, '外掛面板打不開（戰鬥中？）')

    def is_checked() -> bool:
        # 勾選框內暗色（✓ 筆劃）點數：有勾約 63、沒勾 0（2026-10-13 實測）。舊版只取 (439,270) 一個像素，
        # 有勾時那個點也可能是白的 → 以為「沒勾」就不去關，自動轉換戰寵一直開著（使用者 2026-10-13 發現）
        pts = [(x, y) for y in range(259, 281, 2) for x in range(428, 452, 2)]
        c = q.px(pts) or []
        return sum(1 for (r_, g_, b_) in c if r_ < 110 and g_ < 110 and b_ < 110) >= 8

    def turn_off(r: int, nm: str, tries: int = 3) -> bool:
        """回傳最後是否仍勾選"""
        if not ass.select_role(nm):
            raise q.Halt(q.EXIT_ASS, f'外掛選不到角色 {r}')
        q.click(AUTOSWAP_TAB, wait_ms=800, note='questflow 外掛一般設置分頁')
        checked = is_checked()
        for k in range(tries):
            if not checked:
                break
            q.click(AUTOSWAP_CHK, wait_ms=900, note=f'questflow 角色 {r} 取消自動轉換戰寵（第 {k + 1}/{tries} 次）')
            checked = is_checked()
        return checked

    try:
        for sweep in (1, 2):                     # 第 1 輪逐人處理；第 2 輪整體重掃（只看 / 補關，不放過任何一個）
            still = []
            for r, nm in enumerate(ROLE_NAMES, 1):
                if turn_off(r, nm):
                    still.append(r)
                if sweep == 1:
                    log(f'角色 {r} 自動轉換戰寵：{"仍勾選" if r in still else "關"}')
            if not still:
                if sweep == 2:
                    log('5 人自動轉換戰寵重掃確認：全部關')
                break
            log(f'第 {sweep} 輪後仍勾選的角色：{still}' + ('，整體重掃一次' if sweep == 1 else ''))
        if still:
            raise q.Halt(q.EXIT_ASS, f'角色 {still} 自動轉換戰寵重試 3 次 + 重掃後仍取消不掉：停手（會把任務寵換掉）')
    finally:
        ass.close_panel()


def levels_at(keyword: str, slot: int, roles, fix_battle: bool = False) -> dict:
    """面板只開一次，依序點各角色的第 slot 格 → 讀名稱 + 中間下方「0轉N」→ {角色: 等級 or None}；
    名稱對不上 keyword 就當沒讀到（寧可不達標，不能誤判）"""
    open_pet_panel()
    out = {}
    try:
        for r in roles:
            q.click((PET_ROLE_X, PET_ROLE_Y[r - 1]), wait_ms=900, note=f'questflow 讀第 {slot} 格：角色 {r}')
            name, lvl = read_pet(slot - 1)
            if not name_match(name, keyword):
                log(f'角色 {r} 第 {slot} 格名稱讀到「{name}」，不是「{keyword}」→ 當作沒讀到')
                lvl = None
            elif fix_battle and not ensure_battle(slot - 1):    # 名稱對上才補出戰（猜謎三兄弟金布伊在第 5 格，使用者 2026-10-13）
                log(f'警告：角色 {r}「{keyword}」不是出戰狀態，按了出戰仍沒變')
            out[r] = lvl
    finally:
        close_pet_panel()
    return out


def ensure_battle_roles(slot: int, roles) -> dict:
    """面板開一次，逐個角色確認第 slot 格（0 起算）出戰，沒出戰就補 → {角色: 是否出戰}（出戰檢查不靠等級讀取，所以 2~5 號不會漏）"""
    open_pet_panel()
    out = {}
    try:
        for r in roles:
            q.click((PET_ROLE_X, PET_ROLE_Y[r - 1]), wait_ms=900, note=f'questflow 確認出戰：角色 {r}')
            out[r] = ensure_battle(slot)
            if not out[r]:
                log(f'警告：角色 {r} 第 {slot + 1} 格沒有出戰（空格 / 按了出戰仍沒變）')
    finally:
        close_pet_panel()
    return out


def train_pets_slot(keyword: str, target: int, opts: dict) -> None:
    """固定第 slot 格的任務寵（猜謎三兄弟金布衣在第 5 格）：先看角色 1，達標才逐個看角色 2~5（使用者 2026-10-12）。
    傳去 opts['spot']、第一次檢查等 opts['first_s'] 秒、之後每 opts['poll_s'] 秒；不設時間上限。"""
    slot, spot = opts['slot'], opts.get('spot', TRAIN_SPOT)
    first_s, poll_s = opts.get('first_s', TRAIN_POLL_S), opts.get('poll_s', TRAIN_POLL_NEXT_S)
    roles = [1, 2, 3, 4, 5]
    log(f'--- 練寵：「{keyword}」第 {slot} 格 → {target} 級（5 人），地點 {spot}，首次 {first_s} 秒、之後每 {poll_s} 秒 ---')
    lv0 = levels_at(keyword, slot, roles)
    if all(lv0.get(r) is not None and lv0[r] >= target for r in roles):
        log(f'「{keyword}」5 隻已是 {lv0}，不用再練')
        rest_quest_pets(keyword)
        return
    set_battle_all(keyword)
    autoswap_off()
    q.grind(spot)
    t0, first = q.clock(), True
    last = {}
    polls = 0
    while True:
        q.sleep(first_s if first else poll_s)
        first = False
        polls += 1
        if polls % 5 == 0:                            # 每 5 輪全員確認一次出戰（不明原因沒出戰就補；平常只讀角色 1）
            try:
                ensure_battle_roles(slot - 1, roles)
            except q.Halt:
                pass
        if q.state() == 'OTHER':
            q.sleep(5)
            if q.state() == 'OTHER':
                raise q.Halt(q.EXIT_HALT, '練寵中連續看到不認得的畫面（疑似驗證視窗）：停手')
        try:
            got = levels_at(keyword, slot, [1], fix_battle=True)
        except q.Halt:
            continue                                  # 戰鬥中開不了面板：下一輪再讀
        last.update(got)
        log(f'練寵進度（{int(q.clock() - t0)} 秒）：角色 1 = {got.get(1)}（目標 {target}）')
        if got.get(1) is None or got[1] < target:
            continue
        try:
            rest = levels_at(keyword, slot, roles[1:], fix_battle=True)   # 角色 1 達標 → 檢查角色 2~5
        except q.Halt:
            continue
        last.update(rest)
        log(f'角色 1 達標，檢查角色 2~5：{rest}')
        if all(last.get(r) is not None and last[r] >= target for r in roles):
            break
    q.set_ass(encounter=False)
    q.wait_battle_end()
    log(f'「{keyword}」5 隻都到 {target} 級，已關原地遇敵')
    rest_quest_pets(keyword)


def train_pets(keyword: str, target: int, opts: dict | None = None) -> None:
    if opts and opts.get('slot'):
        return train_pets_slot(keyword, target, opts)
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
            lv = levels(keyword, fix_battle=True)
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
    if name in NO_POTION_QUESTS:
        use_potion = False
    q.NAV_ADJUST = lambda: find_track_row(name, scroll=True, reveal=False) is not None   # 導覽沒反應 3 次後往下拉重新定位（使用者規則）
    q.TRACK_GUARD = (lambda: not track_row_is_dark(q.track_xy()[1])) if not name.startswith('漆黑') else None   # 點之前確認不是漆黑那一列
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
        accept_top(name, side=False, nth=0)      # 主線永遠取最上面那格（使用者 2026-10-14：待接取排最上、已完成沉到最下；用位置 nth 會選到四轉）
        row = find_track_row(name)
        for _ in range(2):                       # 剛接完追蹤欄常還沒更新（2026-10-15 333：接完馬上讀不到 → 誤去支線找 → 停手）
            if row is not None:
                break
            time.sleep(2)
            row = find_track_row(name, scroll=True, reveal=True)
    else:
        row = find_track_row(name, reveal=name in TRAIN_STEPS)
        for _ in range(2):                       # 剛吃完藥 / 面板還沒收好時 OCR 會暫時讀不到：先重讀，不要直接去任務詳情接（2026-10-12 四寶玉之謎）
            if row is not None:
                break
            time.sleep(2)
            row = find_track_row(name, scroll=False, reveal=False)
    fresh = False
    if row is None:
        try:
            fresh = accept_top(name, side=name not in ADULT and not stop_after_last_boss)    # 成人儀式、漆黑都在任務詳情「主線」分頁
        except q.Halt as h:
            # 正在解的任務（帳本 doing / paused）追蹤欄、任務詳情都找不到 → 多半是剛解完（2026-10-15 22222 夢德洞窟：
            # 起始步猜錯多做幾輪，最後一輪任務已完成 → 找不到就停手、看門狗重啟）。任務詳情判讀為「已完成」才記完成繼續，否則照停手
            if h.code != q.EXIT_NOQUEST or led.get('status') not in ('doing', 'paused') or stop_after_last_boss:
                raise
            st = detail_status(name, side=name not in ADULT)
            if st != '已完成':
                raise
            log(f'「{name}」追蹤欄、任務詳情都找不到，任務詳情判讀為已完成（帳本原本 {led.get("status")}）→ 記完成，接著做下一個')
            q.ledger_mark(name, 'done', 'questflow：解到一半後追蹤欄 / 任務詳情都找不到 → 判讀已完成')
            q.save_state({'quest': name, 'step': None, 'done': True, 'at': time.strftime('%F %T')})
            return
        if fresh:                                # 剛接：先記「做完第 0 步」，這次中途停手的話下次從第 1 步開始，不靠副標題 OCR 猜
            q.save_state({'quest': name, 'step': 0, 'at': time.strftime('%F %T')})
        # 回 False = 任務詳情顯示「進行中」/ 不是待接取 → 正在解的任務：追蹤欄往下拉找出來接著解（不重接、不重置）
        row = find_track_row(name, reveal=name in TRAIN_STEPS) if fresh else find_track_row(name, scroll=True, reveal=True)
        if row is None:
            raise q.Halt(q.EXIT_NOQUEST, f'接完任務後追蹤欄找不到「{name}」' if fresh else
                         f'「{name}」任務詳情是進行中，但追蹤欄找不到：停手（不按重置）')
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
    if STEP_REPEAT_FIRST.get(name) and steps and steps[0][0] == 1 and from_step in (None, 1):
        steps = [steps[0]] * STEP_REPEAT_FIRST[name] + list(steps)
    if to_step is not None:                      # 只做到第 to_step 步（卡坦的願望步 1 / 步 2 分兩次交）
        steps = [s for s in steps if s[0] <= to_step]
    if stop_after_last_boss:
        steps = [s for s in steps if s[0] <= last]
    log(f'「{disp}」追蹤欄第 {row} 條；起始步來源：{src or "預設（第 1 步）"}；要做 {len(steps)} 步：' + ' '.join(f'{st}:{k}' for st, k, _, _ in steps))
    t0 = q.clock()
    for j, (st, kind, desc, _) in enumerate(steps, 1):
        pausegate.wait(log)                      # 步與步之間的安全點：有暫停檔就停在這裡
        if st in TRAIN_STEPS.get(name, {}):
            kw, tgt, *_o = TRAIN_STEPS[name][st]
            opts = _o[0] if _o else None
            try:
                train_pets(kw, tgt, opts)
            except q.Halt as h:
                # 寵物要到這一步跟 NPC 對話時才領到（使用者 2026-10-12）：還沒有 → 先對話一次領取，再練，練完再對話交
                if h.code == q.EXIT_USAGE and '找不到' in h.msg:
                    log(f'還沒領到「{kw}」→ 先對話一次領取')
                    q.step_team(fight=False)
                    train_pets(kw, tgt, opts)
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
        if still is not None and not name.startswith('漆黑'):
            st = detail_status(name, side=name not in ADULT)
            log(f'追蹤欄仍有「{name}」→ 任務詳情狀態：{st}')
            if st == '已完成':                   # 以任務詳情為準（排在最下 + 已完成標籤）；追蹤欄殘留只是顯示延遲
                still = None
        if still is not None and _retry < 3 and steps:
            # 追蹤欄還看得到任務（使用者 2026-10-13 成人儀式：做完所列步驟仍殘留）→ 不直接停手：還有後面的步驟就接著做，
            # 沒有後面的步驟就把最後一步再做一次（再點追蹤欄 / 再對話），最多 3 輪；仍殘留才走下面的 paused + 停手
            later = [s[0] for s in sorted(all_steps) if s[0] > steps[-1][0]]
            nxt = later[0] if later else steps[-1][0]
            try:                                 # 追蹤欄副標題比對出「更前面的步驟」（上一個 BOSS 沒算贏，例：四寶玉之謎步 4 沒過卻去交步 5）→ 退回那一步重做
                _, gsteps = q.plan_steps(key, None)
                g = gsteps[0][0] if gsteps else None
                if g is not None and g < steps[-1][0]:
                    log(f'追蹤欄副標題對應第 {g} 步（比剛做的第 {steps[-1][0]} 步前面）→ 退回第 {g} 步重做')
                    nxt = g
            except Exception as e:
                log(f'副標題比對步驟失敗（{e}），沿用 {nxt}')
            log(f'殘留 → 自己從第 {nxt} 步再做一次（第 {_retry + 1}/3 輪）')
            time.sleep(3)
            return run_quest(name, key=key, stop_after_last_boss=stop_after_last_boss, use_potion=use_potion,
                             dry=dry, from_step=nxt, to_step=to_step, _retry=_retry + 1)
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


INFO_BTN, INFO_X, INFO_LV = (75, 45), (866, 65), (140, 410, 275, 24)   # HUD 左上頭像 → 人物資訊面板 / 右上 ✕ / 面板左下綠字「N轉M級(ID)」（960×508）


def trans_from_info_panel():
    """從人物資訊面板讀目前轉數（綠字「N轉M級」字大，實測很準；HUD 的 stat 會把 1 轉讀成 0，2026-10-13）。
    開面板後偵測 ✕ 紅圓有出現才讀；沒開成功 → ESC 復原再重新點，最多 3 次。讀不到回 None。"""
    def opened() -> bool:
        c = q.px([INFO_X])
        return bool(c) and c[0][0] > 170 and c[0][1] < 120 and c[0][2] < 110

    ok = False
    for _ in range(3):
        q.click(INFO_BTN, wait_ms=1500, note='questflow 開人物資訊（讀轉數）')
        if opened():
            ok = True
            break
        q.key('{ESC}')
        q.sleep(0.9)
    if not ok:
        return None
    try:
        votes = {}
        for opts in (('-Zooms', '3,4'), ('-Zooms', '2,3', '-Dark', '200')):
            for t in q.uk().ocr(INFO_LV, *opts):
                m = re.search(r'(\d)\s*轉\s*\d{1,3}\s*級', str(t))
                if m:
                    votes[int(m.group(1))] = votes.get(int(m.group(1)), 0) + 1
        return max(votes.items(), key=lambda kv: kv[1])[0] if votes else None
    finally:
        q.click(INFO_X, wait_ms=800, note='questflow 關人物資訊')


def current_trans() -> int:
    n = trans_from_info_panel()
    if n is not None:
        return n
    import walk                                   # 保底：HUD stat（會把 1 轉讀成 0，只在面板讀不到時才用）
    s = walk.stat()
    m = re.match(r'(\d+)轉', str(s.get('level') or ''))
    if not m:
        raise q.Halt(q.EXIT_USAGE, f'讀不到轉生數（人物資訊面板與 HUD 都讀不到，HUD level={s.get("level")!r}），請用 --trans 指定')
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
    ap.add_argument('--no-dark-heal', action='store_true', help='不要在第一次漆黑任務前回醫院補血（預設會補一次，見 HEAL_BEFORE_DARK）')
    ap.add_argument('--no-potion', action='store_true', help='不管龍王的守護（不領、不吃）')
    ap.add_argument('--trans', type=int, help='轉生數（決定漆黑洞窟是第幾轉；預設讀 HUD）')
    ap.add_argument('--skip-bag', action='store_true', help='跳過整理背包階段')
    ap.add_argument('--from-step', type=int, help='搭配 --only：該任務從第幾步開始（不用 OCR 猜）')
    ap.add_argument('--ledger', action='store_true', help='只列出這個客戶端的帳本（各任務狀態）後結束')
    ap.add_argument('--dark-gate', action='store_true', help='只做漆黑洞窟步 5「通過守護人」（跟守門人講話領守護獸；轉生前要做，之後追蹤欄變成覲見精靈王）')
    ap.add_argument('--solo', action='store_true', help='單人模式（搭配 --dark-gate）：不組隊，目前這個角色自己去跟守門人講話；5 人要各跑一次（gatesolo1920）')
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
        if not a.dry and a.solo:
            # 單人模式（使用者 2026-10-13：守門人要 5 個角色各自單人去講才領得到守護獸）：不組隊、自動逃跑開 / 自動戰鬥關
            q.TRUST_TEAM = True
            q.set_ass(flee=True, auto=False)
            log('單人模式：不組隊、自動逃跑開；不做支線快照')
        elif not a.dry:
            if not q.team_ok():
                q.form_team()
            q.require_team()
            q.set_ass(flee=False, auto=True)
            q.TRUST_TEAM = True
            log('開頭驗證完成：5 人隊 + 自動戰鬥開 / 自動逃跑關；之後不再逐步驗證')
            try:
                snap = side_snapshot()
                log(f'任務詳情支線第一頁：進行中 {snap["active"]}；待接取 {snap["pending"]}；推定已完成 {snap["done"]}')
                sync_ledger_with_game(snap)
                presume_adult_done(snap)
                _tr = a.trans if a.trans is not None else (0 if a.dry else current_trans())
                _dk = dark_cave_name(_tr)
                if _dk:
                    presume_dark_progress(_dk[0])
            except q.Halt:
                raise
            except Exception as e:
                log(f'支線快照失敗（{e}），沿用帳本')
        trans = a.trans if a.trans is not None else (0 if a.dry else current_trans())
        dark = dark_cave_name(trans)
        if a.dark_gate:
            if not dark:
                raise q.Halt(q.EXIT_USAGE, '5 轉以上沒有漆黑洞窟可做')
            log(f'=== {dark[0]} 步 5 守門人（領守護獸；轉生前）===')
            # 帳本是以帳號為單位：questflow 解到打完機暴就把這個任務標 done（步 5 守門人是故意留到轉生前），
            # 這裡不先改回 doing，run_quest 會看到「帳本已完成」直接跳過 → 沒講話、追蹤欄還是「通過守護人」→ 轉生階段停手
            # （2026-10-14 11111 第 2 輪）。單人版每個角色都要重講一次，原因相同。
            q.ledger_mark(dark[0], 'doing', 'gate solo' if a.solo else 'gate')
            run_quest(dark[0], key=str(dark[1]), use_potion=use_potion, from_step=5, to_step=5)
            return q.EXIT_OK

        ran = 0
        plan = [(n, n, False) for n in ADULT + FOUR_CAVES]
        if dark:
            plan.append((dark[0], str(dark[1]), True))
        plan += [(n, n, False) for n in HERO_ISLAND + GROUP_A] + [('__BAG__', None, False)] + [(n, n, False) for n in GROUP_B] + [('__BAG2__', None, False)]
        if only:                                  # 預設不做、點名才做的任務（猜謎三兄弟）
            plan += [(n, n, False) for n in RIDDLE if n in only]

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
            if only and name.startswith('__BAG') and not bag_in_only(name, only):
                # --only 只做部分任務（例：一條龍 adult 階段 --only 成人儀式）時，整理背包只在它前面那組任務有被點名才做；
                # 不然會在成人儀式後就跑掉並標 done，quests 階段解完強盜 / 彌生後反而「帳本已完成，跳過」
                # （2026-10-15 22222 第 2 輪：08:55 / 08:57 兩次整理背包都在成人儀式後跑掉）
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
            if name in ADULT and not a.dry and q.ledger_load().get(q.CLIENT, {}).get(name, {}).get('status') != 'done':
                log('成人儀式開始前：檢查 5 人外掛「自動轉換戰寵」要是不打勾（打勾的就取消）')
                autoswap_off()                   # 使用者 2026-10-13：解成人儀式前先確認自動轉換戰寵沒打勾
            if a.limit and ran >= a.limit:
                log(f'已做滿 --limit {a.limit} 個任務，停止')
                break
            was_done = q.ledger_load().get(q.CLIENT, {}).get(name, {}).get('status') == 'done'
            heal_label = f'第一次漆黑前補血（{name}）'
            if (stop and HEAL_BEFORE_DARK and not a.no_dark_heal and not a.dry and not was_done
                    and q.ledger_load().get(q.CLIENT, {}).get(heal_label, {}).get('status') != 'done'):
                log('=== 第一次漆黑任務前：先回醫院補血一次 ===')
                try:
                    import heal
                    heal.heal_trip('波拉島', no_return=True)     # 補完停在醫院，之後由任務傳送 / 導航去漆黑
                    q.ledger_mark(heal_label, 'done', 'questflow：漆黑前補血')
                except Exception as e:                     # 補血失敗不停手（只是少補一次血）
                    log(f'漆黑前補血失敗（{e}）→ 略過，照常接任務')
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
        notifyhalt.alert(f'questflow 退出碼 {h.code} {h.msg}'[:80])
        return h.code
    except Exception as e:                       # 腳本自己的錯：留 traceback + 畫面，方便事後修
        import traceback
        log('腳本例外：' + ''.join(traceback.format_exception(e)).strip())
        mark_doing_paused(f'腳本例外：{e}')
        failshot.shot('questflow', f'腳本例外：{e}')
        notifyhalt.alert(f'questflow 腳本例外 {e}'[:80])
        return 99


if __name__ == '__main__':
    sys.exit(main())
