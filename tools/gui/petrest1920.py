#!/usr/bin/env python3
"""全部寵物改「休息」（1920×1017）：每個角色寵物欄 5 格逐格偵測狀態，不是「休息」就按休息並驗證。

使用者 2026-10-13：恐龍博士交任務前要取消出戰，但自動轉換戰寵會把出戰換到第 2 隻（貝魯卡），
舊版只動第 1 格，所以第 2 隻一直出戰、NPC 不收。現在 5 格都看，狀態用面板下方三顆鈕哪顆是橘金色判斷。
座標（960×508）：頭像 x=185、y=PET_SLOT_Y；出戰 272,433；騎乘 362,433；休息 452,433。
用法：petrest1920.py --client kkfaq11111 --roles 1,2,3,4,5
退出碼：0 全部休息；3 面板打不開；4 有寵物按了休息仍不是休息狀態。
"""
import argparse, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

SLOT_Y = [120, 197, 275, 352, 430]
MODE_PTS = (('battle', (272, 423)), ('ride', (362, 423)), ('rest', (452, 423)))
REST_BTN = (452, 433)


def pet_mode(cols):
    """選中的是哪顆鈕（橘金色 ≈ 190,125,60；沒選中米色 ≈ 225,200,167）；讀不到回 None"""
    if not cols or len(cols) != len(MODE_PTS):
        return None
    for (name, _), (r, g, b) in zip(MODE_PTS, cols):
        if r > 150 and g < 190 and b < 100:
            return name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='1,2,3,4,5')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv; winenv.enable_server()
    import petdepot1920 as pd
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    bad = []
    try:
        for r in [int(x) for x in a.roles.split(',')]:
            pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1000, note=f'petrest 角色 {r}')
            done = []
            for s in range(5):
                if pd.slot_empty(s):
                    continue
                for k in range(3):
                    pd.click(185, SLOT_Y[s], wait=800, note=f'petrest 角色 {r} 第 {s + 1} 格')
                    mode = pet_mode(pd.px([p for _, p in MODE_PTS]))
                    if mode == 'rest':
                        break
                    pd.click(*REST_BTN, wait=1000, note=f'petrest 角色 {r} 第 {s + 1} 格休息')
                else:
                    pd.click(185, SLOT_Y[s], wait=800, note='petrest 最後驗證')
                    mode = pet_mode(pd.px([p for _, p in MODE_PTS]))
                    if mode != 'rest':
                        bad.append((r, s + 1, mode))
                        pd.log(f'警告：角色{r} 第 {s + 1} 格按了休息仍是 {mode}')
                        continue
                done.append(s + 1)
            pd.log(f'角色{r} 休息確認：第 {done} 格')
    finally:
        pd.click(*pd.CLOSE_X, wait=500)
    if bad:
        print(f'仍不是休息：{bad}')
        return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
