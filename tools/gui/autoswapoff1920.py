#!/usr/bin/env python3
"""5 人外掛「自動轉換戰寵」全部取消勾選（questflow.autoswap_off；勾選用框內暗色點數判斷）。
用法：uv run --no-project python tools/gui/autoswapoff1920.py --client kkfaq11111
退出碼：0 全部沒勾；其他 = 外掛打不開 / 仍有勾（只記警告，不影響一條龍往下跑）"""
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
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import q1920 as q
    import questflow1920 as qf
    q.CLIENT = a.client
    try:
        qf.autoswap_off()
    except Exception as e:
        print(f'警告：關自動轉換戰寵沒成功：{getattr(e, "msg", e)}', flush=True)
        return 4
    print('自動轉換戰寵已全部取消勾選', flush=True)
    return 0


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('autoswapoff1920')       # 印出「停手」就當下存圖（面板還開著）
    sys.exit(main())
