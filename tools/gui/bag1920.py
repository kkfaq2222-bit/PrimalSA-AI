#!/usr/bin/env python3
"""背包整理（1920×1017 專用）：5 個角色逐一把「存個人倉庫」與「刪除」名單處理掉。只用標準庫 + ass / uikit 同一套 gui 呼叫。

規則來源（使用者 2026-10-10 / 11，見記憶 psa-quest-reward-handling）：
  存個人倉庫：薩姆吉爾的首飾、薩頓家的秘藥、英雄的祝福、人龍隨機蛋、…（STORE）
  刪除（不可逆）：儀之兜、老爺爺的護身符、空想的衣服 / 帽子 / 豎琴、亞姆亞姆的斧頭、…（DELETE）
  名單外的道具一律不動，只列出來（回報使用者）。

用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1 較快）：
  uv run --no-project python tools/gui/bag1920.py --client kkfaq11111            # 預覽：5 人各有哪些、準備怎麼處理（不動）
  uv run --no-project python tools/gui/bag1920.py --client kkfaq11111 --do       # 真的執行：先存倉庫、再刪除
  uv run --no-project python tools/gui/bag1920.py --client kkfaq11111 --do --only store   # 只存倉庫 / --only delete 只刪除

座標（截圖 960×508，2026-10-11 實機量）：
  背包鈕 757,462；角色頭像左欄 y = 108/205/290/375/410（頭像 x=52，第 5 位要先把左欄上滑）；背包道具格 5×3，x = 500/570/635/705/770、y = 146/212/278
  倉庫分頁 852,275、背包分頁 852,175、個人 / 公共 220,118 / 372,118、刪除管理 640,385、取消刪除 640,425、確認「確定」477,343（批量刪除提示「確定」477,343，2026-10-11 實機量）
安全：每步先 pixel 驗證面板開著；刪除前用 OCR 對「提示」視窗的名稱清單比對白名單，不符 → 取消不刪。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BAG_BTN = (757, 462)
CLOSE_BAG = (832, 66)
TAB_BAG, TAB_DEPOT = (852, 175), (852, 275)
DEPOT_PERSONAL, DEPOT_PUBLIC = (220, 118), (372, 118)
DEL_MODE, DEL_CONFIRM, DEL_CANCEL = (640, 385), (640, 385), (640, 425)
ROLE_Y = [108, 205, 290, 375, 410]
ROLE_X = 52
SLOT_X = [500, 570, 635, 705, 770]
SLOT_Y = [146, 212, 278]
NAME_BOX = (470, 118, 345, 38)       # 背包第 1 列道具名（格子上方小字；「顯示道具名」開著時才讀得到）

STORE = ['薩姆吉爾的首飾', '薩頓家的秘藥', '英雄的祝福', '人龍隨機蛋']
PUBLIC_STORE = ['龍王的守護']      # 角色 2~5 的存公共倉庫；角色 1（序 0）一律留身上使用（使用者 2026-10-12，main 裡略過）
DELETE = ['儀之兜', '老爺爺的護身符', '空想的衣服', '空想的帽子', '空想的豎琴', '亞姆亞姆的斧頭',
          '月光的手鐲', '馬祖的斧頭', '馬祖的矛', '馬祖的棍棒', '山賊的羽飾', '杉的手環',
          '龍之槍', '龍之鎧', '龍之衣', '不可思議的貝殼', '仙尼亞的花',
          '郵寄物', '切繩石',          # 馬祖快遞任務道具（使用者 2026-10-11 加入刪除名單）
          '巴巴洛的許可證', '龍的魅力之笛',
          '泰坦部隊的通行證', '米蘭達部隊的通行證', '愛麗兒部隊的通行證', '部隊的通行證']   # 英雄島後傳獎勵（使用者 2026-10-12 加入刪除名單；名稱在格子內折兩行，OCR 常只讀到後半）   # 礦工的比賽 / 龍的巢穴獎勵（使用者 2026-10-11 加入；等使用者說整理背包才一次刪）
KEEP_FOREVER = ['大地的羈絆', '風的鎖', '水的戒指', '火的羽毛飾品', '精靈王之弓']   # 留在身上、絕不處理（使用者規定）

sleep = time.sleep


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def gui(*a, note=''):
    import uikit
    return uikit.gui(*a, note=note)


def click(x, y, wait=700, note=''):
    gui('seq', f'click {x} {y}; wait {wait}', note=note)


def px(pts):
    import uikit
    return uikit.px(pts)


def ocr(box, *opts):
    import uikit
    return ''.join(uikit.ocr(box, *opts))


def bag_open() -> bool:
    c = px([(480, 56), (832, 66)])          # 標題「背包」旁與右上 ✕
    return bool(c) and c[1][0] > 150 and c[1][1] < 120


def open_bag() -> bool:
    for _ in range(3):
        if bag_open():
            return True
        click(*BAG_BTN, wait=1500, note='bag1920 開背包')
    return bag_open()


NAMES_BTN = (635, 345)                # 背包「顯示道具名」切換鈕（按鈕外觀開 / 關完全一樣，所以只能看格子上方有沒有名字）
EMPTY_SLOT = (103, 74, 49)            # 空格底色（2026-10-12 實測）
ICON_OFFS = [(dx, dy) for dy in (-8, 0, 8) for dx in (-10, 0, 10)]


def slots_with_item() -> list:
    """背包 15 格哪些有道具（格心附近 9 點與空格底色差 > 45）；讀不到回 []"""
    pts = [(SLOT_X[j % 5] + dx, SLOT_Y[j // 5] + dy) for j in range(15) for dx, dy in ICON_OFFS]
    cols = px(pts) or []
    if len(cols) != len(pts):
        return []
    n = len(ICON_OFFS)
    return [j for j in range(15) if any(max(abs(a - b) for a, b in zip(c, EMPTY_SLOT)) > 45 for c in cols[j * n:(j + 1) * n])]


def ensure_names(max_toggle: int = 1):
    """確保「顯示道具名」是開的（使用者 2026-10-12：沒開就自動開）。
    判斷：有道具的格子上方都讀不到名字 → 名稱是關的 → 按一次鈕再讀；仍讀不到就按回去（可能是 OCR 失敗）。
    背包沒有任何道具時看不出狀態，回 None（不動）。回 True = 名稱有顯示。"""
    items = slots_with_item()
    if not items:
        return None
    names = read_names()
    if any(names[j] for j in items):
        return True
    for _ in range(max_toggle):
        log('有道具但讀不到名稱 → 按「顯示道具名」')
        click(*NAMES_BTN, wait=900, note='bag1920 切換顯示道具名')
        names = read_names()
        if any(names[j] for j in items):
            log('道具名已顯示')
            return True
    click(*NAMES_BTN, wait=900, note='bag1920 還原顯示道具名（OCR 仍讀不到）')
    log('按了仍讀不到名稱，已還原（可能 OCR 失敗，請看畫面）')
    return False


def select_role(i: int) -> None:
    click(ROLE_X, ROLE_Y[i], wait=1100, note=f'bag1920 選角色 {i + 1}')


def read_names() -> list:
    """用 OCR 讀背包第一列 5 個格子上的道具名（最多 5 個；沒有字 = 空格）"""
    out = []
    for y in (118, 184, 250):                 # 3 列 × 5 格；名字在格子上方小字，每列 y 差 66
        for x in SLOT_X:
            t = ocr((x - 32, y, 66, 36), '-Zooms', '3,4', '-Dark', '170').strip()
            out.append(t)
    return out


def _hit(name: str, k: str) -> bool:
    """名稱比對：完整包含，或 OCR 只切到前段 / 後段（取 k 的前 4 字、後 3 字、中間 3 字任一在 name 內；k 太短就要全中）"""
    if k in name:
        return True
    if len(k) < 4:
        return False
    return k[:4] in name or k[-3:] in name or k[1:4] in name


def classify(name: str) -> str:
    for group, label in ((KEEP_FOREVER, 'keep'), (PUBLIC_STORE, 'public'), (STORE, 'store'), (DELETE, 'delete')):
        hits = [k for k in group if k and _hit(name, k)]
        if hits:
            return label
    return 'unknown' if name else 'empty'


def survey(roles=range(5)) -> dict:
    """5 人各自的背包第 1 列：{角色序: [(格, 名稱, 類別), ...]}"""
    res = {}
    if not open_bag():
        raise SystemExit('背包打不開（戰鬥 / 對話中？）')
    click(*TAB_BAG, wait=900)
    checked = False
    for i in roles:
        select_role(i)
        if not checked:
            checked = ensure_names() is not None      # 名稱顯示是全帳號共用設定：第一個有道具的角色確認一次就好
        names = read_names()
        res[i] = [(j, n, classify(n)) for j, n in enumerate(names)]
    return res


def show(res: dict) -> None:
    for i, row in res.items():
        parts = [f'{n or "—"}[{c}]' for _, n, c in row]
        print(f'  角色{i + 1}：' + '  '.join(parts))


def do_store(i: int, slots: list, public: bool = False) -> None:
    """存倉庫：倉庫分頁 → 個人 / 公共 → 雙擊背包格（右半）→ 回背包分頁"""
    click(*TAB_DEPOT, wait=1200, note='bag1920 倉庫')
    click(*(DEPOT_PUBLIC if public else DEPOT_PERSONAL), wait=700, note='bag1920 公共倉庫' if public else 'bag1920 個人倉庫')
    for j in slots:
        x, y = SLOT_X[j % 5], SLOT_Y[j // 5]
        # 雙擊後跳道具浮窗，要再按「存入」488,400（2026-10-11 實機量；有些道具雙擊就直接存，按到空處無害）
        gui('seq', f'dclick {x} {y}; wait 1000; click 488 400; wait 1000', note=f'bag1920 角色{i + 1} 存個人倉庫 格{j}')
    click(*TAB_BAG, wait=900, note='bag1920 回背包')


def do_delete(i: int, slots: list, expect: list) -> bool:
    """批量刪除：刪除管理 → 勾格 → 刪除選中 → 提示視窗 OCR 名稱比對 → 確定。比對不符就取消"""
    click(*DEL_MODE, wait=1000, note='bag1920 刪除管理')
    for j in slots:
        x, y = SLOT_X[j % 5], SLOT_Y[j // 5]
        gui('seq', f'click {x} {y}; wait 250', note=f'bag1920 勾 格{j}')
    click(*DEL_CONFIRM, wait=1200, note='bag1920 刪除選中')
    tip = ocr((250, 150, 460, 160), '-Zooms', '2,3')
    # 比對：提示視窗只要含任一刪除名單關鍵字、且完全沒有保留名單 / 名單外的關鍵字 → 通過
    # （OCR 常漏掉最後一件，所以不要求每件都讀到；格子上已勾的都來自白名單分類，這裡只做「沒勾錯」的最後檢查）
    seen = [k for k in DELETE if _hit(tip, k)]
    bad = [k for k in KEEP_FOREVER + STORE if k and k in tip]
    ok = bool(seen) and not bad
    if not ok:
        log(f'角色{i + 1} 刪除提示 {tip!r} 看不到刪除名單或含保留 / 存倉名單（{bad}）→ 取消，不刪')
        gui('seq', 'key {ESC}; wait 400')
        click(*DEL_CANCEL, wait=800, note='bag1920 取消刪除')
        return False
    log(f'角色{i + 1} 刪除提示通過：{tip!r}')
    click(477, 343, wait=1800, note=f'bag1920 角色{i + 1} 確定刪除')
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--do', action='store_true', help='真的執行（預設只預覽）')
    ap.add_argument('--only', choices=['store', 'delete'], help='只存倉庫 / 只刪除')
    ap.add_argument('--roles', default='1,2,3,4,5', help='要處理的角色序（1~5，逗號分隔）')
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
    roles = [int(x) - 1 for x in a.roles.split(',') if x.strip()]
    log('=== 預覽（背包第 1 列）===')
    res = survey(roles)
    show(res)
    unknown = [(i, n) for i, row in res.items() for _, n, c in row if c == 'unknown']
    if unknown:
        log(f'名單外的道具（不處理，請使用者決定）：{unknown}')
    if not a.do:
        log('預覽結束（加 --do 才會執行）')
        click(*CLOSE_BAG, wait=600)
        return 0
    for i in roles:
        select_role(i)
        row = res[i]
        store = [j for j, n, c in row if c == 'store']
        pub = [j for j, n, c in row if c == 'public']
        if i == 0:
            pub = []          # 使用者 2026-10-12：角色 1 的龍王的守護不存公共倉庫，留在身上使用
        dele = [j for j, n, c in row if c == 'delete']
        if pub and a.only != 'delete':
            log(f'角色{i + 1} 存公共倉庫：{[row[j][1] for j in pub]}')
            do_store(i, pub, public=True)
        if store and a.only != 'delete':
            log(f'角色{i + 1} 存個人倉庫：{[row[j][1] for j in store]}')
            do_store(i, store)
        if dele and a.only != 'store':
            names = [row[j][1] for j in dele]
            log(f'角色{i + 1} 刪除：{names}')
            do_delete(i, dele, names)
    log('完成，重新預覽：')
    show(survey(roles))
    click(*CLOSE_BAG, wait=600)
    return 0


if __name__ == '__main__':
    sys.exit(main())
