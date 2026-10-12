#!/usr/bin/env python3
"""鯊魚分類（1920×1017）：從角色個人倉庫依「圖示顏色 + 標籤是數字暱稱」挑出指定種類，逐隻取出 → 存公共。
每次都重新讀倉庫（取出後位置會補位），不靠記憶座標。寵物欄必須是空的（逐隻進出第 1 格）。
用法：uv run --no-project python tools/gui/petshark1920.py --client kkfaq11111 --role 2 [--n 4]
  角色 2：克邦凱斯（青綠）+ 加克拉（藍身黃肚）；角色 3：加格（深藍）+ 邦恩吉（淺藍綠）
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
PUBLIC, PERSONAL, TAKE_BTN, STORE_BTN = (757, 100), (542, 100), (362, 430), (360, 430)


def within(c, lo, hi):
    return all(l <= v <= h for v, l, h in zip(c, lo, hi))


# 中心點 (0,-2) 與肚子點 (0,16) 的顏色範圍（2026-10-12 實測）
CLASSES = {
    2: [('克邦凱斯', lambda a, b: within(a, (115, 205, 180), (150, 245, 215))),
        ('加克拉', lambda a, b: within(a, (70, 135, 185), (105, 175, 225)) and within(b, (225, 170, 0), (255, 215, 60)))],
    3: [('加格', lambda a, b: within(a, (40, 105, 140), (70, 140, 180))),
        ('邦恩吉', lambda a, b: within(a, (68, 145, 180), (125, 205, 240)))],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--role', type=int, required=True)
    ap.add_argument('--n', type=int, default=4)
    ap.add_argument('--flush', action='store_true', help='欄 1 有上次中斷留下的寵物就先存公共')
    ap.add_argument('--kinds', default='', help='只處理這些種類（逗號分隔，例 克邦凱斯）；沒給就用該角色預設的兩種')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    pd.click(pd.ROLE_X, pd.ROLE_Y[a.role - 1], wait=1000, note=f'petshark 選角色 {a.role}')
    if any(not pd.slot_empty(i) for i in range(5)):
        if a.flush:                                         # 欄 1 留有上次中斷時取出的鯊魚：先存公共
            pd.click(*pd.TAB_DEPOT, wait=1100); pd.click(*PUBLIC, wait=800)
            pd.click(pd.SLOT_X, pd.SLOT_Y[0], wait=700); pd.click(*STORE_BTN, wait=1200)
        if any(not pd.slot_empty(i) for i in range(5)):
            print('寵物欄不是空的 → 停手'); return 4
    if a.kinds:
        every = {n: p for lst in CLASSES.values() for n, p in lst}
        bad = [k for k in a.kinds.split(',') if k not in every]
        if bad:
            print(f'不認得的種類：{bad}（可用：{list(every)}）'); return 2
        todo = [(k, every[k]) for k in a.kinds.split(',')]
    else:
        todo = CLASSES[a.role]
    for name, pred in todo:
        for k in range(a.n):
            pd.click(*pd.TAB_DEPOT, wait=1100, note='petshark 倉庫分頁')
            pd.click(*PERSONAL, wait=800, note='petshark 個人分頁')
            pts = []
            for y in YS:
                for x in XS:
                    pts += [(x, y - 2), (x, y + 16)]
            cols = uikit.px(pts) or []
            if len(cols) != len(pts):
                print('讀不到像素 → 停手'); return 5
            cand = [i for i in range(20) if pred(cols[2 * i], cols[2 * i + 1])]
            picked = None
            for i in cand:
                x, y = XS[i % 5], YS[i // 5]
                t = ''.join(uikit.ocr((x - 33, y - 30, 66, 18), '-Zooms', '2,3'))
                if any(ch.isdigit() or ch == '/' for ch in t):
                    picked = i
                    break
            if picked is None:
                print(f'{name} 倉庫找不到（候選 {cand}）→ 停手'); return 6
            pd.click(XS[picked % 5], YS[picked // 5], wait=800, note=f'petshark {name} 第 {picked + 1} 格')
            pd.click(*TAKE_BTN, wait=1100, note='petshark 取出寵物')
            for _ in range(8):                                  # 取出後欄 1 出現寵物可能延遲：最多等約 4 秒
                if not pd.slot_empty(0):
                    break
                time.sleep(0.5)
            if pd.slot_empty(0):
                print('取出後欄 1 仍空 → 停手'); return 7
            pd.click(*PUBLIC, wait=800, note='petshark 公共分頁')
            pd.click(pd.SLOT_X, pd.SLOT_Y[0], wait=700, note='petshark 選欄 1')
            pd.click(*STORE_BTN, wait=1000, note='petshark 存入公共')
            for _ in range(8):
                if pd.slot_empty(0):
                    break
                time.sleep(0.5)
            if not pd.slot_empty(0):
                print('存入公共後欄 1 仍有寵物 → 停手'); return 8
            pd.log(f'角色{a.role} {name} 第 {k + 1}/{a.n} 隻已存公共')
    pd.click(*pd.CLOSE_X, wait=500, note='petshark 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
