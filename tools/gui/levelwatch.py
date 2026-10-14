#!/usr/bin/env python3
"""等級監測換練功點（用實測的真門檻，見 ui/transfer.md），掛到 131 級後留在最高練功點繼續補血 / 檢查（--stop-at-end 才結束）。

  1 級 柯奧龜洞、10 級 阿布龜洞、20 級 海主人隧道、45 級 五兄弟洞窟、60 級 柯奧4F龜洞、
  80 級 波拉島、120 級 地雷區

用法（專案根目錄）：
  PSA_EXE_MATCH=gameClient uv run --no-project python tools/gui/levelwatch.py [--every 30] [--verbose] [--dry-run]
  --label：改用傳送面板標的 Lv 當門檻（比真門檻晚換點）

組隊：換點前先確認 1 隊長 + 4 隊員，沒組就一鍵組隊（q1920.form_team，只支援 1920×1017；--no-team 關掉）；補血回來後再確認一次。
外掛：換點前、補血回來後檢查 5 人快速戰鬥 + 自動戰鬥，沒勾的補勾（ass.py fix-all；--no-ass 關掉）。
補血：隊長血條 < --hp% 或魔條 < --mp%（連續讀到 2 次）就用 heal.heal_trip 回村補血，再傳回「現在該在的練功點」（--no-heal 關掉）。
換點流程：關原地遇敵 → 等戰鬥結束（VS 牌消失）→ 傳送 → 開原地遇敵。
視窗被最小化會自動還原（不搶焦點）。
異常檢查（healthcheck.py，只看不改）：發現下列情況就檢查外掛 5 個角色的「快速戰鬥 / 自動戰鬥」有沒有打勾（--no-check 關掉）
  - 經驗速度異常：目前等級已花的時間 > 預期 × --exp-slow（預期 = 該級升級經驗 ÷ 基準每分鐘經驗；
    基準 = --exp-per-min，沒給就用同一張地圖最近 5 次升級的中位數）
  - 戰鬥過久：連續 --battle-max 秒每次取樣都在戰鬥中（頭上有 VS 牌）
  觸發後等戰鬥結束、HUD 回來才檢查；兩次檢查至少隔 --check-every 分鐘。新增檢查項目見 healthcheck.py 開頭。
出現答題 / 驗證視窗無法偵測；讀不到 HUD（面板蓋住等）超過 5 次就停下來請人看（鐵則 5）。
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import healthcheck
import heal
import layout
import pausegate
import progress
import winenv
from walk import log, stat

# (等級門檻, 練功點名稱) 由高到低；0～5 轉都用同一組門檻（使用者 2026-10-12：每次轉生都從 1 級重練，只看人物等級）
END_LEVEL = 131      # 到這個等級才結束監測
PANEL_FROM = 128      # --stop-at-end：HUD 確認讀到這個等級後，開始定期開人物資訊面板確認 5 人等級
PANEL_EVERY_S = 300   # 面板確認的間隔（秒）
HEARTBEAT_S = 600    # 練功中每 10 分鐘印一行心跳，讓看門狗知道還活著（不然升級間隔 > 看門狗卡住門檻會被誤重啟）
STAGES = [(130, '地雷區'), (120, '波拉島'), (80, '柯奧4F龜洞'), (60, '五兄弟洞窟'),
          (30, '海主人隧道'), (20, '阿布龜洞'), (10, '柯奧龜洞')]
REAL_STAGES = [(120, '地雷區'), (80, '波拉島'), (60, '柯奧4F龜洞'), (45, '五兄弟洞窟'),
               (20, '海主人隧道'), (10, '阿布龜洞'), (1, '柯奧龜洞')]


def _one_level(v):
    """「N轉M級」→ (N, M)。OCR 常把「1轉」讀成一個怪字、「級」漏掉（2026-10-12「1轉117級」讀成「嘨117」→ 連續 5 次讀不到而停止），
    所以格式不完整但還剩 2~3 位數字時，轉生數記 -1（未知）、等級照讀；等級只升不降 + 連續兩次一致的保護照舊。"""
    t = str(v or '')
    m = re.match(r'(\d+)轉(\d+)級', t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.fullmatch(r'\D{0,3}(\d{2,3})\D{0,2}', t.strip())
    return (-1, int(m.group(1))) if m else None


def parse_level(s: dict) -> tuple[int, int] | None:
    """隊長等級。隊長等級的 OCR 會漏讀位數（112 級讀成 2），所以同時看寵物等級取較大者
    （練功階段隊長和戰寵等級相同；寵物欄讀到的位數比較穩）。"""
    a, b = _one_level(s.get('level')), _one_level(s.get('petLevel'))
    if a and b:
        return max(a, b, key=lambda x: x[1])
    return a or b


def first_read_ok(s: dict) -> bool:
    """啟動後第一次確認等級用：隊長等級要讀到；寵物等級也讀到時等級差 ≤ 2（不一致不採信；轉生數不比，寵物的轉數跟人物無關）。
    寵物等級讀不到（1920 的寵物欄常讀不到）就只靠隊長等級 + 後面「連續兩次相同」的確認。
    只升不降的保護要有「已確認的等級」才擋得住；第一次若兩次都漏讀同樣位數（112 讀成 2）就會傳錯地圖。"""
    a, b = _one_level(s.get('level')), _one_level(s.get('petLevel'))
    if not a:
        return False
    # 只比等級：寵物的轉生數跟人物無關（人 2 轉、寵 0 轉很正常；舊版要求同轉生數 → 轉生後永遠「不一致」、只觀察不傳送，2026-10-13）
    return bool(not b or abs(a[1] - b[1]) <= 2)


def target_for(level: int, stages=None) -> str | None:
    return next((name for need, name in (stages or STAGES) if level >= need), None)


def load_exp_table() -> dict[int, int]:
    """等級 → 升級所需經驗（knowledge/pets/levels.md）；讀不到回空（關閉經驗速度檢查）"""
    path = Path(__file__).resolve().parents[2] / 'knowledge' / 'pets' / 'levels.md'
    table: dict[int, int] = {}
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            m = re.match(r'\| (\d+) \| (\d+) \|', line)
            if m:
                table[int(m.group(1))] = int(m.group(2))
    except OSError:
        pass
    return table


# 練功剩餘時間預估（2026-10-15 實測 exp-log）：120 級以下用實測每級分鐘數；121 以上用 經驗表 ÷ 每分鐘經驗
#（125~130 在地雷區 60049 / 60050 實測約 78 萬 / 分，兩個點幾乎一樣）
MIN_PER_LEVEL_LOW = [(60, 0.7), (80, 1.3), (100, 1.8), (110, 3.3), (116, 6.0), (120, 9.0), (121, 15.0)]   # (未滿此級, 分/級)
EXP_PER_MIN_HIGH = 780_000


def ensure_encounter(when: str, plugin: bool = True) -> None:
    """練功中確認原地遇敵還開著（使用者 2026-10-15：開關面板時有機會點到移動，把遇敵關掉 → 原地不動、白掛）。
    plugin=True：開外掛讀「原地遇敵」勾選（最準；ass.set_states 只在沒勾時才點，讀回確認後關面板）。
    plugin=False（心跳）：先只看主畫面遇敵圖示像素，看起來沒開才開外掛確認 / 補勾，平常不開面板。戰鬥中不判斷。"""
    try:
        if not heal.gui('seq', f'waitpix 0 {heal.SIG_NO_BATTLE} 40').startswith('ok'):     # 戰鬥中（頭上 VS 牌）
            return
        if not plugin and heal.encounter_on():
            return
        import ass
        rc, st, msg = ass.set_states('DKBO', {'原地遇敵': True})
        if rc == 0 and st and st.get('原地遇敵'):
            log(f'{when}：外掛確認原地遇敵開著（{ass.fmt(st)}）')
        else:
            log(f'{when}：外掛確認原地遇敵沒成功（退出碼 {rc}：{msg}）→ 改用主畫面遇敵鈕')
            if not heal.encounter_on():
                heal.set_encounter(True)
    except Exception as e:
        log(f'{when}：檢查原地遇敵失敗（{e}）')


def eta_minutes(level: int, end: int, table: dict[int, int], t_in_level_min: float = 0.0, rate: float = 0) -> float | None:
    """從 level 練到 end 還要幾分鐘（扣掉目前這級已經練的時間）。rate = 實測每分鐘經驗（0 = 用預設 78 萬）。"""
    if level >= end:
        return 0.0
    total = 0.0
    for lv in range(level, end):
        if lv >= 121:
            exp = table.get(lv)
            if not exp:
                return None
            total += exp / (rate or EXP_PER_MIN_HIGH)
        else:
            total += next(m for lim, m in MIN_PER_LEVEL_LOW if lv < lim)
    return max(0.0, total - t_in_level_min)


def median(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[len(xs) // 2]


def ensure_team(dry_run: bool = False) -> bool:
    """確認 1 隊長 + 4 隊員，不是就一鍵組隊並驗證（用 q1920.form_team；只支援 1920×1017）。
    組隊失敗（有人離線 / 地圖禁止）→ 回 False，呼叫端停下來請人處理。"""
    if dry_run:
        log('（dry-run）這裡會確認隊伍，沒組好就一鍵組隊')
        return True
    try:
        import q1920
        q1920.preflight()
        q1920.form_team()
        return True
    except Exception as e:      # q1920.Halt 或其他
        log(f'組隊失敗：{getattr(e, "msg", e)}')
        return False


def ensure_ass(dry_run: bool = False) -> bool:
    """5 人「快速戰鬥 + 自動戰鬥」都勾好（ass.py fix-all：沒勾的才點一次並讀回；一次開面板，約 10 秒）。
    戰鬥中 / 面板打不開會回非 0，不當成致命錯誤（回 False，呼叫端只記 log，下次換點 / 補血再試）。"""
    if dry_run:
        log('（dry-run）這裡會檢查 5 人快速 + 自動戰鬥，沒勾的補勾')
        return True
    import subprocess
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'ass.py'), 'fix-all'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    tail = (r.stdout or '').strip().splitlines()[-1:] or ['']
    log(f'外掛勾選檢查：退出碼 {r.returncode}；{tail[0]}')
    return r.returncode == 0


ASS_AFTER_ARRIVE = True        # --no-ass 時關掉到點後的外掛勾選檢查


def move_to(spot: str) -> None:
    sx, sy, spot_map = heal.SPOTS[spot]
    out = heal.gui('seq', heal.encounter_steps(False) + f'; waitpix 20000 {heal.SIG_NO_BATTLE} 40')
    if not heal.encounter_done(out):
        heal.set_encounter(False)
    heal.teleport(heal.TAB_LEVEL, (sx, sy), spot_map, spot, want_xy=heal.SPOT_XY.get(spot_map))
    heal.set_encounter(True)
    log(f'已到 {spot}，原地遇敵開')
    # 到練功區要檢查 5 人快速戰鬥 + 自動戰鬥有沒有勾（使用者 2026-10-13；傳送 / 換點後設定可能被洗掉，沒勾的補勾）
    try:
        if ASS_AFTER_ARRIVE:
            ensure_ass()
    except Exception as e:
        log(f'到點後外掛勾選檢查失敗（{e!r}），之後換點 / 補血時會再檢查')


def main() -> int:
    ap = argparse.ArgumentParser(description='等級監測換練功點')
    ap.add_argument('--every', type=int, default=30, help='監測間隔秒數（預設 30）')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--label', action='store_true', help='改用傳送面板標的 Lv 當門檻（預設用實測的真門檻）')
    ap.add_argument('--at', choices=list(heal.SPOTS), help='重啟時告訴腳本現在已經在這個練功點（地名折兩行的地圖 OCR 讀不到座標）')
    ap.add_argument('--no-heal', action='store_true', help='不要自動回村補血')
    ap.add_argument('--no-ass', action='store_true', help='不要自動補勾 5 人快速戰鬥 / 自動戰鬥（預設換點前、補血回來後會檢查）')
    ap.add_argument('--no-team', action='store_true', help='不要自動確認 / 組隊（預設換點前會確認 5 人隊伍，沒組就一鍵組隊）')
    ap.add_argument('--hp', type=int, default=40, help='隊長血條低於這個百分比就回村（預設 40）')
    ap.add_argument('--mp', type=int, default=20, help='隊長魔條低於這個百分比就回村（預設 20）')
    ap.add_argument('--note', default='', help='寫進經驗紀錄的備註，例：2倍智慧果中')
    ap.add_argument('--no-check', action='store_true', help='不要在異常時自動檢查外掛勾選（healthcheck.py）')
    ap.add_argument('--check-every', type=int, default=20, help='兩次異常檢查至少隔幾分鐘（預設 20）')
    ap.add_argument('--exp-slow', type=float, default=1.6, help='升級時間超過預期的幾倍算經驗速度異常（預設 1.6）')
    ap.add_argument('--exp-per-min', type=float, default=0, help='基準每分鐘經驗；沒給就用同一張地圖最近 5 次升級的中位數')
    ap.add_argument('--battle-max', type=int, default=120, help='連續幾秒都在戰鬥中算戰鬥過久（預設 120）')
    ap.add_argument('--end-level', type=int, default=END_LEVEL, help='練到幾級結束（預設 131；漆黑洞窟(五轉)要 140）')
    ap.add_argument('--stop-at-end', action='store_true', help=f'隊長達 {END_LEVEL} 級就結束監測（預設改成留在練功點繼續補血 / 檢查）')
    ap.add_argument('--dry-run', action='store_true', help='只印會做什麼，不傳送')
    a = ap.parse_args()
    globals()['END_LEVEL'] = a.end_level      # 131（預設）/ 140（五轉）；使用者 2026-10-14
    global ASS_AFTER_ARRIVE
    ASS_AFTER_ARRIVE = not a.no_ass
    if layout.current() not in layout.SUPPORTED:
        log(f'不支援 {layout.current()} 版面，見 ui/layout-1920x1017.md')
        return 2
    done = a.at          # 已經換過去的練功點
    # 經驗紀錄：每次確認讀數後存一行（時間, 視窗, 等級, 地圖, 備註），之後用 Exp 表算每分鐘經驗；notes/ 不進 git
    log_path = Path(__file__).resolve().parents[2] / 'notes' / f'exp-log-{winenv.resolve_client() or "game"}.csv'
    log_path.parent.mkdir(exist_ok=True)
    if not log_path.exists():
        log_path.write_text('time,level,pos,note\n', encoding='utf-8')
    good_level = None    # 已確認的等級（只升不降；轉生數變了就重新算）
    good_trans = None
    pending = None       # 上一次讀到、等第二次確認的等級
    bad = 0
    reached_end = False
    stages = STAGES if a.label else REAL_STAGES
    exp_table = load_exp_table()
    track = {'level': None, 'map': None, 't0': time.time()}   # 目前等級從什麼時候開始、在哪張地圖
    rates: dict[str, list[float]] = {}                        # 地圖 → 最近幾次升級的每分鐘經驗
    want_check: str | None = None                             # 觸發了、等戰鬥結束 + HUD 回來再檢查的原因
    last_check = 0.0
    last_panel = 0.0
    busy_since: float | None = None
    log('監測中：' + '、'.join(f'{n} 級→{name}' for n, name in reversed(stages)) + '（Ctrl+C 結束）')
    last_beat = time.time()
    while True:
        pausegate.wait(log)                      # 每輪開頭的安全點（不會停在補血 / 換點中途）
        s = stat()
        if time.time() - last_beat >= HEARTBEAT_S:
            # 長時間同一等級 / 同一地圖（例：地雷區一練 10 小時）不會有任何事件輸出，看門狗會把沉默當卡住 → 定期印一行心跳
            last_beat = time.time()
            eta = ''
            if good_level and good_level < END_LEVEL:
                cur_map = track.get('map')
                rate = median(rates[cur_map]) if cur_map and rates.get(cur_map) and good_level >= 121 else 0
                m = eta_minutes(good_level, END_LEVEL, exp_table, (time.time() - track['t0']) / 60, rate)
                if m is not None:
                    fin = time.strftime('%m-%d %H:%M', time.localtime(time.time() + m * 60))
                    eta = f'；到 {END_LEVEL} 級約還要 {m / 60:.1f} 小時（預計 {fin}，預估值）'
            log(f'練功中（心跳）：{s.get("level") or "?"} 地圖 {s.get("pos") or "?"}{eta}')
            if not a.dry_run and good_level and good_level < END_LEVEL:
                ensure_encounter('心跳', plugin=False)
        lv = parse_level(s)
        if lv is None and '最小化' in str(s.get('error') or ''):
            # Unity 最小化不繪製（戰鬥也停）：gui info 會用 SW_SHOWNOACTIVATE 還原，不搶焦點；還原後馬上重讀
            log('遊戲視窗最小化，還原')
            heal.gui('info')
            time.sleep(2)
            s = stat()
            lv = parse_level(s)
        # 戰鬥過久：每次取樣看頭上 VS 牌（快速戰鬥一場幾秒，取樣到的機率很低；連續取樣都在戰鬥就是異常）
        in_battle = not heal.gui('seq', f'waitpix 0 {heal.SIG_NO_BATTLE} 40').startswith('ok')
        if in_battle:
            busy_since = busy_since or time.time()
            if time.time() - busy_since >= a.battle_max and not want_check:
                want_check = f'戰鬥過久（連續 {int(time.time() - busy_since)} 秒在戰鬥中）'
        else:
            busy_since = None
        near_end = good_level is not None and good_level >= PANEL_FROM
        if (a.stop_at_end and near_end and not in_battle and not a.dry_run
                and time.time() - last_panel >= PANEL_EVERY_S):
            # 接近 131 後 HUD 的 OCR 會漏位數、讀不準 131（使用者 2026-10-13）→ 不靠 HUD 判斷結束，改定期開人物資訊面板讀 5 人等級
            last_panel = time.time()
            import fullrun1920 as fr
            plv = fr.read_team_levels_retry()
            log(f'人物資訊面板：5 人等級 {plv}（HUD：{s.get("level")}，目標 >= {END_LEVEL}）')
            if fr.levels_ready(plv, END_LEVEL):
                log(f'5 人都 >= {END_LEVEL} 級，結束監測')
                progress.add(f'levelwatch 人物面板確認 5 人都 >= {END_LEVEL} 級，結束監測')
                return 0
            if any(v is not None for v in plv):
                bad = 0                   # 面板開得起來 = 沒有驗證視窗擋著，HUD 讀不到只是 OCR 問題
            ensure_encounter('人物資訊面板檢查後')
        if lv is None:
            bad += 1
            bad_max = 15 if near_end and a.stop_at_end else 5      # 接近 131 時多給幾次，讓定期面板檢查有機會先確認
            log(f'讀不到等級（{bad}/{bad_max}）：{s.get("error") or s.get("level")}')
            if bad >= bad_max:
                log('連續讀不到 HUD，可能有驗證視窗或對話框，停止監測，請人看畫面')
                return 1
        else:
            bad = 0
            trans, level = lv
            # OCR 會漏讀位數（112 讀成 2）：等級只升不降；比已確認的等級低就不信（2026-10-10 112 級被讀成 2 級傳錯地圖）
            # 另外要連續兩次讀到同一個數字才採信
            if good_level is not None and good_trans == trans and level < good_level:
                log(f'讀到 {level} 級，比已確認的 {good_level} 級低，視為 OCR 誤讀，略過')
                time.sleep(a.every)
                continue
            if good_level is None and not first_read_ok(s):
                # 第一次確認：隊長與寵物等級要讀到且一致才採信，否則只觀察不傳送（見 first_read_ok）
                log(f'啟動後第一次確認：隊長 {s.get("level")} / 寵物 {s.get("petLevel")} 讀不到隊長或兩者不一致，先觀察不傳送')
                pending = None
                time.sleep(a.every)
                continue
            if level != pending:
                pending = level
                time.sleep(3)
                continue
            good_level, good_trans = level, trans
            now = time.time()
            m_map = re.match(r'(\d+):', str(s.get('pos') or ''))
            cur_map = m_map.group(1) if m_map else '?'
            if level != track['level']:
                # 升了一級（上一級是從頭看到尾、同一張地圖）→ 記下這一級的每分鐘經驗當基準
                if (track['level'] is not None and level == track['level'] + 1 and track['map'] == cur_map
                        and exp_table.get(track['level']) and now - track['t0'] >= 60 and track.get('clean')):
                    rates.setdefault(cur_map, []).append(exp_table[track['level']] / ((now - track['t0']) / 60))
                    rates[cur_map] = rates[cur_map][-5:]
                track.update(level=level, map=cur_map, t0=now, clean=track['level'] is not None)
            else:
                base = a.exp_per_min or (median(rates[cur_map]) if rates.get(cur_map) else 0)
                need = exp_table.get(level)
                elapsed = (now - track['t0']) / 60
                if base and need and elapsed >= 10 and elapsed > need / base * a.exp_slow and not want_check:
                    want_check = f'經驗速度異常（{level} 級已 {elapsed:.0f} 分，預期約 {need / base:.0f} 分）'
            with log_path.open('a', encoding='utf-8') as fh:
                fh.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")},{level},{s.get("pos") or ""},{a.note}\n')
            if a.verbose:
                log(f'{trans}轉{level}級 地圖 {s.get("pos")}')
            spot = target_for(level, stages)
            if level >= END_LEVEL and not reached_end:
                reached_end = True
                if a.stop_at_end:
                    log(f'隊長已達 {level} 級，結束監測。注意：只看了隊長，5 個角色都要 {END_LEVEL} 級才算完成，請再開「切換」面板確認其他 4 人')
                    progress.add(f'levelwatch 隊長已達 {level} 級，結束監測（5 個角色要逐一確認）')
                    return 0
                log(f'隊長已達 {level} 級；繼續留在 {done or spot} 練功並維持補血 / 組隊 / 外掛檢查（--stop-at-end 才會結束）。5 個角色都要 {END_LEVEL} 級才算完成，請確認其他 4 人')
                progress.add(f'levelwatch 隊長已達 {level} 級，繼續留在練功點（5 個角色要逐一確認）')
            if done is None and spot:
                # 重啟時人已經在該練功點的地圖上就不用再傳送
                m = re.match(r'(\d+):', str(s.get('pos') or ''))
                if m and int(m.group(1)) == heal.SPOTS[spot][2]:
                    done = spot
                    log(f'已在 {spot}，不重複傳送')
            if spot and spot != done:
                if not a.no_team and not ensure_team(a.dry_run):
                    log('隊伍沒組好，停止監測，請人工處理（有人離線 / 地圖禁止組隊？）')
                    return 1
                if not a.no_ass:
                    ensure_ass(a.dry_run)
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
        if want_check and not a.no_check and not a.dry_run and lv is not None and not in_battle                 and time.time() - last_check >= a.check_every * 60:
            last_check = time.time()
            reason, want_check = want_check, None
            log(f'觸發異常檢查：{reason}')
            healthcheck.run(reason)
            busy_since = None
        if not a.no_heal and not a.dry_run and done and lv is not None and heal.low(s, a.hp, a.mp):
            time.sleep(3)
            s2 = stat()
            if heal.low(s2, a.hp, a.mp):
                log(f'血 / 魔太低（HP {s2.get("hpPct")}%，MP {s2.get("mpPct")}%），回村補血後回 {done}')
                try:
                    t_heal = time.time()
                    with (log_path.parent / f'heal-log-{winenv.resolve_client() or "game"}.csv').open('a', encoding='utf-8') as hf:
                        hf.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")},{level},{done},HP{s2.get("hpPct")}%/MP{s2.get("mpPct")}%\n')
                    heal.heal_trip(done)
                    if not a.no_team and not ensure_team():
                        log('補血回來後隊伍不完整，停止監測，請人工處理')
                        return 1
                    if not a.no_ass:
                        ensure_ass()
                except RuntimeError as e:
                    log(f'補血流程失敗：{e}；停止監測，請人工處理')
                    return 1
        time.sleep(a.every)


if __name__ == '__main__':
    import notifyhalt
    rc = main()
    if rc:
        notifyhalt.alert(f'levelwatch 退出碼 {rc}（見上方訊息）')
    sys.exit(rc)
