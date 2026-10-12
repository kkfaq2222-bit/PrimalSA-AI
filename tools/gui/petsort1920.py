#!/usr/bin/env python3
"""依名字讀取結果（notes/pets-names.json）把角色 2~5 的寵物欄補成 4 種火雞各 1：
先把多餘的（依寵物欄格位，格位不會因存入而位移）存公共倉庫 → 再依「存入順序的倉庫位置（模擬往前補位）」領缺的。
用法：uv run --no-project python tools/gui/petsort1920.py --client kkfaq11111 [--plan]
"""
import argparse, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
PUBLIC = (757, 100)
TAKE_BTN = (362, 430)
STORE_BTN = (360, 430)
# 角色 → 要存公共的欄格（1 起算）。存入順序 = 公共倉庫排列順序（角色 2、3、4、5；各角色內依格位由小到大）
SURPLUS = {2: [(3, '火雞'), (4, '霍爾克')], 3: [(5, '火雞')], 4: [(2, '奇寶'), (4, '奇寶'), (5, '奇寶')], 5: [(3, '霍爾克'), (5, '克克洛斯')]}
NEED = {2: ['奇寶'], 4: ['火雞', '霍爾克'], 5: ['奇寶']}


def grid_pt(k):               # 倉庫第 k 格（0 起算）
    return XS[k % 5], YS[k // 5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--plan', action='store_true')
    a = ap.parse_args()
    depot = []
    for r in (2, 3, 4, 5):
        for slot, nm in SURPLUS[r]:
            depot.append(nm)
    print('預期公共倉庫順序：', depot)
    sim = list(depot)
    takes = []
    for r in (2, 4, 5):
        for nm in NEED[r]:
            k = sim.index(nm)
            takes.append((r, nm, k))
            sim.pop(k)
    print('領取：', takes, '→ 剩', sim)
    if a.plan:
        return 0
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    # A. 存多餘
    for r in (2, 3, 4, 5):
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petsort 選角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=1100, note='petsort 倉庫分頁')
        pd.click(*PUBLIC, wait=700, note='petsort 公共分頁')
        for slot, nm in SURPLUS[r]:
            if pd.slot_empty(slot - 1):
                print(f'角色{r} 第 {slot} 格是空的 → 停手'); return 4
            pd.click(pd.SLOT_X, pd.SLOT_Y[slot - 1], wait=600, note=f'petsort 角色{r} 選第 {slot} 格（{nm}）')
            pd.click(*STORE_BTN, wait=1000, note='petsort 存入公共')
            if not pd.slot_empty(slot - 1):
                print(f'角色{r} 第 {slot} 格沒存進去 → 停手'); return 5
        pd.log(f'角色{r} 多餘 {len(SURPLUS[r])} 隻已存公共')
    # B. 領缺的（依模擬的倉庫位置）
    sim = list(depot)
    for r in (2, 4, 5):
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petsort 選角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=1100, note='petsort 倉庫分頁')
        pd.click(*PUBLIC, wait=700, note='petsort 公共分頁')
        for nm in NEED[r]:
            k = sim.index(nm)
            sim.pop(k)
            pd.click(*grid_pt(k), wait=700, note=f'petsort 角色{r} 領 {nm}（倉庫第 {k + 1} 格）')
            pd.click(*TAKE_BTN, wait=1000, note='petsort 取出寵物')
        pd.log(f'角色{r} 已領 {NEED[r]}')
    pd.click(*pd.CLOSE_X, wait=500, note='petsort 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
