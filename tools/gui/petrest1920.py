#!/usr/bin/env python3
"""全部寵物改「休息」（1920×1017）：對第 1 格寵物依序點 騎乘 → 出戰 → 休息（使用者 2026-10-11 快速做法）。
座標：頭像 x=185 y=120；騎乘 348,433；出戰 272,433；休息 452,433。
用法：petrest1920.py --client kkfaq11111 --roles 1,2,3,4,5
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
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petrest 角色 {r}')
        pd.click(185, 120, wait=800, note='petrest 第 1 格')
        for x, n in ((348, '騎乘'), (272, '出戰'), (452, '休息')):
            pd.click(x, 433, wait=1100, note=f'petrest {n}')
        pd.log(f'角色{r} 已全部休息')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
