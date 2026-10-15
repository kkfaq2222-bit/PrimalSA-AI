#!/usr/bin/env python3
"""單角色抓寵流程（1920×1017 專用）：取誘餌 → 拆成 N → 剩餘存回倉庫 → 外掛設系別 / 寵物 → 勾自動存倉庫 + 自動抓寵 → 等抓完。
只用標準庫 + ass + catch1920 + uikit。座標見 notes/progress.md「22:45 背包 1920 座標」與 catch1920.py。

用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1）：
  uv run --no-project python tools/gui/catchrun1920.py --client kkfaq11111 --role 2 --system 鯊魚系 --pet 克邦凱斯 --n 5 [--source personal|public] [--store]
  --dry 只印計畫不動。--no-wait 設好開抓就返回（不等抓完）。
停手：戰鬥中 / 面板打不開 / 背包找不到誘餌 / 抓寵 8 分鐘仍未結束 / 出現不認得的畫面（驗證視窗疑慮）。
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

BAG_BTN, CLOSE_BAG = (757, 462), (832, 66)
TAB_BAG, TAB_DEPOT = (852, 175), (852, 275)
DEPOT_PERSONAL, DEPOT_PUBLIC = (220, 118), (372, 118)
ROLE_X, ROLE_Y = 52, [108, 205, 290, 375, 410]
SLOT_X, SLOT_Y = [500, 570, 635, 705, 770], [146, 212, 278]
DEPOT_X, DEPOT_Y = [178, 238, 298, 358, 418], [175, 235, 295, 355]
POP_NAME = (410, 150, 180, 30)          # 道具浮窗標題
POP_BTN = (488, 400)                    # 浮窗「取出」/「存入」
POP_SPLIT = (422, 400)                  # 背包浮窗「拆分」
QTY_BOX, QTY_OK = (502, 276), (410, 335)
KEY_ENTER = (598, 352)
KEYS = {'1': (336, 203), '2': (414, 203), '3': (493, 203), '0': (570, 203),
        '4': (336, 278), '5': (414, 278), '6': (493, 278),
        '7': (336, 352), '8': (414, 352), '9': (493, 352)}
BAIT = '誘餌'
sleep = time.sleep


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def gui(*a, note=''):
    import uikit
    return uikit.gui(*a, note=note)


def click(x, y, wait=800, note=''):
    gui('seq', f'click {x} {y}; wait {wait}', note=note)


def dclick(x, y, wait=1000, note=''):
    gui('dclick', str(x), str(y), note=note)
    sleep(wait / 1000)


POP_DESC = (340, 235, 300, 30)          # 浮窗「詳細介紹」內文


def title() -> str:
    """浮窗標題 + 內文 OCR 合併（誘餌：標題「寵物誘餌」、內文「用於寵物圖鑑抓捕寵物寶寶」；OCR 會混字，所以兩處一起看）"""
    import uikit
    t = uikit.ocr_name(POP_NAME) + ''.join(uikit.ocr(POP_DESC, '-Zooms', '2,3')).strip()   # 標題：舊讀法 + -Dark 0
    return ('誘餌 ' + t) if any(k in t for k in ('誘餌', '物誘', '誘飯', '抓捕', '圖鑑')) else t


OFFS = [(dx, dy) for dy in (-14, -7, 0, 7, 14) for dx in (-12, -6, 0, 6, 12)]


def bag_open() -> bool:
    import uikit
    c = uikit.px([CLOSE_BAG])
    return bool(c) and all(abs(a - b) <= 35 for a, b in zip(c[0], (197, 73, 49)))


def open_bag(tries: int = 3) -> None:
    """開背包並偵測；沒開成 → ESC 復原再點（使用者規則：打開 → 偵測 → 沒成功 ESC 再來）。
    2026-10-15 22222 角色 5 抓貝魯卡：只點一次、沒開成就退出碼 11 停手（看門狗不重啟）"""
    import time
    for k in range(tries):
        if bag_open():
            return
        if k > 0:
            gui('key', '{ESC}', note='catchrun 背包沒開成 → ESC 復原')
            time.sleep(0.8)
        click(*BAG_BTN, wait=1500, note=f'catchrun 開背包（第 {k + 1}/{tries} 次）')
    need_bag()


def need_bag():
    """背包沒開 → 立刻停手（絕不在面板外亂點：會誤點任務追蹤 / 整理背包）"""
    if not bag_open():
        print('背包面板不在 → 停手')
        raise SystemExit(11)


def bait_score(slot) -> int:
    """格內 25 點像素中「紅 / 橘火焰」色的數量（誘餌圖示特徵：R>150、G<130、B<80）"""
    import uikit
    x, y = slot
    cols = uikit.px([(x + dx, y + dy) for dx, dy in OFFS]) or []
    return sum(1 for r, g, b in cols if r > 150 and g < 130 and b < 80)


def find_bait(slots) -> tuple | None:
    """顏色初篩（不點擊）→ 分數高的先點開浮窗，標題 OCR 含「誘餌」才算。
    只有「確定浮窗存在（標題有字）」才送 ESC；背包不在就停手。位置不固定也能找。"""
    need_bag()
    scored = sorted(((bait_score(s), s) for s in slots), reverse=True)
    for sc, (x, y) in scored:
        if sc < 4:
            break
        need_bag()
        click(x, y, wait=800, note=f'catchrun 候選格（色分 {sc}）')
        t = title()
        if BAIT in t:
            return (x, y)
        if t and bag_open():
            gui('key', '{ESC}', note='catchrun 關浮窗'); sleep(0.5)
    return None


def bag_slots():
    return [(x, y) for y in SLOT_Y for x in SLOT_X]


def depot_slots():
    return [(x, y) for y in DEPOT_Y for x in DEPOT_X]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--role', type=int, required=True)
    ap.add_argument('--system', required=True)
    ap.add_argument('--pet', required=True)
    ap.add_argument('--n', type=int, required=True)
    ap.add_argument('--source', choices=['personal', 'public'], default='personal')
    ap.add_argument('--store', action='store_true', help='勾自動存倉庫')
    ap.add_argument('--split', action='store_true', help='拆分誘餌成 N 個、剩餘存回倉庫（預設不拆）')
    ap.add_argument('--no-bait-check', action='store_true', help='不開背包找誘餌（誘餌已在背包時用；沒有誘餌時外掛會取消自動抓寵）')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--no-wait', action='store_true')
    a = ap.parse_args(argv)
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    log(f'計畫：角色{a.role} {a.system}/{a.pet} ×{a.n}，誘餌來源 {a.source}，自動存倉庫={a.store}')
    if a.dry:
        return 0
    if not (1 <= a.n <= 9 and 1 <= a.role <= 5):
        print('--n 限 1~9、--role 限 1~5')
        return 1
    import winenv
    winenv.enable_server()
    import layout
    if layout.current() != '1920x1017':
        print(f'版面 {layout.current()}，這支只量過 1920x1017')
        return 2
    import ass
    import catch1920 as c
    if ass.in_battle():
        print('戰鬥中，停手')
        return 8

    if not a.no_bait_check:                    # 誘餌已經在背包（使用者 2026-10-12：檢查誘餌是多餘的）→ 整段略過
        # 1. 背包：切角色、看有沒有誘餌；沒有就從倉庫取出
        open_bag()
        click(ROLE_X, ROLE_Y[a.role - 1], wait=1200, note=f'catchrun 背包切角色 {a.role}')
        click(*TAB_BAG, wait=900, note='catchrun 背包分頁')
        pos = find_bait(bag_slots())
        if pos is None:
            dpos = None
            for _try in range(3):                  # 剛切角色後倉庫頁偶爾還沒畫好 → 讀不到就重點分頁再讀（2026-10-12 角色 3 火雞第 1 輪）
                click(*TAB_DEPOT, wait=1300, note='catchrun 倉庫分頁')
                click(*(DEPOT_PUBLIC if a.source == 'public' else DEPOT_PERSONAL), wait=1100, note='catchrun 倉庫來源')
                dpos = find_bait(depot_slots())
                if dpos is not None:
                    break
                sleep(1.0)
            if dpos is None:
                print('背包 / 倉庫都找不到誘餌')
                click(*CLOSE_BAG, wait=500)
                return 4
            click(*POP_BTN, wait=1000, note='catchrun 取出誘餌')
            click(*TAB_BAG, wait=900, note='catchrun 回背包')
            pos = find_bait(bag_slots())
            if pos is None:
                print('取出後背包仍找不到誘餌')
                click(*CLOSE_BAG, wait=500)
                return 5
        # 2. 不用拆分（使用者 2026-10-11）：身上帶滿誘餌，寵物欄 5 個空格就是目標，欄滿遊戲自己停；--split 才拆
        if a.split:
            # 2. 拆分（此時浮窗開著，按「拆分」）
            click(*POP_SPLIT, wait=900, note='catchrun 拆分')
            click(*QTY_BOX, wait=800, note='catchrun 數量框')
            click(*KEYS[str(a.n)], wait=400, note=f'catchrun 輸入 {a.n}')
            click(*KEY_ENTER, wait=700, note='catchrun Enter')
            click(*QTY_OK, wait=1000, note='catchrun 確定')
            # 3. 剩餘（原格）存回倉庫：倉庫分頁開著時雙擊原格 → 「存入」
            click(*TAB_DEPOT, wait=1200, note='catchrun 倉庫分頁')
            click(*(DEPOT_PUBLIC if a.source == 'public' else DEPOT_PERSONAL), wait=800, note='catchrun 倉庫來源')
            click(*pos, wait=900, note='catchrun 剩餘單擊（雙擊不可靠）')
            if BAIT in title():
                click(*POP_BTN, wait=1000, note='catchrun 存入剩餘')
            click(*CLOSE_BAG, wait=700, note='catchrun 關背包')
            log('誘餌拆分完成（背包留 N 個，剩餘已存回倉庫）')

        else:
            gui('key', '{ESC}', note='catchrun 關浮窗'); sleep(0.5)   # 浮窗還開著（找誘餌 / 取出後）
            click(*CLOSE_BAG, wait=700, note='catchrun 關背包')

    # 4. 外掛（前一個指令可能留著寵物面板 / 背包，會蓋住外掛鈕：先關掉）
    try:
        import petdepot1920 as _pd
        for _ in range(3):
            if _pd.panel_open():
                click(*_pd.CLOSE_X, wait=700, note='catchrun 關寵物面板')
        if bag_open():
            click(*CLOSE_BAG, wait=600, note='catchrun 關背包')
    except SystemExit:
        raise
    except Exception:
        pass
    if not ass.open_panel():
        print('外掛面板打不開')
        return 3
    try:
        names = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']
        if not (ass.select_role(names[a.role - 1]) and c.ensure_tab()):
            print('外掛選角色 / 捉寵分頁失敗')
            return 6
        if not c.pick('system', a.system) or not c.pick('pet', a.pet, ctx=c.read_field(c.SYS_BOX)):
            print('系別 / 寵物選不到')
            return 7
        if a.store and not c.set_check(c.CHK_STORE, True, '自動存倉庫'):
            return 8
        if not c.set_check(c.CHK_CATCH, True, '自動抓寵'):
            return 9
        log(f'角色{a.role} 開抓：{c.read_state()}')
        if a.no_wait:
            return 0
        # 勾自動抓寵後面板不關；每圈「切到別的角色 → 切回來」刷新後讀（勾選圖示不會自己更新）：
        #  ① 可抓捕數格像素簽名有變 = 抓到了（記時間）② 自動抓寵勾選被遊戲取消 = 抓完（記總耗時）
        t0 = time.time()
        other = names[0] if a.role != 1 else names[1]

        def sig():
            pts = [(c.CNT_BOX[0] + dx, c.CNT_BOX[1] + dy) for dy in (6, 12, 18, 24) for dx in (4, 10, 16, 22, 28)]
            return c.px(pts)

        base, events, polls = sig(), [], 0
        while time.time() - t0 < 480:
            ass.select_role(other)
            sleep(0.3)
            ass.select_role(names[a.role - 1])
            sleep(0.3)
            polls += 1
            now = sig()
            if base and now and now != base:
                events.append(round(time.time() - t0, 1))
                base = now
                log(f'角色{a.role} 可抓捕數變動（第 {len(events)} 次，{events[-1]} 秒）')
            if not c.is_checked(c.CHK_CATCH):
                log(f'角色{a.role} 抓寵結束：{time.time() - t0:.1f} 秒；可抓捕數變動 {len(events)} 次 {events}；偵測 {polls} 圈')
                __import__('uikit').gui('shot', f'catchrun_r{a.role}_done.png')
                return 0
        print('8 分鐘仍未結束，停手回報')
        return 10
    finally:
        ass.close_panel()


if __name__ == '__main__':
    sys.exit(main())
