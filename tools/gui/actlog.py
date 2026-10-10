#!/usr/bin/env python3
"""AI 操作遊戲畫面的共用 log（只用標準函式庫）：tools/.cache/actions.log，只留最新 100 行，psa-hud pane 會顯示。

  import actlog
  actlog.add('walk', '10204 → 188,13')      # 寫一行：「23:14:25 walk 10204 → 188,13」
命令列：python tools/gui/actlog.py <類別> <說明...>
gui.ps1 的 click / drag / key 等也寫同一個檔（格式相同）；寫入失敗一律忽略，不影響操作。
併發：append 單行 + 裁尾，偶爾多個程序同時裁尾可能掉一行，可接受。
"""
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / '.cache' / 'actions.log'
KEEP = 100


def add(kind: str, msg: str = '', path: Path = LOG, keep: int = KEEP) -> None:
    line = f'{time.strftime("%H:%M:%S")} {kind} {msg}'.rstrip().replace('\r', ' ').replace('\n', ' ')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8', newline='\n') as f:
            f.write(line + '\n')
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        if len(lines) > keep:
            path.write_text('\n'.join(lines[-keep:]) + '\n', encoding='utf-8', newline='\n')
    except OSError:
        pass


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('用法：actlog.py <類別> <說明...>')
    add(sys.argv[1], ' '.join(sys.argv[2:]))
