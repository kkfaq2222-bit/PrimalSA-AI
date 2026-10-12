#!/usr/bin/env python3
"""恐龍博士交遞（1920×1017）：對「當前角色」做 步 1（魯尼帖斯）+ 步 2（貝魯卡）。
流程（2026-10-12 實測）：點追蹤欄導航 → 對話選項「恐龍博士」→ 選項「完成」→ 跳「選擇」視窗 → 依名字點卡片（魯尼帖斯 / 貝魯卡）→ 確定。
用法：dino1920.py --client kkfaq11111 [--track 2]。換角色用 char.py / 切換面板（本檔不換人）。
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
CARD = {'貝魯卡': (450, 205), '魯尼帖斯': (450, 265)}     # 選擇視窗兩張卡的位置；順序每人不同，所以先讀名字再點
CARD_ROWS = [(415, 185, 200, 30), (415, 248, 200, 30)]
OK = (497, 373)
OPT1 = (650, 283)


def card_for(uikit, want):
    for k, box in enumerate(CARD_ROWS):
        t = ''.join(uikit.ocr(box, '-Zooms', '2,3'))
        if want in t or (want == '魯尼帖斯' and '魯' in t and '尼' in t) or (want == '貝魯卡' and '貝' in t):
            return k
    return None


def one_step(q, uikit, want):
    q.click(q.track_xy(), right=2, wait_ms=500, note='dino 點追蹤欄')
    s = q.wait_state(('DIALOG', 'REWARD'), timeout=40)
    if s != 'DIALOG':
        s2 = q.navigate()
        if s2 != 'DIALOG':
            return f'沒有對話（{s2}）'
    for _ in range(4):                                         # 選項：「恐龍博士」→「完成」
        txt = ''.join(uikit.ocr((555, 160, 350, 95), '-Zooms', '2,3'))
        opt = ''.join(uikit.ocr((565, 262, 175, 42), '-Zooms', '2,3'))
        q.log(f'dino 對話：{txt[:30]} / 選項 {opt[:10]}')
        q.click(OPT1, wait_ms=1800, note='dino 選項')
        c = uikit.px([(665, 120), (497, 120)])
        # 「選擇」視窗特徵（2026-10-12 實測）：右上 ✕ ≈(195,70,46)、標題條 ≈(225,181,127)
        if c and abs(c[0][0] - 195) < 30 and abs(c[0][1] - 70) < 30 and abs(c[1][0] - 225) < 30 and abs(c[1][1] - 181) < 30:
            k = card_for(uikit, want)
            if k is None:
                return f'選擇視窗找不到 {want}'
            q.click((500, 205 + 63 * k), wait_ms=700, note=f'dino 選 {want}（第 {k + 1} 張）')
            q.click(OK, wait_ms=1800, note='dino 確定')
            return 'ok'
    return '對話沒走到選擇視窗'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--track', type=int, default=2)
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import q1920 as q, uikit
    q.CLIENT = a.client; q.TRACK_N = a.track; q.TRUST_TEAM = True
    q.scroll_tracker()
    for step, want in ((1, '魯尼帖斯'), (2, '貝魯卡')):
        r = one_step(q, uikit, want)
        q.log(f'dino 步 {step}：{r}')
        if r != 'ok':
            return 5
    return 0


if __name__ == '__main__':
    sys.exit(main())
