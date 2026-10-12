#!/usr/bin/env python3
"""設戰寵 / 坐騎（1920×1017）：第 5 格 → 騎乘、第 1 格 → 出戰。每個角色做完讀兩格的狀態標籤驗證。
座標：頭像 x=185 y=120/197/275/352/430；出戰 272,433；騎乘 348,433；休息 452,433。
"""
import argparse, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='1,2,3,4,5')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petbattle 角色 {r}')
        if any(pd.slot_empty(i) for i in range(5)):
            print(f'角色{r} 寵物欄不滿 5 格 → 停手'); return 4
        pd.click(185, 430, wait=800, note='petbattle 第 5 格')
        pd.click(348, 433, wait=1200, note='petbattle 騎乘')
        pd.click(185, 120, wait=800, note='petbattle 第 1 格')
        pd.click(272, 433, wait=1200, note='petbattle 出戰')
        pd.log(f'角色{r} 已設（第 5 格騎乘、第 1 格出戰）')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
