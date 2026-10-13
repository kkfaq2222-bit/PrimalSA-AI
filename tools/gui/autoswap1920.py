#!/usr/bin/env python3
"""外掛「一般設置 → 自動轉換戰寵」（1920×1017）。
預設只檢查「自動轉換戰寵」有沒有打勾（沒勾就勾上），不開級數對話框、不改任何級數（使用者 2026-10-13：
轉換級數只有剛開始的 0 轉新帳號第一次設定需要，之後帳號都是設好的；卡坦 / 恐龍博士練寵都走預設）。
--setup 才做第一次設定：第 1~4 列轉換級數 = 25、第 5 列不動，並勾選。
流程（2026-10-12 實測）：SET(835,270) 開對話框 → 每列：點數字框(578,y) → 該列 SET(626,y) 開鍵盤 → 2、5、確定（鍵盤位置隨列往下移 30）→ 確認(425,340)。
用法：uv run --no-project python tools/gui/autoswap1920.py --client kkfaq11111 --roles 1,2,3,4,5 [--setup [--level 25]]
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
ROWS_Y = [178, 208, 238, 268]
DIGITS = {'0': (596 + 32, 116 - 60 + 60), }   # 佔位（下面用實測座標表）
KEY = {'1': (567, 56), '2': (596, 56), '3': (626, 56), '4': (567, 86), '5': (596, 86), '6': (626, 86),
       '7': (567, 116), '8': (596, 116), '9': (626, 116), '0': (596, 145)}
OK = (626, 145)          # 確定（相對第 1 列的位置；實際 + 列偏移）
KEY['0'] = (596, 145)
OK = (626, 145 + 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--level', default='25')
    ap.add_argument('--dry', action='store_true', help='只填數字、留圖、按取消（--setup 時）')
    ap.add_argument('--setup', action='store_true', help='第一次設定（0 轉新帳號）：把第 1~4 列轉換級數設成 --level；預設只檢查勾選')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import ass, uikit, catch1920 as c
    names = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']
    if not ass.open_panel():
        print('外掛面板打不開'); return 3
    try:
        for r in [int(x) for x in a.roles.split(',')]:
            if not ass.select_role(names[r - 1]):
                print(f'選不到角色 {r}'); return 4
            uikit.gui('click', '540', '127'); time.sleep(0.8)          # 一般設置分頁
            if not a.setup:
                # 只檢查勾選（預設）：沒勾就勾，勾完再驗證；不碰級數
                cols = uikit.px([(439, 270)])
                if cols and cols[0] == (255, 255, 255):
                    uikit.gui('click', '439', '270'); time.sleep(0.8)
                    cols = uikit.px([(439, 270)])
                on = bool(cols) and cols[0] != (255, 255, 255)
                print(f'角色{r} 自動轉換戰寵勾選={"開" if on else "關"}', flush=True)
                if not on:
                    print(f'角色{r} 自動轉換戰寵勾不起來 → 停手'); return 5
                continue
            uikit.gui('click', '835', '270'); time.sleep(1.2)          # 自動轉換戰寵 SET
            def span(y):
                """數字格亮點橫向跨度：「25」≈12、「0」≈4（2026-10-12 實測；黑底白字 OCR 讀不到）"""
                xs = list(range(556, 606, 2)); n = len(xs); cols = []
                for yy in (y - 4, y, y + 4):
                    cols += uikit.px([(x, yy) for x in xs]) or []
                if len(cols) != 3 * n:
                    return 0
                br = [xs[i] for i in range(n) if any(min(cols[k * n + i]) > 190 for k in range(3))]
                return (br[-1] - br[0] + 2) if br else 0
            todo = [k for k, y in enumerate(ROWS_Y) if span(y) < 10]
            print(f'角色{r} 需要改的列（0 起算）：{todo}（其餘已是 {a.level}）', flush=True)
            for k, y in enumerate(ROWS_Y):
                if k not in todo:
                    continue
                d = 30 * k
                uikit.gui('seq', f'click 578 {y}; wait 400; click 626 {y}; wait 700')
                for ch in a.level:
                    x, yy = KEY[ch]
                    uikit.gui('click', str(x), str(yy + d)); time.sleep(0.25)
                uikit.gui('click', str(OK[0]), str(OK[1] + d)); time.sleep(0.7)
            uikit.gui('shot', f'autoswap_r{r}.png')                      # 確認前留圖（數字是黑底白字，OCR 讀不到，由人 / Claude 看圖）
            if a.dry:
                uikit.gui('click', '548', '340'); time.sleep(0.8); continue
            uikit.gui('click', '425', '340'); time.sleep(1.0)          # 確認
            cols = uikit.px([(439, 270)])
            if cols and cols[0] == (255, 255, 255):
                uikit.gui('click', '439', '270'); time.sleep(0.8)
            cols = uikit.px([(439, 270)])
            print(f'角色{r} 自動轉換戰寵勾選={"開" if cols and cols[0] != (255, 255, 255) else "關"}', flush=True)
    finally:
        ass.close_panel()
    return 0


if __name__ == '__main__':
    sys.exit(main())
