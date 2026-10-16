#!/usr/bin/env python3
"""轉生後整備寵物（1920×1017）：朵拉比斯 → 出戰；金格薩貝魯（金色老虎）→ 騎乘。
每個角色：寵物欄逐格點選讀名字（含「朵拉」→ 出戰；含「金格」→ 騎乘），其他不動。
用法：petsetup1920.py --client kkfaq22222 --roles 1,2,3,4,5 [--shot-dir 前綴]
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
FIGHT_BTN = (280, 433)
RIDE_BTN = (345, 433)


def fail_shot(pd, r, why):
    """停手當下（面板還開著、還停在這個角色）存圖 + 記第 1 / 2 格判空格用的顏色（2026-10-15：停手後才拍只拍到主畫面，看不出是哪隻寵物）"""
    try:
        cols = pd.px([(178, pd.SLOT_Y[i] + 22) for i in range(2)])
        pd.log(f'  判空格顏色：第 1 格 {cols[0] if cols else None}、第 2 格 {cols[1] if cols and len(cols) > 1 else None}')
        import failshot
        failshot.shot('petsetup', f'{why}；顏色 {cols}')
    except Exception:
        pass


def battle_level(uikit, *img):
    """寵物分頁中間下方黃字「0轉N」的 N（選中的那一格）；多種二值化讀，取出現最多的值，讀不到 None"""
    import collections
    import re
    vals = []
    for box in ((310, 380, 110, 26), (320, 382, 90, 22)):
        for opts in (('-Zooms', '3,4', '-Dark', '170'), ('-Zooms', '3,4', '-Dark', '130'), ('-Zooms', '3,4')):
            for t in uikit.ocr(box, *opts, *img):
                m = re.search(r'\d\s*轉\s*(\d+)', t)
                if m and 1 <= int(m[1]) <= 200:
                    vals.append(int(m[1]))
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


STAT_ROWS = (143, 171, 199)       # 寵物分頁右邊 攻擊 / 防禦 / 敏捷 數值列中心 y（數值 x≈560~640，格式「275+(0)」）
STAT_SUM_MIN = 35                 # 第二道防呆（使用者 2026-10-16）：三項合計要超過這個才算戰寵；1 級寵物約 20（實測 1 級鳥 7+4+8）


def battle_pet_ok(lv, sm) -> bool:
    """第 2 格格魯西斯是不是戰寵（使用者 2026-10-16：兩道防呆任一成立就算，防的是等級讀不到）。
    讀不到的那項不算數；兩項都讀到但一個說是、一個說不是 → 矛盾，不按。"""
    votes = [v for v in ((lv > 1) if lv is not None else None, (sm > STAT_SUM_MIN) if sm is not None else None) if v is not None]
    return bool(votes) and all(votes)


def stat_sum(uikit, *img):
    """攻擊 + 防禦 + 敏捷（「+」前的基礎值）；每列分開讀、兩種讀法取出現最多的值，任一列讀不到回 None。
    img：測試用，傳 ('-Image', 截圖檔) 改讀檔案"""
    import collections
    import re
    tot = 0
    for y in STAT_ROWS:
        vals = []
        for opts in (('-Zooms', '2,3', '-Dark', '150'), ('-Zooms', '3,4', '-Dark', '0')):
            for t in uikit.ocr((545, y - 12, 110, 24), *opts, *img):
                m = re.match(r'(\d+)\+', t)
                if m:
                    vals.append(int(m[1]))
        if not vals:
            return None
        tot += collections.Counter(vals).most_common(1)[0][0]
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq22222')
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--shot', default='')
    ap.add_argument('--by-name', action='store_true', help='改用名稱 OCR 判斷（預設固定位置：第 1 格騎乘、第 2 格出戰）')
    a = ap.parse_args()
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
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1200, note=f'petsetup 角色 {r}')
        pd.click(885, 175, wait=900, note='petsetup 寵物分頁')
        if not a.by_name:                  # 固定位置（使用者 2026-10-14：OCR 辨識不穩）：第 1 格騎乘、第 2 格出戰
            names = []
            for i in range(2):             # 先讀名字當護欄：兩格都沒有金格 / 朵拉 = 根本沒領到，停手不要亂按
                pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=1500, note=f'petsetup 第 {i + 1} 格（檢查）')
                names.append(pd.match_pet_name(pd.read_pet_name(uikit)))
            if not any(names):
                pd.log(f'角色{r} 寵物欄前兩格讀不到寵物名（{names}）→ 可能沒領到，不按騎乘 / 出戰')
                fail_shot(pd, r, f'角色{r} 前兩格讀不到寵物名')
                rc = 5
                continue
            # 戰寵 = 第 2 格（使用者 2026-10-14 改成領個人倉庫第 1 隻，不一定是朵拉比斯；2026-10-15 333 全部被「沒讀到朵拉比斯」擋下）。
            # 騎乘已在 lock 階段鎖定，這裡不再按（再按可能變成取消騎乘）。護欄：第 2 格要有寵物，且不是騎寵格魯西斯
            # 2026-10-16 333：個人倉庫第 1 隻本身就是格魯西斯（127 級戰寵）→ 被當成騎寵擋下。剛抓的騎寵是 1 級，
            # 所以第 2 格是格魯西斯時看等級（此時選取的就是第 2 格）：> 1 級 = 領出來的戰寵；1 級 / 讀不到才擋
            # 第二道防呆（使用者 2026-10-16：等級可能讀錯）：攻擊 + 防禦 + 敏捷合計 > STAT_SUM_MIN；兩道都過才按出戰
            ok2 = True
            if names[1] == '格魯西斯':
                lv2, sm2 = battle_level(uikit), stat_sum(uikit)
                ok2 = battle_pet_ok(lv2, sm2)
                pd.log(f'角色{r} 第 2 格是格魯西斯：等級 {lv2}、攻防敏合計 {sm2} → {"戰寵" if ok2 else "不確定是戰寵"}'
                       f'（> 1 級或合計 > {STAT_SUM_MIN} 任一讀得到且成立；兩個都讀到但矛盾就停）')
            if pd.slot_empty(1) or not ok2:
                pd.log(f'角色{r} 第 2 格沒有戰寵（{names}）→ 不按出戰')
                fail_shot(pd, r, f'角色{r} 第 2 格沒有戰寵 {names}')
                rc = 5
                continue
            i = 1
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=1500, note=f'petsetup 第 {i + 1} 格')
            pd.click(*FIGHT_BTN, wait=1000, note=f'petsetup 第 {i + 1} 格 戰寵出戰')
            pd.log(f'角色{r} 第 2 格戰寵（{names[1] or "名字讀不到"}）已按出戰')
            if a.shot:
                uikit.gui('shot', f'{a.shot}{r}.png')
            continue
        for i in range(2):                 # 轉生後寵物欄只有老虎 + 飛龍；空格會殘留上一隻的選取，不要掃
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=800, note=f'petsetup 第 {i + 1} 格')
            nm =uikit.ocr_name((300, 90, 160, 34))
            if '朵拉' in nm:
                pd.click(*FIGHT_BTN, wait=1000, note='petsetup 朵拉比斯 出戰')
                pd.log(f'角色{r} 朵拉比斯（第 {i + 1} 格）已按出戰')
            elif '金格' in nm:
                pd.click(*RIDE_BTN, wait=1000, note='petsetup 金格薩貝魯 騎乘')
                pd.log(f'角色{r} 金格薩貝魯（第 {i + 1} 格）已按騎乘')
        if a.shot:
            uikit.gui('shot', f'{a.shot}{r}.png')
    pd.click(*pd.CLOSE_X, wait=500)
    return rc


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('petsetup1920')       # 印出「停手」就當下存圖（面板還開著）
    sys.exit(main())
