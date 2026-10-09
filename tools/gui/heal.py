#!/usr/bin/env python3
"""回村補血：取消原地遇敵 → 傳送薩姆吉爾 → 走進醫院 → 小護士「恢復氣血」→ 傳送回練功點 → 開原地遇敵。

用法（專案根目錄）：
  uv run --no-project python tools/gui/heal.py                 # 現在就回村補血，再回波拉島
  uv run --no-project python tools/gui/heal.py --spot 波拉島2   # 回到別的練功點（見 SPOTS）
  uv run --no-project python tools/gui/heal.py --watch         # 常駐：每 30 秒讀 HUD，隊長血 / 魔太低就自動補
  uv run --no-project python tools/gui/heal.py --watch --hp 150 --mp 20 --every 30

只透過 tools/gui/gui.sh（背景點擊 / 截圖）與 stat.ps1（OCR 讀 HUD）操作，不碰遊戲記憶體。
座標以最大化 2880×1659（截圖 1440×830）為準；流程與座標的實測紀錄見 notes/leveling.md。
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / 'tools' / 'gui' / 'gui.sh'
STAT = r'C:\games\PrimalSA-AI\tools\gui\stat.ps1'

# 練級傳送分頁的目的地：名稱 → (截圖座標 x, y, 抵達地圖 ID)；見 .claude/skills/psa-game-ui/ui/transfer.md
SPOTS = {
    '柯奧4F龜洞': (859, 356, 11004),
    '波拉島': (1100, 231, 500),
    '波拉島2': (1165, 326, 502),
    '地雷區': (1165, 400, 60049),
    '地雷區2': (1165, 468, 60050),
}
TAB_TOWN, TAB_LEVEL = (259, 196), (259, 314)
SAMUGIL = (750, 507)                 # 尼斯大陸分頁的「薩姆吉爾」→ 1000:92,99
VILLAGE, HOSPITAL = 1000, 1005
# 傳送點 92,99 → 醫院入口 81,66：中間有雕像（x78～83, y74～79），從右邊 x=84 繞過去（2026-10-09 實測）
VILLAGE_PATH = [(86, 84), (84, 80), (84, 75), (81, 68), (81, 66)]
HOSPITAL_SPOT = (23, 62)             # 站這裡，小護士（20,57）在畫面上的位置固定
NURSE_CLICK = (462, 335)             # 站在 23,62 時小護士的截圖座標
HEAL_BUTTON = (948, 460)             # 對話框「恢復氣血」
ENCOUNTER = (1365, 660)              # 主畫面「遇敵 / 取消遇敵」
# 「取消遇敵」（原地遇敵開著）圖示是紅色龍頭；關著是灰色圖示
ENC_PROBES = [(1365, 645), (1380, 630), (1360, 632), (1388, 640)]
ME = (715, 410)                      # 角色腳下的截圖座標
STEP = 5                             # 每次點地面最多走幾格（太遠不會動）


def log(msg: str) -> None:
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def gui(*args: str) -> str:
    r = subprocess.run(['bash', str(GUI), *args], capture_output=True, text=True)
    return r.stdout.strip()


def click(x: int, y: int) -> None:
    gui('click', str(x), str(y))


def stat() -> dict:
    r = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', STAT],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    line = (r.stdout.strip().splitlines() or [''])[-1]
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {'ok': False, 'error': line or r.stderr.strip()}


def pos() -> tuple[int, int, int] | None:
    m = re.match(r'(\d+):(\d+),(\d+)', stat().get('pos') or '')
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def wait_pos(tries: int = 6) -> tuple[int, int, int] | None:
    """讀座標；戰鬥中 / 傳送讀取中讀不到時重試"""
    for _ in range(tries):
        p = pos()
        if p:
            return p
        time.sleep(1.5)
    return None


def encounter_on() -> bool:
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in ENC_PROBES))
    reds = 0
    for c in out.split():
        r, g, b = (int(v) for v in c.split(','))
        reds += r > 120 and g < 80 and b < 80
    return reds >= 2


def set_encounter(on: bool) -> None:
    for _ in range(3):
        if encounter_on() == on:
            log(f'原地遇敵：{"開" if on else "關"}')
            return
        click(*ENCOUNTER)
        time.sleep(1.5)
    raise RuntimeError('切換原地遇敵失敗')


def teleport(tab: tuple[int, int], dest: tuple[int, int], want_map: int, name: str) -> None:
    """傳送；戰鬥中會被擋（「非正常狀態不能傳送」），等一下再試"""
    for i in range(10):
        gui('seq', f'click 1340 65; wait 800; click {tab[0]} {tab[1]}; wait 600; '
                   f'click {dest[0]} {dest[1]}; wait 2500; key {{ESC}}; wait 500')
        p = wait_pos()
        if p and p[0] == want_map:
            log(f'傳送到 {name} {p[0]}:{p[1]},{p[2]}')
            return
        log(f'傳送 {name} 沒成功（{p}），可能在戰鬥中，等 4 秒再試')
        time.sleep(4)
    raise RuntimeError(f'傳送 {name} 失敗')


def walk_to(tx: int, ty: int, map_id: int, next_map: int | None = None) -> tuple[int, int, int]:
    """點地面一段一段走到 (tx, ty)；next_map = 走到這格會換地圖（出口）"""
    stuck = 0
    last = None
    for _ in range(20):
        p = wait_pos()
        if p is None:
            raise RuntimeError('讀不到座標')
        if next_map is not None and p[0] == next_map:
            return p
        if p[0] != map_id:
            raise RuntimeError(f'地圖不對：{p}')
        dx, dy = tx - p[1], ty - p[2]
        if dx == 0 and dy == 0:
            return p
        stuck = stuck + 1 if p == last else 0
        if stuck >= 2:
            raise RuntimeError(f'走不動，卡在 {p}，目標 {tx},{ty}')
        last = p
        k = max(abs(dx), abs(dy))
        if k > STEP:
            dx, dy = round(dx * STEP / k), round(dy * STEP / k)
        # 每格螢幕位移：x+1 ≈ (+32, −23)、y+1 ≈ (+32, +23)（ui/home.md）
        click(ME[0] + 32 * (dx + dy), ME[1] + 23 * (dy - dx))
        time.sleep(1.2 + 0.25 * max(abs(dx), abs(dy)))
    raise RuntimeError(f'走太久還沒到 {tx},{ty}')


def heal_trip(spot: str) -> None:
    sx, sy, spot_map = SPOTS[spot]
    t0 = time.time()
    set_encounter(False)
    teleport(TAB_TOWN, SAMUGIL, VILLAGE, '薩姆吉爾')
    for i, (x, y) in enumerate(VILLAGE_PATH):
        last = i == len(VILLAGE_PATH) - 1
        p = walk_to(x, y, VILLAGE, HOSPITAL if last else None)
    if p[0] != HOSPITAL:
        time.sleep(2)
        p = wait_pos()
        if not p or p[0] != HOSPITAL:
            raise RuntimeError(f'沒進到醫院：{p}')
    log(f'進醫院 {p[0]}:{p[1]},{p[2]}')
    walk_to(*HOSPITAL_SPOT, HOSPITAL)
    click(*NURSE_CLICK)
    time.sleep(2)
    click(*HEAL_BUTTON)
    time.sleep(1.5)
    s = stat()
    log(f'補血後 HP {s.get("hp")} MP {s.get("mp")}')
    teleport(TAB_LEVEL, (sx, sy), spot_map, spot)
    set_encounter(True)
    log(f'完成，耗時 {time.time() - t0:.0f} 秒')


def low(s: dict, hp: int, mp: int) -> bool:
    if not s.get('ok') or not s.get('level'):
        return False   # 戰鬥中 HUD 被蓋住、讀不到等級 → 不判斷
    # OCR 讀不出個位數（實測 HP 1 / MP 5 時回 null）：讀得到等級卻讀不到 HP，當作血量很低（推測）
    if s.get('hp') is None or s.get('mp') is None:
        return True
    return s['hp'] < hp or s['mp'] < mp


def main() -> int:
    ap = argparse.ArgumentParser(description='回村補血再回練功點')
    ap.add_argument('--spot', default='波拉島', choices=SPOTS)
    ap.add_argument('--watch', action='store_true', help='常駐監看，血 / 魔太低就自動補')
    ap.add_argument('--hp', type=int, default=150, help='隊長 HP 低於這個就回村（預設 150）')
    ap.add_argument('--mp', type=int, default=20, help='隊長 MP 低於這個就回村（預設 20）')
    ap.add_argument('--every', type=int, default=30, help='監看間隔秒數（預設 30）')
    a = ap.parse_args()
    if not a.watch:
        heal_trip(a.spot)
        return 0
    log(f'監看中：HP < {a.hp} 或 MP < {a.mp} 就回村補血（Ctrl+C 結束）')
    while True:
        s = stat()
        if low(s, a.hp, a.mp):
            log(f'血 / 魔太低（HP {s.get("hp")} MP {s.get("mp")}），回村補血')
            try:
                heal_trip(a.spot)
            except RuntimeError as e:
                log(f'補血流程失敗：{e}；停止監看，請人工處理')
                return 1
        time.sleep(a.every)


if __name__ == '__main__':
    sys.exit(main())
