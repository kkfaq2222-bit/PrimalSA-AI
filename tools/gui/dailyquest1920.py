#!/usr/bin/env python3
"""每日任務（委託接取）材料規劃與購買（1920×1017；座標用截圖座標，2026-10-14 在 11111 實測）。

子命令：
  plan   離線：由今天 10 項（--pages "p1a,p1b;p2a,p2b;...;p5a,p5b" 或 --file json）查知識庫配方，
         統計材料、依店分組、依「第 5 頁 → 1 頁」順序列出購買計畫（不碰遊戲）。
  here   在「已站在商店地圖」時，買本地圖需要的材料：點 NPC（用目前座標與 NPC 座標換算畫面位置）→ 道具商店 →
         OCR 找商品 → 選取 → 標題核對 → 購買 → 確定 → 石幣數字核對（預設 dry，--do 才真的買）。

用法（專案根目錄）：
  uv run --no-project python tools/gui/dailyquest1920.py plan --pages "出乎意料的混合串燒,蝦子的鹽味串燒;泡菜,魚大鍋煮;蝦子的鹽味串燒,白雪蘋果;合成鎧 5,味道很強的水果酒;超嗆大蒜,秘密的沙拉"
  uv run --no-project python tools/gui/dailyquest1920.py here --client kkfaq11111 --pages "..." [--do]

不核對石幣價格（24h 店全部 500）；只核對店名、商品名、數量、石幣數字有少。背包材料上限 13 種（使用者規則）。
"""
import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import ocrfix  # noqa: E402  OCR 修正表（雙字部首合併 + 單字混淆；2026-10-15 由本檔 OCR_FIX / STR_FIX 合併）

BAG_KINDS_MAX = 13
# 固定原位置（使用者 2026-10-14）：每次都從這裡點 NPC（可遠距離點），畫面座標固定；買完走回原位置
HOME = {2009: (22, 26), 1009: (22, 23)}
# 畫面換算（11111 實測）：角色固定在畫面中心 (481,243)，每格 sx = 10.8*(dx+dy)、sy = 7.5*(dy-dx)
CX, CY, KX, KY = 481, 243, 10.8, 7.5
BODY_DY = 0            # 點 NPC 身體：座標換算本身已是人物位置（實測誤差約 8px）
SHOP_BTN = (650, 283)  # 對話「道具商店」
SHOP_CLOSE = (787, 60)
BUY_BTN = (653, 367)
CONFIRM_BTN = (415, 343)
TITLE_BOX = (580, 105, 150, 36)
COIN_BOX = (210, 5, 110, 22)
# 淺色字的讀法（ocrbench 2026-10-15，我們自己的 960×508 截圖）：預設 -Dark 150 只留深色描邊 → 部首拆字（'古亻古亻'、'有氵睪的地瓜'）。
# -Dark 0（不二值化，只放大）在便利店標題（黃字紅底）24/24、NPC 對話名字框（淺色字棕底）37/37 讀得完整（舊讀法 9/24、22/37）；
# 讀不到字才退回舊讀法。
TITLE_OPTS = ('-Zooms', '2,3', '-Dark', '0')
NAME_OPTS = TITLE_OPTS
NAME_BOX = (590, 128, 200, 38)


def shop_title(uikit) -> str:
    """便利店右側標題（目前選到的商品名）：先 -Dark 0，沒字再用舊讀法（-Zooms 2,3，隱含 -Dark 150）"""
    t = ''.join(uikit.ocr(TITLE_BOX, *TITLE_OPTS))
    return t if t.strip() else ''.join(uikit.ocr(TITLE_BOX, '-Zooms', '2,3'))


def npc_name(uikit, box=NAME_BOX) -> str:
    """NPC 對話名字框：先 -Dark 0，沒字再用舊讀法"""
    t = ''.join(uikit.ocr(box, *NAME_OPTS))
    return t if t.strip() else ''.join(uikit.ocr(box, '-Zooms', '2,3'))


LIST_BOX = (205, 95, 330, 330)
DRAG_UP = 'drag 360 380 360 310; wait 1400'   # 清單小幅往下（約 70px）


def load_recipes() -> dict:
    """item-book.md → {成品名: [[(材料, 數量)...], ...]}（同名可能多組）"""
    out = collections.defaultdict(list)
    for ln in (ROOT / 'knowledge' / 'crafting' / 'item-book.md').read_text(encoding='utf-8').splitlines():
        m = re.match(r'\|\s*\d+\s*\|[^|]*\|\s*(.+?)\((\d+)\)\s*\|\s*(.+?)\s*\|', ln)
        if not m:
            continue
        mats = []
        for part in m.group(3).split('、'):
            mm = re.match(r'(.+?)\(\d+\)×(\d+)$', part.strip())
            if mm:
                mats.append((mm.group(1), int(mm.group(2))))
        if mats:
            out[m.group(1).replace(' ', '')].append(mats)
    return out


ALL_STORE_NAMES = []


def load_stores() -> dict:
    """notes/24h-stores.md → {材料: (店名, NPC, 地圖ID, x, y)}"""
    where = {}
    cur = None
    for ln in (ROOT / 'notes' / '24h-stores.md').read_text(encoding='utf-8').splitlines():
        m = re.match(r'## (.+?) \(NPC (\d+)\) @ (.+?)\((\d+)\) (\d+),(\d+)', ln)
        if m:
            cur = (m.group(1), int(m.group(2)), int(m.group(4)), int(m.group(5)), int(m.group(6)))
            continue
        m = re.match(r'\| (.+?) \| \d+ \| \d+ 石幣', ln)
        if m and cur and m.group(1) not in where:
            where[m.group(1)] = cur
    return where


def parse_pages(s: str) -> list:
    return [[x.strip() for x in p.split(',') if x.strip()] for p in s.split(';') if p.strip()]


def build_plan(pages):
    rec, stores = load_recipes(), load_stores()
    plan = []   # [(頁, 成品, [(材料, 數)])]
    for pi, items in enumerate(pages, 1):
        for it in items:
            cands = rec.get(it.replace(' ', ''), [])
            ok = [c for c in cands if all(n in stores for n, _ in c)]
            pick = (ok or cands or [None])[0]
            if pick is None:
                print(f'警告：知識庫查不到「{it}」的配方（第 {pi} 頁）')
                continue
            if len(ok) > 1:
                print(f'提醒：「{it}」有 {len(ok)} 組配方都買得到，取第 1 組；以遊戲彈窗為準')
            plan.append((pi, it, pick))
    return plan, stores


def shop_route(shops, start):
    """店家照位置排路線（總走路距離最短，純函式）：shops = [(店資料 (名, id, 地圖, x, y), 品項)]；start = (x, y)。
    店 ≤ 8 間就試遍所有順序取最短（2009 的店幾乎在同一直線 x=27，「每次挑最近」會走到底又折回）；更多才用最近優先。"""
    import itertools
    start = start or (0, 0)

    def cost(seq):
        cur, tot = start, 0
        for st, _its in seq:
            tot += abs(st[3] - cur[0]) + abs(st[4] - cur[1])
            cur = (st[3], st[4])
        return tot
    if len(shops) <= 8:
        return list(min(itertools.permutations(shops), key=cost)) if shops else []
    cur, rem, out = start, list(shops), []
    while rem:
        nxt = min(rem, key=lambda s: abs(s[0][3] - cur[0]) + abs(s[0][4] - cur[1]))
        rem.remove(nxt)
        out.append(nxt)
        cur = (nxt[0][3], nxt[0][4])
    return out


def keep_list(plan_all) -> list:
    """留身上的材料（使用者 2026-10-14）：第 1 頁全部留；第 2 頁（再來第 3 頁）依剩餘格數補到 BAG_KINDS_MAX 種；
    第 4、5 頁存倉，但與第 1 頁重複的材料一律留身上。胡椒不算（從個人倉庫拿，不用買、不佔名額；2026-10-15）"""
    keep = []
    for pg in (1, 2, 3):
        for p_, _it, mats in plan_all:
            if p_ == pg:
                for n, _q in mats:
                    if n not in keep and n not in PEPPERS and (pg == 1 or len(keep) < BAG_KINDS_MAX):
                        keep.append(n)
    return keep


def print_plan(pages) -> dict:
    plan, stores = build_plan(pages)
    total = collections.Counter()
    for _, _, mats in plan:
        for n, q in mats:
            total[n] += q
    print(f'成品 {len(plan)} 項；材料 {len(total)} 種、共 {sum(total.values())} 個；'
          f'石幣約 {sum(total.values()) * 500 + len(plan) * 1000}（材料 500 / 個 + 合成 1000 / 項）')
    print('購買順序（第 5 頁 → 1 頁；背包材料上限 %d 種，其餘存公共倉庫）：' % BAG_KINDS_MAX)
    need_by_page = {}
    for page in sorted({p for p, _, _ in plan}, reverse=True):
        mats = collections.Counter()
        for p, _, m in plan:
            if p == page:
                for n, q in m:
                    mats[n] += q
        need_by_page[page] = mats
        print(f'  第 {page} 頁：' + '、'.join(f'{n}×{q}' for n, q in mats.items()))
    by_store = collections.defaultdict(list)
    for n, q in total.items():
        st = stores.get(n)
        key = ((st[0] + f'@{st[2]} {st[3]},{st[4]}') if st else
               '個人倉庫第 1~3 格（胡椒，使用者預先放好）' if n in PEPPERS else '？（24h 店沒賣：合成品 / 遠程店，要另外處理）')
        by_store[key].append(f'{n}×{q}')
    print('依店分組：')
    for s, items in by_store.items():
        print(f'  {s}：' + '、'.join(items))
    keep = keep_list(plan)
    store = [n for n in total if n not in keep and n not in PEPPERS and n in stores]
    print(f'預計留身上 {len(keep)} 種：' + ('、'.join(f'{n}×{total[n]}' for n in keep) or '（無）'))
    print(f'預計存公共倉庫 {len(store)} 種：' + ('、'.join(f'{n}×{total[n]}' for n in store) or '（無）'))
    peps = [n for n in PEPPERS if n in total]
    if peps:
        print('個人倉庫取用（胡椒，用完放回原位）：' + '、'.join(f'{n}×{total[n]}' for n in peps))
    return dict(total)


def npc_screen(me, npc):
    dx, dy = npc[0] - me[0], npc[1] - me[1]
    return int(CX + KX * (dx + dy)), int(CY + KY * (dy - dx) + BODY_DY)


class _Tee:
    """stdout 同時寫到 tools/.cache/daily-live.log（dailywin.py 小視窗讀這個檔）"""
    def __init__(self, stream, path):
        self._s, self._p = stream, path

    def write(self, data):
        try:
            self._s.write(data)
        except Exception:
            pass
        try:
            if data.strip():
                with open(self._p, 'a', encoding='utf-8') as f:
                    f.write(time.strftime('%m-%d %H:%M:%S ') + data.rstrip(chr(10)) + chr(10))
        except Exception:
            pass

    def flush(self):
        try:
            self._s.flush()
        except Exception:
            pass

    def __getattr__(self, k):
        return getattr(self._s, k)



