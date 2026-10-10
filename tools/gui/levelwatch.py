#!/usr/bin/env python3
"""等級監測換練功點（用實測的真門檻，見 ui/transfer.md），掛到 131 級才結束。

  1 級 柯奧龜洞、10 級 阿布龜洞、20 級 海主人隧道、45 級 五兄弟洞窟、60 級 柯奧4F龜洞、
  80 級 波拉島、120 級 地雷區

用法（專案根目錄）：
  PSA_EXE_MATCH=gameClient uv run --no-project python tools/gui/levelwatch.py [--every 30] [--verbose] [--dry-run]
  --label：改用傳送面板標的 Lv 當門檻（比真門檻晚換點）

補血：隊長血條 < --hp% 或魔條 < --mp%（連續讀到 2 次）就用 heal.heal_trip 回村補血，再傳回「現在該在的練功點」（--no-heal 關掉）。
換點流程：關原地遇敵 → 等戰鬥結束（VS 牌消失）→ 傳送 → 開原地遇敵。
視窗被最小化會自動還原（不搶焦點）。
出現答題 / 驗證視窗無法偵測；讀不到 HUD（面板蓋住等）超過 5 次就停下來請人看（鐵則 5）。
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import heal
import layout
from walk import log, stat

# (等級門檻, 練功點名稱) 由高到低；只認 0 轉（轉生後門檻未實測）
END_LEVEL = 131      # 到這個等級才結束監測
STAGES = [(130, '地雷區'), (120, '波拉島'), (80, '柯奧4F龜洞'), (60, '五兄弟洞窟'),
          (30, '海主人隧道'), (20, '阿布龜洞'), (10, '柯奧龜洞')]
REAL_STAGES = [(120, '地雷區'), (80, '波拉島'), (60, '柯奧4F龜洞'), (45, '五兄弟洞窟'),
               (20, '海主人隧道'), (10, '阿布龜洞'), (1, '柯奧龜洞')]


def parse_level(s: dict) -> tuple[int, int] | None:
    """隊長等級。隊長等級的 OCR 會漏讀位數（112 級讀成 2），所以同時看寵物等級取較大者
    （練功階段隊長和戰寵等級相同；寵物欄讀到的位數比較穩）。"""
    def one(v):
        m = re.match(r'(\d+)轉(\d+)級', str(v or ''))
        return (int(m.group(1)), int(m.group(2))) if m else None
    a, b = one(s.get('level')), one(s.get('petLevel'))
    if a and b:
        return max(a, b)
    return a or b


def target_for(level: int, stages=None) -> str | None:
    return next((name for need, name in (stages or STAGES) if level >= need), None)


def move_to(spot: str) -> None:
    sx, sy, spot_map = heal.SPOTS[spot]
    out = heal.gui('seq', heal.encounter_steps(False) + f'; waitpix 20000 {heal.SIG_NO_BATTLE} 40')
    if not heal.encounter_done(out):
        heal.set_encounter(False)
    heal.teleport(heal.TAB_LEVEL, (sx, sy), spot_map, spot, want_xy=heal.SPOT_XY.get(spot_map))
    heal.set_encounter(True)
    log(f'已到 {spot}，原地遇敵開')


def main() -> int:
    ap = argparse.ArgumentParser(description='等級監測換練功點')
    ap.add_argument('--every', type=int, default=30, help='監測間隔秒數（預設 30）')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--label', action='store_true', help='改用傳送面板標的 Lv 當門檻（預設用實測的真門檻）')
    ap.add_argument('--at', choices=list(heal.SPOTS), help='重啟時告訴腳本現在已經在這個練功點（地名折兩行的地圖 OCR 讀不到座標）')
    ap.add_argument('--no-heal', action='store_true', help='不要自動回村補血')
    ap.add_argument('--hp', type=int, default=40, help='隊長血條低於這個百分比就回村（預設 40）')
    ap.add_argument('--mp', type=int, default=20, help='隊長魔條低於這個百分比就回村（預設 20）')
    ap.add_argument('--note', default='', help='寫進經驗紀錄的備註，例：2倍智慧果中')
    ap.add_argument('--dry-run', action='store_true', help='只印會做什麼，不傳送')
    a = ap.parse_args()
    if layout.current() not in layout.SUPPORTED:
        log(f'不支援 {layout.current()} 版面，見 ui/layout-1920x1017.md')
        return 2
    done = a.at          # 已經換過去的練功點
    # 經驗紀錄：每次確認讀數後存一行（時間, 視窗, 等級, 地圖, 備註），之後用 Exp 表算每分鐘經驗；notes/ 不進 git
    log_path = Path(__file__).resolve().parents[2] / 'notes' / f'exp-log-{os.environ.get("PSA_EXE_MATCH") or "game"}.csv'
    log_path.parent.mkdir(exist_ok=True)
    if not log_path.exists():
        log_path.write_text('time,level,pos,note\n', encoding='utf-8')
    good_level = None    # 已確認的等級（只升不降）
    pending = None       # 上一次讀到、等第二次確認的等級
    bad = 0
    stages = STAGES if a.label else REAL_STAGES
    log('監測中：' + '、'.join(f'{n} 級→{name}' for n, name in reversed(stages)) + '（Ctrl+C 結束）')
    while True:
        s = stat()
        lv = parse_level(s)
        if lv is None and '最小化' in str(s.get('error') or ''):
            # Unity 最小化不繪製（戰鬥也停）：gui info 會用 SW_SHOWNOACTIVATE 還原，不搶焦點；還原後馬上重讀
            log('遊戲視窗最小化，還原')
            heal.gui('info')
            time.sleep(2)
            s = stat()
            lv = parse_level(s)
        if lv is None:
            bad += 1
            log(f'讀不到等級（{bad}/5）：{s.get("error") or s.get("level")}')
            if bad >= 5:
                log('連續讀不到 HUD，可能有驗證視窗或對話框，停止監測，請人看畫面')
                return 1
        else:
            bad = 0
            trans, level = lv
            # OCR 會漏讀位數（112 讀成 2）：等級只升不降；比已確認的等級低就不信（2026-10-10 112 級被讀成 2 級傳錯地圖）
            # 另外要連續兩次讀到同一個數字才採信
            if good_level is not None and level < good_level:
                log(f'讀到 {level} 級，比已確認的 {good_level} 級低，視為 OCR 誤讀，略過')
                time.sleep(a.every)
                continue
            if level != pending:
                pending = level
                time.sleep(3)
                continue
            good_level = level
            with log_path.open('a', encoding='utf-8') as fh:
                fh.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")},{level},{s.get("pos") or ""},{a.note}\n')
            if a.verbose:
                log(f'{trans}轉{level}級 地圖 {s.get("pos")}')
            spot = target_for(level, stages) if trans == 0 else None
            if trans != 0:
                log(f'{trans} 轉角色，門檻未實測，停止監測')
                return 1
            if level >= END_LEVEL:
                log(f'隊長已達 {level} 級，結束監測。注意：只看了隊長，5 個角色都要 {END_LEVEL} 級才算完成，請再開「切換」面板確認其他 4 人')
                return 0
            if done is None and spot:
                # 重啟時人已經在該練功點的地圖上就不用再傳送
                m = re.match(r'(\d+):', str(s.get('pos') or ''))
                if m and int(m.group(1)) == heal.SPOTS[spot][2]:
                    done = spot
                    log(f'已在 {spot}，不重複傳送')
            if spot and spot != done:
                log(f'{level} 級，換到 {spot}')
                if a.dry_run:
                    done = spot
                else:
                    try:
                        move_to(spot)
                        done = spot
                    except RuntimeError as e:
                        log(f'換點失敗：{e}；停止監測，請人工處理')
                        return 1
        if not a.no_heal and not a.dry_run and done and lv is not None and heal.low(s, a.hp, a.mp):
            time.sleep(3)
            s2 = stat()
            if heal.low(s2, a.hp, a.mp):
                log(f'血 / 魔太低（HP {s2.get("hpPct")}%，MP {s2.get("mpPct")}%），回村補血後回 {done}')
                try:
                    t_heal = time.time()
                    with (log_path.parent / f'heal-log-{os.environ.get("PSA_EXE_MATCH") or "game"}.csv').open('a', encoding='utf-8') as hf:
                        hf.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")},{level},{done},HP{s2.get("hpPct")}%/MP{s2.get("mpPct")}%\n')
                    heal.heal_trip(done)
                except RuntimeError as e:
                    log(f'補血流程失敗：{e}；停止監測，請人工處理')
                    return 1
        time.sleep(a.every)


if __name__ == '__main__':
    sys.exit(main())
