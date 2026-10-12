#!/usr/bin/env python3
"""抓寵監看（1920×1017）：每 N 秒開外掛看角色 R 的「自動抓寵」勾選；被遊戲取消 = 抓完 → 存檔外掛截圖（讀可抓捕數）並回報耗時。
用法：uv run --no-project python tools/gui/catchwatch1920.py --client kkfaq11111 --role 2 [--every 30] [--max 900]
"""
import argparse, os, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--role', type=int, required=True)
    ap.add_argument('--every', type=int, default=30)
    ap.add_argument('--max', type=int, default=900)
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import ass, catch1920 as c, uikit
    names = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']
    t0 = time.time()
    while time.time() - t0 < a.max:
        if True:
            if ass.open_panel(timeout=20) and ass.select_role(names[0] if a.role != 1 else names[1])                     and ass.select_role(names[a.role - 1]) and c.ensure_tab():   # 切別人再切回來才會刷新勾選
                on = c.is_checked(c.CHK_CATCH)
                print(time.strftime('%H:%M:%S'), f'已過 {int(time.time() - t0)}s 自動抓寵={"開" if on else "關"}', flush=True)
                if not on:
                    uikit.gui('shot', f'catchwatch_r{a.role}.png')
                    ass.close_panel()
                    print(f'抓完：監看起 {int(time.time() - t0)} 秒；外掛截圖 tools/.cache/catchwatch_r{a.role}.png（讀可抓捕數）')
                    return 0
            ass.close_panel()
        time.sleep(a.every)
    print('逾時仍在抓')
    return 10


if __name__ == '__main__':
    sys.exit(main())