def main(argv=None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, str(ROOT / 'tools' / '.cache' / 'daily-live.log'))
    ap = argparse.ArgumentParser(description='每日任務材料規劃 / 購買')
    ap.add_argument('cmd', choices=['plan', 'here', 'verify', 'craft', 'withdraw', 'read', 'pepperback'])
    ap.add_argument('--out', default='', help='read：把 5 頁成品名寫到這個 json')
    ap.add_argument('--pages', default='', help='5 頁成品名：頁以 ; 分隔，項以 , 分隔')
    ap.add_argument('--file', default='', help='json：[[頁1項1,項2],[...],...]')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--skip', default='', help='已買過的材料名（逗號分隔），here 不再買')
    ap.add_argument('--page', type=int, default=0, help='craft：只做這一頁（0 = 第 1、2 頁）')
    ap.add_argument('--craft-pages', default='', help='craft：一次開面板連續做這幾頁（例 4,5；材料要先全部領好）')
    ap.add_argument('--no-craft', action='store_true', help='craft：不合成（該頁已合成好，只提交委託）')
    ap.add_argument('--submit', action='store_true', help='craft：合成完該頁後按「提交委託」')
    ap.add_argument('--do', action='store_true', help='here：真的購買（預設只列出會做什麼）')
    a = ap.parse_args(argv)
    if a.file:
        data = json.loads(Path(a.file).read_text(encoding='utf-8'))
        if isinstance(data, dict):          # {"pages": [[..],..], "skip": ["已買材料"]}
            pages = data.get('pages', [])
            a.skip = ','.join(filter(None, [a.skip] + list(data.get('skip', []))))
        else:
            pages = data
    else:
        pages = parse_pages(a.pages)
    if not pages and a.cmd != 'read':
        print('沒有給 --pages / --file')
        return 2
    total = print_plan(pages)
    if a.cmd == 'plan':
        return 0
    if a.cmd == 'read':
        os.environ['PSA_EXE_MATCH'] = a.client
        os.environ.setdefault('PSA_CLICK_HOLD_MS', '120')
        import winenv
        winenv.enable_server()
        import petdepot1920 as pd
        import uikit
        _CTX.update(pd=pd, uikit=uikit)
        got = read_pages_from_panel(pd, uikit, winenv)
        bad = [(i + 1, j + 1) for i, pg in enumerate(got) for j, n in enumerate(pg) if not n]
        if a.out:
            Path(a.out).write_text(json.dumps({'pages': got, 'skip': []}, ensure_ascii=False), encoding='utf-8')
            print(f'已寫入 {a.out}')
        if bad:
            print(f'有 {len(bad)} 項讀不出來：{bad} → 請人工補 json 再繼續')
            return 7
        return 0
    if a.cmd == 'withdraw':
        os.environ['PSA_EXE_MATCH'] = a.client
        os.environ.setdefault('PSA_CLICK_HOLD_MS', '120')
        import winenv
        winenv.enable_server()
        import petdepot1920 as pd
        import uikit
        _CTX.update(pd=pd, uikit=uikit)
        done_path = ROOT / 'tools' / '.cache' / f'daily-done-{a.client}{os.environ.get("PSA_DAILY_TAG", "")}.json'
        dn = json.loads(done_path.read_text(encoding='utf-8'))
        plan_all, _st = build_plan(pages)
        need = [n for pg, _it, mats in plan_all if pg == a.page for n, _q in mats]
        # 先開背包讀實際內容（合成會用掉材料，格位記憶會以為還在 → 2026-10-14 r4 第 4 頁的炭沒領出來）
        for _ in range(2):
            pd.gui('key', '{ESC}', note='daily 同步前 ESC')
            time.sleep(0.5)
        known = sorted({n for _p, _it, mats in plan_all for n, _q in mats} | {it for _p, it, _m in plan_all})
        sync_bag(dn, sorted(set(known) | set(dn.get("bought", {}))))
        done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
        want = [n for n in dict.fromkeys(need) if n not in dn['bag'] and n in dn['depot']]
        miss = [n for n in dict.fromkeys(need) if n not in dn['bag'] and n not in dn['depot']]
        if miss:
            print(f'第 {a.page} 頁缺：{"、".join(miss)}（背包、公共倉庫記錄都沒有）→ 照樣試合成，沒做出來會停手')
        print(f'第 {a.page} 頁要從公共倉庫領出：' + ('、'.join(want) or '（不用）'))
        if want:
            withdraw_items(want, dn)
            done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
        peps = [n for n in PEPPERS if n in need and n not in dn['bag']]
        if peps:                                   # 胡椒在個人倉庫第 1~3 格（使用者 2026-10-15）
            print(f'第 {a.page} 頁要從個人倉庫取胡椒：' + '、'.join(peps))
            got = pepper_get(peps, dn)
            print(f'[stats] pepper_get page={a.page} want={len(peps)} got={len(got)}')
            done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
        return 0
    if a.cmd == 'pepperback':
        os.environ['PSA_EXE_MATCH'] = a.client
        os.environ.setdefault('PSA_CLICK_HOLD_MS', '120')
        import winenv
        winenv.enable_server()
        import petdepot1920 as pd
        import uikit
        _CTX.update(pd=pd, uikit=uikit)
        done_path = ROOT / 'tools' / '.cache' / f'daily-done-{a.client}{os.environ.get("PSA_DAILY_TAG", "")}.json'
        dn = json.loads(done_path.read_text(encoding='utf-8'))
        n_in = sum(1 for n in PEPPERS if n in dn['bag'])
        bad = pepper_put(dn)
        done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
        print(f'[stats] pepper_put items={n_in} bad={bad}')
        return 0
    if a.cmd == 'craft':
        os.environ['PSA_EXE_MATCH'] = a.client
        os.environ.setdefault('PSA_CLICK_HOLD_MS', '120')
        import winenv
        winenv.enable_server()
        _CTX.update(pd=__import__('petdepot1920'), uikit=__import__('uikit'))
        pgs = [int(x) for x in a.craft_pages.split(',') if x.strip()] if a.craft_pages else ([a.page] if a.page else [1, 2])
        return craft_pages(pgs, a.submit, pages, a.no_craft)

    # here：只買「目前所在地圖」有賣的材料
    os.environ['PSA_EXE_MATCH'] = a.client
    os.environ.setdefault('PSA_CLICK_HOLD_MS', '120')
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import uikit
    import walk
    _CTX.update(pd=pd, uikit=uikit)
    for _ in range(2):                    # 使用者 2026-10-14：先 ESC 關掉上次中斷殘留的對話 / 便利店
        pd.gui('key', '{ESC}', note='daily ESC 關殘留視窗')
        time.sleep(0.6)
    if '便利' in ''.join(uikit.ocr((400, 40, 170, 40), '-Zooms', '2,3')):
        pd.click(*SHOP_CLOSE, wait=800, note='daily 關殘留便利店')
    mp = None
    pos = None
    p3 = walk.wait_pos(tries=4)          # 沿用 walk.py 的座標 OCR（地圖ID, x, y）
    if p3:
        mp, pos = p3[0], (p3[1], p3[2])
    if mp is None:
        print('讀不到目前地圖 / 座標，停手')
        return 3
    # 今天已買的記檔：中斷後重跑不重複買
    done_path = ROOT / 'tools' / '.cache' / f'daily-done-{a.client}{os.environ.get("PSA_DAILY_TAG", "")}.json'
    today = time.strftime('%Y%m%d')
    try:
        dn = json.loads(done_path.read_text(encoding='utf-8'))
    except Exception:
        dn = {}
    if dn.get('date') != today:
        dn = {'date': today, 'bought': {}}
    stores = load_stores()
    ALL_STORE_NAMES[:] = sorted({v[0] for v in stores.values()})
    here = collections.defaultdict(list)
    skip = {x.strip() for x in a.skip.split(',') if x.strip()}
    for n, q in total.items():
        q -= dn['bought'].get(n, 0)
        st = stores.get(n)
        if q > 0 and st and st[2] == mp and n not in skip:
            here[st].append((n, q))
    print(f'目前地圖 {mp}，座標 {pos}；本地圖要買：')
    for st, items in here.items():
        print(f'  {st[0]}（NPC {st[1]} @ {st[3]},{st[4]}）→ 畫面約 {npc_screen(pos, (st[3], st[4]))}：'
              + '、'.join(f'{n}×{q}' for n, q in items))
    if not a.do:
        print('（dry：加 --do 才會真的買）')
        return 0
    init_state(dn)
    plan_all, _st = build_plan(pages)
    if dn['bought']:
        # 中斷後重跑 / 合成過：格位記憶可能和實際不同（合成會用掉材料）→ 開背包實際讀一次再買
        known = sorted({n for _p, _it, mats in plan_all for n, _q in mats} | {it for _p, it, _m in plan_all})
        sync_bag(dn, sorted(set(known) | set(dn.get("bought", {}))))
        done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
    # 留身上的材料（使用者 2026-10-14）：第 1 頁全部留；第 2 頁（再來第 3 頁）依剩餘格數補到 BAG_KINDS_MAX 種；
    # 第 4、5 頁存倉，但與第 1 頁重複的材料一律留身上
    keep = keep_list(plan_all)
    p12 = set(keep)
    print(f'留身上 {len(keep)} 種：' + '、'.join(keep))
    dn.setdefault('stored', [])

    def save_dn():
        done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')

    pend = [n for n in dn['bought'] if n not in p12 and n not in dn['stored']]
    if pend:
        print('先存倉（非第 1、2 頁材料）：' + '、'.join(pend))
        got = store_items(pend, dn)
        dn['stored'] += sorted(got)
        save_dn()
    skipped = []
    # 購買順序（使用者 2026-10-14）：先買「要存倉」的（買完一間就存），最後才買「留身上」的 → 背包從頭到尾都有空位。
    # 要存的材料若第 1 頁也有，以留身上為主（keep 已含第 1 頁全部材料，所以這裡會被排到第二輪）
    # 2026-10-15 加速（使用者要求 1、2）：每間店只去一次（存倉的先買、留身上的後買），店家照位置排最短路線；
    # 存倉改成「背包空位不夠下一間店時才存」，整張地圖買完再存剩下的（原本每間店都開關背包存一次）。
    # 背包滿了的舊保護（later → 存倉 → 回店）保留當備援。
    queue = [(st, sorted(its, key=lambda it: it[0] in p12)) for st, its in shop_route(list(here.items()), pos)]
    queue = [(st, its) for st, its in queue if its]
    print('購買路線（照位置）：' + ' → '.join(f'{st[0]}' for st, _its in queue))
    stuck = 0
    def store_pending(why):
        mine = [n for n in dn['bought'] if n not in p12 and n not in dn['stored'] and n in dn['bag']]
        if mine:
            print(f'存倉（{why}）：' + '、'.join(mine))
            got = store_items(mine, dn)
            dn['stored'] += sorted(got)
            save_dn()

    while queue:
        st, items = queue.pop(0)
        need = len({n for n, _q in items if n not in dn['bag']})
        if dn['bag'].count(None) < need:
            store_pending(f'背包剩 {dn["bag"].count(None)} 格、{st[0]} 要 {need} 格')
        opened = False
        offscreen = False
        for _try in range(len(CLICK_JITTER)):
            # 可遠距離點 NPC：用「目前座標」換算畫面位置；NPC 換算後不在畫面可點範圍才走回固定原位置
            cur = walk.wait_pos(tries=4)
            me = (cur[1], cur[2]) if cur and cur[0] == mp else pos
            sx, sy = npc_screen(me, (st[3], st[4]))
            if not (340 <= sx <= 920 and 100 <= sy <= 420):
                # 店內走路不穩（2026-10-14 實測走不到）：不走，跳過這間，最後列出沒買的請使用者換站位再跑
                print(f'{st[0]}：換算畫面 ({sx},{sy}) 在可點範圍外 → 走到固定位置 {HOME.get(mp)} 再算')
                lms = [(v[0], (v[3], v[4])) for v in {tuple(x) for x in stores.values() if x[2] == mp}] if False else                     [(v[0], (v[3], v[4])) for v in {x for x in stores.values() if x[2] == mp}]
                hop_to(pd, uikit, walk, winenv, mp, HOME.get(mp, me), lms)
                cur = walk.wait_pos(tries=4)
                me = (cur[1], cur[2]) if cur and cur[0] == mp else HOME.get(mp, me)
                sx, sy = npc_screen(me, (st[3], st[4]))
                if not (340 <= sx <= 920 and 100 <= sy <= 420):
                    print(f'{st[0]}：換算畫面 ({sx},{sy}) 仍在可點範圍外 → 跳過（換個站位再跑一次）')
                    skipped.append(st[0])
                    break
            jx, jy = CLICK_JITTER[_try]
            pd.click(*walk.PRIMER_XY, wait=NPC_PRIMER_GAP_MS, note='daily 引子（第一下會被吃掉）')
            pd.click(sx + jx, sy + jy, wait=1400, note=f'daily 點 {st[0]}（第 {_try + 1} 次，偏移 {jx},{jy}）')
            for _w in range(4):                    # 對話框慢出來：多等最多 1.2 秒再判失敗（2026-10-15 加引子後「對話沒出現」仍 28 次 → 不是第一下被吃，是太早判）
                if dialog_open(uikit):
                    break
                time.sleep(0.3)
            if dialog_open(uikit):
                dt = npc_name(uikit)
                if npc_title_ok(st[0], dt, ALL_STORE_NAMES):
                    opened = True
                    break
                print(f'{st[0]}：對話標題 {dt!r} 不是這間店 → ESC 換點位再點')
                pd.gui('key', '{ESC}', note='daily ESC（對話對象不對）')
                time.sleep(0.8)
                continue
            print(f'{st[0]}：對話沒出現 → ESC 再試（第 {_try + 1} 次）')
            pd.gui('key', '{ESC}', note='daily ESC')
            time.sleep(0.8)
        if skipped and skipped[-1] == st[0] and not opened:
            continue
        if not opened:
            print(f'{st[0]}：3 次都沒開到對話 → 停手')
            return 4
        pd.click(*SHOP_BTN, wait=2000, note='daily 道具商店')
        # 店家身分已在 NPC 對話框名字核對過；商店面板標題一律是「便利店」→ 這裡只確認面板開了：看藍色「購買」鈕（不靠 OCR）
        bb = uikit.px([(610, 367), (700, 367)]) or []
        title = str(bb)
        if not (len(bb) == 2 and all(c[2] > c[0] + 60 and c[2] > 120 for c in bb)):
            print(f'沒開到便利店（讀到 {title!r}）→ ESC 後停手')
            pd.gui('key', '{ESC}', note='daily ESC')
            return 4
        order = load_shop_order(st[1])
        state = {'off': 0}                             # 開店時清單在最上
        items = sorted(items, key=lambda it: order.index(it[0]) if it[0] in order else 999)
        later = []
        for k, (name, qty) in enumerate(items):
            if name not in dn['bag'] and None not in dn['bag']:
                # 背包 15 格滿了（2026-10-14 r3：留身上 13 種 + 水果店 2 種 → 櫻桃買不進去）：
                # 剩下的先不買，關店把不留身上的存倉，再回來這間店買
                later = items[k:]
                print(f'背包滿了（{len(dn["bag"])} 格）→ 先存倉再回來買：' + '、'.join(n for n, _q in later))
                break
            rc = buy_item_idx(pd, uikit, order, name, qty, state) if name in order else buy_item(pd, uikit, winenv, name, qty)
            if rc == 0:
                dn['bought'][name] = dn['bought'].get(name, 0) + qty
                bag_acquire(dn, name)
                done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
            if rc == 11:
                # 石幣核對不到（OCR 少讀位數等）：關店、開背包看這次應該放進去的那一格是不是它（使用者 2026-10-14）
                pd.gui('key', '{ESC}', note='daily ESC')
                pd.click(*SHOP_CLOSE, wait=700, note='daily 關便利店')
                if bag_slot_has(dn, name):
                    dn['bought'][name] = dn['bought'].get(name, 0) + qty
                    bag_acquire(dn, name)
                    done_path.write_text(json.dumps(dn, ensure_ascii=False), encoding='utf-8')
                    later = items[k + 1:]
                    print(f'背包確認買到 {name} → 記為已買，回店買剩下的：' + ('、'.join(n for n, _q in later) or '（沒有）'))
                    break
                print(f'背包該格不是 {name}（或是疊在舊格看不出來）→ 停手，請人看背包')
                return 6
            if rc:
                pd.gui('key', '{ESC}', note='daily ESC')
                pd.click(*SHOP_CLOSE, wait=700, note='daily 關便利店')
                return rc
        pd.click(*SHOP_CLOSE, wait=800, note='daily 關便利店')
        if later or not queue:
            store_pending('背包滿了' if later else '本地圖買完')
        if later:
            if None not in dn['bag']:
                stuck += 1
                if stuck >= 2:
                    print('背包滿了、也沒有可以存倉的（都是要留身上的材料）→ 停手；請檢查背包是否先清空 15 格')
                    return 7
            queue.insert(0, (st, later))
    store_pending('收尾（最後一間被跳過時）')
    exp_bag = [n for n in dn['bought'] if n in p12]
    exp_dep = list(dn['stored'])
    print('（背包 / 公共倉庫 OCR 驗證不可靠，已停用；請用 craft 前後的截圖或自己看）')
    vrc = 0
    if skipped:
        print('以下店在目前站位點不到，沒買：' + '、'.join(skipped) + '（請換個站位再跑一次，已買的不會重複）')
        return 8
    print('本地圖材料買完')
    return 0


