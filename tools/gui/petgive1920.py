#!/usr/bin/env python3
"""從公共倉庫依顏色挑指定鯊魚種類，一次讀整個倉庫、由大到小編號連續取出（取出後後面的會補位，所以大號先取，前面位置不變）。
用法：uv run --no-project python tools/gui/petgive1920.py --client kkfaq11111 --plan "2:加格,邦恩吉;3:克邦凱斯,加克拉,加格;4:克邦凱斯,加克拉,加格,邦恩吉;5:克邦凱斯,加克拉,加格,邦恩吉"
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
PUBLIC, TAKE_BTN = (757, 100), (362, 430)


def within(c, lo, hi):
    return all(l <= v <= h for v, l, h in zip(c, lo, hi))


PRED = {
    '克邦凱斯': lambda a, b: within(a, (115, 205, 180), (150, 245, 215)),
    '加克拉': lambda a, b: within(a, (70, 135, 185), (105, 175, 225)) and within(b, (225, 170, 0), (255, 215, 60)),
    '加格': lambda a, b: within(a, (40, 105, 140), (70, 140, 180)),
    '邦恩吉': lambda a, b: within(a, (68, 145, 180), (125, 205, 240)) and not within(b, (225, 170, 0), (255, 215, 60)),
}


def read_public(uikit):
    pts = []
    for y in YS:
        for x in XS:
            pts += [(x, y - 2), (x, y + 16)]
    cols = uikit.px(pts) or []
    if len(cols) != len(pts):
        return None
    return {i: (cols[2 * i], cols[2 * i + 1]) for i in range(20)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--plan', required=True)
    a = ap.parse_args()
    plan = {}
    for part in a.plan.split(';'):
        r, sp = part.split(':')
        plan[int(r)] = sp.split(',')
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r, wanted in plan.items():
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=700, note=f'petgive 選角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=900, note='petgive 倉庫分頁')
        pd.click(*PUBLIC, wait=600, note='petgive 公共分頁')
        have = sum(1 for i in range(5) if not pd.slot_empty(i))
        grid = read_public(uikit)
        if grid is None:
            print('讀不到倉庫像素 → 停手'); return 4
        idxs = []
        for sp in wanted:
            cand = [i for i, (c0, c1) in grid.items() if i not in idxs and PRED[sp](c0, c1)]
            if not cand:
                print(f'角色{r} 要 {sp}，公共倉庫沒有（顏色比對）→ 停手'); return 5
            idxs.append(cand[-1])
        for i in sorted(idxs, reverse=True):
            pd.click(XS[i % 5], YS[i // 5], wait=450, note=f'petgive 角色{r} 取第 {i + 1} 格')
            pd.click(*TAKE_BTN, wait=700, note='petgive 取出寵物')
        time.sleep(0.6)
        now = sum(1 for i in range(5) if not pd.slot_empty(i))
        pd.log(f'角色{r} 領 {wanted}（倉庫格 {sorted(idxs)}）欄內 {have}→{now}')
        if now - have != len(wanted):
            print('數量不符 → 停手'); return 6
    pd.click(*pd.CLOSE_X, wait=500, note='petgive 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
