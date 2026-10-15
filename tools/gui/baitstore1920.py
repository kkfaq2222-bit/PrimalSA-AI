#!/usr/bin/env python3
r"""把角色背包裡剩下的「寵物誘餌」整疊存進共用倉庫（道具倉庫 → 公共分頁）（1920×1017 專用）。

用途（使用者 2026-10-12）：鯊魚抓完後，角色 2 身上剩的誘餌存回共用倉庫，火雞組（角色 3）再從公共倉庫取。
流程：開背包 → 選角色 → 背包分頁找誘餌（顏色初篩 + 浮窗標題含「誘餌」）→ 倉庫分頁 → 公共 →
      單擊誘餌格（不雙擊）→ 確認浮窗標題是誘餌 → 「存入」→ 該格不再是誘餌才算成功 → 關背包。
安全：每次點擊前確認背包面板還開著；浮窗標題不是誘餌就不按「存入」並停手。

用法（專案根目錄）：
  uv run --no-project python tools/gui/baitstore1920.py --client kkfaq22222 --role 2 [--dry]
退出碼：0 成功（存完或背包沒有誘餌，且共用倉庫確認有誘餌）；2 版面不符；4 找不到誘餌格以外的錯誤 / 存入後仍在；11 背包面板不在。
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def depot_has_bait(cr) -> bool:
    """開倉庫分頁 → 公共，看有沒有誘餌格（剛切角色 / 剛存入頁面偶爾沒畫好，最多讀 3 次）"""
    for _ in range(3):
        cr.click(*cr.TAB_DEPOT, wait=1300, note='baitstore 倉庫分頁（確認）')
        cr.click(*cr.DEPOT_PUBLIC, wait=1100, note='baitstore 公共倉庫（確認）')
        if cr.find_bait(cr.depot_slots()) is not None:
            return True
        time.sleep(1.0)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='剩餘寵物誘餌存共用倉庫')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('--role', type=int, required=True)
    ap.add_argument('--dry', action='store_true', help='只找誘餌、不存')
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
    import ass
    import catchrun1920 as cr
    if ass.in_battle():
        print('戰鬥中，停手')
        return 8
    cr.click(*cr.BAG_BTN, wait=1500, note='baitstore 開背包')
    cr.need_bag()
    cr.click(cr.ROLE_X, cr.ROLE_Y[a.role - 1], wait=1200, note=f'baitstore 背包切角色 {a.role}')
    cr.click(*cr.TAB_BAG, wait=900, note='baitstore 背包分頁')
    pos = cr.find_bait(cr.bag_slots())
    if pos is None:
        cr.log(f'角色 {a.role} 背包沒有誘餌，不用存；確認共用倉庫有誘餌')
        ok = depot_has_bait(cr)
        cr.gui('key', '{ESC}', note='baitstore 關浮窗')
        cr.click(*cr.CLOSE_BAG, wait=500, note='baitstore 關背包')
        if not ok:
            cr.log('警告：背包沒有誘餌、共用倉庫也沒有（誘餌已用完？）→ 不停手；下一個要抓寵的角色領不到時會自己示警')
        return 0
    cr.gui('key', '{ESC}', note='baitstore 關浮窗')
    time.sleep(0.5)
    cr.log(f'誘餌在 {pos}')
    if a.dry:
        cr.click(*cr.CLOSE_BAG, wait=500, note='baitstore 關背包')
        return 0
    cr.need_bag()
    cr.click(*cr.TAB_DEPOT, wait=1200, note='baitstore 倉庫分頁')
    cr.click(*cr.DEPOT_PUBLIC, wait=800, note='baitstore 公共倉庫')
    cr.need_bag()
    cr.click(*pos, wait=900, note='baitstore 單擊誘餌格（不雙擊）')
    if cr.BAIT not in cr.title():
        print('浮窗標題不是誘餌 → 不存、停手')
        cr.gui('key', '{ESC}', note='baitstore 關浮窗')
        cr.click(*cr.CLOSE_BAG, wait=500, note='baitstore 關背包')
        return 4
    cr.click(*cr.POP_BTN, wait=1200, note='baitstore 存入')
    cr.need_bag()
    time.sleep(0.8)
    if cr.bait_score(pos) >= 4:
        print('存入後該格仍是誘餌 → 停手（倉庫滿 / 沒按到？）')
        cr.click(*cr.CLOSE_BAG, wait=500, note='baitstore 關背包')
        return 4
    # 存完一定要在共用倉庫看到誘餌，下一個抓寵的角色才領得到（使用者 2026-10-13）
    ok = depot_has_bait(cr)
    cr.gui('key', '{ESC}', note='baitstore 關浮窗')
    cr.click(*cr.CLOSE_BAG, wait=700, note='baitstore 關背包')
    if not ok:
        print('存入後共用倉庫找不到誘餌 → 停手')
        return 4
    cr.log(f'角色 {a.role} 剩餘誘餌已存進共用倉庫（已在共用倉庫確認）')
    return 0


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('baitstore1920')       # 印出「停手」就當下存圖（面板還開著）
    sys.exit(main())
