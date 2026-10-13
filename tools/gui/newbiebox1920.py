#!/usr/bin/env python3
r"""轉生後 1 級：開「N 轉新手禮盒」→ 吃 2 倍智慧果 + 離線水晶 → 安撫之素 / 寵物誘餌存共用倉庫（1920×1017 專用）。

規則（使用者 2026-10-13）：
  - 目前幾轉就開幾轉的禮盒（N = 角色目前轉數；打開會得到下一轉的禮盒，不開）。
  - 禮盒在背包或個人倉庫（禮盒不能放共用倉庫）；在個人倉庫就先取出。
  - 開失敗可以再多開 2 次（共 3 次）；都失敗就放棄，不影響後面步驟、也不會停手（退出碼仍是 0）。
  - 打開後：2 倍智慧果 → 使用；離線水晶 → 打開；安撫之素、寵物誘餌 → 存共用倉庫。
  - 5 人各自處理。

辨識方式（使用者 2026-10-13：要能直接辨識，不要逐格點開確認）：
  背包 / 倉庫開著「顯示道具名」，每格上方的名稱文字一次 OCR 讀完（名稱常少讀一個字，所以用關鍵字的兩字片段比對）。
  認得出的格子直接動手；只有真的要「使用 / 取出 / 存入」時才點它。用完再讀一次名稱確認那格不見了。
  禮盒的轉數直接從名稱「N轉新手禮盒」的數字讀；名稱讀不到數字才交給浮窗標題再確認。

用法（專案根目錄）：
  uv run --no-project python tools/gui/newbiebox1920.py --client kkfaq22222 --roles 1,2,3,4,5 --dry   # 只認不動
  uv run --no-project python tools/gui/newbiebox1920.py --client kkfaq22222 --do
  --trans N  讀不到角色轉數時用這個數字
退出碼：0 完成（含個別失敗，只記警告）；2 版面不符。

浮窗按鈕（960×508 座標，2026-10-13 實機看過各道具）：
  消耗品（智慧果「使用」、離線水晶「打開」）：藍鈕在左 423,400、橘色「丟棄」在右 → 點左鈕
  禮盒 / 倉庫道具（取出、存入）：只有一顆藍鈕在中間 488,400
  寵物誘餌是「拆分 / 丟棄」、安撫之素是「餵養 / 更多」：不是使用，只走「倉庫 → 存入」
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

POP_NAME = (410, 150, 180, 30)       # 道具浮窗標題
POP_BTN = (488, 400)                 # 倉庫浮窗「存入」/「取出」（單顆鈕，中間）
USE_LEFT, USE_CENTER = (423, 400), (488, 400)
LV_TEXT = (215, 118, 125, 24)        # 背包面板人物下方綠字「N轉M級」
DEPOT_X, DEPOT_Y = [178, 238, 298, 358, 418], [175, 235, 295, 355]
MAX_TRIES = 3                        # 開禮盒：第 1 次 + 多開 2 次
sleep = time.sleep

# 名稱關鍵字（名稱 OCR 常少讀字：每個種類給一組片段，任一片段出現就算）
KINDS = {
    'box':     ('禮盒', '手禮', '新手'),
    'fruit':   ('智慧果', '慧果', '智慧', '倍智'),
    'crystal': ('離線', '水晶', '線水'),
    'soothe':  ('安撫', '撫之', '之素'),
    'bait':    ('誘餌', '物誘', '寵物', '寵'),
}
STORE_KINDS = ('soothe', 'bait')


# ---- 純函式（離線可測）----
def parse_trans(text: str):
    """「1轉131級」/「2轉新手禮盒」→ 開頭那個數字；讀不到回 None"""
    m = re.search(r'(\d)\s*轉', text or '')
    return int(m.group(1)) if m else None


def kind_of(name: str):
    """名稱 → 種類（box / fruit / crystal / soothe / bait）或 None"""
    t = name or ''
    for kind in ('crystal', 'fruit', 'soothe', 'bait', 'box'):
        if any(k in t for k in KINDS[kind]):
            return kind
    return None


def box_matches(name: str, n: int) -> bool:
    """名稱是不是「N轉新手禮盒」。數字讀不到時算是（交給後面的浮窗標題再確認）"""
    if kind_of(name) != 'box':
        return False
    m = parse_trans(name)
    return m is None or m == n


# 舊介面（離線測試用）
def is_box(title: str, n: int) -> bool:
    return box_matches(title, n)


def is_fruit(title: str) -> bool:
    return kind_of(title) == 'fruit'


def is_crystal(title: str) -> bool:
    return kind_of(title) == 'crystal'


def is_store_item(title: str) -> bool:
    return kind_of(title) in STORE_KINDS


# ---- 遊戲操作 ----
CUR_ROLE = [0]        # 目前處理的角色（0 起算）；背包被關掉後重開要選回這個角色（重開預設是操作中的角色）


def pop_title() -> str:
    import bag1920 as b
    return b.ocr(POP_NAME, '-Zooms', '2,3').strip()


def reopen_bag() -> None:
    import bag1920 as b
    b.open_bag()
    b.select_role(CUR_ROLE[0])
    b.click(*b.TAB_BAG, wait=900, note='newbiebox 回背包分頁')


def esc_pop() -> None:
    """關浮窗：只有真的有浮窗才送 ESC（沒浮窗的 ESC 會關掉整個背包，重開後還會跳回角色 1 的背包）"""
    import bag1920 as b
    if not b.bag_open():
        reopen_bag()
        return
    if not pop_title():
        return
    b.gui('key', '{ESC}', note='newbiebox 關浮窗')
    sleep(0.5)
    if not b.bag_open():
        reopen_bag()


def slot_xy(j: int):
    import bag1920 as b
    return b.SLOT_X[j % 5], b.SLOT_Y[j // 5]


BAG_REGION = (470, 108, 345, 180)     # 背包 5×3 格上方名稱區（整塊一次 OCR）
NAME_ROW_Y = (130, 196, 262)          # 三列名稱文字的垂直中心（數量數字在格子下半，離這幾條線 > 18 px，會被忽略）
NAME_COL_X = (500, 570, 635, 705, 770)


def ocr_lines(box, *opts) -> list:
    """ocr.ps1 一次 → [(文字, x, y)]（x / y = 該行中心，截圖座標）"""
    import json
    import winenv
    try:
        r = winenv.run_ps('ocr.ps1', *map(str, box), *opts)
        d = json.loads((r.stdout.strip().splitlines() or [''])[-1])
    except Exception:
        return []
    return [(ln['text'], int(ln['x']), int(ln['y'])) for ln in d.get('lines', [])] if d.get('ok') else []


def assign_names(lines) -> list:
    """OCR 文字行依位置分到 15 格（名稱可能折成兩行，同一格的串起來）→ [str×15]"""
    out = [''] * 15
    for text, x, y in sorted(lines, key=lambda t: (t[2], t[1])):
        row = min(range(3), key=lambda k: abs(y - NAME_ROW_Y[k]))
        if abs(y - NAME_ROW_Y[row]) > 18:
            continue
        col = min(range(5), key=lambda k: abs(x - NAME_COL_X[k]))
        if abs(x - NAME_COL_X[col]) > 36:
            continue
        out[row * 5 + col] += text.strip()
    return out


def bag_names() -> list:
    """背包 15 格名稱：整塊區域只跑一次 OCR（舊版每格 1~2 次、共 15~30 次 PowerShell，一個角色要 3~5 分鐘）"""
    lines = ocr_lines(BAG_REGION, '-Zooms', '3,4', '-Dark', '170')
    names = assign_names(lines)
    if not any(names):                       # 保底：換一組設定再整塊讀一次
        names = assign_names(ocr_lines(BAG_REGION, '-Zooms', '2,3'))
    return names


def candidates(kind: str, names: list, occupied=None) -> list:
    """某種道具的候選格：名稱認得的格；名稱被併成一行（同一格讀出 2 種以上）時，左右相鄰的有道具格也列入候選。
    動手前一律用浮窗標題確認，所以候選多一點沒關係。"""
    occupied = set(range(15)) if occupied is None else set(occupied)
    out = []
    for j, nm in enumerate(names):
        kinds = [k for k in KINDS if any(f in (nm or '') for f in KINDS[k])]
        if kind in kinds:
            if j not in out:
                out.append(j)
            if len(kinds) >= 2:
                for nb in (j - 1, j + 1):
                    if 0 <= nb < 15 and nb in occupied and nb not in out and (nb // 5 == j // 5):
                        out.append(nb)
    return out


KNOWN_OTHER_NAMES = ('龍王', '守護', '千年龜', '祝福', '秘藥', '人龍', '隨機蛋', '棍棒', '誘餌', '物誘', '安撫', '撫之')


def probe_unknown(names: list, kind: str, n: int = None):
    """名稱 OCR 認不出（空白 / 讀歪）的有道具格，逐一點開看浮窗標題找某種道具（例：角色 5 的 2 轉禮盒被紅色 NEW 標籤蓋住，名稱讀不到）。
    只點「名稱認不出」的格；認得是別的東西的格不點。找到回格號（浮窗已關）。"""
    import bag1920 as b
    occ = slots_occupied()
    for j in occ:
        nm = names[j] if j < len(names) else ''
        if kind_of(nm) is not None or any(k in (nm or '') for k in KNOWN_OTHER_NAMES):
            continue
        x, y = slot_xy(j)
        b.click(x, y, wait=800, note=f'newbiebox 名稱認不出 → 點開看標題 格{j}')
        t = pop_title()
        hit = kind_of(t) == kind and (kind != 'box' or parse_trans(t) in (None, n))
        esc_pop()
        if hit:
            return j
    return None


def find_slot(kind: str, n: int = None):
    """背包裡找某一種道具的格（只看名稱，不點開）。禮盒要給 n（轉數）。找不到回 None。"""
    names = bag_names()
    for j, nm in enumerate(names):
        if kind_of(nm) != kind:
            continue
        if kind == 'box' and not box_matches(nm, n):
            continue
        return j
    return None


def click_use(note: str = '') -> bool:
    """浮窗的藍色「使用 / 打開」鈕：兩顆鈕（消耗品）點左、一顆鈕（禮盒）點中間；用顏色判斷，絕不點橘色的丟棄。
    取樣點避開按鈕中央的字：左鈕看 x=400、中鈕看 x=520（兩顆鈕時 x=520 是橘色，一顆鈕時是藍色）。"""
    import bag1920 as b
    import uikit
    c = uikit.px([(400, 400), (520, 400)])
    if not c or len(c) != 2:
        return False

    def blue(rgb):
        r, g, bl = rgb
        return bl > 140 and bl > r + 50

    if blue(c[0]):
        x, y, name = USE_LEFT[0], USE_LEFT[1], '左'
    elif blue(c[1]):
        x, y, name = USE_CENTER[0], USE_CENTER[1], '中'
    else:
        return False
    b.click(x, y, wait=1800, note=f'newbiebox 使用 / 打開（{name}鈕）{note}')
    return True


def use_slot(j: int, label: str, expect_kind: str, n: int = None) -> bool:
    """對背包第 j 格按「使用 / 打開」：點格 → 浮窗標題確認是預期道具（動手前最後一道保險）→ 按藍鈕。"""
    import bag1920 as b
    x, y = slot_xy(j)
    b.click(x, y, wait=900, note=f'newbiebox {label}')
    t = pop_title()
    if kind_of(t) != expect_kind or (expect_kind == 'box' and n is not None and parse_trans(t) not in (None, n)):
        b.log(f'  {label}：點開的浮窗是「{t}」不是預期（{expect_kind}{n or ""}）→ 不按')
        esc_pop()
        return False
    ok = click_use(f'：{label}')
    if b.bag_open() and pop_title():
        esc_pop()
    return ok


def use_kind(kind: str, label: str, shot_tag: str) -> bool:
    """直接認出該種道具的格 → 使用 → 再讀名稱確認。回 True = 確實按了"""
    import bag1920 as b
    j = find_slot(kind)
    if j is None:
        b.log(f'  {label}：背包沒有')
        return False
    if not use_slot(j, label, kind):
        return False
    b.gui('shot', f'newbiebox-{shot_tag}.png', note='newbiebox 使用後截圖')
    if find_slot(kind) is None:
        b.log(f'  {label}：已使用（背包已沒有）')
    else:
        b.log(f'  {label}：按了使用，背包仍有（可能是堆疊還有數量）')
    return True


DEPOT_REGION = (148, 140, 300, 250)


def depot_names() -> list:
    """個人倉庫 20 格名稱：整塊 OCR 一次，依位置分格（名稱在格子上緣）"""
    out = [''] * 20
    for text, x, y in sorted(ocr_lines(DEPOT_REGION, '-Zooms', '3,4', '-Dark', '170'), key=lambda t: (t[2], t[1])):
        row = min(range(4), key=lambda k: abs(y - (DEPOT_Y[k] - 16)))
        col = min(range(5), key=lambda k: abs(x - DEPOT_X[k]))
        if abs(y - (DEPOT_Y[row] - 16)) > 16 or abs(x - DEPOT_X[col]) > 30:
            continue
        out[row * 5 + col] += text.strip()
    return out


def take_box_from_depot(n: int, role_idx: int = 0) -> bool:
    """個人倉庫認出 N 轉禮盒（只看名稱）→ 點它 → 「取出」。回 True = 已點取出"""
    import bag1920 as b
    import uikit

    def personal_on() -> bool:
        c = uikit.px([(165, 112)])                 # 「個人」分頁左側空白處：選中 = 亮黃（251,219,135）、沒選中 = 棕（171,125,82）
        return bool(c) and c[0][0] > 225 and c[0][1] > 200

    ok = False
    for k in range(3):
        if not b.bag_open():
            reopen_bag()
        elif pop_title():
            esc_pop()
        b.click(*b.TAB_DEPOT, wait=1300, note=f'newbiebox 倉庫分頁（第 {k + 1}/3 次）')
        b.click(*b.DEPOT_PERSONAL, wait=1000, note='newbiebox 個人倉庫')
        if personal_on():
            ok = True
            break
        b.log('  倉庫分頁沒切成功 → 重來')
    if not ok:
        b.log('  警告：進不了個人倉庫（3 次）→ 不點倉庫格')
        b.click(*b.TAB_BAG, wait=900, note='newbiebox 回背包分頁')
        return False
    names = depot_names()
    hits = [i for i, nm in enumerate(names) if box_matches(nm, n)]
    b.log(f'  個人倉庫名稱：{[nm for nm in names if nm]}')
    if not hits:
        b.click(*b.TAB_BAG, wait=900, note='newbiebox 回背包分頁')
        return False
    i = hits[0]
    x, y = DEPOT_X[i % 5], DEPOT_Y[i // 5]
    b.click(x, y, wait=900, note=f'newbiebox 點倉庫第 {i + 1} 格（{names[i]}）')
    t = pop_title()
    if kind_of(t) != 'box' or (parse_trans(t) not in (None, n)):
        b.log(f'  警告：倉庫第 {i + 1} 格浮窗是「{t}」不是 {n} 轉禮盒 → 不取出')
        esc_pop()
        b.click(*b.TAB_BAG, wait=900, note='newbiebox 回背包分頁')
        return False
    b.click(*POP_BTN, wait=1300, note=f'newbiebox 取出 {t}')
    b.click(*b.TAB_BAG, wait=900, note='newbiebox 回背包分頁')
    return True


def open_box(n: int, dry: bool, role_idx: int = 0) -> str:
    """回 'opened' / 'none'（找不到禮盒）/ 'failed'（3 次都沒打開）/ 'dry'"""
    import bag1920 as b
    names0 = bag_names()
    j = find_slot('box', n)
    if j is None:
        j = probe_unknown(names0, 'box', n)           # 名稱 OCR 讀不到的格（NEW 標籤蓋住等）：點開看浮窗標題
        if j is not None:
            b.log(f'  名稱讀不到，但浮窗確認第 {j} 格是 {n} 轉禮盒')
    if j is None:
        b.log(f'  背包沒有 {n} 轉新手禮盒，去個人倉庫找')
        if dry:
            return 'none'
        if not take_box_from_depot(n, role_idx):
            return 'none'
        j = find_slot('box', n)
        if j is None:
            b.log('  取出後背包仍認不出禮盒')
            return 'none'
    if dry:
        b.log(f'  認出 {n} 轉禮盒在背包第 {j} 格（--dry 不使用）')
        return 'dry'
    for k in range(1, MAX_TRIES + 1):
        b.log(f'  開 {n} 轉禮盒（第 {k}/{MAX_TRIES} 次）')
        if not use_slot(j, f'{n} 轉禮盒 第 {k} 次', 'box', n):
            b.log('  警告：禮盒沒按成功（浮窗不是這一轉的禮盒或沒有藍鈕）→ 不重試')
            return 'none'
        b.gui('shot', f'newbiebox-box{n}-try{k}.png', note='newbiebox 開禮盒後截圖')
        j2 = find_slot('box', n)
        if j2 is None:
            b.log(f'  {n} 轉禮盒已打開')
            return 'opened'
        j = j2
    return 'failed'


def slots_occupied() -> list:
    import bag1920 as b
    return b.slots_with_item() or list(range(15))


def store_items(role_idx: int, names: list, occ) -> None:
    """安撫之素 / 寵物誘餌 → 共用倉庫：切一次「倉庫 → 公共」，逐候選格 點 → 浮窗標題確認是這兩種 → 存入。"""
    import bag1920 as b
    cand = []
    for kind in STORE_KINDS:
        for j in candidates(kind, names, occ):
            if j not in cand:
                cand.append(j)
    # 寵物誘餌的名稱 OCR 常被讀歪（巃物誘餌 / 一龍 / 寵…）：再用圖示的紅橘火焰色補辨識（catchrun1920.bait_score，抓寵流程用的同一套）
    try:
        import catchrun1920 as cr
        for j in sorted(occ):
            if j not in cand and cr.bait_score(slot_xy(j)) >= 4:
                cand.append(j)
    except Exception as e:
        print(f'  誘餌顏色辨識略過：{e!r}', flush=True)
    if not cand:
        return
    b.log(f'  存共用倉庫候選格：{[(j, names[j]) for j in cand]}')
    b.click(*b.TAB_DEPOT, wait=1200, note='newbiebox 倉庫分頁')
    b.click(*b.DEPOT_PUBLIC, wait=800, note='newbiebox 公共倉庫')
    for j in cand:
        x, y = slot_xy(j)
        b.click(x, y, wait=800, note=f'newbiebox 存入候選格 {j}')
        t = pop_title()
        if kind_of(t) in STORE_KINDS:
            b.click(*POP_BTN, wait=1100, note=f'newbiebox 存入 {t}')
            b.log(f'  已存入：{t}')
        elif t:
            esc_pop()
            b.click(*b.TAB_DEPOT, wait=900, note='newbiebox 回倉庫分頁')
    b.click(*b.TAB_BAG, wait=900, note='newbiebox 回背包分頁')


def store_public(role_idx: int) -> None:
    """安撫之素 / 寵物誘餌 → 共用倉庫：直接認出它們的格（只看名稱，不點開確認），最多 4 輪直到背包沒有"""
    import bag1920 as b
    for rnd in range(4):
        names = bag_names()
        slots = [j for j, nm in enumerate(names) if kind_of(nm) in STORE_KINDS]
        if not slots:
            return
        j = slots[0]
        b.log(f'  存共用倉庫：第 {j} 格「{names[j]}」（第 {rnd + 1} 輪）')
        b.do_store(role_idx, [j], public=True)
    b.log('  警告：存共用倉庫 4 輪後背包仍有安撫之素 / 誘餌（倉庫滿？）')


def do_role(i: int, trans_arg, dry: bool) -> None:
    import bag1920 as b
    CUR_ROLE[0] = i
    b.select_role(i)
    b.click(*b.TAB_BAG, wait=900, note='newbiebox 背包分頁')
    b.ensure_names()
    n = parse_trans(b.ocr(LV_TEXT, '-Zooms', '3,4')) or trans_arg
    b.log(f'角色{i + 1}：目前 {n} 轉' if n else f'角色{i + 1}：讀不到轉數（用 --trans 指定）→ 跳過')
    if not n:
        return
    res = open_box(n, dry, i)
    if res in ('none', 'failed'):
        b.log(f'  警告：角色{i + 1} {n} 轉禮盒{"找不到" if res == "none" else "3 次都沒打開"}，略過禮盒、繼續後面步驟')
    if dry:
        return
    # 開完禮盒整個背包只讀一次名稱，之後果子 / 水晶 / 安撫之素 / 誘餌的位置都用這一次（消耗後格子只會變空，不會移位）
    names = bag_names()
    log_names = [f'{j}:{nm}' for j, nm in enumerate(names) if nm]
    b.log(f'  背包：{log_names}')
    occ = set(slots_occupied())
    for kind, label in (('fruit', '2 倍智慧果'), ('crystal', '離線水晶')):
        js = candidates(kind, names, occ)
        if not js:
            pj = probe_unknown(names, kind)
            if pj is not None:
                js = [pj]
        if not js:
            b.log(f'  {label}：背包沒有')
            continue
        done = False
        for j in js:
            if use_slot(j, label, kind):
                done = True
                break
        b.log(f'  {label}：' + ('已按使用 / 打開' if done else '候選格都沒按成功'))
    store_items(i, names, occ)
    after = bag_names()
    again = [j for j, nm in enumerate(after) if kind_of(nm) in STORE_KINDS]
    if again:                                         # 第一次 OCR 漏認的（名稱被讀歪）：存完再讀、還有就再存一次
        b.log(f'  還有沒存的：{[after[j] for j in again]} → 再存一次')
        store_items(i, after, set(slots_occupied()))
        after = bag_names()
    left = [nm for nm in after if kind_of(nm) in ('fruit', 'crystal') or kind_of(nm) in STORE_KINDS]
    try:
        import catchrun1920 as cr
        color_bait = [j for j in slots_occupied() if cr.bait_score(slot_xy(j)) >= 4]
        if color_bait:
            left.append(f'誘餌(顏色)@{color_bait}')
            b.log(f'  顏色辨識仍有誘餌格：{color_bait} → 再存一次')
            store_items(i, after, set(slots_occupied()))
    except Exception:
        pass
    b.log(f'  完成後背包仍有：{left}' if left else '  完成後背包已沒有果子 / 水晶 / 安撫之素 / 誘餌')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--trans', type=int, default=0, help='讀不到轉數時用')
    ap.add_argument('--do', action='store_true', help='真的執行（預設只預覽，不使用 / 取出 / 存入）')
    ap.add_argument('--dry', action='store_true', help='同預設：只認不動')
    a = ap.parse_args(argv)
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import layout
    if layout.current() != '1920x1017':
        print(f'版面 {layout.current()}，這支只量過 1920x1017')
        return 2
    import bag1920 as b
    dry = a.dry or not a.do
    if not b.open_bag():
        b.log('警告：背包打不開（戰鬥 / 對話中？）→ 略過新手禮盒')
        return 0
    for i in [int(x) - 1 for x in a.roles.split(',') if x.strip()]:
        try:
            do_role(i, a.trans or None, dry)
        except SystemExit:
            raise
        except Exception as e:                      # 單一角色出錯不影響其他角色與後面階段
            b.log(f'警告：角色{i + 1} 處理失敗：{e!r}，繼續下一個')
            try:
                esc_pop()
            except Exception:
                pass
    b.click(*b.CLOSE_BAG, wait=600, note='newbiebox 關背包')
    return 0


if __name__ == '__main__':
    sys.exit(main())
