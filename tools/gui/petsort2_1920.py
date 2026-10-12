#!/usr/bin/env python3
"""修正版分寵：領之前一律先讀倉庫格子上方的名字（OCR，位置不靠記憶）。
A. 多餘存公共（依寵物欄格位，欄內格位不會位移）  B. 缺的從公共讀名字後領。
用法：uv run --no-project python tools/gui/petsort2_1920.py --client kkfaq11111
"""
import argparse, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
PUBLIC, TAKE_BTN, STORE_BTN = (757, 100), (362, 430), (360, 430)
SURPLUS = {2: [(3, '霍爾克')], 4: [(2, '奇寶'), (4, '奇寶')], 5: [(4, '火雞')]}
NEED = {2: ['奇寶'], 4: ['火雞', '霍爾克'], 5: ['奇寶']}


def species(t: str):
    if '霍' in t or '爾克' in t:
        return '霍爾克'
    if '克克' in t or '洛斯' in t:
        return '克克洛斯'
    if '奇' in t or '寶' in t:
        return '奇寶'
    if '火' in t or '雞' in t or '難' in t:
        return '火雞'
    return None


def read_depot(uikit, n=12):
    out = []
    for k in range(n):
        x, y = XS[k % 5], YS[k // 5]
        t = ''.join(uikit.ocr((x - 33, y - 30, 66, 18), '-Zooms', '2,3')).strip()
        out.append(species(t))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r in (2, 4, 5):                                   # A. 存多餘
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petsort2 選角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=1100, note='petsort2 倉庫分頁')
        pd.click(*PUBLIC, wait=700, note='petsort2 公共分頁')
        for slot, nm in SURPLUS[r]:
            if pd.slot_empty(slot - 1):
                print(f'角色{r} 第 {slot} 格空 → 停手'); return 4
            pd.click(pd.SLOT_X, pd.SLOT_Y[slot - 1], wait=700, note=f'petsort2 角色{r} 選第 {slot} 格（{nm}）')
            pd.click(*STORE_BTN, wait=1000, note='petsort2 存入公共')
            if not pd.slot_empty(slot - 1):
                print(f'角色{r} 第 {slot} 格沒存進去 → 停手'); return 5
        pd.log(f'角色{r} 多餘已存公共')
    for r in (2, 4, 5):                                   # B. 領缺的（每次先讀名字）
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petsort2 選角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=1100, note='petsort2 倉庫分頁')
        pd.click(*PUBLIC, wait=800, note='petsort2 公共分頁')
        for nm in NEED[r]:
            names = read_depot(uikit)
            if nm not in names:
                print(f'角色{r} 要 {nm}，倉庫讀到 {names} → 停手'); return 6
            k = names.index(nm)
            pd.click(XS[k % 5], YS[k // 5], wait=800, note=f'petsort2 角色{r} 領 {nm}（第 {k + 1} 格）')
            pd.click(*TAKE_BTN, wait=1000, note='petsort2 取出寵物')
        pd.log(f'角色{r} 已領 {NEED[r]}')
    pd.log(f'公共倉庫剩：{read_depot(uikit, 8)}')
    pd.click(*pd.CLOSE_X, wait=500, note='petsort2 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
