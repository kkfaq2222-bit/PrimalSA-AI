#!/usr/bin/env python3
"""外掛 ASS 左欄戰鬥設定的讀 / 設工具（只用標準庫，經 walk.gui → winenv → gui.ps1；背景操作）。

用法（專案根目錄；WSL / Windows 原生指令相同）：
  uv run --no-project python tools/gui/ass.py get DKB0                    # 印五項狀態（開 / 關）
  uv run --no-project python tools/gui/ass.py get DKB0 自動逃跑 自動戰鬥     # 只印指定項目
  uv run --no-project python tools/gui/ass.py set DKB0 自動逃跑 on 自動戰鬥 on 快速戰鬥 off
  uv run --no-project python tools/gui/ass.py pet DKB0 get                # 戰寵 首次動作（勾選 + 值）/ 一般動作（值）
  uv run --no-project python tools/gui/ass.py pet DKB0 first 防禦          # 首次動作 = 防禦 並勾選
  uv run --no-project python tools/gui/ass.py pet DKB0 first off normal 攻擊   # 首次動作取消勾選（值不動）、一般動作 = 攻擊
角色：DKB0 / DKB02 / DKB03 / DKB04 / DKB05（不分大小寫）。
項目：原地遇敵(encounter) / 自動逃跑(flee) / 快速戰鬥(fast) / 自動戰鬥(auto) / 夥伴助戰(partner)。
流程：開外掛 → 驗證面板真的開了 → 選角色並驗證 → pixel 讀五項 → （set：只點與目標不同的，再讀確認）→ 關面板（X 1318,90）並驗證。
安全：每次點面板內座標前都先 pixel 驗證面板還開著（面板沒開時點這些座標會穿透到地面讓角色走掉）；
      主畫面看不到外掛鈕（對話 / 載入中）或被擋 → 等待重試，最多 OPEN_TIMEOUT 秒，失敗回報、不亂點。
退出碼：0 成功 / 1 參數錯 / 2 面板打不開 / 3 選不到角色 / 4 設定確認失敗（點了沒變，不再補點）/ 5 版面不是 2880×1659 / 6 面板中途消失（讀不到）/ 7 右半面板不在頂端（pet：戰寵動作標題讀不到，不點）。
勾選判讀（2026-10-10 實測）：未勾 = 框心 255,255,255；已勾 = 其他值（30,30,30 / 151 / 223 視打勾筆劃而定）。
只動點到的角色；不改其他角色，不碰其他項目。外掛面板不能用 ESC 關。
給其他腳本 import：ass.get_states(role) / ass.set_states(role, {項目: bool}) → (ok, 狀態 dict 或 None, 訊息)。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import layout  # noqa: E402
from walk import gui, log  # noqa: E402

ASS_BTN = (1300, 760)            # 主畫面「外掛」
CLOSE_BTN = (1318, 90)           # 面板右上 X（不能 ESC）
HUD_PROBE = (1300, 745, 254, 0, 0)   # 主畫面外掛鈕紅字（同 quest.SIG_HUD；對話框開著時整個 UI 隱藏）

ROLES = {'DKB0': (137, 151), 'DKB02': (298, 151), 'DKB03': (461, 151), 'DKB04': (137, 204), 'DKB05': (298, 204)}
# 左欄戰鬥設定勾選框（框心）；每個角色各自設定
ITEMS = {'原地遇敵': (146, 343), '自動逃跑': (315, 343), '快速戰鬥': (484, 343), '自動戰鬥': (146, 400), '夥伴助戰': (315, 400)}
ALIASES = {'encounter': '原地遇敵', 'flee': '自動逃跑', 'escape': '自動逃跑', 'fast': '快速戰鬥', 'quick': '快速戰鬥',
           'auto': '自動戰鬥', 'partner': '夥伴助戰', 'assist': '夥伴助戰'}

# 面板開著的特徵：右上橘 X + 五個角色圓鈕（選中 0,0,0、沒選中 197,227,255；有 EXP 橫幅可能蓋住 DKB03，容許 1 個不符）
X_SIG = (1318, 90, 195, 127, 8)
AVATAR_SEL = (0, 0, 0)
AVATAR_OFF = (197, 227, 255)
TOL = 25
UNCHECKED = (255, 255, 255)      # 框心純白 = 未勾；其他 = 已勾

OPEN_TIMEOUT = 40.0              # 等外掛面板能開的最長秒數（戰鬥 / 載入中 / 對話會擋）
OPEN_RETRY_GAP = 1.5
CONFIRM_WAIT = 0.5               # 點勾選後第一次讀回的等待
CONFIRM_WAIT2 = 0.9              # 還沒變就多等一次（不補點，避免切回去）

EXIT_OK, EXIT_USAGE, EXIT_NO_PANEL, EXIT_NO_ROLE, EXIT_CONFIRM, EXIT_LAYOUT, EXIT_PANEL_LOST, EXIT_NOT_TOP = 0, 1, 2, 3, 4, 5, 6, 7

sleep = time.sleep               # 測試時可替換
clock = time.time


def _px(pts):
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
    try:
        cols = [tuple(int(v) for v in c.split(',')) for c in out]
    except ValueError:
        return None
    return cols if len(cols) == len(pts) else None


def _close(c, ref, tol=TOL):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def panel_open() -> bool:
    """外掛面板是否真的開著（X + 至少 4 個角色圓鈕合理）。讀不到 = False"""
    pts = [(X_SIG[0], X_SIG[1])] + list(ROLES.values())
    cols = _px(pts)
    if not cols or not _close(cols[0], X_SIG[2:], TOL):
        return False
    good = sum(1 for c in cols[1:] if _close(c, AVATAR_SEL, 8) or _close(c, AVATAR_OFF, 8))
    return good >= 4


def hud_visible() -> bool:
    cols = _px([HUD_PROBE[:2]])
    return bool(cols) and _close(cols[0], HUD_PROBE[2:], 40)


def open_panel(timeout: float = None) -> bool:
    """開外掛面板並驗證；已開著就直接成功。只在看到主畫面外掛鈕時才點（避免點到別的東西）；等待重試有上限"""
    timeout = OPEN_TIMEOUT if timeout is None else timeout
    end = clock() + timeout
    clicked = 0
    while True:
        if panel_open():
            return True
        if hud_visible() and clicked < 6:
            gui('seq', f'click {ASS_BTN[0]} {ASS_BTN[1]}; wait 900', note='ass.py 開外掛面板')
            clicked += 1
            if panel_open():
                return True
        if clock() >= end:
            return False
        sleep(OPEN_RETRY_GAP)


def close_panel() -> bool:
    """點 X 關面板並驗證面板消失（最多點 3 次；只在面板確實還開著時點）"""
    for _ in range(3):
        if not panel_open():
            return True
        gui('seq', f'click {CLOSE_BTN[0]} {CLOSE_BTN[1]}; wait 600', note='ass.py 關外掛面板')
    return not panel_open()


def selected_role() -> str | None:
    cols = _px(list(ROLES.values()))
    if not cols:
        return None
    sel = [r for r, c in zip(ROLES, cols) if _close(c, AVATAR_SEL, 8)]
    return sel[0] if len(sel) == 1 else None


def select_role(role: str) -> bool:
    if selected_role() == role:
        return True
    if not panel_open():
        return False
    x, y = ROLES[role]
    gui('seq', f'click {x} {y}; wait 600', note=f'ass.py 選角色 {role}')
    return selected_role() == role


def read_checks(items=None) -> dict | None:
    """面板開著、角色已選好時讀五項（或指定項）勾選狀態：True = 開；讀不到回 None"""
    items = list(items or ITEMS)
    cols = _px([ITEMS[i] for i in items])
    if not cols:
        return None
    return {i: c != UNCHECKED for i, c in zip(items, cols)}


def norm_item(name: str) -> str | None:
    n = name.strip()
    n = ALIASES.get(n.lower(), n)
    return n if n in ITEMS else None


def norm_role(name: str) -> str | None:
    n = name.strip().upper()
    return n if n in ROLES else None


def _session(role: str, changes: dict | None, items=None):
    """開面板 → 選角色 → 讀 →（有 changes 就設定並確認）→ 關面板。回 (退出碼, 狀態 dict 或 None, 訊息)"""
    if not open_panel():
        return EXIT_NO_PANEL, None, f'外掛面板 {OPEN_TIMEOUT:.0f} 秒內打不開（戰鬥 / 對話 / 載入中擋住？）；沒點任何面板內座標'
    rc, states, msg = EXIT_OK, None, ''
    try:
        if not select_role(role):
            return EXIT_NO_ROLE, None, f'選不到角色 {role}（圓鈕沒變選中，或面板中途消失）'
        states = read_checks()
        if states is None:
            return EXIT_PANEL_LOST, None, '讀不到勾選框像素'
        for item, want in (changes or {}).items():
            if states[item] == want:
                continue
            if not panel_open() or selected_role() != role:
                return EXIT_PANEL_LOST, states, f'點 {item} 前面板已不在 / 角色不對 → 不點'
            x, y = ITEMS[item]
            gui('seq', f'click {x} {y}; wait 300', note=f'ass.py {role} {item} → {"開" if want else "關"}')
            for w in (CONFIRM_WAIT, CONFIRM_WAIT2):
                sleep(w)
                if not panel_open():
                    return EXIT_PANEL_LOST, states, f'點 {item} 後面板消失'
                now = read_checks([item])
                if now and now[item] == want:
                    break
            else:
                return EXIT_CONFIRM, read_checks(), f'{item} 點了仍是 {"開" if states[item] else "關"}（可能是地圖禁止快速戰鬥等；不補點）'
            states = read_checks() or states
            log(f'ass：{role} {item} → {"開" if want else "關"}（已確認）')
        return rc, states, msg
    finally:
        if not close_panel():
            print('警告：外掛面板沒關成功（請 shot 看畫面，手動點 X 1318,90）', flush=True)


# ---- 戰寵動作（戰鬥設置分頁頂端，未捲動；2026-10-10 實測）----
PET_FIRST_CHK = (656, 463)       # 戰寵 首次動作 勾選框
PET_DD = {'first': (1137, 463), 'normal': (1137, 514)}      # 下拉 ▼
PET_FIELD = {'first': (805, 445, 280, 40), 'normal': (805, 495, 280, 40)}   # 欄位文字 OCR 區（x y w h）
PET_TITLE_BOX = (640, 400, 120, 28)  # 「戰寵動作」標題；OCR 讀到「戰寵」才表示面板在頂端
PET_OPTS = ['攻擊', '防禦', '忠犬']   # 下拉前三項固定順序；第 n 項在欄位 y + 42×(n+1)，x 944（學會的技能排後面，不支援）
PET_OPT_DY, PET_OPT_X = 42, 944
OPT_ALIASES = {'attack': '攻擊', 'defend': '防禦', 'defense': '防禦', 'guard': '防禦'}


def _ocr(box, *opts) -> str:
    """區域 OCR，回傳所有行文字接起來（可替換給測試）"""
    import json
    import winenv
    r = winenv.run_ps('ocr.ps1', *map(str, box), *map(str, opts))
    try:
        return ''.join(l['text'] for l in json.loads(r.stdout.strip().splitlines()[-1])['lines'])
    except (ValueError, KeyError, IndexError):
        return ''


def pet_on_top() -> bool:
    return '戰寵' in _ocr(PET_TITLE_BOX, '-Zooms', '2,3,4')


def read_pet_value(which: str) -> str | None:
    """OCR 欄位文字，對到 PET_OPTS 之一就回該值；讀不到 / 不在三項內回 None"""
    txt = _ocr(PET_FIELD[which], '-Zooms', '2,3,4')
    hits = [o for o in PET_OPTS if o in txt]
    return hits[0] if len(hits) == 1 else None


def read_pet() -> dict | None:
    cols = _px([PET_FIRST_CHK])
    if not cols:
        return None
    return {'first_on': cols[0] != UNCHECKED, 'first': read_pet_value('first'), 'normal': read_pet_value('normal')}


def _pet_session(role: str, want: dict | None):
    """want: {'first_on': bool?, 'first': 值?, 'normal': 值?}。回 (退出碼, 狀態 dict 或 None, 訊息)"""
    if not open_panel():
        return EXIT_NO_PANEL, None, f'外掛面板 {OPEN_TIMEOUT:.0f} 秒內打不開；沒點任何面板內座標'
    st = None
    try:
        if not select_role(role):
            return EXIT_NO_ROLE, None, f'選不到角色 {role}'
        if not pet_on_top():
            return EXIT_NOT_TOP, None, '右半面板不在頂端（讀不到「戰寵動作」標題）；不點。請先 shot 看畫面、手動捲回頂端'
        st = read_pet()
        if st is None:
            return EXIT_PANEL_LOST, None, '讀不到勾選框像素'
        for key in ('first', 'normal'):
            v = (want or {}).get(key)
            if v is None or st[key] == v:
                continue
            if not panel_open() or selected_role() != role or not pet_on_top():
                return EXIT_PANEL_LOST, st, f'選 {key} 前面板已不在 / 角色不對 / 被捲動 → 不點'
            x, y = PET_DD[key]
            gui('seq', f'click {x} {y}; wait 500', note=f'ass.py {role} 戰寵{key} 開下拉')
            oy = y + PET_OPT_DY * (PET_OPTS.index(v) + 1)
            if not panel_open():
                return EXIT_PANEL_LOST, st, '開下拉後面板消失'
            gui('seq', f'click {PET_OPT_X} {oy}; wait 500', note=f'ass.py {role} 戰寵{key} → {v}')
            for w in (CONFIRM_WAIT, CONFIRM_WAIT2):
                sleep(w)
                if not panel_open():
                    return EXIT_PANEL_LOST, st, f'選 {key} 後面板消失'
                if read_pet_value(key) == v:
                    break
            else:
                st = read_pet() or st
                return EXIT_CONFIRM, st, f'戰寵 {key} 選了 {v} 但讀回仍是 {st.get(key)}（不補點；請 shot 確認，OCR 也可能誤讀）'
            st = read_pet() or st
            log(f'ass：{role} 戰寵{key} → {v}（已確認）')
        f_on = (want or {}).get('first_on')
        if f_on is not None and st['first_on'] != f_on:
            if not panel_open() or selected_role() != role or not pet_on_top():
                return EXIT_PANEL_LOST, st, '點首次動作勾選前面板已不在 / 角色不對 / 被捲動 → 不點'
            gui('seq', f'click {PET_FIRST_CHK[0]} {PET_FIRST_CHK[1]}; wait 300', note=f'ass.py {role} 戰寵首次動作勾選 → {"勾" if f_on else "不勾"}')
            for w in (CONFIRM_WAIT, CONFIRM_WAIT2):
                sleep(w)
                if not panel_open():
                    return EXIT_PANEL_LOST, st, '點勾選後面板消失'
                now = read_pet()
                if now and now['first_on'] == f_on:
                    break
            else:
                return EXIT_CONFIRM, read_pet(), '首次動作勾選點了沒變（不補點）'
            st = read_pet() or st
            log(f'ass：{role} 戰寵首次動作勾選 → {"勾" if f_on else "不勾"}（已確認）')
        return EXIT_OK, st, ''
    finally:
        if not close_panel():
            print('警告：外掛面板沒關成功（請 shot 看畫面，手動點 X 1318,90）', flush=True)


def get_pet(role: str):
    return _pet_session(role, None)


def set_pet(role: str, want: dict):
    return _pet_session(role, want)


def get_states(role: str):
    return _session(role, None)


def set_states(role: str, changes: dict):
    return _session(role, changes)


def fmt(states: dict, items=None) -> str:
    return '  '.join(f'{i}={"開" if states[i] else "關"}' for i in (items or ITEMS) if i in states)


def _main_pet(role: str, rest: list) -> int:
    want = {}
    if rest != ['get']:
        if not rest:
            print('pet 用法：get | first <攻擊|防禦|忠犬|on|off> | normal <攻擊|防禦|忠犬>（可串接）')
            return EXIT_USAGE
        i = 0
        while i < len(rest):
            k = rest[i]
            v = rest[i + 1] if i + 1 < len(rest) else ''
            v = OPT_ALIASES.get(v.lower(), v)
            if k == 'first' and v.lower() in ('on', 'off'):
                want['first_on'] = v.lower() == 'on'
            elif k == 'first' and v in PET_OPTS:
                want['first'], want['first_on'] = v, True
            elif k == 'normal' and v in PET_OPTS:
                want['normal'] = v
            else:
                print(f'參數錯：{k} {v}')
                return EXIT_USAGE
            i += 2
    if layout.current() != '2880x1659':
        print('ass.py 只量過 2880×1659 版面，先跑 gui.sh max')
        return EXIT_LAYOUT
    rc, st, msg = _pet_session(role, want or None)
    if st:
        print(f'{role} 戰寵：首次動作={"勾" if st["first_on"] else "不勾"}/{st["first"] or "?"}  一般動作={st["normal"] or "?"}')
    if rc:
        print(f'失敗（退出碼 {rc}）：{msg}')
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='外掛 ASS 左欄戰鬥設定讀 / 設')
    ap.add_argument('cmd', choices=['get', 'set', 'pet'])
    ap.add_argument('role', help='DKB0 / DKB02~05')
    ap.add_argument('rest', nargs='*', help='get：項目…；set：項目 on|off 成對')
    a = ap.parse_args(argv)
    role = norm_role(a.role)
    if not role:
        print(f'角色要是 {" / ".join(ROLES)}')
        return EXIT_USAGE
    if a.cmd == 'pet':
        return _main_pet(role, a.rest)
    changes, items = {}, []
    if a.cmd == 'get':
        for n in a.rest:
            it = norm_item(n)
            if not it:
                print(f'不認得的項目：{n}（{" / ".join(ITEMS)}）')
                return EXIT_USAGE
            items.append(it)
    else:
        if not a.rest or len(a.rest) % 2:
            print('set 要成對：項目 on|off')
            return EXIT_USAGE
        for n, v in zip(a.rest[::2], a.rest[1::2]):
            it = norm_item(n)
            if not it or v.lower() not in ('on', 'off', '開', '關'):
                print(f'參數錯：{n} {v}')
                return EXIT_USAGE
            changes[it] = v.lower() in ('on', '開')
        items = list(changes)
    if layout.current() != '2880x1659':
        print('ass.py 只量過 2880×1659 版面，先跑 gui.sh max')
        return EXIT_LAYOUT
    rc, states, msg = _session(role, changes if a.cmd == 'set' else None)
    if states:
        print(f'{role}：{fmt(states, items or None)}')
    if rc:
        print(f'失敗（退出碼 {rc}）：{msg}')
    return rc


if __name__ == '__main__':
    sys.exit(main())
