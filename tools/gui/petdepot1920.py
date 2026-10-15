#!/usr/bin/env python3
"""寵物存倉庫（1920×1017 專用）：把 5 個角色身上的寵物「全部」存進個人寵物倉庫。只用標準庫 + uikit。

不綁固定寵物名：從寵物欄最後一格往前存（第 5 → 第 1 格；戰鬥 / 騎乘中的通常在前面，所以最後才存），
每存一隻用「該格變成空格（腳印圖）」驗證，並把當時讀到的名稱記進 notes/pets-stored.json（之後取回用）。
任何一格存不進去（倉庫滿、鎖定戰寵、提示視窗）→ 停手回報，不硬點。

用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1 較快）：
  uv run --no-project python tools/gui/petdepot1920.py --client kkfaq11111            # 預覽：5 人各寵物欄 5 格的名稱（只點選格子看，不存）
  uv run --no-project python tools/gui/petdepot1920.py --client kkfaq11111 --do       # 真的存
  uv run --no-project python tools/gui/petdepot1920.py --client kkfaq11111 --do --roles 1,2   # 只處理指定角色

座標（截圖 960×508，2026-10-11 實機量）：寵物頭像 202,40；面板 ✕ 850,62；左欄角色 x=52、y=110/205/290/375/440；
寵物欄 x=185、y=120/197/275/352/430；右側「倉庫」分頁 885,300；個人 542,100 / 公共 757,100；存入寵物 360,430；
寵物名 OCR 框 230,92,260,32。空格判斷：格內 (178, cy+22) R>120 且 G>90（米色腳印）= 空格，有寵物是深褐（R≈80~100）。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]

PET_BTN = (202, 40)
CLOSE_X = (850, 62)
ROLE_X = 52
ROLE_Y = [110, 205, 290, 375, 440]
SLOT_X = 185
SLOT_Y = [120, 197, 275, 352, 430]
TAB_DEPOT = (885, 300)
DEPOT_PERSONAL = (542, 100)
DEPOT_PUBLIC = (757, 100)
DEPOT_TARGET = DEPOT_PERSONAL            # --public 時改成公共分頁
STORE_BTN = (360, 430)
NAME_BOX = (230, 92, 260, 32)
WARN_OK, WARN_NO = (415, 343), (538, 343)    # 「戰鬥或騎乘狀態，確定要存入倉庫？」提示窗：確定（藍）/ 取消（橘紅）
LOG_PATH = ROOT / 'notes' / 'pets-stored.json'

sleep = time.sleep


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


# 名字特徵字（OCR 常缺字 / 重複，所以出現 2 個以上特徵字就算）
NAME_CHARS = {'朵拉比斯': '朵拉比斯', '格魯西斯': '格魯西斯', '金格薩貝魯': '金格薩貝魯'}


def read_pet_name(uikit, tries=3):
    """讀選取寵物的名字：讀空就等 0.5 秒重讀，最多 tries 次"""
    nm = ''
    for _ in range(tries):
        nm = uikit.ocr_name((300, 90, 160, 34))
        if nm.strip():
            break
        time.sleep(0.5)
    return nm


def match_pet_name(nm):
    """模糊比對：名字裡含某寵物 2 個以上特徵字 → 回傳全名；否則 ''"""
    best, hit = '', 1
    for full, chars in NAME_CHARS.items():
        n = len({c for c in chars if c in nm})
        if n > hit:
            best, hit = full, n
    return best


def gui(*a, note=''):
    import uikit
    return uikit.gui(*a, note=note)


def click(x, y, wait=700, note='', right=0):
    parts = [f'click {x} {y} right'] * right + [f'click {x} {y}', f'wait {wait}']
    gui('seq', '; '.join(parts), note=note)


def px(pts):
    import uikit
    return uikit.px(pts)


def ocr(box, *opts):
    import uikit
    return ''.join(uikit.ocr(box, *opts)).strip()


def near(c, ref, tol):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def panel_open() -> bool:
    c = px([CLOSE_X])
    return bool(c) and near(c[0], (197, 73, 49), 35)


def open_panel() -> bool:
    """開寵物面板並偵測；沒開成 → ESC 復原再重新點（使用者規則 2026-10-13），最多 3 次"""
    for k in range(3):
        if panel_open():
            return True
        if k > 0:
            gui('key', '{ESC}', note='petdepot 寵物面板沒開成 → ESC 復原')
            time.sleep(0.8)
        click(*PET_BTN, wait=1500, right=2, note=f'petdepot 開寵物面板（第 {k + 1}/3 次）')
    return panel_open()


def warn_dialog() -> bool:
    c = px([WARN_OK, WARN_NO])
    return bool(c) and near(c[0], (44, 83, 131), 45) and near(c[1], (200, 70, 40), 60)


def slot_empty(i: int) -> bool:
    c = px([(178, SLOT_Y[i] + 22)])
    # 有寵物是深褐（R≈80~100）；空格腳印圖米色（R 145~190、G−B ≈ 40~47）。
    # 使用者 2026-10-14：紅色寵物（多魯寶）這一點是 (179,98,100)，只看 R>120 且 G>90 會被當空格 → organize / clear 完全沒讀到它
    # → 加上「米色」條件：G−B >= 25（紅 / 粉色的寵物身體 G−B 接近 0 或負）
    # 2026-10-15 333 角色 5：藍龍在這一點是黃色 (195,151,0)，G−B=151 也過 → 被當空格、fight 階段不按出戰
    # → 米色腳印 B 約 90~98、G−B 約 40~47：再加 B >= 70、G−B <= 60（黃 / 橘色寵物 B 很低、G−B 很大）
    return is_empty_color(c[0]) if c else False


def is_empty_color(rgb) -> bool:
    """寵物欄空格（米色腳印圖）的顏色判斷；純函式，離線測試用"""
    r, g, b = rgb
    return r > 120 and g > 90 and b >= 70 and 25 <= g - b <= 60


def personal_tab_on() -> bool:
    c = px([DEPOT_TARGET])
    return bool(c) and c[0][0] > 200 and c[0][2] > 100      # 亮黃 = 選中


def goto_depot() -> None:
    click(*TAB_DEPOT, wait=1300, note='petdepot 倉庫分頁')
    if not personal_tab_on():
        click(*DEPOT_TARGET, wait=900, note='petdepot 倉庫目標分頁')


def pet_name() -> str:
    import uikit
    return uikit.ocr_name(NAME_BOX)          # 存倉 / 領寵用（可補救）：舊讀法 + -Dark 0（2026-10-15）


def load_log() -> dict:
    try:
        return json.loads(LOG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--do', action='store_true', help='真的存（預設只預覽名稱）')
    ap.add_argument('--roles', default='1,2,3,4,5')
    ap.add_argument('--check-empty', action='store_true', help='只檢查：--roles 每個角色的寵物欄 5 格都要是空的（不存、不點寵物）；有寵物回傳 6')
    ap.add_argument('--public', action='store_true', help='存公共寵物倉庫（預設個人）；角色 4、5 的火雞用這個')
    a = ap.parse_args(argv)
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import layout
    if layout.current() != '1920x1017':
        print(f'版面 {layout.current()}，這支只量過 1920x1017')
        return 2
    global DEPOT_TARGET
    if a.public:
        DEPOT_TARGET = DEPOT_PUBLIC
    if not open_panel():
        print('寵物面板打不開（戰鬥 / 對話中？）')
        return 3
    goto_depot()
    if a.check_empty:                                  # 雜寵混入檢查：解任務前寵物欄必須全空（使用者 2026-10-12）
        bad = {}
        for r in [int(x) - 1 for x in a.roles.split(',') if x.strip()]:
            click(ROLE_X, ROLE_Y[r], wait=1200, note=f'petdepot 檢查空欄：角色 {r + 1}')
            left = [i + 1 for i in range(5) if not slot_empty(i)]
            if left:
                bad[r + 1] = left
        click(*CLOSE_X, wait=600, note='petdepot 關面板')
        if bad:
            log('寵物欄不是空的（格號）：' + '；'.join(f'角色{r} 第 {",".join(map(str, v))} 格' for r, v in bad.items()))
            return 6
        log('5 人寵物欄全空')
        return 0
    record = load_log()
    for r in [int(x) - 1 for x in a.roles.split(',') if x.strip()]:
        click(ROLE_X, ROLE_Y[r], wait=1200, note=f'petdepot 選角色 {r + 1}')
        names = []
        if not a.do:                                   # 預覽：逐格點選讀名稱（不存）
            for i in range(5):
                if not slot_empty(i):
                    click(SLOT_X, SLOT_Y[i], wait=700, note=f'petdepot 選第 {i + 1} 格')
                    names.append((i + 1, pet_name()))
        else:                                          # 直接連按「存入寵物」：遊戲會自動跳到下一隻（使用者 2026-10-11）
            stuck = 0
            for _ in range(8):
                if warn_dialog():
                    click(*WARN_OK, wait=1300, note='petdepot 提示窗確定')
                left = [i for i in range(5) if not slot_empty(i)]
                if not left:
                    break
                name = pet_name()
                click(*STORE_BTN, wait=500, note='petdepot 存入寵物')
                now = left
                t0 = time.time()
                while time.time() - t0 < 6.0:           # 輪詢：提示窗（戰鬥 / 騎乘中）出現就按確定；欄內隻數減少就算成功
                    if warn_dialog():
                        click(*WARN_OK, wait=900, note='petdepot 提示窗確定')
                    now = [i for i in range(5) if not slot_empty(i)]
                    if len(now) < len(left):
                        sleep(0.6)                      # 讓選取自動跳到下一隻
                        break
                    sleep(0.5)
                if len(now) < len(left):
                    names.append((len(names) + 1, name))
                    log(f'角色{r + 1} 已存：{name}（欄內剩 {len(now)} 隻）')
                    stuck = 0
                else:
                    stuck += 1
                    if stuck >= 2:
                        log(f'角色{r + 1}「{name}」存不進去（倉庫滿 / 鎖定戰寵？）→ 停手')
                        LOG_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
                        return 4
        log(f'角色{r + 1} {"預覽" if not a.do else "存入"}：{names}')
        if a.do:
            record.setdefault(f'角色{r + 1}', []).extend([{'slot': s, 'name': n, 'at': time.strftime('%F %T')} for s, n in names])
            LOG_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
    click(*CLOSE_X, wait=600, note='petdepot 關面板')
    return 0


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('petdepot1920')       # 印出「停手」就當下存圖（面板還開著）
    sys.exit(main())
