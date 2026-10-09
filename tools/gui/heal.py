#!/usr/bin/env python3
"""回村補血：取消原地遇敵 → 傳送薩姆吉爾 → 走進醫院 → 小護士「恢復氣血」→ 傳送回練功點 → 開原地遇敵。

用法（專案根目錄）：
  uv run --no-project python tools/gui/heal.py                 # 現在就回村補血，再回波拉島（約 21～24 秒；HEAL_DEBUG=1 印出每個 seq 的結果）
  uv run --no-project python tools/gui/heal.py --spot 波拉島2   # 回到別的練功點（見 SPOTS）
  uv run --no-project python tools/gui/heal.py --watch         # 常駐：每 15 秒看 HUD 血條，隊長血 / 魔太低就自動補
  uv run --no-project python tools/gui/heal.py --watch --hp 40 --mp 20 --every 15 --confirm 2 [--verbose] [--for 300]

只透過 gui.ps1（經 walk.gui / winenv.py 直接呼叫 powershell.exe；背景點擊 / 截圖）與 stat.ps1（OCR + 血條像素讀 HUD）操作，不碰遊戲記憶體。
走路、座標換算、OCR 讀座標、引子點擊、點 NPC 都用 tools/gui/walk.py（常數只在那裡定義）。
座標以最大化 2880×1659（截圖 1440×830）為準；流程與座標的實測紀錄見 notes/leveling.md。
"""
import argparse
import sys
import time

import layout
from walk import LAYOUT, PRIMER, gui, log, npc_screen, npc_steps, safe, screen, stat, wait_pos, walk_path, step_to

# 練級傳送分頁的目的地：名稱 → (截圖座標 x, y, 抵達地圖 ID)；見 .claude/skills/psa-game-ui/ui/transfer.md
SPOTS = {
    '柯奧4F龜洞': (859, 356, 11004),
    '波拉島': (1100, 231, 500),
    '波拉島2': (1165, 326, 502),
    '地雷區': (1165, 400, 60049),
    '地雷區2': (1165, 468, 60050),
    '海主人隧道': (862, 656, 31401),
}
SPOT_XY = {500: (212, 344), 31401: (91, 29)}   # 練級傳送抵達點（31401 於 2026-10-09 實測兩次）
TELEPORT_BTN = (1340, 65)            # 主畫面右上圓形傳送鈕
TAB_TOWN, TAB_LEVEL = (259, 196), (259, 314)
SAMUGIL = (750, 507)                 # 尼斯大陸分頁的「薩姆吉爾」→ 1000:92,99
VILLAGE, HOSPITAL = 1000, 1005
VILLAGE_START = (92, 99)             # 城鎮傳送抵達點
# 92,99 → 醫院入口 81,66 的快速路線（每段都是相對上一點的格數，遊戲會自己繞開障礙）：
# 先往左下離開傳送點石台（x88～98 y95～100 是障礙），再分 4 段往上；中間有雕像（x78～83, y74～79）從右邊過。
# 每段點擊都控制在主畫面中央（x ≥ 420），避開左邊任務 / 組隊面板與「詳情」「<」鈕（x 75～395）。2026-10-09 實測。
VILLAGE_FAST = [(87, 96), (86, 88), (84, 81), (83, 73), (81, 66)]
# 沒進醫院時 walk_path 會用 maps.bin 通行格從目前位置重新找路、慢速逐段走（walk.py）
HOSPITAL_SPOT = (23, 62)             # 站這裡，小護士在面板右邊點得到（入口 25,65 時她在左側面板底下）
NURSE = (20, 57)                     # 小護士所在格（點她身體的高度差 walk.NPC_DY）
HEAL_BUTTON = (948, 460)             # 對話框「恢復氣血」
ENCOUNTER = (1365, 660)              # 主畫面「遇敵 / 取消遇敵」
# ---- gui.sh waitpix 用的畫面特徵（截圖座標,r,g,b；多點用 / 連接，! = 不是這個顏色）。2026-10-09 實測 ----
# 這些取代原本的固定等待：面板 / 對話框一出現就點下一步。實測出現時間都在 50～150 毫秒內（含截圖本身）。
SIG_PANEL = '1290,97,197,73,49'      # 傳送面板右上紅色 ✕
SIG_TAB = {TAB_TOWN: '185,175,243,173,63', TAB_LEVEL: '185,293,243,175,64'}   # 分頁選中時的橘色
# 主畫面 HUD 在（傳送 Loading 畫面、面板、NPC 對話框都會蓋掉）：外掛鈕 ASS 紅字、寵物框（設置鈕的字會變，不能用）
SIG_HUD = '1300,745,254,0,0/520,57,208,167,118'
# 小護士對話框：兩顆按鈕米色 + 對話框棕底（主畫面沙地 245,225,171 很像米色，所以一定要配棕底一起判斷）
SIG_DIALOG = '948,445,229,197,155/1220,445,229,197,155/1360,300,107,70,44/1100,350,107,70,44'
SIG_ENC_ON = '1380,630,129,6,0/1360,632,179,12,0'          # 「取消遇敵」紅龍頭（容差 50）
SIG_ENC_OFF = '1380,630,129,6,0!/1360,632,179,12,0!'
# 戰鬥中（快速戰鬥沒有戰鬥畫面）角色頭上有綠色「VS」牌；這時傳送會被擋「非正常狀態不能傳送」
# 傳送抵達點的固定景物（HUD 回來後再比對，對得上就不用 OCR 讀座標，省約 1 秒；對不上才 OCR）
SIG_ARRIVE = {
    VILLAGE: '770,330,255,255,86/850,380,195,200,196/530,400,219,223,218',   # 1000:92,99 儲存點金色圖騰旁
    500: '820,470,239,211,133/1300,600,125,204,92/1000,350,245,224,170/1150,700,124,203,93',  # 500:212,344 沙地、草地（警示牌會被隊友擋，不用）
}
# 剛走進醫院（1005:25,65）：右邊一片黑 + 左上地板。走出口也有 Loading（約 0.3 秒），所以要配 HUD 一起判斷
SIG_HOSPITAL = '1300,500,0,0,0/1200,650,0,0,0/1100,300,0,0,0/900,250,170,180,171'
SIG_NO_BATTLE = '706,295,122,227,0!'  # 容差 40；騎寵不同、頭頂高度變了要重量
BARS = [(258, 56), (258, 90)]        # 血條 / 魔條最右端（滿的時候是紅 / 藍）
# 「取消遇敵」（原地遇敵開著）圖示是紅色龍頭；關著是灰色圖示
ENC_PROBES = [(1365, 645), (1380, 630), (1360, 632), (1388, 640)]
# 引子點擊 PRIMER、角色螢幕座標、每格位移、每次最多格數、左側面板限制：見 walk.py

