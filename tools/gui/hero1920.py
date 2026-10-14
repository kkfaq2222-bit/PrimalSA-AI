#!/usr/bin/env python3
r"""英雄戰場（1~132 層）一路打到底的總控（1920×1017；NPC 座標 / 傳送點都從 knowledge 的 NPC 腳本表讀，不寫死）。

來源：knowledge/quests/npc-scripts-*.md 的「英雄戰場（戰鬥）」腳本——每隻守靈者打贏會被傳到固定座標，落點就在下一隻附近，
所以全部串成一條直線鏈（8200 → 中繼 8212 → 8201 → … → 8210 → 路普勒斯 → 回薩姆吉爾）。
  入口：薩姆吉爾的醫院(1005) 路普勒斯(10394) @ 25,11 → 8200 210,30（單人 maxRoleNum 1；v1 還沒量對話鈕座標，要手動對話進場）。
  樓層 BOSS（庫克 / 福恩奇邑 / 斯洛伐特 / 柯爾特 / 艾斯克巴 / 馬塔洛夫）與最後的路普勒斯，腳本需求 = 石幣 50000（是否扣款未實測）。
  120 / 132 層道具說明要攜帶「英雄令牌」（Item 91474），腳本表沒列這個需求，取得方式知識庫沒寫 → 實測再補。
每個戰鬥都是單人（banPartner / maxRoleNum 1）：5 個角色各自打一輪，不組隊。

用法（專案根目錄）：
  uv run --no-project python tools/gui/hero1920.py --plan                 # 離線：印整條鏈（不碰遊戲）
  uv run --no-project python tools/gui/hero1920.py --client kkfaq22222 --do     # 從目前位置接著打（人要先在 8200~8210 / 8212）
  --from-start    忽略進度檔，從 8200 第一隻開始算（從目前座標找最近的 NPC 接）
  --reset         清掉進度檔
  --max-retry 5   同一隻打輸 / 沒打起來的重打上限（使用者規定 5 次失敗就停手）
停手條件：驗證 / 不認得的畫面（quest.py 退出碼 2）、重試用完、被打飛回薩姆吉爾、HP 太低、找不到下一隻、暫停檔。停手會響提示音並寫 notes/hero-log.md。
實際戰鬥 / 點 NPC / 對話 / 輸贏判斷的機制交給 quest.py --fight（--no-track、不驗隊伍）；贏不贏由這支腳本用「落點座標」判斷。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATE_DIR = ROOT / 'tools' / '.cache'
NOTES = ROOT / 'notes' / 'hero-log.md'
SCRIPT_GLOB = 'knowledge/quests/npc-scripts-*.md'
START = (8200, 210, 30)          # 醫院路普勒斯傳進來的落點
HERO_MAPS = set(range(8200, 8214))
NEAR_TILES = 5                   # 落點與預期差在這個格數內算打贏（傳送落點座標會被通行格微調）
HP_MIN_PCT = 35


# ---------------- 鏈資料（純函式，離線可測）----------------
def load_rows(root: Path = ROOT) -> list:
    """解析所有「英雄戰場」NPC 腳本 → [{id, name, map, x, y, to:(map,x,y), need}]"""
    rows = []
    for f in sorted(root.glob(SCRIPT_GLOB)):
        text = f.read_text(encoding='utf-8')
        for blk in re.split(r'\n(?=### 腳本 )', text):
            m = re.match(r'### 腳本 (\d+)：英雄戰場', blk)
            if not m:
                continue
            n = re.search(r'- NPC：(.+?)\((\d+)\) @ (.+?)\((\d+)\) (\d+),(\d+)', blk)
            d = re.search(r'- 目的地 / 地點：(.+?)\((\d+)\) (\d+),(\d+)', blk)
            if not n or not d:
                continue
            rows.append({'id': int(n.group(2)), 'script': int(m.group(1)), 'name': n.group(1),
                         'map': int(n.group(4)), 'x': int(n.group(5)), 'y': int(n.group(6)),
                         'to': (int(d.group(2)), int(d.group(3)), int(d.group(4))),
                         'need': '需求：' in blk})
    return rows


def dist(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def pick_next(rows: list, done: set, cur: tuple):
    """cur = (地圖, x, y)；在目前地圖挑「還沒打」且離自己最近的 NPC。入口（1005）不算。"""
    cands = [r for r in rows if r['map'] == cur[0] and r['id'] not in done and r['map'] in HERO_MAPS]
    if not cands:
        return None
    return min(cands, key=lambda r: dist((r['x'], r['y']), cur[1:]))


def simulate(rows: list, start: tuple = START) -> list:
    """假設每場都贏，從 start 一路排到離開英雄戰場"""
    done, cur, out = set(), start, []
    while True:
        r = pick_next(rows, done, cur)
        if not r:
            break
        out.append(r)
        done.add(r['id'])
        cur = r['to']
        if cur[0] not in HERO_MAPS:
            break
    return out


def stand_candidates(npc: tuple) -> list:
    """NPC 周圍 2 格內的站位，近的優先"""
    c = [(dx, dy) for dx in range(-2, 3) for dy in range(-2, 3) if (dx, dy) != (0, 0)]
    c.sort(key=lambda d: (max(abs(d[0]), abs(d[1])), abs(d[0]) + abs(d[1])))
    return [(npc[0] + dx, npc[1] + dy) for dx, dy in c]


# ---------------- 進度 / log ----------------
def state_path(client: str) -> Path:
    return STATE_DIR / f'hero-{client}.json'


def load_done(client: str) -> set:
    p = state_path(client)
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding='utf-8')).get('done', []))
        except Exception:
            pass
    return set()


def save_done(client: str, done: set) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(client).write_text(json.dumps({'done': sorted(done), 'at': time.strftime('%F %T')}), encoding='utf-8')


def log(m: str) -> None:
    print(time.strftime('%H:%M:%S'), m, flush=True)


def note(client: str, m: str) -> None:
    try:
        NOTES.parent.mkdir(parents=True, exist_ok=True)
        with NOTES.open('a', encoding='utf-8') as f:
            f.write(f'- {time.strftime("%F %H:%M:%S")} [{client}] {m}\n')
    except Exception:
        pass


def halt(client: str, why: str, rc: int) -> int:
    log(f'停手：{why}')
    note(client, f'停手：{why}')
    try:
        import notifyhalt
        notifyhalt.alert(f'hero {why}'[:60])
    except Exception:
        pass
    return rc


# ---------------- 執行 ----------------
def fight(client: str, r: dict, timeout: int = 300) -> int:
    env = dict(os.environ, PSA_EXE_MATCH=client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
    env.setdefault('PSA_TILE_SCALE', '0.5')
    argv = [sys.executable, str(HERE / 'quest.py'), '--fight', '--npc', f'{r["x"]},{r["y"]}', '--npc-map', str(r['map']),
            '--team-size', '1', '--max-seconds', str(timeout)]
    return subprocess.run(argv, cwd=str(ROOT), env=env).returncode


def run(client: str, a) -> int:
    os.environ['PSA_EXE_MATCH'] = client
    os.environ.setdefault('PSA_TILE_SCALE', '0.5')
    sys.path.insert(0, str(HERE))
    import walk
    import pausegate
    rows = load_rows()
    if not rows:
        return halt(client, '讀不到英雄戰場腳本表（knowledge/quests/npc-scripts-*.md）', 4)
    done = set() if (a.from_start or a.reset) else load_done(client)
    if a.reset:
        save_done(client, set())
    fails = 0
    while True:
        pausegate.wait(log)
        cur = walk.wait_pos(tries=6)
        if not cur:
            return halt(client, '讀不到目前座標（戰鬥中 / 讀取中 / 驗證視窗？請人工看畫面）', 3)
        if cur[0] not in HERO_MAPS:
            if done:
                log(f'已離開英雄戰場（{cur}），整輪完成')
                note(client, f'完成：離開英雄戰場到 {cur}；打過 {len(done)} 隻')
                try:
                    import notifyhalt
                    notifyhalt.alert('hero 完成', ok=True)
                except Exception:
                    pass
                return 0
            return halt(client, f'人在 {cur[0]}，不是英雄戰場（8200~8213）；請先從醫院路普勒斯(1005) 25,11 對話進場', 5)
        r = pick_next(rows, done, cur)
        if not r:
            return halt(client, f'{cur} 這張圖找不到下一隻（可能已全打過 / 落點不同）；--from-start 重算或人工確認', 6)
        st = walk.stat()
        hp = st.get('hpPct')
        if hp is not None and hp < HP_MIN_PCT:
            return halt(client, f'HP {hp}% 太低，先補血再接著跑（進度已存）', 7)
        npc = (r['x'], r['y'])
        log(f'下一隻：{r["name"]}({r["id"]}) @ {r["map"]}:{r["x"]},{r["y"]} → {r["to"]}{"（需求 50000 石幣）" if r["need"] else ""}；我在 {cur}')
        # 走到 NPC 旁（有通行格資料才找站位；否則直線走到 NPC 旁一格）
        tile = None
        for t in stand_candidates(npc):
            try:
                if walk.has_grid(r['map'], cur[1:], t):
                    tile = t
                    break
            except Exception:
                break
        if dist(cur[1:], npc) > 1:
            tgt = tile or (npc[0], npc[1] + 1)
            walk.walk_to(r['map'], tgt[0], tgt[1], start=cur[1:], auto=tile is not None)
        rc = fight(client, r)
        if rc == 2:
            return halt(client, f'{r["name"]}：出現不認得的畫面 / 驗證視窗（quest.py 退出碼 2），請人工處理', 2)
        after = walk.wait_pos(tries=8)
        won = bool(after) and after[0] == r['to'][0] and dist(after[1:], r['to'][1:]) <= NEAR_TILES
        if after and after[0] == 1000 and r['to'][0] != 1000:
            return halt(client, f'被打飛回薩姆吉爾 {after}（{r["name"]}）；回醫院重新進場後同一行再跑', 8)
        if won:
            fails = 0
            done.add(r['id'])
            save_done(client, done)
            note(client, f'贏 {r["name"]}({r["id"]}) {r["map"]}:{r["x"]},{r["y"]} → {after}（已打 {len(done)} 隻）')
            continue
        fails += 1
        note(client, f'沒贏 {r["name"]}({r["id"]}) quest.py 退出碼 {rc}，落點 {after}，預期 {r["to"]}（第 {fails}/{a.max_retry} 次）')
        if fails >= a.max_retry:
            return halt(client, f'{r["name"]}({r["id"]}) 連續 {fails} 次沒打贏（落點 {after}，預期 {r["to"]}）', 9)
        log(f'沒打贏（退出碼 {rc}，落點 {after}）→ 重打第 {fails + 1} 次')


def print_plan(rows: list) -> None:
    chain = simulate(rows)
    boss = [r for r in chain if r['need']]
    log(f'共 {len(chain)} 場（含 {len(boss)} 隻要 50000 石幣的樓層 BOSS / 終點）')
    maps_seen = []
    for i, r in enumerate(chain, 1):
        flag = ' ★需求' if r['need'] else ''
        log(f'{i:3d}. {r["map"]}:{r["x"]:>3},{r["y"]:>3} {r["name"]:<8} → {r["to"][0]}:{r["to"][1]},{r["to"][2]}{flag}')
    for r in chain:
        if r['map'] not in maps_seen:
            maps_seen.append(r['map'])
    log('經過地圖：' + ' → '.join(map(str, maps_seen)))
    unvisited = [r for r in rows if r['map'] in HERO_MAPS and r['id'] not in {c['id'] for c in chain}]
    if unvisited:
        log(f'注意：{len(unvisited)} 隻 NPC 沒排進鏈：' + '、'.join(f'{r["name"]}@{r["map"]}' for r in unvisited))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='英雄戰場 1~132 層總控')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('--plan', action='store_true', help='離線印整條鏈')
    ap.add_argument('--do', action='store_true', help='真的執行')
    ap.add_argument('--from-start', action='store_true', help='忽略進度檔')
    ap.add_argument('--reset', action='store_true', help='清進度檔')
    ap.add_argument('--max-retry', type=int, default=5)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if a.plan or not a.do:
        print_plan(load_rows())
        if not a.plan:
            log('預覽結束（加 --do 才真的執行）')
        return 0
    return run(a.client, a)


if __name__ == '__main__':
    sys.exit(main())
