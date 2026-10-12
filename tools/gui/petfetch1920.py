#!/usr/bin/env python3
"""從公共寵物倉庫「永遠點第一格 → 取出寵物」N 隻到指定角色的寵物欄（1920×1017；不分種類）。
用法：uv run --no-project python tools/gui/petfetch1920.py --client kkfaq11111 --roles 2,3,4,5 --n 5
每個角色做完讀寵物欄是否有 N 隻；少了就停手回報。第一格位置固定（倉庫取出後會往前補位），所以不用記其他座標。
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
FIRST_SLOT = (542, 170)
TAKE_BTN = (362, 430)       # 選中倉庫寵物時，左下按鈕是「取出寵物」
PUBLIC = (757, 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='2,3,4,5')
    ap.add_argument('--n', type=int, default=5)
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r in [int(x) - 1 for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r], wait=1200, note=f'petfetch 選角色 {r + 1}')
        pd.click(*pd.TAB_DEPOT, wait=1300, note='petfetch 倉庫分頁')
        pd.click(*PUBLIC, wait=900, note='petfetch 公共分頁')
        before = [i for i in range(5) if not pd.slot_empty(i)]
        if before:
            print(f'角色{r + 1} 寵物欄已有 {len(before)} 隻 → 停手'); return 4
        for k in range(a.n):
            pd.click(*FIRST_SLOT, wait=800, note=f'petfetch 第一格（第 {k + 1} 隻）')
            pd.click(*TAKE_BTN, wait=1100, note='petfetch 取出寵物')
        got = [i for i in range(5) if not pd.slot_empty(i)]
        pd.log(f'角色{r + 1} 寵物欄 {len(got)} 隻')
        if len(got) != a.n:
            print('數量不對 → 停手'); return 5
    pd.click(*pd.CLOSE_X, wait=600, note='petfetch 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
