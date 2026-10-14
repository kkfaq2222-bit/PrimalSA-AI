#!/usr/bin/env python3
"""遊戲畫面預覽小視窗（一個客戶端一個視窗、一個程式）：定時背景截圖（PrintWindow，不搶焦點、不還原最小化），縮小顯示。
唯讀：不點擊、不按鍵；視窗本身滑鼠穿透（WS_EX_TRANSPARENT）+ 不搶焦點（WS_EX_NOACTIVATE），點下去會點到後面的東西，所以「不能點」。
置頂；關閉方式：工作管理員 / 本程式的終端機 Ctrl+C / `--stop`（見下）。

用法（專案根目錄）：
  uv run --no-project python tools/gui/hudview.py --client kkfaq11111
  uv run --no-project python tools/gui/hudview.py --client 333 --width 400 --every 4 --pos 20,300
  tools\\gui\\run_view.cmd 333
  uv run --no-project python tools/gui/hudview.py --client 333 --stop     結束該客戶端的預覽（寫 tools/.cache/hudview-<client>.stop）
"""
import argparse
import ctypes
import os
import sys
import time
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'
DEFAULT_POS = {'kkfaq11111': (20, 20), 'kkfaq22222': (20, 330), '333': (520, 20), 'kkfaq33333': (520, 20)}


def click_through(root) -> None:
    """視窗滑鼠穿透 + 不啟用 + 工具視窗（不進工作列）；失敗就算了（視窗仍可用，只是點得到）"""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE = -20
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080      # LAYERED | TRANSPARENT | NOACTIVATE | TOOLWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', required=True)
    ap.add_argument('--every', type=float, default=3.0, help='幾秒截一次（預設 3；越小越吃資源）')
    ap.add_argument('--width', type=int, default=480, help='視窗寬度像素（截圖 960 寬，用整數倍縮小：480 / 320 / 240）')
    ap.add_argument('--pos', default='', help='視窗左上角 x,y')
    ap.add_argument('--movable', action='store_true', help='可用滑鼠拖曳移動（不穿透）；雙擊視窗關閉')
    ap.add_argument('--stop', action='store_true')
    a = ap.parse_args()
    stop_file = CACHE / f'hudview-{a.client}.stop'
    if a.stop:
        stop_file.write_text('stop', encoding='utf-8')
        print('已要求結束', a.client)
        return 0
    try:
        stop_file.unlink()
    except OSError:
        pass
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    out = CACHE / f'view-{a.client}.png'
    div = max(1, round(960 / max(120, a.width)))          # subsample 倍數
    x, y = (tuple(int(v) for v in a.pos.split(',')) if a.pos else DEFAULT_POS.get(a.client, (20, 20)))

    root = tk.Tk()
    root.title(f'view {a.client}')
    root.attributes('-topmost', True)
    root.overrideredirect(True)
    root.configure(bg='#000000')
    img_label = tk.Label(root, bg='#000000', bd=0)
    img_label.pack()
    tag = tk.Label(root, text=a.client, bg='#000000', fg='#7ee787', font=('Microsoft JhengHei UI', 9), anchor='w')
    tag.pack(fill='x')
    w, h = 960 // div, 508 // div
    root.geometry(f'{w}x{h + 18}+{x}+{y}')
    if a.movable:
        drag = {'x': 0, 'y': 0}

        def on_press(e):
            drag['x'], drag['y'] = e.x_root - root.winfo_x(), e.y_root - root.winfo_y()

        def on_move(e):
            root.geometry(f'+{e.x_root - drag["x"]}+{e.y_root - drag["y"]}')
        for wdg in (root, img_label, tag):
            wdg.bind('<ButtonPress-1>', on_press)
            wdg.bind('<B1-Motion>', on_move)
            wdg.bind('<Double-Button-1>', lambda e: root.destroy())
    else:
        click_through(root)
    state = {'img': None, 'n': 0}

    def refresh() -> None:
        if stop_file.exists():
            root.destroy()
            return
        t0 = time.time()
        note = ''
        try:
            r = winenv.run_ps('gui.ps1', 'shot', str(out), '-NoRestore', '1')
            txt = (r.stdout or '').strip()
            if 'minimized' in txt:
                note = '（遊戲視窗最小化）'
            else:
                img = tk.PhotoImage(file=str(out))
                if div > 1:
                    img = img.subsample(div, div)
                state['img'] = img                          # 要持有參考，否則會被回收
                img_label.config(image=img)
        except Exception as e:                               # 截圖失敗 / 檔案寫到一半：保留上一張
            note = f'（截圖失敗：{type(e).__name__}）'
        state['n'] += 1
        tag.config(text=f'{a.client}　{time.strftime("%H:%M:%S")}{note}')
        wait = max(500, int((a.every - (time.time() - t0)) * 1000))
        root.after(wait, refresh)

    root.after(200, refresh)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
