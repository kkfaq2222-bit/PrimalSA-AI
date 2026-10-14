#!/usr/bin/env python3
"""每日任務監看小視窗（獨立、可用滑鼠拖曳、置頂）：上半 = 遊戲畫面（定時背景截圖），下半 = 我現在在做什麼
（讀 tools/.cache/daily-live.log 最後幾行 + 每日一條龍階段）。唯讀：不點擊、不按鍵。
用法：
  uv run --no-project python tools/gui/dailywin.py --client kkfaq11111 [--width 480] [--every 2] [--lines 12] [--role 2]
操作：左鍵拖曳移動；雙擊關閉；右鍵切換「放大 / 縮小」畫面。
"""
import argparse
import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--width', type=int, default=480, help='畫面寬（960 的整數分之一：480 / 320 / 240）')
    ap.add_argument('--every', type=float, default=2.0)
    ap.add_argument('--lines', type=int, default=12)
    ap.add_argument('--role', type=int, default=0)
    ap.add_argument('--pos', default='20,20')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    os.environ.setdefault('PSA_GUI_SERVER', '1')
    import winenv
    out = CACHE / f'dailywin-{a.client}.png'
    log_f = CACHE / 'daily-live.log'
    tag = f'-r{a.role}' if a.role else ''
    st_f = CACHE / f'dailyrun-{a.client}{tag}.json'
    div = max(1, round(960 / max(120, a.width)))
    x, y = (int(v) for v in a.pos.split(','))

    root = tk.Tk()
    root.title(f'每日任務監看 {a.client}')
    root.attributes('-topmost', True)
    root.configure(bg='#111111')
    img_label = tk.Label(root, bg='#000000', bd=0)
    img_label.pack()
    stage = tk.Label(root, text='', bg='#111111', fg='#7ee787', font=('Microsoft JhengHei UI', 10, 'bold'), anchor='w')
    stage.pack(fill='x')
    txt = tk.Label(root, text='', bg='#111111', fg='#e6e6e6', font=('Microsoft JhengHei UI', 9), anchor='nw',
                   justify='left', wraplength=960 // div - 10)
    txt.pack(fill='both', expand=True)
    w = 960 // div
    root.geometry(f'{w}x{508 // div + 30 + a.lines * 17}+{x}+{y}')
    state = {'img': None, 'div': div}
    drag = {'x': 0, 'y': 0}

    def press(e):
        drag['x'], drag['y'] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

    def move(e):
        root.geometry(f'+{e.x_root - drag["x"]}+{e.y_root - drag["y"]}')

    def toggle(_e=None):
        state['div'] = 1 if state['div'] > 1 else div
        root.geometry('')

    for wdg in (root, img_label, stage, txt):
        wdg.bind('<ButtonPress-1>', press)
        wdg.bind('<B1-Motion>', move)
        wdg.bind('<Double-Button-1>', lambda e: root.destroy())
        wdg.bind('<Button-3>', toggle)

    def refresh_img():
        try:
            winenv.run_ps('gui.ps1', 'shot', str(out), '-NoRestore', '1')
            img = tk.PhotoImage(file=str(out))
            if state['div'] > 1:
                img = img.subsample(state['div'], state['div'])
            state['img'] = img
            img_label.config(image=img)
        except Exception:
            pass

    def refresh_txt():
        try:
            lines = log_f.read_text(encoding='utf-8', errors='replace').splitlines()[-a.lines:]
        except OSError:
            lines = ['（還沒有 daily-live.log：跑 dailyrun1920 / dailyquest1920 之後會出現）']
        txt.config(text='\n'.join(l[:60] for l in lines))
        try:
            st = json.loads(st_f.read_text(encoding='utf-8'))
            stage.config(text=f'{a.client}{tag}　已完成：' + '、'.join(st.get('done', [])[-6:]) + f'　{time.strftime("%H:%M:%S")}')
        except Exception:
            stage.config(text=f'{a.client}{tag}　{time.strftime("%H:%M:%S")}')

    def loop():
        t0 = time.time()
        refresh_txt()
        refresh_img()
        root.after(max(500, int((a.every - (time.time() - t0)) * 1000)), loop)

    root.after(200, loop)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
