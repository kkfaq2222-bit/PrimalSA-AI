#!/usr/bin/env python3
"""對帳補齊（1920×1017）：每個角色寵物欄要有 克邦凱斯 / 加克拉 / 加格 / 邦恩吉 各 1。
每一步都現場判讀（寵物欄名字、倉庫格上方名字）；多餘 / 非鯊魚存公共，缺的先找公共、再找個人倉庫。位置一律不記憶。
鯊魚情境下 OCR 讀不出的 4 字名 = 克邦凱斯（霍爾克 / 克克洛斯 都不是鯊魚）。
"""
import argparse, os, sys, time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import petnames1920 as pn
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
PUBLIC, PERSONAL, TAKE, STORE = (757, 100), (542, 100), (362, 430), (360, 430)
TARGET = ['克邦凱斯', '加克拉', '加格', '邦恩吉']
SHARKS = set(TARGET)


def bar_names(pd, uikit):
    out = []
    for i in range(5):
        if pd.slot_empty(i):
            out.append(None); continue
        pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=1000)
        got = None
        for z in ('2,3', '3,4', '4'):
            t = ''.join(uikit.ocr((230, 92, 260, 32), '-Zooms', z)).strip()
            got = pn.canon(t)
            if got:
                break
        if not got:
            w = pn.text_width(uikit)
            got = '克邦凱斯' if w >= 4 else ('霍爾克' if w == 3 else f'?{w}')
        out.append(got)
    return out


def teal(c):   # 克邦凱斯 icon 中心色
    return all(l <= v <= h for v, l, h in zip(c, (115, 205, 180), (150, 245, 215)))


def label_chars(uikit, x, y):
    """倉庫格上方名字的字數（白字亮點橫向範圍 / 12.5px）"""
    xs = list(range(x - 33, x + 33, 3))
    n = len(xs)
    cols = []
    for yy in (141, 146, 151):
        cols += uikit.px([(xx, y - 170 + yy) for xx in xs]) or []
    if len(cols) != 3 * n:
        return 0
    bright = [xs[i] for i in range(n) if any(min(cols[k * n + i]) > 215 for k in range(3))]
    return round((bright[-1] - bright[0] + 3) / 12.5) if bright else 0


def depot_names(pd, uikit):
    """每格：標籤 OCR → 種類名；標籤有數字 = 未命名鯊魚('?')；讀不出時用「字數 + 顏色」；黃色系火雞組 = 'T'（不碰）"""
    pts = []
    for y in YS:
        for x in XS:
            pts += [(x, y - 2), (x, y + 16)]
    cols = uikit.px(pts) or []
    out = []
    for i in range(20):
        c, b = (cols[2 * i], cols[2 * i + 1]) if 2 * i + 1 < len(cols) else ((0, 0, 0), (0, 0, 0))
        if abs(c[0] - 155) < 12 and abs(c[1] - 124) < 25 and abs(c[2] - 82) < 12:     # 空格腳印底色
            out.append(None); continue
        x, y = XS[i % 5], YS[i // 5]
        t = ''
        n = None
        for z in ('2,3', '3,4'):
            t = ''.join(uikit.ocr((x - 33, y - 30, 66, 18), '-Zooms', z)).strip()
            n = pn.canon(t)
            if n:
                break
        if n is None and any(ch.isdigit() or ch == '/' for ch in t):
            n = '?'                                              # 還沒改名的鯊魚（暱稱是能力數字）
        elif n is None:
            yellow_icon = c[0] > 200 and c[1] > 170 and c[2] < 120      # 火雞組偏黃
            if yellow_icon:
                n = 'T'
            else:
                ch = label_chars(uikit, x, y)
                belly_yellow = b[0] > 225 and 170 < b[1] < 215 and b[2] < 70
                n = {2: '加格', 4: '克邦凱斯'}.get(ch) or (('加克拉' if belly_yellow else '邦恩吉') if ch == 3 else 'T')
        out.append(n)
    return out


def goto(pd, which):
    pd.click(*pd.TAB_DEPOT, wait=900, note='reconcile 倉庫分頁')
    pd.click(*(PUBLIC if which == 'public' else PERSONAL), wait=700, note=f'reconcile {which}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='2,3,4,5')
    ap.add_argument('--passes', type=int, default=3)
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    roles = [int(x) for x in a.roles.split(',')]
    for p in range(a.passes):
        changed = False
        for r in roles:
            for _ in range(8):
                pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=800, note=f'reconcile 角色 {r}')
                bar = bar_names(pd, uikit)
                cnt = Counter(n for n in bar if n in SHARKS)
                extra = [i for i, n in enumerate(bar) if n is not None and (n not in SHARKS or cnt[n] > 1)]
                # 重複的只算多的那幾隻：第二隻起算多餘
                seen, extra2 = set(), []
                for i, n in enumerate(bar):
                    if n is None:
                        continue
                    if n not in SHARKS or n in seen:
                        extra2.append(i)
                    seen.add(n)
                missing = [t for t in TARGET if t not in seen]
                pd.log(f'角色{r} 第{p + 1}輪 欄={bar} 多餘格={[i + 1 for i in extra2]} 缺={missing}')
                if not extra2 and not missing:
                    break
                if extra2:
                    i = extra2[0]
                    goto(pd, 'public')
                    pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=700)
                    pd.click(*STORE, wait=900, note='reconcile 存公共')
                    changed = True
                    continue
                moved = False
                for src in ('public', 'personal'):
                    goto(pd, src)
                    names = depot_names(pd, uikit)
                    for m in missing:
                        if m in names:
                            k = names.index(m)
                            pd.click(XS[k % 5], YS[k // 5], wait=600, note=f'reconcile 領 {m}（{src} 第 {k + 1} 格）')
                            pd.click(*TAKE, wait=900, note='reconcile 取出')
                            moved = changed = True
                            break
                    if moved:
                        break
                if not moved:
                    # 倉庫裡還有沒改名的（暱稱是數字、讀不出種類）：取到欄內空格 → 鉛筆 → 確認恢復原名，下一圈再依名字處理
                    empty_i = next((i for i, n in enumerate(bar) if n is None), None)
                    if empty_i is not None:
                        for src in ('public', 'personal'):
                            goto(pd, src)
                            names = depot_names(pd, uikit)
                            if '?' in names:
                                k = names.index('?')
                                pd.click(XS[k % 5], YS[k // 5], wait=600, note=f'reconcile 取未命名（{src} 第 {k + 1} 格）')
                                pd.click(*TAKE, wait=1000, note='reconcile 取出')
                                pd.click(pd.SLOT_X, pd.SLOT_Y[empty_i], wait=800, note='reconcile 選新寵')
                                pd.click(468, 106, wait=800, note='reconcile 鉛筆')
                                pd.click(410, 320, wait=900, note='reconcile 確認恢復原名')
                                moved = changed = True
                                break
                    if not moved:
                        pd.log(f'角色{r} 缺 {missing} 找不到（公共/個人都沒有）'); break
        if not changed:
            break
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
