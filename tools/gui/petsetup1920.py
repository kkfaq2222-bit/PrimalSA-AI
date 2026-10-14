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
    ap.add_argument('--by-name', action='store_true', help='改用名稱 OCR 判斷（預設固定位置：第 1 格騎乘、第 2 格出戰）')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import uikit
    if not pd.open_panel():
        print('寵物面板打不開')
        return 3
    rc = 0
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1200, note=f'petsetup 角色 {r}')
        pd.click(885, 175, wait=900, note='petsetup 寵物分頁')
        if not a.by_name:                  # 固定位置（使用者 2026-10-14：OCR 辨識不穩）：第 1 格騎乘、第 2 格出戰
            names = []
            for i in range(2):             # 先讀名字當護欄：兩格都沒有金格 / 朵拉 = 根本沒領到，停手不要亂按
                pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=1500, note=f'petsetup 第 {i + 1} 格（檢查）')
                names.append(pd.match_pet_name(pd.read_pet_name(uikit)))
            if not any(names):
                pd.log(f'角色{r} 寵物欄前兩格讀不到寵物名（{names}）→ 可能沒領到，不按騎乘 / 出戰')
                rc = 5
                continue
            # 只對朵拉比斯按「出戰」；騎乘已在 lock 階段鎖定，這裡不再按（再按可能變成取消騎乘）
            if '朵拉比斯' not in names:
                pd.log(f'角色{r} 前兩格沒讀到朵拉比斯（{names}）→ 不按出戰')
                rc = 5
                continue
            i = names.index('朵拉比斯')
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=1500, note=f'petsetup 第 {i + 1} 格')
            pd.click(*FIGHT_BTN, wait=1000, note=f'petsetup 第 {i + 1} 格 朵拉比斯 出戰')
            pd.log(f'角色{r} 朵拉比斯（第 {i + 1} 格）已按出戰')
            if a.shot:
                uikit.gui('shot', f'{a.shot}{r}.png')
            continue
        for i in range(2):                 # 轉生後寵物欄只有老虎 + 飛龍；空格會殘留上一隻的選取，不要掃
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=800, note=f'petsetup 第 {i + 1} 格')
            nm =''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '2,3')) + ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '3,4'))
            if '朵拉' in nm:
                pd.click(*FIGHT_BTN, wait=1000, note='petsetup 朵拉比斯 出戰')
                pd.log(f'角色{r} 朵拉比斯（第 {i + 1} 格）已按出戰')
            elif '金格' in nm:
                pd.click(*RIDE_BTN, wait=1000, note='petsetup 金格薩貝魯 騎乘')
                pd.log(f'角色{r} 金格薩貝魯（第 {i + 1} 格）已按騎乘')
        if a.shot:
            uikit.gui('shot', f'{a.shot}{r}.png')
    pd.click(*pd.CLOSE_X, wait=500)
    return rc


if __name__ == '__main__':
    sys.exit(main())