_CTX = {}


def recover():
    """防呆收尾：任何失敗 / 例外 / Ctrl-C 都把畫面收乾淨（ESC 關對話 / 提示彈窗、便利店開著就按 ✕），避免卡在買東西畫面"""
    pd, uikit = _CTX.get('pd'), _CTX.get('uikit')
    if not pd or not uikit:
        return
    try:
        for _ in range(2):
            pd.gui('key', '{ESC}', note='daily 收尾 ESC')
            time.sleep(0.5)
        if '便利' in ''.join(uikit.ocr((400, 40, 170, 40), '-Zooms', '2,3')):
            pd.click(*SHOP_CLOSE, wait=700, note='daily 收尾 關便利店')
            pd.gui('key', '{ESC}', note='daily 收尾 ESC')
    except Exception as e:
        print('收尾失敗：', e)


def match_known(t, known) -> str:
    """浮窗文字 → 已知材料名（字稀有度加權涵蓋率，同 title_matches；得分最高且 >= 0.4）"""
    tt = ocrfix.fix(''.join(c for c in t if c.strip() and c not in ',，.。|'))
    if len(tt) < 2 or not known:
        return ''
    cnt = collections.Counter(c for n in known for c in set(n))

    def score(n):
        w = {c: 1.0 / cnt[c] for c in set(n)}
        return sum(w[c] for c in w if c in tt) / (sum(w.values()) or 1.0)
    best = max(known, key=score)
    return best if score(best) >= 0.4 else ''


BAG_INIT = [None, '洗滌石', '珍貴的葉', '加加產的高級炭', '高級串', '夢幻的蜥蜴', '四六的青蛙', '新鮮的魚', '大的蝦',
            '高級瑪麗娜絲海星', '普通的鹽', '粗鹽', '銳利的串', '井戶水', '燃燒完全的炭']


def init_state(dn):
    """格位記憶：背包 15 格 / 公共倉庫 20 格都是固定位置、不會補位；新東西放進「第一個空格」。
    第一次用 2026-10-14 實機看到的狀態當起點（之後每次買 / 存都由程式自己維護，並在最後用 OCR 驗證）"""
    if 'bag' not in dn and not dn.get('bought'):
        # 新的一天 / 新的一輪：使用者每次都會先清空背包 15 格與公共倉庫 20 格 → 從空狀態開始記
        dn['bag'] = [None] * 15
        dn['depot'] = [None] * 20
        dn['stored'] = []
        return
    if 'bag' not in dn:                          # 以下只是 2026-10-14 中途接手用的一次性起點
        dn['bag'] = list(BAG_INIT)
        dn['depot'] = ['厚的皮'] + [None] * 19
        dn['stored'] = sorted(set(dn.get('stored', [])) | {'厚的皮'})
        # c37 那輪已存：洗滌石、珍貴的葉（實機 log 確認）
        for nm in ('洗滌石', '珍貴的葉'):
            if nm in dn['bag']:
                dn['bag'][dn['bag'].index(nm)] = None
                dn['depot'][dn['depot'].index(None)] = nm
                if nm not in dn['stored']:
                    dn['stored'].append(nm)


def bag_acquire(dn, name):
    if name in dn['bag']:
        return                                   # 同名疊在同一格
    if None in dn['bag']:
        dn['bag'][dn['bag'].index(None)] = name
    else:
        print(f'警告：背包已滿，{name} 放不進（記憶中）')


PRICE_BOX = (610, 310, 120, 26)                  # 便利店花費欄（2026-10-14 實測 OCR 3 種縮放都穩定讀到 500）


QTY_BOX = (600, 268, 110, 36)                    # 便利店數量框


def shopnum(box):
    """便利店數字框先用 digitmatch 字元樣板讀（< 0.1 s、不會少讀一位）→ (數字字串 or None, 二值化列 or None)。
    樣板不在 / 認不出 → (None, rows)，呼叫端退回 OCR，OCR 讀值確認後用 rows 補學（digitmatch.learn_box）。
    PSA_SHOPNUM_DM=0 關掉（只用 OCR，同 2026-10-15 前）。"""
    if os.environ.get('PSA_SHOPNUM_DM', '1') == '0':
        return None, None
    try:
        import digitmatch
        rows = digitmatch.box_rows([box])
        return (digitmatch.read_digits(rows[0]), rows[0]) if rows else (None, None)
    except Exception as e:
        print('digitmatch 讀數字失敗（改用 OCR）：', e)
        return None, None


def shopnum_learn(box, rows, label: str) -> None:
    if rows is None:
        return
    try:
        import digitmatch
        if digitmatch.learn_box(box, rows, label):
            print(f'digitmatch 學到便利店數字樣板：{label}')
    except Exception as e:
        print('digitmatch 補學失敗：', e)


def price_reads(uikit, expect: int | None = None) -> list:
    """花費欄 → 數字字串清單（讀不到的是 ''）。digitmatch 認得 → [值]；否則 OCR 3 種縮放各讀一次。
    OCR 3 次都一樣、且等於 expect（有給時）→ 拿來補學 digitmatch 樣板。"""
    v, rows = shopnum(PRICE_BOX)
    if v:
        return [v]
    # OCR 常把同一行回傳兩次（['1000', '1000']）→ 只取第一個有數字的，不要接起來（2026-10-14 讀成 10001000）
    out = []
    for z in ('2,3', '3,4', '4,5'):
        ds = [re.sub(r'\D', '', t) for t in uikit.ocr(PRICE_BOX, '-Zooms', z)]
        out.append(next((d for d in ds if d), ''))
    if out[0] and all(r == out[0] for r in out) and (expect is None or out[0] == str(expect)):
        shopnum_learn(PRICE_BOX, rows, out[0])
    return out


