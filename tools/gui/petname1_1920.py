#!/usr/bin/env python3
"""把寵物欄指定格的寵物暱稱改成「1」（1920×1017）：選格 → 名稱旁鉛筆 → 點輸入框 → 打 1 → 確認 → 讀名字驗證。

用途（使用者 2026-10-13）：卡坦的願望，角色 2 抓鯊魚 / 角色 3 抓火雞，每輪第一隻改名「1」，之後只領名字是 1 的。
用法（專案根目錄）：
  uv run --no-project python tools/gui/petname1_1920.py --client kkfaq11111 --role 3 --slots 3,4 [--name 1] [--dry]
  --slots 寵物欄格序 1~5；已經是目標名的不動。只動寵物欄，不碰倉庫。
退出碼：0 成功；3 面板打不開；4 改名後名字不對（停手）；5 格子是空的。
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
PENCIL, INPUT_BOX, OK_BTN = (468, 106), (475, 250), (410, 320)


INK_PTS = [(x, y) for y in range(96, 122, 3) for x in range(230, 490, 4)]
FORCE = False
SHORT_MAX = 27        # 名稱區奶白字取樣點數：長名「34/7/3/8」33~40、「11」約 20，門檻取中間（2026-10-13 11111 實測；名稱 OCR 讀不了數字名）


def name_ink() -> int:
    """名稱區奶白色字的取樣點數（OCR 讀不出數字名稱，改看字的多寡）"""
    import uikit
    cols = uikit.px(INK_PTS) or []
    return sum(1 for r, g, b in cols if r > 200 and g > 170)


def rename_slot(pd, i: int, name: str) -> bool:
    """寵物欄第 i 格（0 起算）改名；回 True = 改成功（或本來就是）。
    驗證：名稱區字數從長名降到單字（<= SHORT_MAX）；--name 只准單一字元。"""
    import uikit
    pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=800, note=f'petname1 選第 {i + 1} 格')
    cur = name_ink()
    if cur <= SHORT_MAX and not FORCE:
        pd.log(f'第 {i + 1} 格名稱字數 {cur}（已是短名）→ 不動')
        return True
    pd.click(*PENCIL, wait=1000, note='petname1 鉛筆')
    pd.click(*INPUT_BOX, wait=800, note='petname1 點輸入框')
    uikit.gui('key', name, note=f'petname1 打 {name}')
    pd.click(*OK_BTN, wait=1000, note='petname1 確認')
    got = name_ink()
    pd.log(f'第 {i + 1} 格名稱字數：{cur} → {got}')
    if got <= SHORT_MAX:
        return True
    # 使用者 2026-10-14：WW 這種短名只要「沒有數字」就算改成功（白字數門檻會被 WW 的字寬 / 描邊影響）：
    # 名稱 OCR 多種倍率都讀不到數字名，且白字數明顯少於改名前（< 70%）→ 成功
    try:
        import re
        import uikit
        import questflow1920 as qf
        from petfetchimg1920 import is_numeric_name
        txts = [''.join(uikit.ocr(qf.PET_NAME_BOX, *o)).strip()
                for o in (('-Zooms', '3,4'), ('-Zooms', '2,3'), ('-Zooms', '3,4', '-Dark', '130'))]
        has_digits = any(is_numeric_name(t) or len(re.findall(r'\d', t)) >= 2 for t in txts)
        pd.log(f'第 {i + 1} 格名稱 OCR：{txts}（有數字={has_digits}）')
        return (not has_digits) and got < cur * 0.7
    except Exception as e:
        pd.log(f'名稱 OCR 檢查失敗：{e}')
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--role', type=int, required=True)
    ap.add_argument('--slots', required=True)
    ap.add_argument('--name', default='WW', help='遊戲不接受單字元名字（要至少 2 字）；使用者 2026-10-13 選 WW')
    ap.add_argument('--force', action='store_true', help='已經是短名也照改（例：把 11 改成 WW）')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args(argv)
    global FORCE
    FORCE = a.force
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    if not pd.open_panel():
        print('寵物面板打不開')
        return 3
    try:
        pd.click(pd.ROLE_X, pd.ROLE_Y[a.role - 1], wait=1200, note=f'petname1 選角色 {a.role}')
        for s in [int(x) for x in a.slots.split(',') if x.strip()]:
            if pd.slot_empty(s - 1):
                print(f'寵物欄第 {s} 格是空的 → 停手')
                return 5
            if a.dry:
                pd.click(pd.SLOT_X, pd.SLOT_Y[s - 1], wait=800, note='petname1 選格（dry）')
                pd.log(f'[dry] 第 {s} 格名稱字數 {name_ink()}')
                continue
            if not rename_slot(pd, s - 1, a.name):
                print(f'第 {s} 格改名後名字不對 → 停手')
                return 4
        return 0
    finally:
        pd.click(*pd.CLOSE_X, wait=600, note='petname1 關寵物面板')


if __name__ == '__main__':
    sys.exit(main())
