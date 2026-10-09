#!/usr/bin/env python3
"""通用走路工具：點地面走到某地圖座標（OCR 讀座標 + 每次最多 N 格 + waitstill + 卡住偵測），可用 maps.bin 通行格自動找路。

用法（專案根目錄）：
  uv run --no-project python tools/gui/walk.py 1000 81 66                  # 走到 1000:81,66（有通行格資料就自動找路）
  uv run --no-project python tools/gui/walk.py 1000 81 66 --exit 1005      # 目標是出口：走到就換地圖，抵達 1005 算成功
  uv run --no-project python tools/gui/walk.py --path "1000:86,88 84,81 83,73 81,66" [--exit 1005]   # 照手動 waypoint 走
  uv run --no-project python tools/gui/walk.py --plan 1000 81 66 [--from 92,99]   # 只印自動找路的 waypoint，不動
  其他選項：--slow（每段都 OCR 驗證，慢但穩）、--no-auto（不用通行格，直線分段讓遊戲自己繞）、--from X,Y（不 OCR，假設起點）
  WALK_DEBUG=1：印出每次 gui.ps1 的輸出。

給其他腳本 import（heal.py 就是這樣用）：
  import walk
  walk.walk_to(1000, 81, 66, exit_map=1005)        # → (地圖, x, y)
  walk.walk_path(1000, [(87, 96), (86, 88)], start=(92, 99))
  walk.plan(1000, (92, 99), (81, 66))               # → waypoint 清單；沒資料回 None
  walk.npc_steps((20, 57), at=(23, 62), then='click 948 460')   # 點 NPC 開對話的 seq 片段
  walk.prime()                                      # 換地圖後的引子點擊

只透過 gui.ps1（經 winenv.py 直接呼叫 powershell.exe；背景點擊 / 截圖）與 stat.ps1（OCR 讀 HUD 座標）操作，不碰遊戲記憶體。
通行格讀取重用 tools/query/psa.py（load_maps / grid），格子值 1 = 可走。
"""
import argparse
import heapq
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'query'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, 'reconfigure'):   # Windows 原生 Python 預設 cp950，中文會變亂碼
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import winenv  # noqa: E402  平台判斷（WSL / Windows 原生）與路徑換算
import layout  # noqa: E402  依遊戲視窗大小選座標（2880×1659 / 1920×1017）
import psa  # noqa: E402  知識庫查詢工具：load_maps() / grid(map_id) / T('Npc')

# ======== 走路常數（2026-10-09 實測；遊戲最大化客戶區 2880×1659 → 截圖 1440×830 為準）========
# 文件（.claude/skills/psa-game-ui/ui/home.md「走路」）只寫原則，數字以這裡為準。
ME = (715, 410)              # 角色腳下的截圖座標（鏡頭跟著角色，角色固定在這附近）
TILE_X = (32, -23)           # 地圖 x+1 的螢幕位移（往右上）
TILE_Y = (32, 23)            # 地圖 y+1 的螢幕位移（往右下）
MAX_TILES = 10               # 點一次地面最多走幾格（實測 10 格 OK；遊戲會自己繞障礙）
SEC_PER_TILE = 0.17          # 每格約 0.15～0.17 秒（7～8 格 waitstill 1.25～1.35 秒，含起步與判停）
PANEL_RIGHT = 400            # 左側任務 / 組隊面板與「詳情」「<」鈕在 x 75～395，點擊要在這右邊 → 往左一次最多約 9 格
# 點地面時不能點到的 UI 範圍（截圖座標 x1, y1, x2, y2）。點到 UI 會沒反應（waitstill 回 nomove）或開面板。
# 實測：點 459,134（寵物 HP 框下緣）沒反應，所以上緣抓 150。
UI_RECTS = [
    (0, 0, PANEL_RIGHT, 830),        # 左側：角色 HUD、任務 / 組隊面板、詳情、<、喇叭列
    (0, 0, 1440, 150),               # 上排：HP / 寵物框、商城…LuckyCard、地圖名、傳送鈕
    (0, 610, 530, 830),              # 左下聊天區（x 65～525）
    (0, 700, 1440, 830),             # 底部按鈕列（切換…外掛、<）
    (1290, 150, 1440, 225),          # 右上小地圖圖示
    (1290, 610, 1440, 830),          # 右下遇敵鈕
    (1420, 0, 1440, 830),            # 右邊界
]
# 換地圖（傳送、走出口）後第一下左鍵會被遊戲吃掉（等 4 秒再點也一樣；右鍵當引子無效）→ 先點右上狀態列空白處當引子。
# 狀態正常時點它也沒有作用，所以每次開始走都先點一下。
PRIMER_XY = (1215, 18)
PRIMER = f'click {PRIMER_XY[0]} {PRIMER_XY[1]}; wait 100'
WAITSTILL_MS = 4000          # 每段等鏡頭停下的逾時（10 格約 1.7 秒）。走路途中點下一段會點偏，一定要等鏡頭停
NPC_DY = -29                 # 點 NPC 身體：比腳下那格的螢幕座標高約 29px（醫院小護士實測）
# 一般 NPC 對話框的棕底（小護士對話框實測；別的 NPC 對話框版面不同時要自己給 sig）
SIG_NPC_DIALOG = '1360,300,107,70,44/1100,350,107,70,44'