# ======== 1920×1017 版面（截圖 960×508）：2026-10-09 在 31401 → 薩姆吉爾 → 醫院 → 31401 實際走一趟量的 ========
# 上面 2880×1659 的常數不動；layout.py 判斷是 1920×1017 時改用這組。
if LAYOUT == '1920x1017':
    SPOTS = {
        '柯奧4F龜洞': (567, 216, 11004),
        '波拉島': (718, 138, 500),
        '波拉島2': (759, 198, 502),
        '地雷區': (759, 245, 60049),
        '地雷區2': (759, 288, 60050),
        '海主人隧道': (571, 405, 31401),      # 實測
    }
    TELEPORT_BTN = (905, 38)
    TAB_TOWN, TAB_LEVEL = (192, 118), (192, 190)
    SAMUGIL = (500, 312)
    HEAL_BUTTON = (650, 283)
    ENCOUNTER = (913, 400)
    SIG_PANEL = '832,48,167,52,28/835,51,171,52,33'        # 面板右上 ✕ 的紅色筆畫
    SIG_TAB = {TAB_TOWN: '150,118,249,175,68', TAB_LEVEL: '150,190,251,177,70'}
    # HUD：外掛鈕 ASS 紅字（NPC 對話框開著時整個 UI 隱藏 → 0,0,0）。左上寵物框旁邊會透出場景，不能當特徵
    SIG_HUD = '872,455,255,0,0/876,455,255,0,0'
    SIG_DIALOG = '620,272,229,197,159/860,272,229,197,155/900,205,107,70,44/700,215,107,70,44'
    SIG_ENC_ON = '910,386,201,12,0/920,390,177,8,0'
    SIG_ENC_OFF = '910,386,201,12,0!/920,390,177,8,0!'
    SIG_ARRIVE = {VILLAGE: '640,150,153,163,86/600,300,213,219,211/400,110,123,201,96'}   # 1000:92,99（其他抵達點用 OCR）
    SIG_HOSPITAL = '800,250,0,0,0/700,330,0,0,0/650,420,0,0,0/480,110,103,129,135'
    SIG_NO_BATTLE = '481,168,177,244,10!'                  # 頭上 VS 牌綠框
    BARS = [(164, 36), (164, 57)]
    ENC_PROBES = [(910, 386), (920, 390), (905, 394), (925, 398)]


