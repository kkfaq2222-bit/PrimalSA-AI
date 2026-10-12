#!/usr/bin/env python3
"""個人倉庫領火雞組 4 種（火雞 / 克克洛斯 / 霍爾克 / 奇寶）到寵物欄（1920×1017）。只認這 4 種的關鍵字，
其餘（魯尼帖斯、瑪斯貝卡、摩娜西普…）一律當 None 不碰。每領一隻重讀倉庫、欄內數量 +1 才算。
用法：petbirds1920.py --client kkfaq11111 --roles 1,2,3,4,5
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
WANT = ['火雞', '克克洛斯', '霍爾克', '奇寶']


def bird(t: str):
    t = ''.join(ch for ch in t if '一' <= ch <= '鿿')
    if '迪' in t or '左' in t or '摩' in t or '娜' in t or '瑪' in t or '巴朵' in t or '魯尼' in t or '帖' in t:
        return None
    if '霍' in t or '爾克' in t:
        return '霍爾克'
    if '克克' in t:
        return '克克洛斯'
    if '奇' in t or '寶' in t:
        return '奇寶'
    if '火' in t or '雞' in t or '難' in t:
        return '火雞'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='1,2,3,4,5')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=900, note=f'petbirds 角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=1000, note='petbirds 倉庫')
        pd.click(*pd.DEPOT_PERSONAL, wait=800, note='petbirds 個人')
        got = []
        for _ in range(8):
            if not pd.panel_open():
                print('面板不在 → 停手'); return 4
            have = sum(1 for i in range(5) if not pd.slot_empty(i))
            if have >= 4 and len(got) >= 4:
                break
            names = []
            for k in range(20):
                x, y = XS[k % 5], YS[k // 5]
                t = ''.join(uikit.ocr((x - 33, y - 30, 66, 18), '-Zooms', '2,3')) + ''.join(uikit.ocr((x - 33, y - 30, 66, 18), '-Zooms', '3,4'))
                n = bird(t)
                if n is None and not t.strip():
                    c = uikit.px([(x, y - 2)])
                    empty = bool(c) and abs(c[0][0] - 155) < 12 and abs(c[0][1] - 124) < 25 and abs(c[0][2] - 82) < 12
                    if not empty:                      # 格內有寵物但標籤 OCR 空白：點開讀上方大名字
                        pd.click(x, y, wait=700)
                        t2 = ''.join(uikit.ocr((230, 92, 260, 32), '-Zooms', '2,3')) + ''.join(uikit.ocr((230, 92, 260, 32), '-Zooms', '3,4'))
                        n = bird(t2)
                        if n is None and not t2.strip():
                            import petnames1920 as pn
                            w = pn.text_width(uikit)
                            n = {2: '奇寶', 3: '霍爾克', 4: '克克洛斯'}.get(w)
                names.append(n)
            need = [w for w in WANT if w not in got and w in names]
            if not need:
                break
            w = need[0]
            k = names.index(w)
            pd.click(XS[k % 5], YS[k // 5], wait=700, note=f'petbirds 角色{r} 取 {w}（第 {k + 1} 格）')
            pd.click(362, 430, wait=900, note='petbirds 取出')
            for _ in range(8):
                if sum(1 for i in range(5) if not pd.slot_empty(i)) == have + 1:
                    break
                time.sleep(0.4)
            else:
                print(f'角色{r} 取 {w} 後欄內數量沒變 → 停手'); return 5
            got.append(w)
            pd.log(f'角色{r} 已領 {w}（{len(got)}/4）')
        if sum(1 for i in range(5) if not pd.slot_empty(i)) < 5:
            print(f'角色{r} 欄內不滿 5 隻（領到 {got}）→ 停手'); return 6
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
