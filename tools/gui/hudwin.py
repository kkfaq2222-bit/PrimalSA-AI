#!/usr/bin/env python3
"""獨立小視窗（一個客戶端一個視窗、一個程式）：只讀 tools/.cache 的存檔，不碰遊戲畫面、不送任何輸入。
顯示：一條龍進度（已完成 N/16、下一階段）、停手旗標 / 暫停檔、該客戶端看門狗最近一次動靜、最近完成階段時間。

用法（專案根目錄）：
  uv run --no-project python tools/gui/hudwin.py --client kkfaq11111
  uv run --no-project python tools/gui/hudwin.py --client 333 --every 5
  tools\\gui\\run_hud.cmd 333                 （同上；cmd 版）
視窗置頂、可拖曳；關掉視窗就結束。三個客戶端各開一個。
"""
import argparse
import json
import sys
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'tools' / '.cache'
STAGES = ['train', 'wait131', 'stopenc', 'ledger', 'prebag', 'quests', 'riddle', 'katan', 'dino', 'gate',
          'rebirth', 'gift', 'organize', 'clear', 'prep', 'grind']
CN = {'train': '練等', 'wait131': '等131', 'stopenc': '關遇敵', 'ledger': '帳本', 'prebag': '整背包', 'quests': '任務',
      'riddle': '猜謎', 'katan': '卡坦', 'dino': '恐龍博士', 'gate': '守門人', 'rebirth': '轉生', 'gift': '禮盒',
      'organize': '整理寵', 'clear': '清寵', 'prep': '備戰', 'grind': '練1~131'}


def read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def ago(t: float) -> str:
    s = max(0, int(time.time() - t))
    return f'{s}秒前' if s < 90 else (f'{s // 60}分前' if s < 5400 else f'{s // 3600}小時前')


def snapshot(client: str) -> dict:
    st = read_json(CACHE / f'fullrun-{client}.json')
    done = [s for s in st.get('done', []) if s in STAGES]
    nxt = next((s for s in STAGES if s not in done), None)
    flag = read_json(CACHE / f'fullrun-flag-{client}.json')
    paused = (CACHE / f'PAUSE-{client}').exists() or (CACHE / 'PAUSE').exists()
    log = CACHE / f'watchdog-{client}.log'
    last = ''
    lt = 0.0
    try:
        lines = log.read_text(encoding='utf-8', errors='replace').strip().splitlines()
        last = lines[-1] if lines else ''
        lt = log.stat().st_mtime
    except OSError:
        pass
    return {'done': len(done), 'next': nxt, 'flag': flag, 'paused': paused, 'last': last, 'log_t': lt, 'at': st.get('at', '')}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', required=True)
    ap.add_argument('--every', type=float, default=5.0)
    a = ap.parse_args()
    root = tk.Tk()
    root.title(f'一條龍 {a.client}')
    root.attributes('-topmost', True)
    root.geometry('420x150+40+40')
    root.configure(bg='#1e1e1e')
    f = ('Microsoft JhengHei UI', 11)
    head = tk.Label(root, text='', font=('Microsoft JhengHei UI', 14, 'bold'), bg='#1e1e1e', fg='white', anchor='w')
    l1 = tk.Label(root, text='', font=f, bg='#1e1e1e', fg='#dddddd', anchor='w', justify='left')
    l2 = tk.Label(root, text='', font=f, bg='#1e1e1e', fg='#dddddd', anchor='w', justify='left')
    l3 = tk.Label(root, text='', font=('Microsoft JhengHei UI', 9), bg='#1e1e1e', fg='#999999', anchor='w', justify='left',
                  wraplength=400)
    for w in (head, l1, l2, l3):
        w.pack(fill='x', padx=10, pady=1)

    def refresh() -> None:
        s = snapshot(a.client)
        if s['flag']:
            color, tag = '#ff6b6b', f'停手（退出碼 {s["flag"].get("code")}）'
        elif s['paused']:
            color, tag = '#ffd166', '暫停中'
        else:
            color, tag = '#7ee787', '執行中'
        head.config(text=f'{a.client}　{tag}', fg=color)
        nxt = CN.get(s['next'], '全部完成') if s['next'] else '全部完成'
        l1.config(text=f'進度 {s["done"]}/{len(STAGES)}　下一階段：{nxt}')
        l2.config(text=f'最近完成階段：{s["at"] or "—"}　看門狗動靜：{ago(s["log_t"]) if s["log_t"] else "—"}')
        reason = s['flag'].get('reason') if s['flag'] else ''
        l3.config(text=(reason or s['last'])[:140], fg='#ff9b9b' if reason else '#999999')
        root.after(int(a.every * 1000), refresh)

    refresh()
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