def pixels(points: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in points))
    return [tuple(int(v) for v in c.split(',')) for c in out.split()]


def encounter_on() -> bool:
    reds = sum(r > 120 and g < 80 and b < 80 for r, g, b in pixels(ENC_PROBES))
    return reds >= 2


def encounter_steps(on: bool) -> str:
    """seq：先看一次，已經是目標狀態就不點（ifnok）；不是就點引子 + 遇敵鈕，再等圖示變色"""
    sig = SIG_ENC_ON if on else SIG_ENC_OFF
    return (f'waitpix 0 {sig} 50; ifnok {PRIMER.replace("; wait", "; ifnok wait")}; '
            f'ifnok click {ENCOUNTER[0]} {ENCOUNTER[1]}; ifnok waitpix 1500 {sig} 50')


def encounter_done(out: str) -> bool:
    """encounter_steps 的輸出：前兩個 waitpix 結果裡最後一個是 ok 就成功"""
    res = [l.split()[0] for l in out.splitlines() if l.startswith(('ok', 'timeout'))][:2]
    return bool(res) and res[-1] == 'ok'


def set_encounter(on: bool) -> None:
    """點「遇敵」並輪詢圖示顏色，變色就結束（實測 < 0.1 秒）"""
    for _ in range(3):
        if encounter_done(gui('seq', encounter_steps(on))):
            log(f'原地遇敵：{"開" if on else "關"}')
            return
    raise RuntimeError('切換原地遇敵失敗')


LAST_OUT = ''                        # 最近一次傳送 seq 的輸出（含 pre 動作的結果）


def teleport_steps(tab: tuple[int, int], dest: tuple[int, int]) -> str:
    """傳送的 seq：開面板 → 等 ✕ 出現 → 切分頁 → 等分頁變橘 → 點目的地 → 等 Loading 結束、HUD 回來。
    實測：面板 / 分頁 50～150 毫秒；Loading 約 1.2～1.4 秒。"""
    # 面板沒開（例：換地圖後第一下被吃掉）就跳過後面的點擊（ifok），免得點穿面板走到別處
    return (f'{PRIMER}; click {TELEPORT_BTN[0]} {TELEPORT_BTN[1]}; waitpix 1500 {SIG_PANEL}; ifok click {tab[0]} {tab[1]}; '
            f'ifok waitpix 800 {SIG_TAB[tab]}; ifok click {dest[0]} {dest[1]}; ifok wait 300; ifok waitpix 6000 {SIG_HUD}')


def teleport(tab: tuple[int, int], dest: tuple[int, int], want_map: int, name: str,
             pre: str = '', want_xy: tuple[int, int] | None = None) -> tuple[int, int, int]:
    """傳送；戰鬥中會被擋（「非正常狀態不能傳送」），等一下再試。成功時面板自己關。pre = 同一個 seq 前面先做的動作。"""
    for i in range(10):
        steps = (pre + '; ' if pre and i == 0 else '') + teleport_steps(tab, dest)
        if want_map in SIG_ARRIVE:
            steps += f'; ifok waitpix 1000 {SIG_ARRIVE[want_map]} 25'
        out = gui('seq', steps)
        global LAST_OUT
        LAST_OUT = out
        if want_map in SIG_ARRIVE and out.splitlines()[-1].startswith('ok'):
            p = (want_map, *(want_xy or (0, 0)))
            log(f'傳送到 {name}（畫面比對）')
            return p
        p = wait_pos(4, want_map, 0.3)
        if p and p[0] == want_map and (want_xy is None or p[1:] == want_xy):
            log(f'傳送到 {name} {p[0]}:{p[1]},{p[2]}')
            return p
        gui('key', '{ESC}')            # 被擋時面板還開著；在主畫面按 ESC 沒有作用
        log(f'傳送 {name} 沒成功（{p}），可能在戰鬥中，等 2 秒再試')
        time.sleep(2)
    raise RuntimeError(f'傳送 {name} 失敗')


