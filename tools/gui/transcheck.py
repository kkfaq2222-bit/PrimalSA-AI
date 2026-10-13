#!/usr/bin/env python3
"""讀目前角色的轉生數（人物資訊面板；HUD 會把 1 轉讀成 0）→ 印數字。退出碼：0 讀到；3 讀不到。
用法：uv run --no-project python tools/gui/transcheck.py --client kkfaq11111
（fullrun_watchdog --loop 用來判斷「轉到 5 轉就不再開下一輪」）"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    os.environ.setdefault('PSA_GUI_SERVER', '1')
    import winenv
    winenv.enable_server()
    import q1920 as q
    import questflow1920 as qf
    q.CLIENT = a.client
    n = qf.trans_from_info_panel()
    if n is None:
        return 3
    print(n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