def bag_slot_has(dn, name) -> bool:
    """開背包，OCR「這次新買的東西應該在的那一格」（格位記憶的第一個空格）的名稱，跟 name 比對。
    同名疊在舊格的看不出有沒有多 → 回 False（交給人看）。看完關背包。"""
    import catchrun1920 as cr
    import uikit
    if name in dn['bag'] or None not in dn['bag']:
        return False
    i = dn['bag'].index(None)
    cr.click(*cr.BAG_BTN, wait=1500, note='daily 開背包（核對購買）')
    x, y = cr.bag_slots()[i]
    t = ''.join(''.join(uikit.ocr((x - 36, y - 28, 72, 24), '-Zooms', z)) for z in ('2,3', '3,4'))
    t = ocrfix.fix(t)
    cover = sum(1 for c in set(name) if c in t) / len(set(name))
    print(f'背包第 {i + 1} 格讀到 {t!r}，與 {name} 字元涵蓋率 {cover:.2f}')
    uikit.gui('shot', 'daily-buycheck.png')
    cr.gui('key', '{ESC}', note='daily ESC')
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    return cover >= 0.5


ALIAS_PATH = ROOT / 'tools' / '.cache' / 'daily-ocr-alias.json'   # 格子 OCR 讀到的字 → 實際名稱（浮窗核對過才記）


