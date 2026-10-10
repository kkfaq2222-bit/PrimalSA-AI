#!/usr/bin/env python3
"""異常檢查清單：練功中發現異常（經驗速度掉、戰鬥過久…）時，levelwatch 會跑這裡的檢查，也可以單獨手動跑。

用法（專案根目錄；多客戶端先設 PSA_EXE_MATCH 與 PSA_TILE_SCALE）：
  PSA_EXE_MATCH=gameClient uv run --no-project python tools/gui/healthcheck.py [--only 外掛勾選]

只「看」不改：開外掛面板 → 逐一選 5 個角色 → 用像素判斷「快速戰鬥」「自動戰鬥」有沒有打勾 → 選回第 1 個角色 → ESC。
不會點任何勾選框（外掛裡的勾選只有使用者同意才能改，見 psa-game-ui 紅區）。
單獨手動跑時不要和同一個客戶端的 levelwatch / heal 同時動作（游標瞬移點擊會互相干擾）。

新增檢查：寫一個 `def 檢查名() -> list[str]`（回傳問題描述；沒問題回空串列；不能檢查回 ['(略過) 原因'] 以 (略過) 開頭），
再加進下面的 CHECKS。levelwatch 的觸發條件（經驗速度、戰鬥過久）不用改。
目前只支援 1920×1017 版面（座標 2026-10-10 實測；2880×1659 的外掛面板座標還沒量）。
"""
import argparse
import sys
import time

import heal
import layout
from walk import PRIMER, log

# ---- 1920×1017 版面（截圖 960×508），2026-10-10 實測 ----
ASS_BTN = (872, 462)                    # 主畫面「外掛」
PANEL_X = (855, 50)                     # 外掛面板右上橘色 ✕（開著 ≈ 195,127,8）
ROLES = [(113, 89), (219, 89), (317, 89), (113, 121), (219, 121)]   # 左上角色圓鈕（選取中 = 0,0,0；沒選 = 197,227,255）
FLAGS = {'快速戰鬥': (332, 208), '自動戰鬥': (121, 243)}             # 勾選框中心；有勾時框內有黑色勾，沒勾全白
GRID = [(dx, dy) for dx in (-6, -3, 0, 3, 6) for dy in (-6, -3, 0, 3, 6)]
DARK = 160                              # 亮度低於這個算「黑色勾」


def _panel_open() -> bool:
    r, g, b = heal.pixels([PANEL_X])[0]
    return r > 170 and 90 < g < 170 and b < 60


def _ticked(cx: int, cy: int) -> bool:
    px = heal.pixels([(cx + dx, cy + dy) for dx, dy in GRID])
    return sum(max(c) < DARK for c in px) >= 2


def ass_flags() -> list[str]:
    """外掛：5 個角色的「快速戰鬥」「自動戰鬥」都要打勾。回傳有問題的項目。"""
    if layout.current() != '1920x1017':
        return [f'(略過) 外掛面板座標只量過 1920x1017，目前 {layout.current()}']
    out = heal.gui('seq', f'waitpix 0 {heal.SIG_HUD} 50')
    if not out.startswith('ok'):
        return ['(略過) 看不到主畫面 HUD（戰鬥中或有視窗），不開外掛面板']
    problems: list[str] = []
    heal.gui('seq', f'{PRIMER}; click {ASS_BTN[0]} {ASS_BTN[1]}; wait 900')
    try:
        if not _panel_open():
            return ['(略過) 外掛面板沒有開起來']
        for i, (rx, ry) in enumerate(ROLES):
            heal.gui('seq', f'click {rx} {ry}; wait 500')
            # 選取中的圓鈕是黑點；第 3 個圓鈕會被「翻倍成功」之類的浮動訊息半蓋住，所以取 3 點、至少 2 點夠暗
            if sum(max(c) < 100 for c in heal.pixels([(rx, ry), (rx + 4, ry), (rx, ry - 4)])) < 2:
                problems.append(f'DKB0{i + 1 if i else ""} 選不到角色，無法檢查')
                continue
            who = f'DKB0{i + 1}' if i else 'DKB0'
            for name, (cx, cy) in FLAGS.items():
                if not _ticked(cx, cy):
                    problems.append(f'{who} 沒勾「{name}」')
    finally:
        heal.gui('seq', f'click {ROLES[0][0]} {ROLES[0][1]}; wait 400')   # 選回第 1 個角色
        heal.gui('key', '{ESC}')
        time.sleep(0.6)
        if _panel_open():
            log('外掛面板沒關掉（ESC 後還在），請人看一下')
    return problems


CHECKS = [('外掛勾選', ass_flags)]


def run(reason: str, only: str | None = None) -> list[str]:
    """跑全部（或指定）檢查；回傳「真的有問題」的描述（略過的只印 log）。有問題會記一筆 errlog。"""
    found: list[str] = []
    for name, fn in CHECKS:
        if only and only != name:
            continue
        log(f'異常檢查（{reason}）：{name}')
        try:
            res = fn()
        except Exception as e:   # 檢查本身出錯不能讓監測中斷
            log(f'  {name} 檢查出錯：{e}')
            continue
        for line in res:
            log(f'  {name}：{line}')
            if not line.startswith('(略過)'):
                found.append(f'{name}：{line}')
        if not res:
            log(f'  {name}：正常')
    if found:
        try:
            import errlog
            errlog.add(f'異常檢查（{reason}）發現：' + '；'.join(found), source='healthcheck')
        except Exception:
            pass
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description='異常檢查（只看不改）')
    ap.add_argument('--only', choices=[n for n, _ in CHECKS], help='只跑這一項')
    a = ap.parse_args()
    found = run('手動', a.only)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
