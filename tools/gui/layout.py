#!/usr/bin/env python3
"""遊戲視窗版面判斷（只用標準函式庫）：依客戶區大小決定用哪一套截圖座標。

支援的版面：
  '2880x1659'  原本的基準（2880×1659 客戶區 → 截圖 1440×830），ui/ 文件與各腳本的預設常數都以它為準
  '1920x1017'  1920×1080 螢幕最大化（截圖 960×508）；UI 約為 2880×1659 的 0.613 倍，座標見 ui/layout-1920x1017.md

  import layout
  layout.current()        # → '2880x1659' | '1920x1017' | 其他 'WxH' | None（遊戲沒開）；同一個行程只問一次
  layout.SUPPORTED        # 支援的版面

環境變數 PSA_LAYOUT=1920x1017 可直接指定（不問遊戲；例：遊戲沒開時用 walk.py --plan 試算）。
命令列：python tools/gui/layout.py   → 印出目前版面
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winenv  # noqa: E402

SUPPORTED = ('2880x1659', '1920x1017')
DEFAULT = '2880x1659'
_cache: list = []


def current() -> str | None:
    """目前遊戲客戶區大小 'WxH'（gui.ps1 info）；PSA_LAYOUT 優先。遊戲沒開或讀不到回 None"""
    env = os.environ.get('PSA_LAYOUT')
    if env:
        return env
    if not _cache:
        try:
            out = winenv.run_ps('gui.ps1', 'info', timeout=30).stdout
        except Exception:   # 不是 Windows / WSL、powershell 逾時…
            out = ''
        m = re.search(r'client=(\d+)x(\d+)', out)
        _cache.append(f'{m[1]}x{m[2]}' if m else None)
    return _cache[0]


def resolve() -> str:
    """給腳本選常數用：支援的版面原樣回傳；遊戲沒開 / 不支援的大小回 DEFAULT（維持原本行為）"""
    cur = current()
    return cur if cur in SUPPORTED else DEFAULT


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cur = current()
    print(f'客戶區 {cur}；採用版面 {resolve()}' + ('' if cur in SUPPORTED else '（不支援的大小，沿用預設；請最大化遊戲視窗）'))