# ======== 1920×1017 版面（1920×1080 螢幕最大化 → 截圖 960×508）========
# 上面 2880×1659 的常數不動；遊戲視窗是 1920×1017 時（layout.py 判斷）改用這組。
# 2026-10-09 實測（31401 奇努伊的海底通路）：UI 依高度縮放（×0.613），但地圖畫面依寬度縮放（×0.667）。
LAYOUT = layout.resolve()
if LAYOUT == '1920x1017':
    ME = (477, 251)                  # 角色腳下（截圖看約 480,250；3 / 5 / 8 格點擊都落在正確格子）
    TILE_X = (21.2, -15.2)           # 實測：走 3 / 5 格前後截圖比對，畫面平移 42.4×30.4 px / 格（= 32,23 × 0.667）
    TILE_Y = (21.2, 15.2)
    NPC_DY = -19                     # 實測：醫院小護士（-29 × 0.667）
    PANEL_RIGHT = 250                # 左側任務 / 組隊面板、「詳情」「<」到 x≈248
    UI_RECTS = [
        (0, 0, PANEL_RIGHT, 508),    # 左側：角色 HUD、EXP、任務 / 組隊面板、詳情、<
        (0, 0, 960, 92),             # 上排：HP / 寵物框（含下方漩渦鈕到 y≈82）、商城…LuckyCard、地圖名、傳送鈕
        (0, 330, 335, 508),          # 左下：喇叭 / 信封 / 鈴鐺、聊天區、表情…發送
        (0, 430, 960, 508),          # 底部按鈕列（切換…外掛、<）
        (870, 85, 960, 140),         # 右上小地圖圖示
        (870, 370, 960, 508),        # 右下遇敵鈕
        (950, 0, 960, 508),          # 右邊界
    ]
    PRIMER_XY = (822, 11)            # 右上狀態列（wifi / 時間那一列）；實測點了沒副作用，換地圖後當引子有效
    PRIMER = f'click {PRIMER_XY[0]} {PRIMER_XY[1]}; wait 100'
    SIG_NPC_DIALOG = '900,205,107,70,44/700,215,107,70,44'   # 對話框棕底（小護士實測；別的 NPC 版面不同時自己給 sig）


def log(msg: str) -> None:
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def gui(*args: str) -> str:
    """直接呼叫 powershell.exe -File gui.ps1（不經 bash）；WSL / Windows 原生都通"""
    r = winenv.run_ps('gui.ps1', *args)
    out = (r.stdout.strip() or r.stderr.strip())
    if os.environ.get('WALK_DEBUG') or os.environ.get('HEAL_DEBUG'):
        print('   ', args[0], '→', out.replace('\n', ' | '), flush=True)
    return out


def last_ok(out: str) -> bool:
    """seq 輸出的最後一行是 ok / still（waitpix / waitstill 成功）"""
    lines = out.splitlines()
    return bool(lines) and lines[-1].split()[0] in ('ok', 'still')


def prime() -> None:
    """換地圖後的引子點擊（之後的第一下左鍵才有效）"""
    gui('seq', PRIMER)


