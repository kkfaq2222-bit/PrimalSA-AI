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


def take_label_ok(uikit) -> bool:
    """選中的是「倉庫裡的寵物」時，左下按鈕是「取出寵物」；若倉庫第 1 格是空的，選取還停在寵物欄的寵物上，
    同一個位置的按鈕是「存入寵物」→ 點下去會把自己的寵物存進公共（2026-10-12 角色 1 的克邦凱斯因此被存走）。
    所以按之前一定要確認按鈕文字含「取出」。"""
    t = ''.join(uikit.ocr((300, 412, 125, 36), '-Zooms', '2,3'))
    return '取出' in t or ('取' in t and '存' not in t)


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
    ap.add_argument('--first', action='store_true',
                    help='公共倉庫只放同一種（katan 每輪的 4 隻）時：每次都取第 1 格（取出後後面會補位），不用顏色比對')
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
        for _t in range(3):                          # 公共分頁一定要真的選中（亮黃）才取，不然取到的是個人倉庫
            c = uikit.px([(790, 96)])
            if c and c[0][0] > 225 and c[0][1] > 190:
                break
            pd.click(*PUBLIC, wait=900, note='petgive 重點公共分頁')
        else:
            print(f'角色{r} 公共分頁切不過去 → 停手')
            return 8
        have = sum(1 for i in range(5) if not pd.slot_empty(i))
        if a.first:
            idxs = [0] * len(wanted)                 # 永遠第 1 格：取出後後面的會往前補位
        else:
            grid = read_public(uikit)
            if grid is None:
                print('讀不到倉庫像素 → 停手'); return 4
            idxs = []
            for sp in wanted:
                cand = [i for i, (c0, c1) in grid.items() if i not in idxs and PRED[sp](c0, c1)]
                if not cand:
                    print(f'角色{r} 要 {sp}，公共倉庫沒有（顏色比對）→ 停手'); return 5
                idxs.append(cand[-1])
        want_n = len(wanted)
        base_have = have
        attempts = 3 if a.first else 1               # 固定第 1 格時可安全重試（2026-10-12 角色 4 點了沒取到：3→3）
        for attempt in range(attempts):
            for i in sorted(idxs, reverse=True):
                pd.click(XS[i % 5], YS[i // 5], wait=450, note=f'petgive 角色{r} 取第 {i + 1} 格')
                ready = False
                for _k in range(3):                  # 遊戲偶爾吃掉這一下點擊：等一下重讀，不對就重點該格（最多 2 次）
                    time.sleep(0.4)
                    if take_label_ok(uikit):
                        ready = True
                        break
                    if _k < 2:
                        pd.click(XS[i % 5], YS[i // 5], wait=800, note=f'petgive 重點倉庫第 {i + 1} 格')
                if not ready:
                    print(f'角色{r} 按鈕不是「取出寵物」（倉庫第 {i + 1} 格是空的？）→ 不按、停手')
                    return 7
                pd.click(*TAKE_BTN, wait=700, note='petgive 取出寵物')
            time.sleep(0.8)
            other = 0 if r != 1 else 1                # 切別人再切回來才會刷新寵物欄
            pd.click(pd.ROLE_X, pd.ROLE_Y[other], wait=700, note='petgive 先切別人（刷新）')
            pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petgive 切回角色 {r}')
            now = sum(1 for i in range(5) if not pd.slot_empty(i))
            got = now - base_have
            pd.log(f'角色{r} 領 {wanted}（倉庫格 {sorted(idxs)}）欄內 {base_have}→{now}' + (f'（第 {attempt + 1} 次）' if attempt else ''))
            if got >= want_n:
                break
            if attempt < attempts - 1:
                if got > 0:
                    idxs = idxs[:want_n - got]        # 只取到一部分：只補差額
                    base_have, want_n = now, want_n - got
                pd.click(*pd.TAB_DEPOT, wait=900, note='petgive 重試：倉庫分頁')
                pd.click(*PUBLIC, wait=600, note='petgive 重試：公共分頁')
        if now - have != len(wanted):
            print('數量不符 → 停手'); return 6
    pd.click(*pd.CLOSE_X, wait=500, note='petgive 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
