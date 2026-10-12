#!/usr/bin/env python3
"""丟棄恐龍博士獎勵「布克布克」（1920×1017；只准丟 布克布克 / 修寶）。
每個角色：逐格點選讀名字（含「布克」才處理）→ 垃圾桶 472,348 → 提示窗 OCR 必須含「布克」才按確定 415,343，否則按取消。
用法：petdelbk1920.py --client kkfaq11111 --roles 1,2,3,4,5
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
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petdelbk 角色 {r}')
        done = False
        for i in range(5):
            if not pd.panel_open():
                print('面板不在 → 停手'); return 4
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=900, note=f'petdelbk 第 {i + 1} 格')
            nm = ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '2,3')) + ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '3,4'))
            if '布克' not in nm:
                continue
            pd.click(472, 348, wait=1200, note='petdelbk 垃圾桶')
            t = ''.join(uikit.ocr((385, 205, 240, 60), '-Zooms', '2,3')) + ''.join(uikit.ocr((385, 205, 240, 60), '-Zooms', '3,4'))
            if '布克' not in t:
                print(f'角色{r} 提示窗不是布克布克（{t!r}）→ 取消、停手')
                pd.click(538, 343, wait=600)
                return 5
            pd.click(415, 343, wait=1300, note='petdelbk 確定丟棄')
            pd.log(f'角色{r} 已丟棄布克布克（第 {i + 1} 格）')
            done = True
            break
        if not done:
            pd.log(f'角色{r} 沒找到布克布克')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
