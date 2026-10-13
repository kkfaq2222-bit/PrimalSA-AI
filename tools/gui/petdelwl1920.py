#!/usr/bin/env python3
"""丟棄轉生獎勵「烏力斯坦」（1920×1017；只准丟名稱含「烏力」或「斯坦」的寵物）。
每個角色：逐格點選讀名字（含「布克」才處理）→ 垃圾桶 472,348 → 提示窗 OCR 必須含「布克」才按確定 415,343，否則按取消。
用法：petdelwl1920.py --client kkfaq11111 --roles 1,2,3,4,5
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
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petdelwl 角色 {r}')
        done = False
        for i in range(5):
            if not pd.panel_open():
                print('面板不在 → 停手'); return 4
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=900, note=f'petdelwl 第 {i + 1} 格')
            nm = ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '2,3')) + ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '3,4'))
            if not any(k in nm for k in ('烏力', '斯坦')):
                continue
            pd.click(472, 348, wait=1200, note='petdelwl 垃圾桶')
            t = ''.join(uikit.ocr((385, 205, 240, 60), '-Zooms', '2,3')) + ''.join(uikit.ocr((385, 205, 240, 60), '-Zooms', '3,4'))
            if not any(k in t for k in ('烏力', '斯坦')):
                print(f'角色{r} 提示窗不是烏力斯坦（{t!r}）→ 取消、停手')
                pd.click(538, 343, wait=600)
                return 5
            pd.click(415, 343, wait=1300, note='petdelwl 確定丟棄')
            pd.log(f'角色{r} 已丟棄烏力斯坦（第 {i + 1} 格）')
            done = True
            break
        if not done:
            pd.log(f'角色{r} 沒找到烏力斯坦')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