# ---------------- 座標換算 ----------------
def screen(dx: int, dy: int) -> tuple[int, int]:
    """相對角色 (dx, dy) 格的截圖座標（1920×1017 的每格位移不是整數，四捨五入）"""
    return (round(ME[0] + TILE_X[0] * dx + TILE_Y[0] * dy), round(ME[1] + TILE_X[1] * dx + TILE_Y[1] * dy))


def safe(sx: int, sy: int) -> bool:
    """點這個截圖座標不會點到 UI（面板、按鈕）"""
    return not any(x1 <= sx < x2 and y1 <= sy < y2 for x1, y1, x2, y2 in UI_RECTS)


def reachable(dx: int, dy: int, lim: int = MAX_TILES) -> bool:
    """這段位移能不能一次點完：格數 ≤ lim 且點擊位置不在 UI 上"""
    return max(abs(dx), abs(dy)) <= lim and safe(*screen(dx, dy))


def split(a: tuple[int, int], b: tuple[int, int], lim: int = MAX_TILES) -> list[tuple[int, int]]:
    """a → b 太遠（或點擊位置會落在 UI 上）時沿直線切成幾段；回傳不含 a、含 b 的點"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    k = max(abs(dx), abs(dy))
    for n in range(1, k + 1):
        pts = [(a[0] + round(dx * i / n), a[1] + round(dy * i / n)) for i in range(1, n + 1)]
        prev, ok = a, True
        for p in pts:
            ok = reachable(p[0] - prev[0], p[1] - prev[1], lim)
            if not ok:
                break
            prev = p
        if ok:
            return pts
    return [b]


# ---------------- 讀座標（stat.ps1 OCR，每次約 0.9 秒）----------------
def stat() -> dict:
    r = winenv.run_ps('stat.ps1')
    line = (r.stdout.strip().splitlines() or [''])[-1]
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {'ok': False, 'error': line or r.stderr.strip()}


def pos() -> tuple[int, int, int] | None:
    m = re.match(r'(\d+):(\d+),(\d+)', stat().get('pos') or '')
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def wait_pos(tries: int = 6, want_map: int | None = None, gap: float = 0.5) -> tuple[int, int, int] | None:
    """讀座標；讀不到（戰鬥中 / 讀取中）或還不在 want_map 時重試。HUD 座標比角色慢半拍，要在停下後讀"""
    p = None
    for i in range(tries):
        p = pos()
        if p and (want_map is None or p[0] == want_map):
            return p
        if i < tries - 1:
            time.sleep(gap)
    return p


# ---------------- 通行格自動找路（knowledge/data/maps.bin，經 psa.py 讀取）----------------
def _cells(map_id: int):
    g = psa.grid(map_id)
    if not g:
        return None
    w, h, c = g
    npcs = {(n.get('x'), n.get('y')) for n in psa.T('Npc') if n.get('map') == map_id}
    return w, h, c, npcs


def has_grid(map_id: int, start: tuple[int, int], goal: tuple[int, int]) -> bool:
    """maps.bin 有這張圖、起點終點都在範圍內、起點是可走格（例：醫院 1005 資料是 30×30，實際座標 25,65 超出 → 視為沒資料）"""
    cs = _cells(map_id)
    if not cs:
        return False
    w, h, c, _ = cs
    inb = lambda p: 0 <= p[0] < w and 0 <= p[1] < h
    return inb(start) and inb(goal) and c[start[1] * w + start[0]] == 1


WALL_COST = 1                # 找路時貼著障礙的格子多算的成本（maps.bin 與實際碰撞在障礙邊緣常有出入）
# 每走一格的成本 ≈ 點擊次數：往左（dx+dy < 0）被左側面板限制，往左上斜走 (-1,-1) 一次只能點 4 格、正左 / 正上 9 格，
# 其他方向 10 格。依此加權，路線會選點擊次數少的那邊繞（例：薩姆吉爾雕像從右邊過）。
STEP_COST = {(dx, dy): MAX_TILES / max(k for k in range(1, MAX_TILES + 1) if reachable(dx * k, dy * k))
             for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy}


def _near_wall(cs, x: int, y: int) -> bool:
    w, h, c, npcs = cs
    return any(not (0 <= x + i < w and 0 <= y + j < h) or c[(y + j) * w + x + i] != 1
               for i in (-1, 0, 1) for j in (-1, 0, 1))


def find_path(map_id: int, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]] | None:
    """8 方向最短路（Dijkstra；可走格 = 1，NPC 所在格不走；終點不論格子值都可以，出口格常標成障礙）。
    貼著障礙的格子多算 WALL_COST，路線會離牆遠一點；斜走時兩側直格都擋住就不走（避免穿牆角）。
    回傳含起點、終點的格子路徑。"""
    cs = _cells(map_id)
    w, h, c, npcs = cs
    ok = lambda x, y: 0 <= x < w and 0 <= y < h and (((x, y) == goal) or (c[y * w + x] == 1 and (x, y) not in npcs))
    dist, prev = {start: 0}, {start: None}
    pq = [(0, start)]
    while pq:
        d, p = heapq.heappop(pq)
        if p == goal:
            break
        if d > dist[p]:
            continue
        x, y = p
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
            n = (x + dx, y + dy)
            if not ok(*n) or (dx and dy and not ok(x + dx, y) and not ok(x, y + dy)):
                continue
            nd = d + STEP_COST[(dx, dy)] + (WALL_COST if n != goal and _near_wall(cs, *n) else 0)
            if nd < dist.get(n, 1 << 30):
                dist[n], prev[n] = nd, p
                heapq.heappush(pq, (nd, n))
    if goal not in prev:
        return None
    path, p = [], goal
    while p is not None:
        path.append(p)
        p = prev[p]
    return path[::-1]


def plan(map_id: int, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]] | None:
    """自動找路 → waypoint 清單（不含起點）。每段沿路徑不超過 MAX_TILES 步、點擊位置不落在 UI 上，
    waypoint 優先選不貼障礙的格子（實測 1000:74,75 貼著障礙，maps.bin 說可走但點了不會動）。
    遊戲收到點擊會自己繞小障礙。沒有通行格資料或走不到回 None。"""
    if not has_grid(map_id, start, goal):
        return None
    path = find_path(map_id, start, goal)
    if not path:
        return None
    cs = _cells(map_id)
    out, i = [], 0
    while i < len(path) - 1:
        cand = [j for j in range(min(i + MAX_TILES, len(path) - 1), i, -1)
                if reachable(path[j][0] - path[i][0], path[j][1] - path[i][1])]
        clear = [j for j in cand if j == len(path) - 1 or not _near_wall(cs, *path[j])]
        j = (clear or cand or [i + 1])[0]
        out.append(path[j])
        i = j
    return out


# ---------------- 走路 ----------------
def step_to(map_id: int, tx: int, ty: int, exit_map: int | None = None) -> tuple[int, int, int]:
    """慢速：每段點地面最多 MAX_TILES 格、等鏡頭停、OCR 讀座標再點下一段。
    座標沒變（點到 UI、點到障礙、被擋）就把每段格數減半再點，減到 0 = 卡住。
    exit_map = 這格是出口，走到就換地圖（讀到 exit_map 就回傳）。"""
    lim, last = MAX_TILES, None
    for _ in range(25):
        p = wait_pos()
        if p is None:
            raise RuntimeError('讀不到座標（戰鬥中？）')
        if exit_map is not None and p[0] == exit_map:
            return p
        if p[0] != map_id:
            raise RuntimeError(f'地圖不對：{p}，應該在 {map_id}')
        dx, dy = tx - p[1], ty - p[2]
        if dx == 0 and dy == 0:
            return p
        if p == last:
            lim //= 2
            if lim < 1:
                raise RuntimeError(f'走不動，卡在 {p}，目標 {tx},{ty}')
        last = p
        nx, ny = split((p[1], p[2]), (tx, ty), lim)[0]
        sx, sy = screen(nx - p[1], ny - p[2])
        gui('seq', f'{PRIMER}; click {sx} {sy}; waitstill {WAITSTILL_MS}')
    raise RuntimeError(f'走太久還沒到 {tx},{ty}')


def _start(map_id: int, start: tuple[int, int] | None) -> tuple[int, int]:
    if start is not None:
        return start
    p = wait_pos(4)
    if not p:
        raise RuntimeError('讀不到目前座標')
    if p[0] != map_id:
        raise RuntimeError(f'目前在 {p[0]}:{p[1]},{p[2]}，不是地圖 {map_id}')
    return p[1], p[2]


def walk_path(map_id: int, pts: list[tuple[int, int]], start: tuple[int, int] | None = None,
              exit_map: int | None = None, end_sig: str | None = None,
              arrive: tuple[int, int, int] | None = None, prime: bool = True) -> tuple[int, int, int]:
    """快速模式：一個 gui.sh seq 連點每段（每段之間 waitstill 等鏡頭停），只在終點驗證；沒到就退回慢速逐段走。
    pts = waypoint（不含起點，太長的段會自動切開）；start = 起點（None = OCR 讀）；
    exit_map = 最後一點是出口；end_sig = 終點畫面特徵（waitpix 用，對上就不 OCR，例：剛進醫院的畫面 + HUD）；
    arrive = end_sig 對上時回傳的座標。回傳 (地圖, x, y)。"""
    cur = _start(map_id, start)
    segs, prev = [], cur
    for p in pts:
        segs += split(prev, p)
        prev = p
    steps = [PRIMER] if prime else []
    prev = cur
    for i, p in enumerate(segs):
        sx, sy = screen(p[0] - prev[0], p[1] - prev[1])
        # 第 2 段起加 ifok：上一段 waitstill 沒有 still（nomove = 點擊沒讓角色走）就跳過後面全部，
        # 免得用錯的起點繼續換算越點越偏；最後再 OCR 驗證、退回慢速
        k = 'ifok ' if i else ''
        if i == len(segs) - 1 and end_sig:
            steps.append(f'{k}click {sx} {sy}; {k}waitpix 5000 {end_sig} 25')
        else:
            steps.append(f'{k}click {sx} {sy}; {k}waitstill {WAITSTILL_MS}')
        prev = p
    out = gui('seq', '; '.join(steps))
    goal = segs[-1] if segs else cur
    if end_sig and last_ok(out):
        return arrive or wait_pos(4, exit_map or map_id, 0.3)
    p = wait_pos(4, exit_map or map_id, 0.3)
    if p and ((exit_map is not None and p[0] == exit_map) or (exit_map is None and p == (map_id, *goal))):
        return p
    log(f'快速走路沒到 {goal}（現在 {p}），改慢速逐段走')
    if not p or p[0] != map_id:
        raise RuntimeError(f'不在地圖 {map_id}：{p}')
    # 從離目前位置最近的 waypoint 接著走（有通行格就重新找路）
    rest = plan(map_id, (p[1], p[2]), goal)
    if rest is None:
        k = min(range(len(segs)), key=lambda i: max(abs(segs[i][0] - p[1]), abs(segs[i][1] - p[2])))
        rest = segs[k:]
    for i, (x, y) in enumerate(rest):
        p = step_to(map_id, x, y, exit_map if i == len(rest) - 1 else None)
        if exit_map is not None and p[0] == exit_map:
            return p
    if exit_map is not None:
        p = wait_pos(4, exit_map)
        if not p or p[0] != exit_map:
            raise RuntimeError(f'走到出口但沒換到 {exit_map}：{p}')
    return p


def walk_to(map_id: int, x: int, y: int, start: tuple[int, int] | None = None, exit_map: int | None = None,
            end_sig: str | None = None, arrive: tuple[int, int, int] | None = None,
            auto: bool = True, slow: bool = False) -> tuple[int, int, int]:
    """走到 map_id 的 (x, y)。auto = 有通行格資料就 BFS 找路（每段 ≤ MAX_TILES）；沒資料就直線分段讓遊戲自己繞。
    slow = 每段都 OCR 驗證（step_to）。exit_map / end_sig / arrive 同 walk_path。"""
    cur = _start(map_id, start)
    pts = plan(map_id, cur, (x, y)) if auto else None
    if auto:
        log(f'自動找路 {map_id}:{cur[0]},{cur[1]} → {x},{y}：'
            + (' '.join(f'{a},{b}' for a, b in pts) if pts else '沒有通行格資料或走不到，改直線分段'))
    if pts is None:
        pts = [(x, y)]
    if slow:
        p = None
        for i, (a, b) in enumerate(pts):
            p = step_to(map_id, a, b, exit_map if i == len(pts) - 1 else None)
        return p
    return walk_path(map_id, pts, start=cur, exit_map=exit_map, end_sig=end_sig, arrive=arrive)


# ---------------- NPC ----------------
def npc_screen(npc: tuple[int, int], at: tuple[int, int], dy: int = NPC_DY) -> tuple[int, int]:
    """站在 at 時，NPC（所在格 npc）身體的截圖座標"""
    sx, sy = screen(npc[0] - at[0], npc[1] - at[1])
    return sx, sy + dy


def npc_steps(npc: tuple[int, int], at: tuple[int, int], sig: str = SIG_NPC_DIALOG, then: str = '',
              timeout: int = 1500, dy: int = NPC_DY) -> str:
    """點 NPC 開對話的 seq 片段：點她 → 輪詢對話框出現 → ifok 做 then（例：'click 948 460' 按對話框按鈕）。
    直接點 NPC 會自己走過去開對話（3 格外也行），但必須停穩再點（走路中點常變成點地面）；
    NPC 在左側面板底下（x < 400）點不到，要先走到別的格子。"""
    if not sig:
        raise ValueError(f'{LAYOUT} 版面還沒有 NPC 對話框的特徵色（SIG_NPC_DIALOG），請自己給 sig')
    nx, ny = npc_screen(npc, at, dy)
    if not safe(nx, ny):
        raise ValueError(f'NPC {npc} 在 {at} 看出去的點擊位置 {nx},{ny} 會落在 UI 上，先走近一點')
    s = f'click {nx} {ny}; waitpix {timeout} {sig} 20'
    return s + (f'; ifok {then}' if then else '')


def talk_npc(npc: tuple[int, int], at: tuple[int, int], sig: str = SIG_NPC_DIALOG, then: str = '', pre: str = '') -> bool:
    """點 NPC 並等對話框；pre = 同一個 seq 前面先做的動作。回傳對話框有沒有出現"""
    out = gui('seq', (pre + '; ' if pre else '') + npc_steps(npc, at, sig, then))
    return any(l.split()[:1] == ['ok'] for l in out.splitlines())


# ---------------- CLI ----------------
def _xy(s: str) -> tuple[int, int]:
    a, b = s.split(',')
    return int(a), int(b)


def main() -> int:
    ap = argparse.ArgumentParser(description='點地面走到某地圖座標（自動找路 / 手動 waypoint）')
    ap.add_argument('target', nargs='*', help='地圖ID X Y')
    ap.add_argument('--path', help='手動 waypoint："地圖:x,y x,y ..."（不含起點）')
    ap.add_argument('--exit', type=int, help='終點是出口，抵達這張地圖算成功')
    ap.add_argument('--from', dest='start', help='起點 X,Y（不給就 OCR 讀）')
    ap.add_argument('--plan', action='store_true', help='只印自動找路結果，不走')
    ap.add_argument('--slow', action='store_true', help='每段都 OCR 驗證')
    ap.add_argument('--no-auto', action='store_true', help='不用通行格找路')
    a = ap.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    start = _xy(a.start) if a.start else None
    t0 = time.time()
    if a.path:
        m, rest = a.path.split(':', 1)
        pts = [_xy(s) for s in rest.split()]
        p = walk_path(int(m), pts, start=start, exit_map=a.exit)
    else:
        if len(a.target) != 3:
            ap.error('要給 地圖ID X Y，或 --path')
        m, x, y = map(int, a.target)
        if a.plan:
            if start is None:
                start = _start(m, None)
            pts = plan(m, start, (x, y))
            if pts is None:
                print('沒有通行格資料（或座標超出 / 起點不是可走格 / 走不到）')
                return 1
            prev = start
            for q in pts:
                print(f'{q[0]},{q[1]}  （{q[0] - prev[0]:+d},{q[1] - prev[1]:+d} → 點 {screen(q[0] - prev[0], q[1] - prev[1])}）')
                prev = q
            return 0
        p = walk_to(m, x, y, start=start, exit_map=a.exit, auto=not a.no_auto, slow=a.slow)
    log(f'到達 {p}，耗時 {time.time() - t0:.1f} 秒')
    return 0


if __name__ == '__main__':
    sys.exit(main())