def load_alias() -> dict:
    try:
        return json.loads(ALIAS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def learn_alias(text: str, name: str) -> None:
    """格子名稱認不出（記成 '?…'）、之後點開浮窗核對確定是 name → 記下來，下次背包同步直接認"""
    if not text or text == name:
        return
    al = load_alias()
    if al.get(text) != name:
        al[text] = name
        ALIAS_PATH.write_text(json.dumps(al, ensure_ascii=False, indent=0), encoding='utf-8')
        print(f'學到格子名稱對照：{text!r} → {name}')


def sync_bag(dn, known) -> list:
    """開背包讀 15 格名稱（每格 OCR 一次），對照 known（今天會用到的材料 / 成品名）重建 dn['bag']；看完關背包。
    讀不到字 = 空格；讀到字但對不上 known → 記 '?名稱'（佔格，不會被當空格放新東西）。"""
    import catchrun1920 as cr
    import uikit
    cr.click(*cr.BAG_BTN, wait=1600, note='daily 開背包（同步格位）')
    out = []
    for x, y in cr.bag_slots():
        t = ocrfix.fix(''.join(uikit.ocr((x - 36, y - 28, 72, 24), '-Zooms', '2,3')))
        if not t.strip():
            out.append(None)
            continue
        al = load_alias().get(t[:8])
        if al:
            out.append(al)
            continue
        exact = [n for n in known if n in t]        # 只認完整出現的名稱（取最長）；模糊比對會把「普通的大蒜」配成「大的大蒜」
        if not exact:                                # 長名字在卡片上折兩行，只讀到前半（「水分多的蘋」）：開頭相同字數最多、且唯一的就算
            def lcp(n):
                k = 0
                while k < min(len(n), len(t)) and n[k] == t[k]:
                    k += 1
                return k
            sc = sorted(((lcp(n), n) for n in known), reverse=True)
            if sc and sc[0][0] >= 4 and (len(sc) == 1 or sc[0][0] > sc[1][0]):
                exact = [sc[0][1]]
        out.append(max(exact, key=len) if exact else '?' + t[:8])
    uikit.gui('shot', 'daily-syncbag.png')
    cr.gui('key', '{ESC}', note='daily ESC')
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    dn['bag'] = out
    print('背包實際：' + '、'.join(n or '空' for n in out))
    return out


def ensure_public(cr) -> bool:
    """公共分頁一定要真的選中（亮黃 ≈ 255,221,139；沒選中棕 171,125,82）才存 / 取：
    2026-10-14 r2 遊戲吃掉分頁點擊，高級肉 / 普通的蛋被存進個人倉庫 → 後面頁數領不到、背包塞滿交不了。"""
    import uikit
    for _ in range(4):
        c = uikit.px([(330, 110), (410, 110)])
        if c and all(v[0] > 225 and v[1] > 190 for v in c):
            return True
        cr.click(*cr.DEPOT_PUBLIC, wait=1000, note='daily 重點公共分頁')
    print('公共倉庫分頁切不過去 → 停手（不存 / 不取，避免進錯倉庫）')
    return False


STR_FIX = ocrfix.PAIR_FIX      # 舊名保留（2026-10-15 合併到 ocrfix.py）


def fix_text(t: str) -> str:
    return ocrfix.fix(t)


def _pop_is(cr, name) -> bool:
    """道具浮窗標題是不是 name：浮窗字型 OCR 不穩（同一個字，換範圍 / 縮放結果不同）→ 3 個範圍 × 3 種縮放，任一次讀到就算。
    浮窗沒開時這塊會讀到底下格子的半截字，所以要求完整名稱（或 4 字以上高涵蓋率）。"""
    import uikit
    for box in ((408, 148, 120, 30), cr.POP_NAME, (412, 150, 90, 26)):
        for z in ('2,3', '3,4', '4,5'):
            t = fix_text(''.join(uikit.ocr(box, '-Zooms', z)))
            if name in t:
                return True
            cov = sum(1 for c in set(name) if c in t) / len(set(name))
            if len(name) >= 4 and cov >= 0.8 and len(t) >= len(name) - 1:
                return True
    return False


def _close_pop(cr):
    """浮窗開著（藍色「存入 / 取出」鈕在 (488,400)）才按 ESC；沒浮窗時按 ESC 會把整個背包關掉"""
    import uikit
    c = uikit.px([cr.POP_BTN]) or []
    if c and c[0][2] > c[0][0] + 60:
        cr.gui('key', '{ESC}', note='daily ESC 關浮窗')
        time.sleep(0.6)


def pick_slot(cr, slots, name, first, mem):
    """點記憶的格子 → 浮窗標題是 name 就回傳格序（浮窗開著，呼叫端接著按存入 / 取出）。
    有問題才處理（使用者 2026-10-14：不要每格都點開）：ESC 關浮窗（實測 ESC 只關浮窗、背包還開著）→
    用格子上的名稱文字找最像的最多 3 格再試。絕不點空白處（2026-10-14 點 (180,440) 誤觸「擴容」→ 花鑽石提示）。"""
    import uikit
    x, y = slots[first]
    cr.click(x, y, wait=900, note=f'daily 點第 {first + 1} 格（{name}）')
    if _pop_is(cr, name):
        if isinstance(mem[first], str) and mem[first].startswith('?'):
            learn_alias(mem[first][1:], name)
        return first
    _close_pop(cr)
    big = len(slots) == 15                       # 背包卡片較大；倉庫卡片名稱會被截半，只能部分比對
    scored = []
    for k, (sx, sy) in enumerate(slots):
        if k == first:
            continue
        box = (sx - 36, sy - 28, 72, 24) if big else (sx - 32, sy - 28, 64, 22)
        t = ocrfix.fix(''.join(uikit.ocr(box, '-Zooms', '2,3')))
        t = ''.join(c for c in t if '一' <= c <= '鿿')
        if len(t) < 2:
            continue
        hit = sum(1 for c in set(t) if c in name) / len(set(t))       # 讀到的字有幾成屬於這個名字（截半也能比）
        if hit >= 0.7:
            scored.append((hit, len(t), k))
    for _h, _l, k in sorted(scored, reverse=True)[:3]:
        x, y = slots[k]
        cr.click(x, y, wait=900, note=f'daily 改點第 {k + 1} 格找 {name}')
        if _pop_is(cr, name):
            if isinstance(mem[k], str) and mem[k].startswith('?'):
                learn_alias(mem[k][1:], name)
            return k
        _close_pop(cr)
    return None


def store_items(names, dn) -> set:
    """依格位記憶存入：名稱 → 背包格序 → 點該格 → 「存入」→ 該格清空、公共倉庫第一個空格記下。
    不再用 OCR 找格子；只在開頭確認背包面板開了，之後不因面板判斷偶爾失準就停手。"""
    import catchrun1920 as cr
    stored = set()
    todo = [n for n in names if n in dn['bag']]
    if not todo:
        return stored
    cr.click(*cr.BAG_BTN, wait=1500, note='daily 開背包（存倉）')
    cr.need_bag()
    cr.click(*cr.TAB_DEPOT, wait=1200, note='daily 倉庫分頁')
    cr.click(*cr.DEPOT_PUBLIC, wait=900, note='daily 公共倉庫')
    if not ensure_public(cr):
        cr.gui('key', '{ESC}', note='daily ESC')
        return stored
    slots = cr.bag_slots()
    for nm in todo:
        i = pick_slot(cr, slots, nm, dn['bag'].index(nm), dn['bag'])
        if i is None:
            print(f'{nm}：背包裡找不到（每格都核對過浮窗名稱）→ 不存，略過')
            continue
        if dn['bag'][i] != nm:
            j = dn['bag'].index(nm)
            print(f'{nm}：格位記憶說在第 {j + 1} 格，實際在第 {i + 1} 格 → 已修正')
            # 記憶那格實際有別的東西（不知道是什麼）→ 標「?」佔用，不要換成空格：
            # 2026-10-15 333 對調把 None 換回第 2 格 → 之後每買一樣都猜第 2 格、每樣都要多找一輪
            old = dn['bag'][i]
            dn['bag'][j], dn['bag'][i] = (old if old is not None else '?'), nm
        cr.click(*cr.POP_BTN, wait=1300, note=f'daily 存入 {nm}')
        dn['bag'][i] = None
        if None in dn['depot']:
            dn['depot'][dn['depot'].index(None)] = nm
        stored.add(nm)
        print(f'已存公共倉庫：{nm}（背包第 {i + 1} 格）')
    cr.gui('key', '{ESC}', note='daily ESC')
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    return stored


def read_grid(winenv, box, slots, known) -> dict:
    """整面格子 OCR 一次（顯示道具名開著時每格有名稱）→ {格序: 材料名}；對不上的記 '?'，空格不列"""
    r = winenv.run_ps('ocr.ps1', *[str(v) for v in box], '-Zooms', '3,4')
    try:
        lines = json.loads((r.stdout.strip().splitlines() or [''])[-1]).get('lines', [])
    except Exception:
        lines = []
    cells = collections.defaultdict(str)
    for ln in lines:
        x, y = int(ln['x']), int(ln['y'])
        i = min(range(len(slots)), key=lambda k: (slots[k][0] - x) ** 2 + (slots[k][1] - 12 - y) ** 2)
        if abs(slots[i][0] - x) <= 36 and abs(slots[i][1] - y) <= 40 and not re.fullmatch(r'\d+', ln['text'].strip()):
            cells[i] += ln['text'].strip()
    return {i: (match_known(t, known) or '?') for i, t in cells.items()}


def verify_inventory(known, expect_bag, expect_depot) -> int:
    """背包 / 公共倉庫格內名稱 OCR → 與預期比對並列印差異（使用者 2026-10-14：買完要驗證身上與共用倉庫）"""
    import catchrun1920 as cr
    import winenv
    cr.click(*cr.BAG_BTN, wait=1500, note='daily 開背包（驗證）')
    cr.need_bag()
    cr.click(*cr.TAB_BAG, wait=900, note='daily 背包分頁')
    bag = read_grid(winenv, (465, 115, 345, 205), cr.bag_slots(), known)
    cr.click(*cr.TAB_DEPOT, wait=1200, note='daily 倉庫分頁')
    cr.click(*cr.DEPOT_PUBLIC, wait=900, note='daily 公共倉庫')
    dep = read_grid(winenv, (145, 135, 310, 250), cr.depot_slots(), known)
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    gb, gd = sorted(set(bag.values())), sorted(set(dep.values()))
    print(f'背包 {len(bag)} 格：' + '、'.join(gb))
    print(f'公共倉庫 {len(dep)} 格：' + '、'.join(gd))
    miss_b = sorted(set(expect_bag) - set(gb))
    miss_d = sorted(set(expect_depot) - set(gd))
    extra_b = sorted(n for n in gb if n not in expect_bag and n != '?')
    if miss_b:
        print('背包缺：' + '、'.join(miss_b))
    if miss_d:
        print('倉庫缺：' + '、'.join(miss_d))
    if extra_b:
        print('背包多（預期該存倉）：' + '、'.join(extra_b))
    if '?' in gb or '?' in gd:
        print('有格子名稱讀不出來（?）→ 請人看一眼圖')
    return 0 if not (miss_b or miss_d or extra_b) else 9


MAP_NAMES = {'薩姆吉爾的醫院': 1005, '薩姆吉爾村': 1000, '薩姆吉爾的便利商店': 1009, '瑪麗娜絲的便利商店': 2009, '瑪麗娜絲村': 2000,
             '村長家': 1006}


def map_from_name(uikit):
    """右上角地圖名 OCR → 地圖 ID（字稀有度加權涵蓋率，最高且 >= 0.5）。"""
    t = ''.join(uikit.ocr((735, 28, 175, 28), '-Zooms', '2,3')) + ''.join(uikit.ocr((735, 28, 175, 28), '-Zooms', '3,4'))
    t = t.replace(' ', '')
    if len(t) < 3:
        return None, t
    cnt = collections.Counter(c for n in MAP_NAMES for c in set(n))

    def sc(n):
        w = {c: 1.0 / cnt[c] for c in set(n)}
        return sum(w[c] for c in w if c in t) / (sum(w.values()) or 1.0)
    best = max(MAP_NAMES, key=sc)
    return (MAP_NAMES[best], t) if sc(best) >= 0.5 else (None, t)


def pos_from_landmark(winenv, label, npc_tile):
    """畫面上找 NPC 頭上的標籤（OCR 行位置），反推自己所在格子：標籤中心 → 人物身體(+21px) → 與 NPC 格的位移。"""
    r = winenv.run_ps('ocr.ps1', '300', '60', '620', '380', '-Zooms', '3,4')
    try:
        lines = json.loads((r.stdout.strip().splitlines() or [''])[-1]).get('lines', [])
    except Exception:
        return None
    key = label.replace(' ', '')
    for ln in lines:
        txt = ln['text'].replace(' ', '')
        if txt and (key in txt or txt in key) and len(txt) >= max(2, len(key) - 2):
            bx, by = int(ln['x']), int(ln['y']) + 21
            u, v = (bx - CX) / KX, (by - CY) / KY          # u = dx+dy, v = dy-dx
            dy, dx = (u + v) / 2, (u - v) / 2
            return (round(npc_tile[0] - dx), round(npc_tile[1] - dy))
    return None


def locate(uikit, walk, winenv, landmark=None):
    """多訊號定位（使用者 2026-10-14）：地圖名稱 + 地標反推 + HUD 座標數字，兩個以上一致才算數；
    回傳 (地圖ID, x, y, 來源說明) 或 None。座標數字讀不到不算失敗（以地標為準）。"""
    mp, name_txt = map_from_name(uikit)
    hud = walk.wait_pos(tries=2)
    lm = pos_from_landmark(winenv, landmark[0], landmark[1]) if landmark else None
    cands = []
    if lm:
        cands.append(('地標', lm))
    if hud and (mp is None or hud[0] == mp):
        cands.append(('HUD', (hud[1], hud[2])))
        mp = mp or hud[0]
    if mp is None:
        return None
    if lm and hud and abs(lm[0] - hud[1]) <= 2 and abs(lm[1] - hud[2]) <= 2:
        return (mp, hud[1], hud[2], f'地圖名「{name_txt}」+ 地標 + HUD 一致')
    if lm:
        return (mp, lm[0], lm[1], f'地圖名「{name_txt}」+ 地標（HUD {hud}）')
    if hud:
        return (mp, hud[1], hud[2], f'地圖名「{name_txt}」+ HUD')
    return None


def hospital_pos(uikit, walk):
    """醫院內位置：地圖名 + 「委託接取」標籤反推 + HUD 座標，取一致的（讀不到座標數字也行）。"""
    import winenv
    r = locate(uikit, walk, winenv, ('委託接取', (41, 42)))
    if r:
        print(f'定位：{r[3]} → 地圖 {r[0]} 座標 ({r[1]},{r[2]})')
        return (r[0], r[1], r[2])
    return None


def popup_open(uikit) -> bool:
    """「快速合成」彈窗有沒有開：標題 / 「所需物品」/ 成品名下方「合成」鈕，多區域多縮放，任一讀到就算"""
    for zm in ('2,3', '3,4'):
        t = ''.join(uikit.ocr((385, 60, 190, 40), '-Zooms', zm)) + ''.join(uikit.ocr((400, 112, 290, 36), '-Zooms', zm))
        if '快速' in t or '所需' in t or '物品' in t:
            return True
    return False


def read_page_no(uikit, pages):
    """每日任務面板目前第幾頁：先讀頁碼「n/5」（三組縮放投票）；數字讀不到時，用清單項目名稱跟各頁成品名比對。"""
    votes = collections.Counter()
    for zm in ('2,3', '3,4', '4,5'):
        t = ''.join(uikit.ocr((305, 405, 145, 44), '-Zooms', zm))
        m = re.search(r'(\d)\s*/\s*5', t)
        if m:
            votes[int(m.group(1))] += 1
    if votes:
        return votes.most_common(1)[0][0]
    txt = ''.join(uikit.ocr((200, 130, 360, 130), '-Zooms', '2,3')).replace(' ', '')
    cnt = collections.Counter(c for pg in pages for it in pg for c in set(it))
    best, bs = None, 0.0
    for i, pg in enumerate(pages, 1):
        sc = 0.0
        for it in pg:
            w = {c: 1.0 / cnt[c] for c in set(it)}
            sc += sum(w[c] for c in w if c in txt) / (sum(w.values()) or 1.0)
        if sc > bs:
            best, bs = i, sc
    return best if bs >= 0.8 else None


def craft_pages(pages_to_do, submit: bool, pages=None, no_craft: bool = False) -> int:
    """在醫院「委託接取」NPC 旁：開每日任務面板 → 切到指定頁 → 每項按「合成」→ 彈窗再按「合成」→ 該頁（可選）提交委託。
    座標用截圖座標（2026-10-14 在 11111 實測：NPC 身體 (447,160)、面板「合成」(490,160 / 226)、彈窗「合成」(330,340)、
    關閉彈窗 (707,92)、翻頁 下一頁 (497,427) / 上一頁 (258,427)、提交委託 (667,423)、關閉面板 (779,57)）。
    每一步後存截圖到 tools/.cache/craft-*.png，第一次請人看過再放手。"""
    import petdepot1920 as pd
    import uikit
    import walk
    for _ in range(2):
        pd.gui('key', '{ESC}', note='daily craft ESC')
        time.sleep(0.5)
    cur = hospital_pos(uikit, walk)
    if not cur or cur[0] != 1005:
        print(f'目前不在醫院（1005）：{cur} → 請先把角色帶到「委託接取」NPC 旁（約 37,49）')
        return 3
    sx, sy = npc_screen((cur[1], cur[2]), (41, 42))
    if not (340 <= sx <= 920 and 100 <= sy <= 420):
        print(f'委託接取 NPC 換算畫面 ({sx},{sy}) 在可點範圍外（目前座標 {cur[1]},{cur[2]}）→ 請先走近一點（37,49 附近）')
        return 3
    opened = False
    for k, (jx, jy) in enumerate(CLICK_JITTER[:6]):
        pd.click(*walk.PRIMER_XY, wait=NPC_PRIMER_GAP_MS, note='daily craft 引子')
        pd.click(sx + jx, sy + jy, wait=2200, note=f'daily craft 點委託接取（第 {k + 1} 次）')
        t = ''.join(uikit.ocr((400, 35, 170, 45), '-Zooms', '2,3'))
        if '每日' in t or '任務' in t:
            opened = True
            break
        pd.gui('key', '{ESC}', note='daily craft ESC')
        time.sleep(0.6)
    if not opened:
        print('沒開到「每日任務」面板 → 停手')
        return 4
    for pg in pages_to_do:
        for _ in range(8):                         # 切到指定頁：頁碼「n/5」多組縮放讀；讀不到數字就用該頁項目名稱比對
            now = read_page_no(uikit, pages)
            if now == pg:
                break
            if now is None:
                time.sleep(0.8)
                continue
            pd.click(*((497, 427) if now < pg else (258, 427)), wait=1300, note=f'daily craft 翻到第 {pg} 頁（現在 {now}）')
        else:
            print(f'翻不到第 {pg} 頁 → 停手')
            return 5
        time.sleep(1.0)
        pass  # 例行截圖拿掉（只留失敗 / 完成驗證的圖，2026-10-15 加速）；原：uikit.gui('shot', f'craft-p{pg}-before.png')
        for item, y in (() if no_craft else ((1, 160), (2, 226))):
            if item_state(uikit, y + 18) == 'green':     # 已經做出來（1/1 綠）就不要再做（重跑時會遇到）
                print(f'第 {pg} 頁第 {item} 項已是 1/1 → 跳過')
                continue
            pd.click(490, y, wait=1500, note=f'daily craft 第 {pg} 頁第 {item} 項 合成（開彈窗）')
            time.sleep(0.8)
            if not popup_open(uikit):
                print(f'第 {pg} 頁第 {item} 項：沒開到「快速合成」彈窗 → 停手')
                return 6
            pd.click(330, 340, wait=2000, note=f'daily craft 第 {pg} 頁第 {item} 項 合成（確認）')
            pass  # 例行截圖拿掉（只留失敗 / 完成驗證的圖，2026-10-15 加速）；原：uikit.gui('shot', f'craft-p{pg}-i{item}.png')
            if popup_open(uikit):
                pd.click(707, 92, wait=800, note='daily craft 關彈窗')
        time.sleep(0.8)
        st = [item_state(uikit, y) for y in (178, 243)]
        print(f'第 {pg} 頁合成結果：' + '、'.join(f'第 {i + 1} 項 {"1/1 完成" if v == "green" else "0/1 沒做出來" if v == "red" else "讀不到"}' for i, v in enumerate(st)))
        if st != ['green', 'green']:
            uikit.gui('shot', f'craft-p{pg}-fail.png')
            print(f'第 {pg} 頁沒有兩項都變綠色 1/1（常見原因：背包滿了放不下成品 / 缺材料）→ 不提交、停手；看 tools/.cache/craft-p{pg}-fail.png')
            return 9
        if submit:
            pd.click(667, 423, wait=2000, note=f'daily craft 第 {pg} 頁 提交委託')
            mark_crafted(pg)
            pass  # 例行截圖拿掉（只留失敗 / 完成驗證的圖，2026-10-15 加速）；原：uikit.gui('shot', f'craft-p{pg}-submit.png')
            if pg == 5 and not verify_all_done(pd, uikit):
                return 10
    print('craft 完成（每項都確認綠色 1/1 才提交）')
    return 0


def crafted_path() -> Path:
    return ROOT / 'tools' / '.cache' / f'daily-crafted-{os.environ.get("PSA_EXE_MATCH", "")}{os.environ.get("PSA_DAILY_TAG", "")}.json'


def mark_crafted(pg: int) -> None:
    """每頁提交後記一筆（一次做好幾頁時，中途失敗重跑不會重做已提交的頁；dailyrun 讀它）"""
    try:
        d = json.loads(crafted_path().read_text(encoding='utf-8')) if crafted_path().exists() else {}
    except (OSError, ValueError):
        d = {}
    if d.get('date') != time.strftime('%Y%m%d'):
        d = {'date': time.strftime('%Y%m%d'), 'pages': []}
    if pg not in d['pages']:
        d['pages'].append(pg)
    crafted_path().write_text(json.dumps(d), encoding='utf-8')


def item_state(uikit, y) -> str:
    """每日任務面板項目下方「n/1」的 n：綠色 = 已做出來（1/1）、紅色 = 還沒（0/1）。
    2026-10-14 實測：紅字像素 (127~193, 0, 0)；y = 178 / 243（第 1 / 2 項），x 270~282。"""
    c = uikit.px([(x, y + dy) for x in range(270, 284, 2) for dy in (-2, 0, 2)]) or []
    if any(g > 120 and g > r + 40 for r, g, b in c):
        return 'green'
    if any(r > 90 and g < 50 and b < 50 for r, g, b in c):
        return 'red'
    return '?'


REWARD = '裝備升級石'
NPC_PRIMER_GAP_MS = 400         # 點 NPC 前的引子間隔（使用者 2026-10-15：不要 0.1 秒那麼近）


def verify_all_done(pd, uikit) -> bool:
    """5 頁都提交後的完成驗證（使用者 2026-10-14：要防呆，避免圖片文字誤判）。三個訊號，至少兩個成立才算完成：
      A. 面板上兩個藍色「合成」鈕都消失（全部完成後項目只剩名稱 + 0/1，沒有按鈕；像素判斷，不靠 OCR）
      B. 右側「完成所有任務額外獎勵」計數讀到 5/5（OCR，多組縮放）
      C. 背包出現獎勵「裝備升級石」（背包整塊 OCR，名稱字元涵蓋率 >= 0.6，容許讀錯 1~2 字）
    只有一個成立 → 存截圖 daily-done-check*.png、回 False 讓人看。"""
    def blue(c):
        return c[2] > c[0] + 60
    btn = uikit.px([(490, 160), (490, 226), (700, 410)]) or []
    # 面板要真的開著（右下「提交委託」橘色鈕在，(700,410) 實測 193,130,61）才算「合成鈕消失」；面板沒開時按鈕位置也不是藍色，會誤判
    a_ok = len(btn) == 3 and not any(blue(c) for c in btn[:2]) and btn[2][0] > 180 and btn[2][2] < 120
    txt = ''.join(''.join(uikit.ocr((610, 195, 110, 55), '-Zooms', z)) for z in ('2,3', '3,4', '4,5'))
    b_ok = '5/5' in txt.replace(' ', '') or '5/5' in txt.replace('l', '/').replace('|', '/')
    uikit.gui('shot', 'daily-done-check.png')
    for _ in range(2):
        pd.gui('key', '{ESC}', note='daily 完成驗證 ESC')
        time.sleep(0.6)
    pd.click(757, 462, wait=1600, note='daily 完成驗證 開背包')
    bag = ''.join(''.join(uikit.ocr((470, 115, 335, 200), '-Zooms', z)) for z in ('2,3', '3,4'))
    cover = sum(1 for ch in set(REWARD) if ch in bag) / len(set(REWARD))
    c_ok = cover >= 0.6
    uikit.gui('shot', 'daily-done-check-bag.png')
    pd.click(832, 66, wait=700, note='daily 完成驗證 關背包')
    n = a_ok + b_ok + c_ok
    print(f'完成驗證：合成鈕消失={a_ok}、計數 5/5={b_ok}（讀到 {txt!r}）、背包有{REWARD}={c_ok}（涵蓋率 {cover:.2f}）→ {n}/3')
    if n >= 2:
        print(f'每日任務 5/5 完成，已拿到{REWARD}' if c_ok else '每日任務 5/5 完成（背包沒讀到獎勵名稱，請順便看一下 daily-done-check-bag.png）')
        return True
    print('完成訊號不足 2 個 → 不當作完成，請看 tools/.cache/daily-done-check*.png')
    return False


def withdraw_items(names, dn) -> set:
    """公共倉庫 → 背包：依格位記憶找倉庫格序 → 點該格 → 「取出」→ 倉庫格清空、背包放進第一個空格。"""
    import catchrun1920 as cr
    for _ in range(2):                              # 先 ESC 關掉每日任務等面板（面板開著會擋背包按鈕）
        cr.gui('key', '{ESC}', note='daily 領出前 ESC')
        time.sleep(0.6)
    got = set()
    todo = [n for n in names if n in dn['depot']]
    if not todo:
        return got
    cr.click(*cr.BAG_BTN, wait=1500, note='daily 開背包（領出）')
    cr.need_bag()
    cr.click(*cr.TAB_DEPOT, wait=1200, note='daily 倉庫分頁')
    cr.click(*cr.DEPOT_PUBLIC, wait=900, note='daily 公共倉庫')
    if not ensure_public(cr):
        cr.gui('key', '{ESC}', note='daily ESC')
        return got
    slots = cr.depot_slots()
    for nm in todo:
        i = pick_slot(cr, slots, nm, dn['depot'].index(nm), dn['depot'])
        if i is None:
            print(f'{nm}：公共倉庫裡找不到（每格都核對過浮窗名稱）→ 略過')
            continue
        if dn['depot'][i] != nm:
            print(f'{nm}：倉庫記憶說在第 {dn["depot"].index(nm) + 1} 格，實際在第 {i + 1} 格 → 已修正')
            dn['depot'][dn['depot'].index(nm)], dn['depot'][i] = dn['depot'][i], nm
        cr.click(*cr.POP_BTN, wait=1300, note=f'daily 取出 {nm}')
        dn['depot'][i] = None
        bag_acquire(dn, nm)
        got.add(nm)
        print(f'已從公共倉庫取出：{nm}（倉庫第 {i + 1} 格）')
    cr.gui('key', '{ESC}', note='daily ESC')
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    return got


# ---- 胡椒：個人倉庫固定格（使用者 2026-10-15：三種胡椒只有遠程店賣 → 使用者每個帳號 5 角色都先放好，用完原位置原順序放回）----
PEPPERS = ['普通的胡椒', '黑胡椒', '香味濃厚的胡椒']     # 個人倉庫第 1 / 2 / 3 格
PERSONAL_LIT = [(180, 110), (260, 110)]                # 個人分頁選中時亮黃 (255,221,139)、沒選中棕 (171,125,82)（2026-10-15 333 實機量）


def ensure_personal(cr) -> bool:
    """個人分頁一定要真的選中才存 / 取（同 ensure_public：遊戲會吃掉分頁點擊 → 進錯倉庫）"""
    import uikit
    for _ in range(4):
        c = uikit.px(PERSONAL_LIT)
        if c and all(v[0] > 225 and v[1] > 190 for v in c):
            return True
        cr.click(*cr.DEPOT_PERSONAL, wait=1000, note='daily 重點個人分頁')
    print('個人倉庫分頁切不過去 → 停手（不存 / 不取，避免進錯倉庫）')
    return False


def pepper_slot(cr, slots, name):
    """個人倉庫找胡椒：先點固定格（第 1/2/3 格）；浮窗名稱不對 → 改看第 1~3 格的另外兩格（順序被打亂成 321 / 231 也找得到，
    使用者 2026-10-15 要的防呆）。找到回格序（浮窗開著），找不到回 None。"""
    first = PEPPERS.index(name)
    for k in [first] + [i for i in range(3) if i != first]:
        x, y = slots[k]
        cr.click(x, y, wait=900, note=f'daily 個人倉庫第 {k + 1} 格（找 {name}）')
        if _pop_is(cr, name):
            if k != first:
                print(f'{name}：不在固定的第 {first + 1} 格，在第 {k + 1} 格（順序亂了，放回時會照 1/2/3 排回）')
            return k
        _close_pop(cr)
    return None


def _open_depot_tab(cr, personal: bool) -> bool:
    for _ in range(2):
        cr.gui('key', '{ESC}', note='daily 開倉庫前 ESC')
        time.sleep(0.6)
    cr.open_bag()
    cr.click(*cr.TAB_DEPOT, wait=1200, note='daily 倉庫分頁')
    cr.click(*(cr.DEPOT_PERSONAL if personal else cr.DEPOT_PUBLIC), wait=900, note='daily 個人倉庫' if personal else 'daily 公共倉庫')
    if (ensure_personal if personal else ensure_public)(cr):
        return True
    cr.gui('key', '{ESC}', note='daily ESC')
    return False


def pepper_get(names, dn) -> set:
    """個人倉庫 → 背包：要用的胡椒整疊取出（剩的合成後 pepper_put 放回）"""
    import catchrun1920 as cr
    got = set()
    todo = [n for n in PEPPERS if n in names and n not in dn['bag']]
    if not todo or not _open_depot_tab(cr, personal=True):
        return got
    slots = cr.depot_slots()
    for nm in todo:
        k = pepper_slot(cr, slots, nm)
        if k is None:
            print(f'{nm}：個人倉庫第 1~3 格都沒有 → 請補貨（每個角色第 1 普通 / 2 黑 / 3 香味濃厚，各 10 個）；照樣試合成')
            continue
        cr.click(*cr.POP_BTN, wait=1300, note=f'daily 取出 {nm}（個人倉庫）')
        bag_acquire(dn, nm)
        got.add(nm)
        print(f'已從個人倉庫第 {k + 1} 格取出：{nm}')
    cr.gui('key', '{ESC}', note='daily ESC')
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    return got


def pepper_put(dn) -> int:
    """背包剩的胡椒 → 個人倉庫，照 普通 / 黑 / 香味濃厚 的順序存（取出時那格空了，存入會回到第一個空格 = 原位置）。
    存完核對第 1~3 格；不對只印警告不停手。回傳沒放回 / 位置不對的數量。"""
    import catchrun1920 as cr
    todo = [n for n in PEPPERS if n in dn['bag']]
    if not todo:
        return 0
    if not _open_depot_tab(cr, personal=True):
        return len(todo)
    bag = cr.bag_slots()
    bad = 0
    for nm in todo:
        i = pick_slot(cr, bag, nm, dn['bag'].index(nm), dn['bag'])
        if i is None:
            print(f'{nm}：背包找不到（可能剛好用完）→ 那格會空著，請補貨')
            dn['bag'][dn['bag'].index(nm)] = None
            bad += 1
            continue
        cr.click(*cr.POP_BTN, wait=1300, note=f'daily 存入 {nm}（個人倉庫）')
        dn['bag'][i] = None
        print(f'已放回個人倉庫：{nm}')
    slots = cr.depot_slots()
    for k, nm in enumerate(PEPPERS):
        cr.click(*slots[k], wait=900, note=f'daily 核對個人倉庫第 {k + 1} 格')
        ok = _pop_is(cr, nm)
        _close_pop(cr)
        if not ok:
            bad += 1
            print(f'警告：個人倉庫第 {k + 1} 格不是 {nm}（用完了或順序亂了）→ 請補貨 / 排回 1 普通、2 黑、3 香味濃厚')
    cr.gui('key', '{ESC}', note='daily ESC')
    cr.click(*cr.CLOSE_BAG, wait=700, note='daily 關背包')
    return bad


def read_pages_from_panel(pd, uikit, winenv) -> list:
    """在醫院 NPC 旁：開每日任務面板 → 從第 1 頁讀到第 5 頁，每頁 2 個成品名（OCR 文字對照知識庫配方名，取最像的）。"""
    import walk
    recipes = load_recipes()
    names = list(recipes)
    cnt = collections.Counter(c for n in names for c in set(n))

    def best(txt):
        # 先去掉項目下方的計數「0/1」「1/1」：2026-10-14 '合成斧頭10/1合成斧頭1' 被當成「合成斧頭10」（其實是合成斧頭1 + 0/1）
        txt = re.sub(r'\d\s*/\s*\d', '', txt)
        t = fix_text(''.join(c for c in txt if c.strip()))
        if len(t) < 2:
            return ''
        exact = [n for n in names if n in t]
        if exact:                            # OCR 裡完整出現的成品名取最長的（2026-10-14：「特製2倍厚肉片」被選成「特製厚肉片」）
            return max(exact, key=len)

        def sc(n):
            w = {c: 1.0 / cnt[c] for c in set(n)}
            rec = sum(w[c] for c in w if c in t) / (sum(w.values()) or 1.0)
            seen = {c for c in set(t) if c in cnt}
            prec = sum(1.0 / cnt[c] for c in seen if c in n) / (sum(1.0 / cnt[c] for c in seen) or 1.0)
            return 2 * rec * prec / (rec + prec) if rec + prec else 0.0
        b = max(names, key=sc)
        return b if sc(b) >= 0.5 else ''
    for _ in range(2):
        pd.gui('key', '{ESC}', note='daily read ESC')
        time.sleep(0.5)
    cur = hospital_pos(uikit, walk)
    if not cur or cur[0] != 1005:
        raise SystemExit(f'不在醫院：{cur}')
    sx, sy = npc_screen((cur[1], cur[2]), (41, 42))
    opened = False
    for jx, jy in CLICK_JITTER[:6]:
        pd.click(sx + jx, sy + jy, wait=2200, note='daily read 點委託接取')
        if '每日' in ''.join(uikit.ocr((400, 35, 170, 45), '-Zooms', '2,3')):
            opened = True
            break
        pd.gui('key', '{ESC}', note='daily read ESC')
        time.sleep(0.6)
    if not opened:
        raise SystemExit('沒開到每日任務面板')
    for _ in range(5):                       # 回到第 1 頁（上一頁；到第 1 頁就不再變）
        pd.click(258, 427, wait=700, note='daily read 上一頁')
    out = []
    for pg in range(1, 6):
        time.sleep(0.8)
        lines = []
        # 舊讀法 + -Dark 0（淺色字；2026-10-15 11111 第 4 頁「肉粽」清單讀成空白、快速合成視窗只讀到「肉」）
        for opts in (('-Zooms', '3,4'), ('-Zooms', '3,4', '-Dark', '0')):
            r = winenv.run_ps('ocr.ps1', '200', '130', '360', '130', *opts)
            try:
                lines += json.loads((r.stdout.strip().splitlines() or [''])[-1]).get('lines', [])
            except Exception:
                pass
        rows = {0: '', 1: ''}
        for ln in lines:
            y = int(ln['y'])
            if 140 <= y <= 175 and int(ln['x']) < 480:
                rows[0] += ln['text']
            elif 205 <= y <= 240 and int(ln['x']) < 480:
                rows[1] += ln['text']
        page = [best(rows[0]), best(rows[1])]
        for k, y in ((0, 160), (1, 226)):
            t0 = ocrfix.fix(''.join(c for c in re.sub(r'\d\s*/\s*\d', '', rows[k]) if c.strip()))   # 套全表（2026-10-15 前只套單字：'蛋氵十' 沒修成蛋汁）
            if page[k] and page[k] in t0:
                continue
            # 不是完整讀到名稱 → 開「快速合成」視窗讀成品名（字較大較清楚；2026-10-14 第 1 頁讀成「酸海台」）
            pd.click(490, y, wait=1500, note=f'daily read 第 {pg} 頁第 {k + 1} 項 開快速合成確認名稱')
            pop = uikit.ocr_name((270, 248, 125, 24))        # 舊讀法 + -Dark 0
            pd.click(707, 92, wait=800, note='daily read 關快速合成')
            b2 = best(pop)
            print(f'  第 {pg} 頁第 {k + 1} 項：清單讀到 {rows[k]!r} → 快速合成視窗讀到 {pop!r} → {b2 or "（還是認不出）"}')
            if b2:
                page[k] = b2
        print(f'第 {pg} 頁：{page}（OCR {rows[0]!r} / {rows[1]!r}）')
        out.append(page)
        if pg < 5:
            pd.click(497, 427, wait=1100, note='daily read 下一頁')
    pd.gui('key', '{ESC}', note='daily read ESC')
    pd.click(779, 57, wait=700, note='daily read 關面板')
    return out


def hop_to(pd, uikit, walk, winenv, mp, target, landmarks, max_hops=7) -> bool:
    """店內走路（座標數字不穩 / 沒有通行格時用）：目前位置 = HUD 或「店家標籤反推」；
    把目標格換算成畫面位置，點地面走一段（畫面範圍內），再重新定位，直到離目標 <= 1 格。landmarks = [(標籤, (x,y)), ...]"""
    for hop in range(max_hops):
        me = None
        cur = walk.wait_pos(tries=2)
        if cur and cur[0] == mp:
            me = (cur[1], cur[2])
        if me is None:
            for label, tile in landmarks:
                me = pos_from_landmark(winenv, label, tile)
                if me:
                    break
        if me is None:
            print('hop：定位不到（HUD 與店家標籤都讀不到）')
            return False
        dx, dy = target[0] - me[0], target[1] - me[1]
        if abs(dx) <= 1 and abs(dy) <= 1:
            print(f'hop：已到 {target}（目前 {me}）')
            return True
        step = max(1.0, min(1.0, 6.0 / max(abs(dx), abs(dy))))   # 每次最多 6 格
        sx = int(CX + KX * ((dx + dy) * step))
        sy = int(CY + KY * ((dy - dx) * step))
        sx = max(360, min(900, sx))
        sy = max(120, min(400, sy))
        print(f'hop {hop + 1}：{me} → {target}，點地面 ({sx},{sy})')
        pd.click(sx, sy, wait=2200, note=f'daily hop {hop + 1}')
    return False


def go_home(walk, mp) -> bool:
    """不在固定原位置就走回去（用 walk.py 的通行格找路）；已在原位置回 True"""
    home = HOME.get(mp)
    if not home:
        return True
    import subprocess
    for _ in range(2):
        cur = walk.wait_pos(tries=3)
        if cur and cur[0] == mp and (cur[1], cur[2]) == home:
            return True
        subprocess.run([sys.executable, str(HERE / 'walk.py'), str(mp), str(home[0]), str(home[1])],
                       env=dict(os.environ, PYTHONIOENCODING='utf-8'), timeout=120)
    cur = walk.wait_pos(tries=3)
    return bool(cur and cur[0] == mp and abs(cur[1] - home[0]) <= 1 and abs(cur[2] - home[1]) <= 1)


def coins(uikit) -> int | None:
    """石幣：先 digitmatch 樣板（OCR 偶爾少讀一位：2026-10-14 4838000→483500），認不出才 OCR。
    OCR 兩個縮放讀到同一個數字（>= 4 位）才拿來補學樣板（少讀一位時切字數對不上，也不會學）。"""
    for _ in range(3):
        v, rows = shopnum(COIN_BOX)
        if v and len(v) >= 4:
            return int(v)
        ds = [d for d in (re.sub(r'\D', '', t) for t in uikit.ocr(COIN_BOX, '-Zooms', '2,3')) if len(d) >= 4]
        if ds:
            if len(ds) >= 2 and all(d == ds[0] for d in ds):
                shopnum_learn(COIN_BOX, rows, ds[0])
            return int(ds[0])
        time.sleep(0.4)
    return None


# 點不到時換幾個點位（人物身體比座標公式約大 ±10px）；順序 = 正中 → 往下（腳）→ 往上 → 左右 → 斜
CLICK_JITTER = [(0, -8), (0, 0), (0, 8), (-8, 0), (8, 0), (0, -16), (-10, -8), (10, -8), (0, 16), (-14, 0)]   # 實測（1009 / 醫院）：往上 8px 最常命中人物身體


def npc_title_ok(expect: str, t: str, all_names) -> bool:
    """對話標題（NPC 名）是不是這間店：跟其他店名比字的涵蓋率，期望那間得分最高才算"""
    tt = ''.join(c for c in t if c.strip() and c not in ',，.。|')
    if len(tt) < 2:
        return False
    cnt = collections.Counter(c for n in all_names for c in set(n))

    def score(n):
        w = {c: 1.0 / cnt[c] for c in set(n)}
        return sum(w[c] for c in w if c in tt) / (sum(w.values()) or 1.0)
    best = max(all_names, key=score)
    return best == expect and score(expect) >= 0.3


def dialog_open(uikit) -> bool:
    """NPC 對話有沒有開：多重判定（任一成立）= 按鈕區讀到「道具 / 商店 / 再見」、標題區有文字、內文有 hello / welcome。"""
    btn = ''.join(uikit.ocr((560, 265, 190, 36), '-Zooms', '2,3')) + ''.join(uikit.ocr((740, 265, 180, 36), '-Zooms', '2,3'))
    if any(k in btn for k in ('道具', '商店', '再見', '再见')):
        return True
    body = ''.join(uikit.ocr((560, 165, 340, 40), '-Zooms', '2,3')).lower()
    if any(k in body for k in ('hello', 'welcome', 'here')):
        return True
    title = npc_name(uikit, (590, 130, 200, 34))
    return len(title.replace(' ', '')) >= 3 and ('素材' in title or '店' in title or '賣' in title or '員' in title)


def load_shop_order(npc_id: int) -> list:
    """knowledge/economy/npc-shops.md → 該 NPC 商店的商品順序（遊戲清單 = 這個順序，2 欄、先左後右）"""
    out, on = [], False
    for ln in (ROOT / 'knowledge' / 'economy' / 'npc-shops.md').read_text(encoding='utf-8').splitlines():
        m = re.match(r'## .+? \(NPC (\d+)\)', ln)
        if m:
            if on:
                break
            on = int(m.group(1)) == npc_id
            continue
        if on:
            m = re.match(r'\| (.+?) \| \d+ \| \d+ 石幣', ln)
            if m:
                out.append(m.group(1).strip())
    return out


ROW_Y0, ROW_PITCH, COL_X = 125, 72, (280, 447)   # 清單第 1 列中心 y、列距、左右欄 x（960 座標）
ROW_Y_LAST = 393                                  # 拖到底時最後一列中心 y（2026-10-14 實測 2825 清單 33 項）
DRAG_ROWS = 2                                    # 一次拖 70px 約捲 2 列（實測）


OCR_FIX = ocrfix.CHAR_FIX       # 舊名保留（2026-10-15 合併到 ocrfix.py）


def title_matches(name, t, order) -> bool:
    """標題 OCR 常缺字 / 讀錯 / 重複 / 混逗號：先套已知混淆字，再用「字稀有度加權的涵蓋率」跟同店商品比，
    目標得分最高且 >= 0.4 才算（稀有字如 鹽 / 海星 的權重高，常見字如 的 / 普通 權重低）"""
    tt = ocrfix.fix(''.join(c for c in t if c.strip() and c not in ',，.。|'))
    if not tt:
        return False
    cnt = collections.Counter(c for n in order for c in set(n))

    seen = {c for c in set(tt) if c in cnt}          # OCR 讀到、且是這間店商品會用到的字（雜訊字不算）

    def score(n):
        # 涵蓋率（商品名的字有幾成被讀到）× 精確率（讀到的字有幾成屬於這個商品名）的調和平均，都用字稀有度加權。
        # 只看涵蓋率會偏向字少的名字：2026-10-14 「有睪的地瓜」（光澤讀錯）被判成「大的地瓜」（大 是常見字、權重低）
        w = {c: 1.0 / cnt[c] for c in set(n)}
        rec = sum(w[c] for c in w if c in tt) / (sum(w.values()) or 1.0)
        pw = sum(1.0 / cnt[c] for c in seen) or 1.0
        prec = sum(1.0 / cnt[c] for c in seen if c in n) / pw
        return 2 * rec * prec / (rec + prec) if rec + prec else 0.0
    # 標題常只讀到一半（「古代木」→「古亻古亻」）：不要求唯一最高，目標與最高分並列、且 >= 0.25 就算
    # （位置已由固定順序算出，標題只是攔截「明顯是別的商品」）
    top = max(score(n) for n in order)
    return score(name) >= top - 1e-9 and score(name) >= 0.25


def buy_item_idx(pd, uikit, order, name, qty, state) -> int:
    """依商店固定順序算位置；清單捲動位置記在 state['off']（開店時 0，不用先往上拉）。標題跟同店商品比對，不符就停手。"""
    import math
    idx = order.index(name)
    row, col = divmod(idx, 2)
    total_rows = math.ceil(len(order) / 2)
    max_off = max(0, total_rows - 5)
    off = state.get('off', 0)
    n_up = n_down = 0
    bottom_mode = False
    if row >= max_off and max_off > 0 and off != max_off:   # 最底部 5 列：直接拖到底（夾住），位置 = 從底往上數，不靠估計的每次捲動量
        n_up = max(1, math.ceil((max_off - off) / DRAG_ROWS)) + 2
        off = max_off
        bottom_mode = True
    elif row - off > 4:                               # 要往下看：拖上去
        while row - off > 4 and off < max_off:
            off = min(off + DRAG_ROWS, max_off)
            n_up += 1
    elif row < off:                                 # 要回頭看：拖下來
        while row < off:
            off = max(0, off - DRAG_ROWS)
            n_down += 1
    for _ in range(n_up):
        pd.gui('seq', DRAG_UP, note='daily 清單往下一段')
    for _ in range(n_down):
        pd.gui('seq', 'drag 360 310 360 380; wait 1400', note='daily 清單往回一段')
    state['off'] = off
    if n_up or n_down:
        time.sleep(1.6)                            # 拖完等清單停穩再點 / 再讀（使用者：不要秒截圖認證，避免上下錯亂）
    vis = row - off
    x, y = COL_X[col], ROW_Y0 + ROW_PITCH * vis
    if bottom_mode or (max_off > 0 and off == max_off):
        # 拖到底時最後一列貼齊清單底部（實測 y≈393，不是 413）：位置從底往上數；最上面被截一半的列點可見的下半部
        y = max(112, ROW_Y_LAST - ROW_PITCH * (total_rows - 1 - row))
    print(f'{name}：第 {idx + 1} 項 → 第 {row + 1} 列{"右" if col else "左"}欄，拖 {n_up}/{n_down} 次，點 ({x},{y})')
    t = ''
    cy = y
    for k, dy in enumerate((0,) if idx < 8 and state.get('off', 0) == 0 else (0, -8, -14)):          # 標題空白 = 點選沒生效 / 還沒畫好：等一下重讀，再微調點位（最底列貼著邊框）
        cy = y + dy
        pd.click(x, y + dy, wait=1100 + 400 * k, note=f'daily 選 {name}（第 {k + 1} 次）')
        for _ in range(2):
            t = shop_title(uikit)
            if t.strip():
                break
            time.sleep(0.6)
        if t.strip():
            break
    middle = idx >= 8 and not (max_off > 0 and row >= max_off)   # 拖動幅度不保證每次一樣 → 中間段（第 9 項起、且不在最後 5 列）一定驗證商品
    if middle and not title_matches(name, t, order):   # 前 8 項 / 最後 5 列用固定位置，不驗；中間段驗證標題
        got = [n for n in order if n != name and title_matches(n, t, order)]
        rows = {order.index(n) // 2 for n in got}
        if len(rows) == 1:
            # 點到別的商品：目標就在畫面上的話，直接從「點到的那列」推算目標的 y 去點，不再拖清單
            # （2026-10-14 r5：往回拖的捲動量很不穩，拖了等於沒拖 → 校正 3 次都點到同一個）
            r_act = next(iter(rows))
            ny = cy - (r_act - row) * ROW_PITCH
            if 112 <= ny <= 413:
                pd.click(x, ny, wait=1300, note=f'daily 直接點目標列 {name}')
                t2 = shop_title(uikit)
                if title_matches(name, t2, order):
                    print(f'標題 {t!r} = {got[0]}（偏 {r_act - row:+d} 列）→ 直接點 y={ny} 選到 {name}')
                    state['off'] = min(max(0, off + (r_act - row)), max_off)
                    t = t2
                    rows = set()
        if title_matches(name, t, order):
            pass
        elif len(rows) == 1 and state.get('_fixed', 0) < 3:
            # 目標不在畫面上：用點到的列號反推實際捲動位置，校正後重拖再點
            fix = rows.pop() - row
            print(f'標題 {t!r} = {got[0]}（偏 {fix:+d} 列）→ 校正捲動位置重點')
            state['off'] = min(max(0, off + fix), max_off)
            state['_fixed'] = state.get('_fixed', 0) + 1    # 最多校正 3 次（拖動慣性大，一次拖 2~4 列都有）
            try:
                return buy_item_idx(pd, uikit, order, name, qty, state)
            finally:
                state['_fixed'] = 0
        else:
            print(f'標題 {t!r} 與 {name} 不符（預期位置第 {idx + 1} 項）→ 不買、停手')
            return 5
    before = coins(uikit)
    for _ in range(qty - 1):
        pd.click(727, 286, wait=500, note='daily 數量 +')
    shown, qrows = shopnum(QTY_BOX)                  # 數量框：不等於 qty 就不按購買（2026-10-14 炭一次買成 27 個）
    if not shown:
        shown = ''.join(uikit.ocr(QTY_BOX, '-Zooms', '2,3'))
        if re.sub(r'\D', '', shown) == str(qty):
            shopnum_learn(QTY_BOX, qrows, str(qty))
    digits = re.sub(r'\D', '', shown)
    if qty > 1 and digits and digits != str(qty):        # 讀得到數字才比對（讀不到不擋，購買後仍用石幣差核對）
        print(f'{name}：數量框讀到 {shown!r}，預期 {qty} → 不按購買、停手')
        return 6
    # 花費欄（數量下面那格，(667,322)）：按購買前要等於 500×數量；購買成功後會歸 0（使用者 2026-10-14）
    pr = price_reads(uikit, 500 * qty)
    price0 = next((r for r in pr if r), '')
    if price0 and price0 != str(500 * qty) and all(r == price0 for r in pr if r):
        print(f'{name}：花費欄讀到 {price0}，預期 {500 * qty}（數量不對）→ 不按購買、停手')
        return 6
    pd.click(*BUY_BTN, wait=1200, note=f'daily 購買 {name}×{qty}')
    pd.click(*CONFIRM_BTN, wait=1500, note='daily 確定')
    if '提示' in ''.join(uikit.ocr((385, 105, 190, 40), '-Zooms', '2,3')):
        pd.gui('key', '{ESC}', note='daily 提示彈窗還在 → ESC')
        time.sleep(0.6)
    after = coins(uikit)
    for _ in range(4):        # 石幣 OCR 偶爾少讀一位（2026-10-14 r4：4058499→405999，其實有買到）→ 對不上就重讀幾次
        if before is None or after is None or before - after == 500 * qty:
            break
        time.sleep(0.6)
        after = coins(uikit)
    if before is not None and after is not None and before - after != 500 * qty:
        # 第二個訊號：購買成功後數量框會歸 0（使用者 2026-10-14）。只有一位數字、字形差很多，多組縮放都讀成 0 才算
        reads = price_reads(uikit)
        # 購買後花費欄歸 0；單一個「0」OCR 常讀不出來（2026-10-14 r4 連 3 次 ''）→ 買前讀到 500×數量、買後全是 0 或讀不到 = 有變化 = 買到
        # （沒買成功時花費欄會維持原數字，讀得到就不會被當成功）
        if price0 == str(500 * qty) and all(r in ('', '0') for r in reads):
            print(f'石幣 {before}→{after} 對不上，但花費欄 {price0} → 0（3 次都讀到 0，購買成功會歸 0）→ 當作已買 {name}×{qty}')
            return 0
        print(f'石幣 {before}→{after}，與預期少 {500 * qty} 不符；花費欄 {price0} → {reads} → 開背包看該格有沒有買到')
        return 11
    print(f'已買 {name}×{qty}（石幣 {before}→{after}）')
    return 0


def _title_ok(name, t) -> bool:
    import difflib
    tt = t.replace(' ', '')
    if len(tt) % 2 == 0 and tt[:len(tt) // 2] == tt[len(tt) // 2:]:
        tt = tt[:len(tt) // 2]                  # OCR 常把標題讀兩次（厚的皮厚的皮）
    return name in tt or difflib.SequenceMatcher(None, name, tt).ratio() >= 0.75


def buy_item(pd, uikit, winenv, name, qty) -> int:
    """清單先捲回最上 → OCR 找候選（相似度排序，名稱可能被讀錯 / 折行）→ 逐個點、標題核對 → 數量 → 購買 → 確定 → 石幣核對。
    候選標題不對就換下一個、都不對才往下捲（最多 14 次）。回 0 成功"""
    import difflib
    for _ in range(3):
        pd.gui('seq', 'drag 360 310 360 410; wait 500', note='daily 清單捲回最上')
    tried = set()
    for _scroll in range(22):
        lines = []
        for zm in ('3,4', '2,3'):                 # 兩組縮放各讀一次合併（單一組合常漏字 / 讀錯）
            r = winenv.run_ps('ocr.ps1', *[str(v) for v in LIST_BOX], '-Zooms', zm)
            try:
                lines += json.loads((r.stdout.strip().splitlines() or [''])[-1]).get('lines', [])
            except Exception:
                pass
        cands = []
        for ln in lines:
            txt = ln['text'].replace(' ', '')
            sc = 1.0 if name in txt else difflib.SequenceMatcher(None, name, txt).ratio()
            if sc >= 0.55:
                cands.append((sc, int(ln['x']), int(ln['y'])))
        cands.sort(reverse=True)
        for sc, x, y in cands[:3]:
            key = (x // 20, y // 20, _scroll)
            if key in tried:
                continue
            tried.add(key)
            pd.click(x, y, wait=1100, note=f'daily 選 {name}')
            t = shop_title(uikit)
            if not _title_ok(name, t):
                continue                          # 不是這個：不買，換下一個候選
            before = coins(uikit)
            for _ in range(qty - 1):
                pd.click(727, 286, wait=300, note='daily 數量 +')
            pd.click(*BUY_BTN, wait=1200, note=f'daily 購買 {name}×{qty}')
            pd.click(*CONFIRM_BTN, wait=1500, note='daily 確定')
            if '提示' in ''.join(uikit.ocr((385, 105, 190, 40), '-Zooms', '2,3')):
                pd.gui('key', '{ESC}', note='daily 提示彈窗還在 → ESC')
                time.sleep(0.6)
            after = coins(uikit)
            if before is not None and after is not None and before - after != 500 * qty:
                print(f'石幣 {before}→{after}，與預期少 {500 * qty} 不符，停手')
                return 6
            print(f'已買 {name}×{qty}（石幣 {before}→{after}）')
            return 0
        pd.gui('seq', DRAG_UP, note='daily 清單小幅下拉')
    print(f'清單找不到 {name} → 停手')
    return 7


if __name__ == '__main__':
    _rc = 1
    try:
        _rc = main()
    finally:
        if _rc != 0:
            recover()
    sys.exit(_rc)
