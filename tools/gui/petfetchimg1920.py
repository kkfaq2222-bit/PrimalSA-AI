#!/usr/bin/env python3
r"""用「頭像顏色樣板」從寵物倉庫領回指定的寵物（1920×1017 專用；只用標準庫 + petdepot1920 / uikit）。

為什麼不用「永遠點第一格」：個人倉庫裡混著別的寵物，而且取出一隻後後面的會往前補位。
所以每領一隻都要：現場讀整頁 20 格 → 用樣板找目標 → 點選 → 取出 → 重新讀整頁 → 再找下一隻（每一隻都重新定位）。

樣板 = 每格頭像區 4×4 取樣點的 RGB（16 點）；不依賴名稱（剛抓的寵物名稱是四圍數字，OCR 讀不出種類）。
樣板檔：tools/.cache/petdepot-tpl.json（不進 git）。每種寵物第一次放進倉庫時用 learn 學一次。

用法（專案根目錄；先在遊戲開好寵物面板 → 倉庫 → 個人 / 公共分頁）：
  scan  --client kkfaq22222 [--tab personal|public]                     讀 20 格，印每格最像哪個樣板與距離（唯讀）
  learn --client kkfaq22222 --slot 3 --name 克邦凱斯 [--tab ...]          把第 3 格（1~20，由左到右由上到下）的頭像存成樣板「克邦凱斯」
  names --client kkfaq22222 [--tab ...]                                 唯讀：印 20 格名稱 OCR 與是否為數字名稱
  fetch --client kkfaq22222 --role 2 --numeric 3 [--do]                 領 3 隻「名稱是數字」的寵物（別的寵物都是本名，不用樣板）
  move  --client kkfaq22222 --role 3 --name 火雞 --n 4 [--do]            個人倉庫 → 公共：依樣板搬 N 隻（寵物欄須為空）
  storebar --client kkfaq22222 --role 2 --slots 2,3,4,5 [--do]          把寵物欄第 2~5 格存公共倉庫（第 1 格不動）
  snap  --client kkfaq22222 [--tab ...]                                 存入寵物「之前」先拍一次整頁
  learn --client kkfaq22222 --new --name 克邦凱斯 [--tab ...]             存入後跑：變動的那一格就是剛存的，直接學成「克邦凱斯」（名稱是數字時用這個）
  fetch --client kkfaq22222 --role 2 --names 克邦凱斯,加克拉,加格 [--tab personal] [--do]
        預設只預覽（找得到幾隻、在哪格），加 --do 才真的取出；每隻取完重新定位，數量不對就停手。

使用者規劃（2026-10-12）：角色 2 第一格留邦恩吉（第四輪抓的），只從個人倉庫領克邦凱斯 / 加克拉 / 加格；
角色 3 第一格留奇寶，只領火雞 / 克克洛斯 / 霍爾克。寵物欄第 2~5 格先存進個人倉庫再領。

座標（截圖 960×508，2026-10-12 實機量）：格子 5 欄 × 4 列，中心 x = 541 + 66.75*欄、y = 166 + 67*列；
個人 / 公共分頁 592,100 / 757,100；取出寵物 362,430（選中倉庫寵物時，和「存入寵物」同一個位置）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
TPL_PATH = ROOT / 'tools' / '.cache' / 'petdepot-tpl.json'

COLS, ROWS = 5, 4
XS = [542, 608, 675, 742, 808]          # 與 petshark / petgive 同一組（實機校準）
YS = [170, 237, 303, 370]
STORE_BTN = (360, 430)                  # 選中寵物欄的寵物時是「存入寵物」
SAMPLE_DX = (-21, -7, 7, 21)           # 頭像區取樣（避開上方名稱字、下方等級字）
SAMPLE_DY = (-14, -4, 6, 16)
TAB = {'personal': (592, 100), 'public': (757, 100)}
TAKE_BTN = (362, 430)
SAME_SPECIES_MAX = 35.0                # 同一批同種寵物兩兩距離的上限（learn --new）
MATCH_MAX = 28.0                       # 平均每通道差距門檻（RGB 0~255）；超過就當作不是這個
AMBIG_MARGIN = 8.0                     # 最佳與「不同名稱」次佳至少差這麼多，否則判為不明確


# ---------- 純函式（離線測試用）----------
def slot_center(i: int):
    """第 i 格（0~19，由左到右由上到下）的中心 (x, y)"""
    return XS[i % COLS], YS[i // COLS]


def slot_points(i: int) -> list:
    cx, cy = slot_center(i)
    return [(cx + dx, cy + dy) for dy in SAMPLE_DY for dx in SAMPLE_DX]


def dist(a: list, b: list) -> float:
    """兩個向量（[(r,g,b)×16]）的平均每通道絕對差"""
    if not a or len(a) != len(b):
        return 999.0
    return sum(abs(p - q) for ca, cb in zip(a, b) for p, q in zip(ca, cb)) / (3 * len(a))


def best_match(vec: list, tpls: dict):
    """→ (名稱 or None, 距離, 狀態)；狀態 ok / far（太遠）/ ambiguous（最佳與次佳名稱太接近）/ none（沒樣板）"""
    if not tpls:
        return None, 999.0, 'none'
    ds = sorted((min(dist(vec, v) for v in vs), n) for n, vs in tpls.items())
    d0, n0 = ds[0]
    if d0 > MATCH_MAX:
        return None, d0, 'far'
    if len(ds) > 1 and ds[1][0] - d0 < AMBIG_MARGIN:
        return None, d0, 'ambiguous'
    return n0, d0, 'ok'


def is_numeric_name(text: str) -> bool:
    """剛抓的寵物名稱是四圍數字（例 49/10/5/4）；本名都是中文。數字 >= 3 個且中文字 <= 1 個才算。"""
    t = str(text or '')
    digits = sum(ch.isdigit() for ch in t)
    cjk = sum('一' <= ch <= '鿿' for ch in t)
    return digits >= 3 and cjk <= 1


def load_tpls() -> dict:
    try:
        d = json.loads(TPL_PATH.read_text(encoding='utf-8'))
        return {n: [[tuple(c) for c in v] for v in vs] for n, vs in d.items()}
    except (OSError, ValueError):
        return {}


def save_tpls(t: dict) -> None:
    TPL_PATH.parent.mkdir(parents=True, exist_ok=True)
    TPL_PATH.write_text(json.dumps(t, ensure_ascii=False), encoding='utf-8')


# ---------- 遊戲操作 ----------
def take_label_ok() -> bool:
    """選中的是倉庫寵物時左下按鈕是「取出寵物」；若選取還停在寵物欄的寵物上，同位置是「存入寵物」，點下去會把自己的寵物存走
    （2026-10-12 角色 1 的克邦凱斯因此被存走）。按之前一定要確認。"""
    import uikit
    t = ''.join(uikit.ocr((300, 412, 125, 36), '-Zooms', '2,3'))
    return '取出' in t or ('取' in t and '存' not in t)


def ensure_take_ready(x: int, y: int) -> bool:
    """點選倉庫格後按鈕要變成「取出寵物」。遊戲偶爾吃掉這一下點擊（或標籤還沒更新）：
    先等一下重讀，還不是就重點該格（最多 2 次），仍不是才放棄（不會去按「存入寵物」）。"""
    import time as _t
    import petdepot1920 as pd
    for k in range(3):
        _t.sleep(0.4)
        if take_label_ok():
            return True
        if k < 2:
            pd.click(x, y, wait=800, note=f'petfetchimg 重點倉庫格（第 {k + 1} 次重試）')
    return False


def read_grid():
    """一次讀 20 格 → [vec×20]；讀不到回 None"""
    import uikit
    pts = [p for i in range(COLS * ROWS) for p in slot_points(i)]
    cols = uikit.px(pts)
    if not cols:
        return None
    n = len(SAMPLE_DX) * len(SAMPLE_DY)
    return [cols[i * n:(i + 1) * n] for i in range(COLS * ROWS)]


def name_box(i: int):
    cx, cy = slot_center(i)
    return (cx - 32, cy - 31, 64, 20)       # 格子上方名稱字（寵物名疊在頭像上緣）


def read_names(only_filled=None):
    """20 格名稱 OCR → [str×20]（空格回 ''）；唯讀"""
    import uikit
    out = []
    for i in range(COLS * ROWS):
        if only_filled is not None and i not in only_filled:
            out.append('')
            continue
        try:
            out.append(''.join(uikit.ocr(name_box(i), '-Zooms', '2,3')).strip())
        except Exception:
            out.append('')
    return out


def bar_filled():
    import petdepot1920 as pd
    return [i for i in range(5) if not pd.slot_empty(i)]


def goto(role: int, tab: str):
    import petdepot1920 as pd
    try:                                    # 外掛面板還開著（catchrun 剛抓完）會蓋住寵物鈕 → 寵物面板打不開（2026-10-12 火雞 r1）
        import ass
        if ass.panel_open():
            ass.close_panel()
    except Exception:
        pass
    if not pd.open_panel():
        raise SystemExit('寵物面板打不開')
    other = 0 if role != 1 else 1          # 先切到別的角色再切回來才會刷新寵物欄（剛抓完的第 5 隻否則還顯示空格；2026-10-12 實測）
    pd.click(pd.ROLE_X, pd.ROLE_Y[other], wait=900, note='petfetchimg 先切別人（刷新）')
    pd.click(pd.ROLE_X, pd.ROLE_Y[role - 1], wait=1200, note=f'petfetchimg 選角色 {role}')
    pd.click(*pd.TAB_DEPOT, wait=1300, note='petfetchimg 倉庫分頁')
    pd.click(*TAB[tab], wait=900, note=f'petfetchimg {tab} 分頁')


def close_pet_panel_if_open() -> None:
    try:
        import petdepot1920 as pd
        for _ in range(3):
            if not pd.panel_open():
                return
            pd.click(*pd.CLOSE_X, wait=700, note='petfetchimg 關寵物面板')
    except Exception:
        pass


def maybe_open(a):
    """--open-role N：先開寵物面板、選角色 N、倉庫、--tab 分頁（沒給就用目前畫面）"""
    if getattr(a, 'open_role', 0):
        goto(a.open_role, a.tab)


def cmd_scan(a):
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    tpls = load_tpls()
    print(f'樣板：{", ".join(tpls) or "（無）"}')
    for i, vec in enumerate(grid):
        n, d, st = best_match(vec, tpls)
        print(f'  第 {i + 1:2d} 格  {n or "-":<8} 距離 {d:5.1f}  {st}')
    return 0


def cmd_names(a):
    """唯讀：印 20 格名稱 OCR 與是否判為數字名稱（先用它確認 OCR 讀得準，再用 fetch --numeric）"""
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    tpls = load_tpls()
    names = read_names()
    for i, (nm, vec) in enumerate(zip(names, grid)):
        empty = best_match(vec, {'空': tpls['空']})[0] == '空' if '空' in tpls else None
        print(f'  第 {i + 1:2d} 格  {nm!r:<24} 數字名稱={is_numeric_name(nm)}' + ('' if empty is None else f'  空格={empty}'))
    return 0


def snap_path(a) -> Path:
    return ROOT / 'tools' / '.cache' / f'petdepot-snap-{a.client}-{a.tab}.json'


def cmd_snap(a):
    """存入寵物「之前」先拍一次整頁（learn --new 用來找出剛存進去的那一格）"""
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    snap_path(a).parent.mkdir(parents=True, exist_ok=True)
    snap_path(a).write_text(json.dumps(grid), encoding='utf-8')
    print(f'已拍下 {a.tab} 倉庫整頁（存入寵物後再跑 learn --new --name 名稱）')
    return 0


def changed_slots(old: list, new: list, thr: float = 12.0) -> list:
    """兩次整頁快照之間「頭像變了」的格號（0 起算）"""
    return [i for i, (o, n) in enumerate(zip(old, new)) if dist([tuple(c) for c in o], n) > thr]


def cmd_learn(a):
    if not a.name:
        print('要用 --name 指定名稱')
        return 2
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    if a.new:
        try:
            old = json.loads(snap_path(a).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            print('沒有存入前的快照：先在存入寵物前跑 snap')
            return 2
        ch = changed_slots(old, grid)
        # 同一種寵物的頭像會有動作 / 位置差（實測 4 隻火雞兩兩差 3~22、不同種差 70 以上）→ 門檻 35
        if not ch or any(dist(grid[ch[0]], grid[j]) > SAME_SPECIES_MAX for j in ch[1:]):
            print(f'變動的格子 {[i + 1 for i in ch]} 不是同一種（或沒有變動）→ 不學，請改用 --slot 指定')
            return 5
        a.slot = ch[0] + 1
        print(f'剛存進去的是第 {a.slot} 格')
    vecs = [grid[i] for i in ch] if a.new else [grid[a.slot - 1]]   # --new：剛存進去的每一隻都當變體（涵蓋頭像動作差）
    tpls = load_tpls()
    tpls.setdefault(a.name, [])
    added = 0
    for vec in vecs:
        if any(dist(vec, v) < 3.0 for v in tpls[a.name]):
            continue
        if len(tpls[a.name]) >= 6:
            tpls[a.name].pop(0)
        tpls[a.name].append(vec)
        added += 1
    save_tpls(tpls)
    print(f'已存「{a.name}」樣板（新增 {added} 個，共 {len(tpls[a.name])} 個變體）')
    return 0


def cmd_storebar(a):
    """把角色 --role 寵物欄的 --slots（1~5，例 2,3,4,5）存進 --tab 倉庫（預設公共）；從大號往小號存（存了不影響前面格位）"""
    import time
    import petdepot1920 as pd
    slots = sorted({int(x) for x in a.slots.split(',') if x.strip()}, reverse=True)
    if not slots or not all(1 <= x <= 5 for x in slots):
        print('--slots 要寫 1~5，例如 2,3,4,5')
        return 2
    tab = 'public' if a.tab == 'personal' and not a.tab_given else a.tab
    goto(a.role, tab)
    for sl in slots:
        if pd.slot_empty(sl - 1):
            print(f'寵物欄第 {sl} 格是空的 → 停手')
            return 4
        pd.log(f'角色 {a.role} 欄 {sl} → {tab} 倉庫' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        pd.click(pd.SLOT_X, pd.SLOT_Y[sl - 1], wait=700, note=f'petfetchimg 選欄 {sl}')
        pd.click(*STORE_BTN, wait=1000, note='petfetchimg 存入寵物')
        for _ in range(10):
            if pd.warn_dialog():
                pd.click(*pd.WARN_OK, wait=1000, note='petfetchimg 提示窗確定')
            if pd.slot_empty(sl - 1):
                break
            time.sleep(0.5)
        if not pd.slot_empty(sl - 1):
            print(f'欄 {sl} 存不進去 → 停手')
            return 5
    pd.log('完成' if a.do else '預覽結束（加 --do 才真的存）')
    return 0


def cmd_move(a):
    """個人倉庫 → 公共倉庫：依樣板找出 --name 的寵物 --n 隻，逐隻「取出到寵物欄第 1 格 → 存入公共」（寵物欄必須是空的）"""
    import petdepot1920 as pd
    tpls = load_tpls()
    if a.name not in tpls:
        print(f'沒有「{a.name}」樣板（先用 learn 學）')
        return 2
    goto(a.role, 'personal')
    if bar_filled():
        print('寵物欄不是空的 → 停手')
        return 4
    for k in range(1, a.n + 1):
        pd.click(*TAB[a.tab], wait=800, note='petfetchimg 來源分頁')
        grid = read_grid()
        if grid is None:
            print('讀不到畫面 → 停手')
            return 3
        hits = [(d, i) for i, v in enumerate(grid) for n, d, st in [best_match(v, tpls)] if n == a.name]
        if not hits:
            print(f'找不到「{a.name}」→ 停手（已搬 {k - 1} 隻）')
            return 5
        d, i = min(hits)
        pd.log(f'第 {k}/{a.n} 隻「{a.name}」在第 {i + 1} 格（距離 {d:.1f}）' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        x, y = slot_center(i)
        pd.click(x, y, wait=800, note=f'petfetchimg 選第 {i + 1} 格')
        if not ensure_take_ready(x, y):
            print('按鈕不是「取出寵物」→ 不按、停手')
            return 8
        pd.click(*TAKE_BTN, wait=1100, note='petfetchimg 取出寵物')
        for _ in range(8):
            if not pd.slot_empty(0):
                break
            import time
            time.sleep(0.5)
        if pd.slot_empty(0):
            print('取出後欄 1 仍空 → 停手')
            return 6
        pd.click(*TAB['public'], wait=800, note='petfetchimg 公共分頁')
        pd.click(pd.SLOT_X, pd.SLOT_Y[0], wait=700, note='petfetchimg 選欄 1')
        pd.click(*STORE_BTN, wait=1000, note='petfetchimg 存入公共')
        for _ in range(8):
            if pd.slot_empty(0):
                break
            import time
            time.sleep(0.5)
        if not pd.slot_empty(0):
            print('存入公共後欄 1 仍有寵物 → 停手')
            return 7
    pd.log(f'完成：搬了 {a.n} 隻「{a.name}」到公共' if a.do else '預覽結束（加 --do 才真的搬）')
    return 0


def cmd_fetch_numeric(a):
    """領「名稱是數字」的寵物 N 隻（別的寵物都是本名，不會錯亂）：每領一隻重新讀整頁名稱、重新定位"""
    import petdepot1920 as pd
    goto(a.role, a.tab)
    before = bar_filled()
    free = 5 - len(before)
    pd.log(f'角色 {a.role} 寵物欄 {len(before)} 隻、空 {free} 格；要領 {a.numeric} 隻數字名稱寵物（{a.tab}）')
    if free < a.numeric:
        print('寵物欄空格不夠 → 停手')
        return 4
    taken = 0
    for k in range(1, a.numeric + 1):
        names = read_names()
        hits = [i for i, nm in enumerate(names) if is_numeric_name(nm)]
        if not hits:
            print(f'找不到數字名稱的寵物 → 停手（已領 {taken} 隻）')
            return 5
        i = hits[0]
        pd.log(f'第 {k}/{a.numeric} 隻：第 {i + 1} 格 {names[i]!r}（共 {len(hits)} 隻數字名稱）' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        x, y = slot_center(i)
        pd.click(x, y, wait=800, note=f'petfetchimg 選第 {i + 1} 格')
        if not ensure_take_ready(x, y):
            print('按鈕不是「取出寵物」→ 不按、停手')
            return 8
        pd.click(*TAKE_BTN, wait=1200, note='petfetchimg 取出寵物')
        now = bar_filled()
        if len(now) != len(before) + taken + 1:
            print(f'取出後寵物欄數量不對（{len(now)}）→ 停手')
            return 6
        taken += 1
    pd.log(f'完成：領回 {taken} 隻' if a.do else '預覽結束（加 --do 才真的取出）')
    return 0


def cmd_fetch(a):
    if a.numeric:
        return cmd_fetch_numeric(a)
    import petdepot1920 as pd
    tpls = load_tpls()
    names = [n.strip() for n in a.names.split(',') if n.strip()]
    missing = [n for n in names if n not in tpls]
    if missing:
        print(f'沒有這些樣板：{missing}（先用 learn 學）')
        return 2
    goto(a.role, a.tab)
    before = bar_filled()
    free = 5 - len(before)
    pd.log(f'角色 {a.role} 寵物欄 {len(before)} 隻、空 {free} 格；要領 {len(names)} 隻（{a.tab}）')
    if free < len(names):
        print('寵物欄空格不夠 → 停手')
        return 4
    taken = 0
    for k, name in enumerate(names, 1):
        grid = read_grid()
        if grid is None:
            print('讀不到畫面 → 停手')
            return 3
        hits = []
        for i, vec in enumerate(grid):
            n, d, st = best_match(vec, tpls)       # 對全部樣板比，避免把別種誤認成目標
            if n == name:
                hits.append((d, i))
        if not hits:
            print(f'找不到「{name}」→ 停手（已領 {taken} 隻）')
            return 5
        d, i = min(hits)
        pd.log(f'第 {k}/{len(names)} 隻「{name}」在第 {i + 1} 格（距離 {d:.1f}）' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        x, y = slot_center(i)
        pd.click(x, y, wait=800, note=f'petfetchimg 選第 {i + 1} 格「{name}」')
        if not ensure_take_ready(x, y):
            print('按鈕不是「取出寵物」→ 不按、停手')
            return 8
        pd.click(*TAKE_BTN, wait=1200, note='petfetchimg 取出寵物')
        now = bar_filled()
        if len(now) != len(before) + taken + 1:
            print(f'取出後寵物欄數量不對（{len(now)}）→ 停手')
            return 6
        taken += 1
    pd.log(f'完成：領回 {taken} 隻' if a.do else '預覽結束（加 --do 才真的取出；預覽時清單沒變，同種多隻會都指到同一格）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='用頭像樣板從倉庫領回指定寵物')
    ap.add_argument('cmd', choices=['scan', 'names', 'snap', 'learn', 'fetch', 'move', 'storebar'])
    ap.add_argument('--client', default='kkfaq22222')
    ap.add_argument('--tab', choices=list(TAB), default=None)
    ap.add_argument('--slots', default='')
    ap.add_argument('--open-role', type=int, default=0, help='scan / names / snap / learn：先開面板並切到這個角色的倉庫')
    ap.add_argument('--slot', type=int, default=1)
    ap.add_argument('--name', default='')
    ap.add_argument('--role', type=int, default=2)
    ap.add_argument('--names', default='')
    ap.add_argument('--new', action='store_true', help='learn：用 snap 的快照找出剛存進去的那一格')
    ap.add_argument('--numeric', type=int, default=0, help='fetch：領名稱是數字的寵物 N 隻（不用樣板）')
    ap.add_argument('--n', type=int, default=4)
    ap.add_argument('--do', action='store_true')
    a = ap.parse_args(argv)
    a.tab_given = a.tab is not None
    a.tab = a.tab or 'personal'
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    winenv.enable_server()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    fn = {'scan': cmd_scan, 'names': cmd_names, 'snap': cmd_snap, 'learn': cmd_learn, 'fetch': cmd_fetch, 'move': cmd_move, 'storebar': cmd_storebar}[a.cmd]
    try:
        return fn(a)
    finally:
        close_pet_panel_if_open()      # 不留著面板（會蓋住外掛按鈕，後面的抓寵就打不開外掛面板；2026-10-12 火雞 r3）


if __name__ == '__main__':
    sys.exit(main())