def walk_village() -> tuple[int, int, int]:
    """1000:92,99 → 醫院 1005。walk.walk_path 快速模式：一個 seq 連點 5 段（每段 waitstill），
    最後一段輪詢「醫院畫面 + HUD」出現就結束不 OCR；沒進醫院時 walk_path 會用通行格重新找路、慢速逐段走。"""
    return walk_path(VILLAGE, VILLAGE_FAST, start=VILLAGE_START, exit_map=HOSPITAL,
                     end_sig=f'{SIG_HUD}/{SIG_HOSPITAL}', arrive=(HOSPITAL, 25, 65))


def talk_nurse(p: tuple[int, int, int]) -> None:
    """站到小護士點得到的位置 → 點她 → 等對話框。入口 25,65 時她在左邊面板底下，要先走 3 格到 23,62。"""
    hx, hy = HOSPITAL_SPOT
    dx, dy = hx - p[1], hy - p[2]
    walk = f'click {" ".join(map(str, screen(dx, dy)))}; waitstill 2500; ' if dx or dy else ''
    # 走完要停穩再點（走路中點她會變成點到地面）：等鏡頭停（3 格實測約 0.9 秒）；沒開再重點。
    # 對話框一出現（實測點下去 0.1～0.3 秒）就在同一個 seq 裡按「恢復氣血」。
    then = f'click {HEAL_BUTTON[0]} {HEAL_BUTTON[1]}'
    out = gui('seq', f'{PRIMER}; {walk}' + npc_steps(NURSE, HOSPITAL_SPOT, SIG_DIALOG, then))
    for i in range(4):
        if 'ok' in out.split():
            return
        # 沒開：照目前座標重算她的位置再點
        p = wait_pos(3, HOSPITAL)
        if not p or p[0] != HOSPITAL:
            raise RuntimeError(f'在醫院裡讀不到座標：{p}')
        at = (p[1], p[2])
        if not safe(*npc_screen(NURSE, at)):
            p = step_to(HOSPITAL, hx, hy)      # 醫院沒有通行格資料，直接點地面走
            at = HOSPITAL_SPOT
        log(f'小護士對話框沒開，在 {at[0]},{at[1]} 重點她 {npc_screen(NURSE, at)}')
        out = gui('seq', npc_steps(NURSE, at, SIG_DIALOG, then))
    raise RuntimeError('點不開小護士對話框')


def heal_trip(spot: str) -> None:
    sx, sy, spot_map = SPOTS[spot]
    t0 = last = time.time()
    seg = []

    def lap(name: str) -> None:
        nonlocal last
        now = time.time()
        seg.append(f'{name} {now - last:.1f}')
        last = now

    # 關遇敵 → 等 VS 牌消失（關遇敵不會中止正在打的那場，一場約 2～5 秒；不等的話傳送會被擋）→ 傳送，同一個 seq
    out = gui('seq', encounter_steps(False) + f'; waitpix 20000 {SIG_NO_BATTLE} 40')
    if not encounter_done(out):
        set_encounter(False)
    else:
        log('原地遇敵：關')
    lap('關遇敵 + 等戰鬥結束')
    teleport(TAB_TOWN, SAMUGIL, VILLAGE, '薩姆吉爾', want_xy=VILLAGE_START)
    lap('傳送村子')
    p = walk_village()
    log(f'進醫院 {p[0]}:{p[1]},{p[2]}')
    lap('村子走路')
    talk_nurse(p)              # 走 3 格 + 點小護士 + 對話框一出現就按「恢復氣血」
    lap('醫院補血')
    # 按完不等提示動畫：等 HUD 回來（對話框自己關）→ 讀血 / 魔條最右端的顏色 → 直接傳送，同一個 seq
    teleport(TAB_LEVEL, (sx, sy), spot_map, spot, want_xy=SPOT_XY.get(spot_map),
             pre=f'waitpix 1500 {SIG_HUD}; pixel {"/".join(f"{x},{y}" for x, y in BARS)}')
    out = LAST_OUT
    full = False
    for line in out.splitlines():
        cs = line.split()
        if len(cs) == 2 and all(c.count(',') == 2 for c in cs):
            (hr, hg, hb), (mr, mg, mb) = (tuple(int(v) for v in c.split(',')) for c in cs)
            full = hr > 150 and hr - hg > 60 and mb > 150 and mb - mr > 60
    log('血 / 魔已補滿' if full else f'警告：血 / 魔條看起來沒補滿（{out!r}），請檢查畫面')
    lap('確認 + 傳送回去')
    set_encounter(True)
    lap('開遇敵')
    log(f'完成，耗時 {time.time() - t0:.1f} 秒（{"、".join(seg)}）')


