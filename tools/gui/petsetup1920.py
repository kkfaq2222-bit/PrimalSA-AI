#!/usr/bin/env python3
"""轉生後整備寵物（1920×1017）：朵拉比斯 → 出戰；金格薩貝魯（金色老虎）→ 騎乘。
每個角色：寵物欄逐格點選讀名字（含「朵拉」→ 出戰；含「金格」→ 騎乘），其他不動。
用法：petsetup1920.py --client kkfaq22222 --roles 1,2,3,4,5 [--shot-dir 前綴]
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
FIGHT_BTN = (280, 433)
RIDE_BTN = (345, 433)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq22222')
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--shot', default='')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import uikit
    if not pd.open_panel():
        print('寵物面板打不開')
        return 3
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1200, note=f'petsetup 角色 {r}')
        pd.click(885, 175, wait=900, note='petsetup 寵物分頁')
        for i in range(2):                 # 轉生後寵物欄只有老虎 + 飛龍；空格會殘留上一隻的選取，不要掃
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=800, note=f'petsetup 第 {i + 1} 格')
            nm = ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '2,3')) + ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '3,4'))
            if '朵拉' in nm:
                pd.click(*FIGHT_BTN, wait=1000, note='petsetup 朵拉比斯 出戰')
                pd.log(f'角色{r} 朵拉比斯（第 {i + 1} 格）已按出戰')
            elif '金格' in nm:
                pd.click(*RIDE_BTN, wait=1000, note='petsetup 金格薩貝魯 騎乘')
                pd.log(f'角色{r} 金格薩貝魯（第 {i + 1} 格）已按騎乘')
        if a.shot:
            uikit.gui('shot', f'{a.shot}{r}.png')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
