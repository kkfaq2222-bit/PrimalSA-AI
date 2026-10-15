#!/usr/bin/env python3
"""整理寵物（1920×1017）：每個角色寵物欄逐格讀名字 → 丟棄名單直接丟、保留名單存個人寵物倉庫，其餘不動。

丟棄（寵物面板「寵物」分頁，垃圾桶 + 確定）：奇娜、多魯寶、烏力斯坦、修寶、布克布克
存個人倉庫（「倉庫」分頁 → 個人 → 存入寵物）：
  金飛 = 朵拉比斯（卡坦獎勵）      紅飛 = 洛卡倫恩（漆黑洞窟四轉獎勵；使用者尚未確認，推測）
  紅暴 = 巴朵蘭恩（英雄島前傳）    藍暴 = 左迪洛斯（猜謎三兄弟）      金羊 = 摩娜西普（黃金羚羊之謎）
  機暴 = 帖拉所伊朵（漆黑洞窟五轉獎勵）
名稱依遊戲內顯示（knowledge/quests/guides.md 獎勵 + knowledge/pets 圖示編號比對）。OCR 常缺字，每種用多個片段比對。

安全：
  - 丟棄前提示窗 OCR 必須含同一隻的片段才按確定，否則按取消並停手（退出碼 5）。
  - 存入遇到「戰鬥 / 騎乘狀態」提示窗預設按取消並跳過該隻（--battle-ok 才按確定）。
  - 每個動作用「寵物欄隻數減少」驗證；沒減少就停手（退出碼 4）。
  - 名稱讀不出來 / 不在名單的寵物一律不動。

用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1 較快）：
  uv run --no-project python tools/gui/petorganize1920.py --client kkfaq22222            # 預覽：只印每隻的名稱與會怎麼處理
  uv run --no-project python tools/gui/petorganize1920.py --client kkfaq22222 --do      # 真的整理
  ... --do --roles 1,2 --only delete|store       # 指定角色 / 只丟或只存
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# (顯示名, 比對片段) —— 任一片段出現在 OCR 名稱就算命中；寧缺勿濫，容易和他種混的片段不放
DELETE = [
    ('奇娜', ('奇娜',)),
    ('多魯寶', ('多魯', '魯寶')),
    ('烏力斯坦', ('烏力', '斯坦')),
    ('修寶', ('修寶',)),
    ('布克布克', ('布克',)),
]
STORE = [
    ('朵拉比斯（金飛）', ('朵拉', '拉比斯')),
    ('洛卡倫恩（紅飛）', ('洛卡', '卡倫')),
    ('巴朵蘭恩（紅暴）', ('巴朵', '朵蘭', '蘭恩')),
    ('左迪洛斯（藍暴）', ('左迪', '左迧', '迪洛')),
    ('摩娜西普（金羊）', ('摩娜', '西普', '摩西')),
    # 使用者 2026-10-15：機暴也要存 = 帖拉所伊朵（漆黑洞窟五轉獎勵、20F 機暴守衛）。「帖拉」開頭寵物很多（帖拉卡伊朵 / 帖拉吉魯…），
    # 「伊朵」也撞帖拉卡伊朵 → 只用「所伊」系列片段
    ('帖拉所伊朵（機暴）', ('所伊', '拉所伊', '所伊朵')),
]
PET_TAB = (885, 175)
TRASH, TRASH_OK, TRASH_NO = (472, 348), (415, 343), (538, 343)
TAB_NAME_BOX = (300, 90, 160, 34)           # 寵物分頁名稱框（同 petdelbk）
DIALOG_BOX = (385, 205, 240, 60)


def match(table, text):
    for name, keys in table:
        if any(k in text for k in keys):
            return name, keys
    return None, ()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--do', action='store_true', help='真的丟 / 存（預設只預覽）')
    ap.add_argument('--only', choices=('delete', 'store'), default='', help='只做丟棄或只做存倉庫')
    ap.add_argument('--battle-ok', action='store_true', help='存入遇到戰鬥 / 騎乘中提示窗時按確定（預設取消跳過）')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import uikit
    import layout
    if layout.current() != '1920x1017':
        print(f'版面 {layout.current()}，這支只量過 1920x1017')
        return 2

    def read_tab_name():
        # 丟棄用：維持舊讀法（不加 -Dark 0）——讀越多字、誤中丟棄片段的機會越大，丟棄不可逆（2026-10-15）
        return (''.join(uikit.ocr(TAB_NAME_BOX, '-Zooms', '2,3')) + ''.join(uikit.ocr(TAB_NAME_BOX, '-Zooms', '3,4'))).strip()

    def filled():
        return [i for i in range(5) if not pd.slot_empty(i)]

    def scan(reader, table, role, skip):
        """逐格點選讀名稱，回傳第一隻命中 table 的 (格, 顯示名, 片段, 原始名稱)；其餘記進 skip 不再讀。"""
        for i in filled():
            if i in skip:
                continue
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=800, note=f'petorganize 角色{role} 第 {i + 1} 格')
            raw = reader()
            name, keys = match(table, raw)
            if name:
                return i, name, keys, raw
            skip.add(i)
            pd.log(f'角色{role} 第 {i + 1} 格「{raw}」→ 不在名單，不動')
        return None

    do_del = a.only in ('', 'delete')
    do_store = a.only in ('', 'store')
    if not pd.open_panel():
        print('寵物面板打不開（戰鬥 / 對話中？）')
        return 3
    summary = []
    for r in [int(x) for x in a.roles.split(',') if x.strip()]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1200, note=f'petorganize 選角色 {r}')
        # ---- 1. 丟棄（寵物分頁）----
        if do_del:
            pd.click(*PET_TAB, wait=900, note='petorganize 寵物分頁')
            skip = set()
            for _ in range(6):
                if not pd.panel_open():
                    print('面板不在 → 停手')
                    return 4
                hit = scan(read_tab_name, DELETE, r, skip)
                if not hit:
                    break
                i, name, keys, raw = hit
                if not a.do:
                    pd.log(f'角色{r} 第 {i + 1} 格「{raw}」→ 會丟棄 {name}')
                    skip.add(i)
                    continue
                before = len(filled())
                pd.click(*TRASH, wait=1200, note='petorganize 垃圾桶')
                t = ''.join(uikit.ocr(DIALOG_BOX, '-Zooms', '2,3')) + ''.join(uikit.ocr(DIALOG_BOX, '-Zooms', '3,4'))
                if not any(k in t for k in keys):
                    print(f'角色{r} 提示窗不是{name}（{t!r}）→ 取消、停手')
                    pd.click(*TRASH_NO, wait=600)
                    return 5
                pd.click(*TRASH_OK, wait=1300, note='petorganize 確定丟棄')
                if len(filled()) >= before:
                    print(f'角色{r} 丟棄{name}後寵物欄隻數沒減少 → 停手')
                    return 4
                pd.log(f'角色{r} 已丟棄 {name}（第 {i + 1} 格）')
                summary.append(f'角色{r} 丟 {name}')
                skip = set()                      # 隻數變了，重讀
        # ---- 2. 存個人倉庫（倉庫分頁）----
        if do_store:
            pd.DEPOT_TARGET = pd.DEPOT_PERSONAL
            pd.goto_depot()
            skip = set()
            for _ in range(6):
                if not pd.panel_open():
                    print('面板不在 → 停手')
                    return 4
                hit = scan(pd.pet_name, STORE, r, skip)
                if not hit:
                    break
                i, name, keys, raw = hit
                if not a.do:
                    pd.log(f'角色{r} 第 {i + 1} 格「{raw}」→ 會存個人倉庫 {name}')
                    skip.add(i)
                    continue
                before = len(filled())
                pd.click(*pd.STORE_BTN, wait=600, note=f'petorganize 存入 {name}')
                t0 = time.time()
                warned = False
                while time.time() - t0 < 6.0:
                    if pd.warn_dialog():
                        warned = True
                        pd.click(*(pd.WARN_OK if a.battle_ok else pd.WARN_NO), wait=900, note='petorganize 戰鬥 / 騎乘提示窗')
                        if not a.battle_ok:
                            break
                    if len(filled()) < before:
                        break
                    time.sleep(0.5)
                if len(filled()) < before:
                    pd.log(f'角色{r} 已存個人倉庫 {name}（第 {i + 1} 格）')
                    summary.append(f'角色{r} 存 {name}')
                    skip = set()
                elif warned and not a.battle_ok:
                    pd.log(f'角色{r} {name} 是戰鬥 / 騎乘中 → 已取消，沒存（要存請先取消出戰 / 騎乘或加 --battle-ok）')
                    summary.append(f'角色{r} 略過 {name}（出戰 / 騎乘中）')
                    skip.add(i)
                else:
                    print(f'角色{r} 「{name}」存不進去（倉庫滿 / 鎖定？）→ 停手')
                    return 4
    pd.click(*pd.CLOSE_X, wait=500, note='petorganize 關面板')
    pd.log('完成：' + ('；'.join(summary) if summary else ('預覽結束（沒動任何寵物）' if not a.do else '沒有需要處理的寵物')))
    return 0


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('petorganize1920')       # 印出「停手」就當下存圖（面板還開著）
    sys.exit(main())