def low(s: dict, hp: int, mp: int) -> bool | None:
    """看血條 / 魔條比例（stat.ps1 的 hpPct / mpPct）。讀不到（戰鬥畫面、對話框蓋住 HUD）回 None = 不判斷。
    不用 OCR 的 hp / mp 數字：個位數（例 HP 1）OCR 會回 null，以前把 null 當低血，剛補滿也會誤判。"""
    if not s.get('ok') or s.get('hpPct') is None or s.get('mpPct') is None:
        return None
    return s['hpPct'] < hp or s['mpPct'] < mp


def main() -> int:
    ap = argparse.ArgumentParser(description='回村補血再回練功點')
    ap.add_argument('--spot', default='波拉島', choices=SPOTS)
    ap.add_argument('--watch', action='store_true', help='常駐監看，血 / 魔太低就自動補')
    # 波拉島實測掉血很快：滿血到 20% 約 70 秒、25% → 1 只要一場，所以門檻抓高、間隔抓短
    ap.add_argument('--hp', type=int, default=40, help='隊長血條低於這個百分比就回村（預設 40）')
    ap.add_argument('--mp', type=int, default=20, help='隊長魔條低於這個百分比就回村（預設 20）')
    ap.add_argument('--every', type=int, default=15, help='監看間隔秒數（預設 15）')
    ap.add_argument('--confirm', type=int, default=2, help='連續幾次讀到低值才回村（預設 2，間隔 3 秒）')
    ap.add_argument('--verbose', action='store_true', help='監看時每次都印出讀數')
    ap.add_argument('--for', dest='duration', type=int, default=0, help='監看幾秒後自己結束（測試用；不會在補血途中停）')
    a = ap.parse_args()
    # 傳送面板、醫院、遇敵鈕的座標與特徵色量過 2880×1659、1920×1017；別的版面會點錯，先擋下來
    if layout.current() not in layout.SUPPORTED:
        log(f"heal.py 不支援 {layout.current()} 版面（只量過 2880×1659、1920×1017），見 ui/layout-1920x1017.md")
        return 2
    if not a.watch:
        heal_trip(a.spot)
        return 0
    log(f'監看中：血條 < {a.hp}% 或魔條 < {a.mp}%（連續 {a.confirm} 次）就回村補血（Ctrl+C 結束）')
    end = time.time() + a.duration if a.duration else None
    while end is None or time.time() < end:
        hits = 0
        for i in range(a.confirm):
            s = stat()
            r = low(s, a.hp, a.mp)
            if a.verbose:
                log(f'HP {s.get("hp")} ({s.get("hpPct")}%) MP {s.get("mp")} ({s.get("mpPct")}%) → {r}')
            if not r:
                break          # 不低或讀不到：這輪不算
            hits += 1
            if hits < a.confirm:
                time.sleep(3)
        if hits >= a.confirm:
            log(f'血 / 魔太低（HP {s.get("hp")} {s.get("hpPct")}%，MP {s.get("mp")} {s.get("mpPct")}%），回村補血')
            try:
                heal_trip(a.spot)
            except RuntimeError as e:
                log(f'補血流程失敗：{e}；停止監看，請人工處理')
                return 1
        time.sleep(a.every)
    log('監看時間到，結束')
    return 0


if __name__ == '__main__':
    sys.exit(main())
