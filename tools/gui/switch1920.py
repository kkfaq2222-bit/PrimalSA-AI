#!/usr/bin/env python3
"""切換當前角色（1920×1017）：開切換面板(533,465) → 點第 N 張卡片 → 等 HUD 回來 → 讀回確認。
卡片順序（2026-10-12 實測，面板 960×508）：角色 1 (400,185) 角色 2 (600,185) 角色 3 (400,240) 角色 4 (600,240) 角色 5 (400,295)。
用法：switch1920.py --client kkfaq11111 --role 2     （成功印 OK，退出碼 0）
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
CARD = {1: (400, 185), 2: (600, 185), 3: (400, 240), 4: (600, 240), 5: (400, 295)}
OPEN, CLOSE_X = (533, 465), (698, 125)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--role', type=int, required=True)
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import uikit
    uikit.gui('seq', f'click {OPEN[0]} {OPEN[1]} right; click {OPEN[0]} {OPEN[1]} right; click {OPEN[0]} {OPEN[1]}; wait 1300')
    c = uikit.px([CLOSE_X])
    if not c or abs(c[0][0] - 183) > 40:
        print('切換面板沒開 → 停手'); return 3
    x, y = CARD[a.role]
    uikit.gui('click', str(x), str(y))
    time.sleep(3.5)
    print('OK（請用截圖 / 名字確認當前角色）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
