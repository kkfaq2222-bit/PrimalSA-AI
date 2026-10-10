#!/usr/bin/env python3
"""切換「當前角色」（P3）。計畫：notes/plan-scriptify.md §4。只用標準函式庫。

用法（專案根目錄；WSL / Windows 原生指令相同；角色名 DKB0 / DKBO 兩種寫法都收，輸出用真名 DKBO）：
  uv run --no-project python tools/gui/char.py current [--json]    # 唯讀：開切換面板讀「當前」是誰（讀得到名字就更新 current-char.json）
  uv run --no-project python tools/gui/char.py switch DKBO2        # 切過去並確認；已經是就不點
  uv run --no-project python tools/gui/char.py ensure DKBO         # 同 switch（語意：是就不動、不是才切；grind / pet-quest 收尾用）
  最後一行一律印 JSON：{"ok", "rc", "current", "target", "changed", "ms", ...}

不會自動切回 DKBO（計畫 §9 第 10 條）：切到別人之後由呼叫端負責 `ensure DKBO`。
切換後畫面換成那個角色的位置（可能不同地圖），之後的走路 / 點擊以新角色為準；隊伍身分不變（P-I3 實測）。

退出碼（共用 0 / 1 / 2 / 8 / 9 / 10 見 uikit；char 自己 60～65）：
  60 切換面板打不開或讀圖中途消失（沒點任何面板內座標）
  61 目標卡片找不到：名字沒有被 namematch 樣板（或 OCR 一致）確認、或該卡不是「線上」（離線 / 狀態不明）→ 不點，不猜
  62 點了卡片但驗證時當前不是目標（不重點第二次）
  63 當前框數量 ≠ 1（讀不準）
  64 名字矛盾（樣板與順序不同、OCR 讀到別人）
  65 點了卡片但「加載中」後 HUD 6 s 內沒回來（可能是別的視窗，停手看畫面）

流程（P-I3 實測 2026-10-11）：點卡片後切換面板一定自己關；加載畫面約 0.25～0.5 s，HUD 在點擊返回後約 0.6 s 回來（整體約 1.2～1.4 s）。
所以：點卡片前 team.read_state(keep_open) 讀一次，名字確認 + 狀態線上才點；點完先等加載特徵出現（≤1.5 s）再等 SIG_HUD（≤6 s）；
最後重開面板（read_state）以「當前框 + 名字」驗證，沒到就再等 1.5 s 重讀一次（唯讀，不重點）。成功才寫 charstate。
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import charstate  # noqa: E402
import screen_sigs  # noqa: E402
import team  # noqa: E402
import uikit  # noqa: E402

SRC = 'char'
EXIT_PANEL, EXIT_NO_CARD, EXIT_NOT_SWITCHED, EXIT_CUR_COUNT, EXIT_CONFLICT, EXIT_NO_HUD = 60, 61, 62, 63, 64, 65
CLICK_DX = 204                       # 點卡片中段（左欄 620、右欄 930；ui/team.md 的卡片座標）
LOADING_SEEN_S = 1.5                 # 點完最多等這麼久看加載畫面出現
HUD_TIMEOUT_S = 6.0
VERIFY_RETRY_S = 1.5
POLL_S = 0.15


def confirmed(c) -> bool:
    """卡片名字是否「有證據」：namematch 樣板命中且與順序不矛盾，或舊 OCR 交叉一致。順序單獨推得的名字（check unknown / unread）不算"""
    return bool(c.name) and c.check == 'ok'


def analyse(r: dict, target=None) -> dict:
    """純函式：team.read_state 結果 → {'rc', 'msg', 'current', 'target_card'}。rc 0 = 讀得準（current 已確認名字）
    順序：名字矛盾 64 > 當前框 ≠ 1 → 63 > 當前名字沒確認 61；target_card = 目標卡（確認名字 + 線上）或 None"""
    cards = r['cards']
    bad = [c for c in cards if c.check == 'conflict']
    if bad:
        return {'rc': EXIT_CONFLICT, 'msg': '名字矛盾：' + '、'.join(f'slot{c.slot}={c.name} OCR {c.ocr}' for c in bad), 'current': None, 'target_card': None}
    cur = [c for c in cards if c.status == 'current']
    if len(cur) != 1:
        return {'rc': EXIT_CUR_COUNT, 'msg': f'當前框 {len(cur)} 個（要剛好 1 個）', 'current': None, 'target_card': None}
    cc = cur[0]
    tc = next((c for c in cards if target and confirmed(c) and c.status == 'online' and charstate.same(c.name, target)), None)
    if not confirmed(cc):
        return {'rc': EXIT_NO_CARD, 'msg': f'當前框在 slot{cc.slot}，但名字無法確認（樣板 / OCR 都沒證據）', 'current': None, 'target_card': tc}
    return {'rc': 0, 'msg': '', 'current': charstate.display(cc.name), 'target_card': tc}


def wait_switched(loading_s: float = LOADING_SEEN_S, hud_s: float = HUD_TIMEOUT_S) -> tuple:
    """點卡片後：先等加載畫面出現（≤ loading_s；太快錯過也沒關係），再等 SIG_HUD（≤ hud_s）。→ (看到加載, HUD 回來, 秒數)"""
    t0 = uikit.clock()
    seen = False
    while uikit.clock() - t0 < loading_s:
        if uikit.sig_match(screen_sigs.SIG_LOADING):
            seen = True
            break
        uikit.sleep(POLL_S)
    end = uikit.clock() + hud_s
    while True:
        if uikit.hud_visible():
            return seen, True, uikit.clock() - t0
        if uikit.clock() >= end:
            return seen, False, uikit.clock() - t0
        uikit.sleep(POLL_S)


def _out(rc: int, info: dict, t0: float, msg: str = '') -> int:
    info.setdefault('changed', False)
    info.update(ok=rc == 0, rc=rc, ms=int((time.time() - t0) * 1000))
    if msg:
        info['msg'] = msg
    print(json.dumps(info, ensure_ascii=False))
    return rc


def _record(name) -> None:
    if name:
        charstate.write(name, src='char.py')


def current(as_json: bool = False) -> int:
    """唯讀：讀當前是誰；名字確認才寫 charstate"""
    t0 = time.time()
    rc = uikit.preflight(SRC)
    if rc:
        return _out(rc, {'current': None}, t0)
    r = team.read_state(True)
    if not r['ok']:
        uikit.snap('char-current-fail')
        uikit.fail(SRC, EXIT_PANEL, r['err'])
        return _out(EXIT_PANEL, {'current': None}, t0, r['err'])
    a = analyse(r)
    if a['rc']:
        uikit.snap('char-current-fail')
        uikit.fail(SRC, a['rc'], a['msg'])
        return _out(a['rc'], {'current': None}, t0, a['msg'])
    _record(a['current'])
    if not as_json:
        print(f'當前角色：{a["current"]}')
    return _out(0, {'current': a['current']}, t0)


def switch(target_text: str) -> int:
    """切到 target（已是就不點）。回退出碼；最後一行 JSON"""
    t0 = time.time()
    hit = charstate.norm_char(target_text)
    target = charstate.display(hit) if hit else None
    if not target:
        print(f'char：角色名 {target_text!r} 不在白名單 {charstate.chars()}', file=sys.stderr)
        return _out(uikit.EXIT_USAGE, {'target': None, 'current': None}, t0, '角色名不在白名單')
    info = {'target': target, 'current': None}
    rc = uikit.preflight(SRC)
    if rc:
        return _out(rc, info, t0)
    clicked = False
    try:
        r = team.read_state(True, keep_open=True)
        if not r['ok']:
            uikit.snap('char-switch-fail')
            uikit.fail(SRC, EXIT_PANEL, r['err'])
            return _out(EXIT_PANEL, info, t0, r['err'])
        a = analyse(r, target)
        info['current'] = a['current']
        if a['rc']:                                   # 矛盾 / 當前框數不對 / 當前名字不明：不知道來源狀態，不敢切
            uikit.snap('char-switch-fail')
            uikit.fail(SRC, a['rc'], a['msg'])
            return _out(a['rc'], info, t0, a['msg'])
        if charstate.same(a['current'], target):
            _record(target)
            print(f'char：當前已是 {target}，沒有點擊')
            return _out(0, info, t0)
        tc = a['target_card']
        if tc is None:
            names = [(c.name, c.status, c.check) for c in r['cards']]
            uikit.snap('char-switch-nocard')
            msg = f'找不到可點的 {target} 卡片（要求：名字確認 + 線上）；卡片 {names}'
            uikit.fail(SRC, EXIT_NO_CARD, msg)
            return _out(EXIT_NO_CARD, info, t0, msg)
        x0, y = team.SLOTS[tc.slot]
        if not uikit.safe_click(x0 + CLICK_DX, y, uikit.SWITCH, note=f'char 切到 {target}（slot{tc.slot}）'):
            msg = '點卡片前切換面板特徵不在，沒點'
            uikit.fail(SRC, EXIT_PANEL, msg)
            return _out(EXIT_PANEL, info, t0, msg)
        clicked = True
    finally:
        if not clicked:
            uikit.close_panel(uikit.SWITCH)
    # 面板會自己關；等加載 → HUD → 重開面板驗證（唯讀，絕不重點）
    seen, hud, sec = wait_switched()
    info['loading_seen'] = seen
    info['changed'] = True                             # 已點擊：畫面可能已換角色，呼叫端要知道
    if not hud:
        uikit.snap('char-switch-nohud')
        msg = f'點了 {target} 卡片，但 HUD {HUD_TIMEOUT_S:.0f} s 內沒回來（可能是別的視窗）'
        uikit.fail(SRC, EXIT_NO_HUD, msg)
        return _out(EXIT_NO_HUD, info, t0, msg)
    a = {'rc': EXIT_NOT_SWITCHED, 'msg': '', 'current': None}
    for i in range(2):
        r = team.read_state(True)
        if r['ok']:
            a = analyse(r)
            if a['rc'] == 0 and charstate.same(a['current'], target):
                break
        else:
            a = {'rc': EXIT_PANEL, 'msg': r['err'], 'current': None}
        if i == 0:
            uikit.sleep(VERIFY_RETRY_S)
    info['current'] = a['current']
    if a['rc'] == 0 and charstate.same(a['current'], target):
        _record(target)
        print(f'char：已切到 {target}（加載 {"有" if seen else "沒"}看到，HUD 回來 {sec:.1f} s）')
        return _out(0, info, t0)
    rc = a['rc'] or EXIT_NOT_SWITCHED
    msg = a['msg'] or f'點了 {target} 卡片但驗證時當前是 {a["current"]}'
    uikit.snap('char-switch-verify-fail')
    uikit.fail(SRC, rc, msg)
    return _out(rc, info, t0, msg)


ensure = switch


def main() -> int:
    import winenv
    winenv.enable_server()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('current', help='唯讀：當前角色')
    p.add_argument('--json', action='store_true', help='只印最後一行 JSON')
    for n in ('switch', 'ensure'):
        p = sub.add_parser(n, help='切到指定角色（已是就不點）')
        p.add_argument('name')
    a = ap.parse_args()
    if a.cmd == 'current':
        return current(a.json)
    return switch(a.name)


if __name__ == '__main__':
    sys.exit(main())
