#!/usr/bin/env python3
"""從個人寵物倉庫領出「金格薩貝薈（金色老虎坐騎）」與「朵拉比斯（金色飛龍戰寵）」（1920×1017）。
每個角色：倉庫 → 個人分頁 → 逐格點選讀名字 → 名稱符合且左下按鈕是「取出寵物」才取出；每隻只取一次，取完重掃。
用法：petgetgold1920.py --client kkfaq22222 --roles 1,2,3,4,5
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import depotlvl1920  # noqa: E402
XS = [542, 608, 675, 742, 808]
YS = [170, 237, 303, 370]
TAKE_BTN = (362, 430)
TARGETS = {'金格': '金格薩貝薈', '朵拉': '朵拉比斯'}
TARGETS_ALL = list(TARGETS)


LEVEL_BOX_DY = 9                  # 倉庫卡片底部「0轉N級」小字：卡片中心 y + 9 起、高 18（2026-10-12 11111 實機看過）


def parse_card_level(texts):
    """卡片小字 OCR（多組）→ 等級：優先取「轉」後面的數字，其次最後一個數字；讀不到 None"""
    import collections
    import re
    vals = []
    for t in texts:
        t = str(t).replace(' ', '')
        m = re.search(r'轉(\d+)', t)
        if m:
            vals.append(int(m.group(1)))
        else:
            nums = re.findall(r'\d+', t)
            if nums:
                vals.append(int(nums[-1]))
    vals = [v for v in vals if 1 <= v <= 200]
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def fast_candidates(uikit, a) -> list:
    """整頁一次截圖 + 一次 OCR：回傳「名稱含目標、(--level 1 時) 綠字是 1 級」的格序（0 起算）。讀不到回 []（呼叫端改逐格點選）。"""
    import json
    import winenv
    shot_name = 'depot_grid.png'
    uikit.gui('shot', shot_name)
    shot = str(Path(__file__).resolve().parents[1] / '.cache' / shot_name)
    r = winenv.run_ps('ocr.ps1', '505', '135', '340', '215', '-Zooms', '3,4', '-Dark', '170')
    d = json.loads((r.stdout.strip().splitlines() or [''])[-1])
    if not d.get('ok'):
        return []
    names = [''] * 10
    for ln in d.get('lines', []):
        x, y = int(ln['x']), int(ln['y'])
        row = min(range(2), key=lambda k: abs(y - (YS[k] - 20)))
        col = min(range(5), key=lambda k: abs(x - XS[k]))
        if abs(y - (YS[row] - 20)) > 20 or abs(x - XS[col]) > 34:
            continue
        names[row * 5 + col] += ln['text']
    out = []
    for idx in range(10):
        if not any(k in names[idx] for k in TARGETS):
            continue
        x, y = XS[idx % 5], YS[idx // 5]
        if a.level:
            ok1, gi, wi = depotlvl1920.card_is_level1(shot, x, y)
            if not ok1:
                continue
        out.append(idx)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq22222')
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--max-slots', type=int, default=10)
    ap.add_argument('--level', type=int, default=1, choices=[0, 1], help='1 = 只領 1 級的（點選後比對卡片綠字「0轉1級」；預設）；0 = 不驗證等級')
    ap.add_argument('--only', default='', help='只領名稱含這個關鍵字的（例：朵拉 = 只領金飛朵拉比斯）；預設全領')
    a = ap.parse_args()
    if a.only:
        global TARGETS
        TARGETS = {k: v for k, v in TARGETS.items() if k in a.only or a.only in k}
        if not TARGETS:
            print(f'--only {a.only} 不是已知目標（{"、".join(TARGETS_ALL)}）')
            return 2
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import uikit
    if not pd.open_panel():
        print('寵物面板打不開')
        return 3
    rc = 0
    for r in [int(x) for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1200, note=f'getgold 角色 {r}')
        pd.click(*pd.TAB_DEPOT, wait=1300, note='getgold 倉庫分頁')
        pd.click(*pd.DEPOT_PERSONAL, wait=900, note='getgold 個人分頁')
        found = set()
        # 快速路徑（使用者 2026-10-13：不要一格一格慢慢點）：倉庫整頁一次截圖 + 整頁名稱 OCR 一次，名稱符合、且綠字是 1 級的卡片才點。
        # 舊版每一格都點一次再 OCR 名稱 2 次、讀按鈕、截圖（每格 5~8 秒，10 格 + 3 輪）。
        fast = []
        try:
            fast = fast_candidates(uikit, a)
        except Exception as e:
            pd.log(f'快速辨識失敗（{e!r}）→ 改用逐格點選')
        order = fast if fast else list(range(a.max_slots))
        if fast:
            pd.log(f'角色{r} 整頁辨識到候選格：{[i + 1 for i in fast]}')
        for _round in range(3):
            took = False
            for idx in order:
                x, y = XS[idx % 5], YS[idx // 5]
                pd.click(x, y, wait=700, note=f'getgold 倉庫第 {idx + 1} 格')
                nm = ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '2,3')) + ''.join(uikit.ocr((300, 90, 160, 34), '-Zooms', '3,4'))
                key = next((k for k in TARGETS if k in nm and k not in found), None)
                if not key:
                    continue
                lab = ''.join(uikit.ocr((300, 412, 125, 36), '-Zooms', '2,3'))
                if '取出' not in lab:
                    continue
                if a.level:                          # 點選後驗證卡片底部綠字「0轉1級」（像素比對，不用 OCR）；不是 1 級就不領
                    shot_name = 'depot_lvl.png'
                    uikit.gui('shot', shot_name)
                    ok1, gi, wi = depotlvl1920.card_is_level1(str(Path(__file__).resolve().parents[1] / '.cache' / shot_name), x, y)
                    if not ok1:
                        pd.log(f'角色{r} 倉庫第 {idx + 1} 格 {TARGETS[key]} 不是 1 級（綠字比對 整體 {gi:.2f} / 數字窗口 {wi:.2f}）→ 不領')
                        continue
                    pd.log(f'角色{r} 倉庫第 {idx + 1} 格 {TARGETS[key]} 驗證 1 級（整體 {gi:.2f} / 窗口 {wi:.2f}）')
                pd.click(*TAKE_BTN, wait=1200, note=f'getgold 取出 {TARGETS[key]}')
                found.add(key)
                pd.log(f'角色{r} 已取出 {TARGETS[key]}（倉庫第 {idx + 1} 格）')
                took = True
                break
            if len(found) == len(TARGETS) or not took:
                break
        if len(found) != len(TARGETS):
            pd.log(f'角色{r} 只取到 {sorted(TARGETS[k] for k in found)}，少了 {sorted(TARGETS[k] for k in TARGETS if k not in found)}')
            rc = 5
    pd.click(*pd.CLOSE_X, wait=500)
    return rc


if __name__ == '__main__':
    sys.exit(main())
