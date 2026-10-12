#!/usr/bin/env python3
"""刪除卡坦步 1 獎勵「修寶」（1920×1017；只准丟 修寶 / 布克布克）。每隻：選第 1 格 → 垃圾桶 472,348 → 提示窗 OCR 含「修寶」才按確定 415,343。
前提：寵物面板已開（先 open_panel；點擊前確認面板在）。用法：petdelxb1920.py --client kkfaq11111 --roles 2,3,4,5
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='2,3,4,5')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petdelxb 角色 {r}')
        if not pd.panel_open():
            print('面板不在 → 停手'); return 4
        if pd.slot_empty(0):
            pd.log(f'角色{r} 第 1 格是空的，略過'); continue
        pd.click(185, 120, wait=900, note='petdelxb 第 1 格')
        pd.click(472, 348, wait=1200, note='petdelxb 垃圾桶')
        t = ''.join(uikit.ocr((385, 205, 240, 60), '-Zooms', '2,3'))
        if '修' not in t and '寶' not in t:
            print(f'角色{r} 提示窗不是修寶（{t!r}）→ 取消、停手')
            pd.click(538, 343, wait=600)
            return 5
        pd.click(415, 343, wait=1200, note='petdelxb 確定丟棄')
        pd.log(f'角色{r} 已丟棄修寶（第 1 格空={pd.slot_empty(0)}）')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
