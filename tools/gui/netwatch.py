#!/usr/bin/env python3
"""網路異常自動重連（只用標準函式庫）。遊戲跳出「提示：網路異常，是否重連?」時點「確定」。

實測（2026-10-10）：點確定後遊戲**直接回到登入畫面**（帳號 / 密碼欄由遊戲自動帶入、登錄 / 註冊鈕），不會自動重連。
使用者授權（2026-10-10，AGENTS.md 鐵則 2 的例外，只限這樣）：登入畫面**只點「登錄」**（用遊戲自動帶入的帳密），
之後處理「選擇角色 → 一鍵全登」→ 載入 → 進遊戲 → 檢查隊伍 / 原地遇敵。絕不輸入 / 修改 / 清除帳密欄、不點鑰匙 / 註冊、
不讀 savepwd.txt 或登錄檔、不把帳號寫進任何 log。帳密欄空的 / 登錄後出現提示視窗 / 連續 3 次登錄失敗 / 看不懂的畫面 → halt 停手通知使用者。

  import netwatch
  r = netwatch.guard('quest')            # 腳本迴圈每輪呼叫；要停手時直接 sys.exit(10 / 11)，否則回傳 dict
  r = netwatch.check_and_reconnect()     # 不 exit 的版本，回傳 {'status': ...}
status：ok（沒事）/ reconnected（重連 / 重新登錄成功，已恢復）/ halt（要人類）/ fatal（連續失敗 3 次）
命令列：
  python tools/gui/netwatch.py --once                 檢查一次
  python tools/gui/netwatch.py --watch [--interval 10]  常駐（沒有其他腳本在跑、只是掛機時用）
  python tools/gui/netwatch.py --status                印目前 halt / 失敗計數
退出碼：0 正常、10 需要人類登入（halt）、11 連續重連失敗、2 版面不支援。
狀態檔（tools/.cache/，不進 git）：netwatch.halt（存在 = 已停手，等人類登入；HUD 回來後自動刪除）、
netwatch.json（連續失敗計數）、netwatch.act.lock（動作鎖：同時只有一支腳本在處理重連，不會互相亂點）、netwatch.lock（--watch 單例）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actlog  # noqa: E402
import errlog  # noqa: E402
import layout  # noqa: E402
import screen_sigs  # noqa: E402
import winenv  # noqa: E402
from walk import gui, log  # noqa: E402

PS_TIMEOUT = 40                      # 單次 PowerShell 呼叫上限（秒）；逾時當讀取失敗
READ_FAIL_MAX = 5                    # 登入畫面連續 N 輪讀不到帳密欄 / 遊戲畫面 → halt

CACHE = Path(__file__).resolve().parents[1] / '.cache'
HALT = CACHE / 'netwatch.halt'
STATE = CACHE / 'netwatch.json'
ACT_LOCK = CACHE / 'netwatch.act.lock'
WATCH_LOCK = CACHE / 'netwatch.lock'

EXIT_HALT = 10
EXIT_FATAL = 11
MAX_FAILS = 3
TOL = screen_sigs.NET_TOL

# ---- 特徵（2880×1659 版面，截圖座標；2026-10-10 實測）----
CONFIRM = (715, 557)                 # 提示視窗唯一的藍色「確定」
# 米色「提示」視窗：左右 + 按鈕列兩側是米色（兩顆鈕的對話框兩側會是藍 / 米，所以左右 600 / 830 也要米色）、中間按鈕是藍
SIG_DIALOG = screen_sigs.sig_str(screen_sigs.NET_DIALOG)
# 登入畫面：登錄鈕橘、註冊鈕藍、面板米色
SIG_LOGIN = screen_sigs.sig_str(screen_sigs.NET_LOGIN)
MSG_BOX = (585, 370, 260, 40)        # 提示視窗訊息文字（OCR 輔助確認，白字深邊）
MSG_KEYS = ('網', '路', '異', '重', '連')
LOGIN_BOX = (460, 380, 520, 130)     # 登入畫面「帳號 / 密碼」標籤（只讀標籤，不讀欄位內容）
SWITCH_BTN = (763, 760)
# 登錄流程（2026-10-10 實測）
LOGIN_BTN = (590, 585)               # 登入畫面橘色「登錄」（唯一允許在登入畫面點的東西）
ACCT_BOX = (700, 900, 400, 425)      # 帳號欄 x0,x1,y0,y1（只數深色像素判斷「非空」，不讀內容）
PWD_BOX = (690, 880, 484, 502)       # 密碼欄（星號）
ALL_LOGIN_BTN = (740, 640)           # 選擇角色面板「一鍵全登」
# 選擇角色面板：全登鈕橘、面板米色、右上紅 X、角色列棕
SIG_CHARSEL = screen_sigs.sig_str(screen_sigs.NET_CHARSEL)
SWITCH_ALL_BTN = (716, 578)          # 切換角色面板「全部登錄」
QUICK_TEAM_SEQ = ('click 520 578; wait 500; click 549 320; wait 400; click 549 520; wait 150; click 682 520; wait 150; '
                  'click 815 520; wait 150; click 948 520; wait 300; click 720 665; wait 1500')
LOGIN_TIMEOUT = 120                  # 登錄後等進遊戲的上限（秒）
CARDS_BOX = (560, 280, 450, 230)     # 切換角色面板的角色卡片（讀「單人 / 隊長 / 隊員」）


def _scale_sig(sig: str) -> str:
    """1920×1017 版面：截圖座標 × 2/3（顏色不變）。未實測，只當備援"""
    if layout.resolve() != '1920x1017':
        return sig
    out = []
    for p in sig.split('/'):
        v = p.split(',')
        out.append(','.join([str(round(int(v[0]) * 2 / 3)), str(round(int(v[1]) * 2 / 3))] + v[2:]))
    return '/'.join(out)


# ---- 讀取失敗追蹤（errlog 限頻：同一段連續失敗只記一筆，恢復後補 fix；psa-hud 會顯示 errlog，不能洗版）----
_fail_id: list = []                  # 目前這段連續失敗對應的 errlog id（空 = 沒在失敗中）


def _read_failed(what: str) -> None:
    if not _fail_id:
        _fail_id.append(errlog.add(f'netwatch 讀不到遊戲畫面（{what}：PowerShell 失敗 / 截圖失敗 / 輸出異常），暫不判斷、不點擊',
                                   source='netwatch'))


def _read_ok() -> None:
    if _fail_id:
        i = _fail_id.pop()
        if i is not None:
            errlog.fix(i, '已恢復（下一次讀取成功）')


def _ps(*args: str) -> tuple[int, str]:
    """直接呼叫 gui.ps1，回 (returncode, 輸出)。逾時 / 無法執行 → (-1, '')。
    （walk.gui 只回字串、丟掉 returncode，這裡才分得出 PS 失敗與「沒符合」）"""
    try:
        r = winenv.run_ps('gui.ps1', *args, timeout=PS_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return -1, ''
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def _match(sig: str) -> bool | None:
    """用 waitpix 單次檢查（逾時 0）。三態：True = 全部符合；False = 確定不符合（timeout）；
    None = 讀不到（rc≠0、空輸出、pwfail、其他）— 已重試一次。呼叫端 None 時不點、不宣告成功。"""
    for _ in range(2):
        rc, out = _ps('seq', f'waitpix 0 {_scale_sig(sig)} {TOL}')
        lines = out.splitlines()
        head = lines[-1].split()[0] if rc == 0 and lines and lines[-1].split() else ''
        if head == 'ok':
            _read_ok()
            return True
        if head == 'timeout':
            _read_ok()
            return False
    _read_failed('waitpix')
    return None


def _ocr(box, *opts) -> list:
    r = winenv.run_ps('ocr.ps1', *map(str, box), *map(str, opts))
    try:
        d = json.loads((r.stdout.strip().splitlines() or [''])[-1])
    except ValueError:
        return []
    return [l['text'] for l in d.get('lines', [])] if d.get('ok') else []


def hud_ok() -> bool:
    """主畫面 HUD 讀得到（stat.ps1 ok）= 已在遊戲裡"""
    from walk import stat
    s = stat()
    # stat.ps1 在登入畫面也回 ok:true（全空欄位），所以要求讀得到地圖座標或等級，且不是登入畫面
    # _match 讀不到（None）時不確定是不是登入畫面 → 當作 HUD 沒到，不宣告成功
    return bool(s.get('ok') and (s.get('pos') or s.get('level'))) and _match(SIG_LOGIN) is False


def detect() -> str | None:
    """'dialog'（網路異常提示）/ 'login'（登入畫面）/ None。不點任何東西。
    提示視窗：像素特徵符合 → OCR 訊息若讀到文字卻不含 網路異常 相關字，就當成別種提示（不亂點）；OCR 讀不到則信任像素。"""
    if _match(SIG_DIALOG) is True:          # None（讀不到）當「不是對話框」往下判斷
        txt = ''.join(_ocr(MSG_BOX, '-Light', 200, '-Zooms', '2,3'))
        if txt and not any(k in txt for k in MSG_KEYS):
            log(f'netwatch：像素像提示視窗，但訊息是「{txt}」不是網路異常，不處理', act=False)
            return None
        return 'dialog'
    if _match(SIG_LOGIN) is True:
        return 'login'
    return None


# ---------------- 狀態檔 ----------------
def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'fails': 0}


def _save(d: dict) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d), encoding='utf-8')
    except OSError:
        pass


def _take(lock: Path, stale: int) -> bool:
    """O_EXCL 建鎖檔；超過 stale 秒的舊鎖直接接手"""
    CACHE.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f'{os.getpid()} {int(time.time())}'.encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink()
                    continue
            except OSError:
                pass
            return False
    return False


def _release(lock: Path) -> None:
    try:
        lock.unlink()
    except OSError:
        pass


def _dark_count(box) -> int | None:
    """欄位框內的深棕色（文字 / 星號）像素數；只看有沒有字，不讀內容。
    PS 失敗或回傳點數少於預期（讀不完整）→ 重試一次，仍失敗回 None（不是 0，0 代表「確定是空的」）"""
    x0, x1, y0, y1 = box
    coords = [(x, y) for y in range(y0, y1, 3) for x in range(x0, x1, 3)]
    pts = ' '.join(f'{x},{y}' for x, y in coords)
    for _ in range(2):
        rc, out = _ps('pixel', pts)
        vals = []
        for p in out.split():
            try:
                r, g, _b = (int(v) for v in p.split(','))
            except ValueError:
                continue
            vals.append((r, g))
        if rc == 0 and len(vals) == len(coords):
            _read_ok()
            return sum(1 for r, g in vals if r < 130 and g < 90)
    _read_failed('pixel')
    return None


def login_fields_filled() -> bool | None:
    """帳號、密碼欄都有內容（遊戲自動帶入）。True = 都有；False = 確定有一欄是空的（絕不自己填）；
    None = 讀不到（不能當成「空」halt，由 relogin 重試、有次數上限）"""
    a = _dark_count(ACCT_BOX)
    if a is None:
        return None
    if a < 10:
        return False
    p = _dark_count(PWD_BOX)
    if p is None:
        return None
    return p >= 10


def halt(reason: str, src: str) -> dict:
    """停手：寫 halt 檔、errlog、大聲警告。絕不輸入帳密"""
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        HALT.write_text(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {reason}\n', encoding='utf-8')
    except OSError:
        pass
    errlog.add(f'斷線重登停手：{reason}（{src}）', source='netwatch')
    actlog.add('netwatch', f'HALT {reason}')
    bar = '!' * 64
    print(f'\n{bar}\n!!! 遊戲回到登入畫面 / 需要人類登入：{reason}\n'
          f'!!! 所有自動化已停止（退出碼 {EXIT_HALT}）。請使用者自己登入並進入遊戲，不要讓 AI 輸入帳密（鐵則 2）。\n'
          f'!!! 人類登入後恢復：確認 5 人同隊（/psa-quick-team）、原地遇敵開著，再重新啟動腳本。\n{bar}\n', flush=True)
    return {'status': 'halt', 'reason': reason}


# ---------------- 恢復 ----------------
CARD_BADGES = [(450, 272, 70, 32), (730, 272, 70, 32), (450, 357, 70, 32), (730, 357, 70, 32), (450, 442, 70, 32)]


def team_report() -> dict:
    """開切換角色面板存圖，逐張卡片 OCR 隊伍標籤（整個區域一起讀很不準，單一標籤才準）：
    長 = 隊長、員 = 隊員、單 / 人 = 單人，讀不出來算 unknown。只回報，不組隊。"""
    shot = CACHE / 'netwatch_team.png'
    gui('seq', f'key {{ESC}}; wait 300; click {SWITCH_BTN[0]} {SWITCH_BTN[1]}; wait 900; shot {shot}')
    n = {'leader': 0, 'member': 0, 'solo': 0, 'unknown': 0}
    for box in CARD_BADGES:
        txt = ''.join(_ocr(box, '-Zooms', '2,3,4'))
        if '長' in txt:
            n['leader'] += 1
        elif '員' in txt:
            n['member'] += 1
        elif '單' in txt or '人' in txt:
            n['solo'] += 1
        else:
            n['unknown'] += 1
    gui('key', '{ESC}')
    n['shot'] = str(shot)
    return n


def fix_team(t: dict) -> dict:
    """隊伍不全：先「全部登錄」讓離線角色上線；若全員單人再快速組隊（/psa-quick-team 流程）。回傳新的 team_report"""
    log('netwatch：隊伍不全，點「全部登錄」並視情況快速組隊')
    gui('seq', f'key {{ESC}}; wait 300; click {SWITCH_BTN[0]} {SWITCH_BTN[1]}; wait 900; '
               f'click {SWITCH_ALL_BTN[0]} {SWITCH_ALL_BTN[1]}; wait 4000; key {{ESC}}', note='全部登錄')
    t = team_report()
    if t['solo'] >= 4 and t['leader'] + t['member'] == 0:
        gui('seq', f'key {{ESC}}; wait 300; click {SWITCH_BTN[0]} {SWITCH_BTN[1]}; wait 900; {QUICK_TEAM_SEQ}; key {{ESC}}',
            note='快速組隊')
        t = team_report()
    return t


def recover(src: str, encounter: bool = True, team: bool = True) -> dict:
    """人類登入 / 重連完成後：確認原地遇敵、檢查隊伍。回傳摘要（也會 log）"""
    info: dict = {}
    if encounter:
        try:
            import heal
            if not heal.encounter_on():
                log('netwatch：原地遇敵沒開，重新開啟')
                heal.set_encounter(True)
                info['encounter'] = 'reopened'
            else:
                info['encounter'] = 'on'
        except Exception as e:      # 不讓恢復流程拖垮呼叫端
            info['encounter'] = f'error {e}'
    if team:
        try:
            info['team'] = team_report()
            t = info['team']
            log(f'netwatch：隊伍檢查 隊長 {t["leader"]} / 隊員 {t["member"]} / 單人 {t["solo"]} / 讀不出 {t["unknown"]}（{t["shot"]}）')
            if t['solo']:
                t = info['team'] = fix_team(t)
            if t['solo'] or t['leader'] + t['member'] + t['unknown'] < 5:
                print('!!! 隊伍可能散了：請看截圖確認，不同隊就照 /psa-quick-team 組回（組隊前先確認真的散了）', flush=True)
        except Exception as e:
            info['team'] = f'error {e}'
    return info


def relogin(src: str) -> dict:
    """登入畫面 → 檢查帳密欄有內容 → 點「登錄」→ 處理選擇角色 / 載入 → 回到遊戲 → recover。
    失敗規則：欄位空 / 出現提示視窗（密碼錯誤、封停、維護、驗證）/ 看不懂的畫面逾時 / 連續 3 次 → halt（不重試）"""
    if not _take(ACT_LOCK, 300):
        return {'status': 'ok', 'busy': True}
    try:
        st = _load()
        if st.get('login_fails', 0) >= MAX_FAILS:
            return halt(f'連續 {MAX_FAILS} 次登錄失敗', src) | {'status': 'fatal'}
        filled = login_fields_filled()
        if filled is None:
            # 讀取失敗：不點登錄、不以「欄位空」halt；下輪再試，連續 READ_FAIL_MAX 輪讀不到才 halt
            st['read_fails'] = st.get('read_fails', 0) + 1
            _save(st)
            if st['read_fails'] >= READ_FAIL_MAX:
                return halt(f'連續 {READ_FAIL_MAX} 輪讀不到帳密欄 / 遊戲畫面（不是欄位空）', src)
            log(f'netwatch：登入畫面讀不到帳密欄（{st["read_fails"]}/{READ_FAIL_MAX}），本輪不點登錄')
            return {'status': 'ok', 'failed': True}
        if st.get('read_fails'):
            st['read_fails'] = 0
            _save(st)
        if not filled:
            return halt('登入畫面的帳號 / 密碼欄是空的（遊戲沒自動帶入），不自己填', src)
        i = errlog.add('斷線回到登入畫面，自動按「登錄」重新登入（使用者授權）', source=src)
        log('netwatch：登入畫面，帳密欄已有內容 → 按登錄')
        gui('click', str(LOGIN_BTN[0]), str(LOGIN_BTN[1]), note='按登錄')
        deadline = time.time() + LOGIN_TIMEOUT
        picked = 0                       # 一鍵全登最多點 2 次
        t0 = time.time()
        while time.time() < deadline:
            time.sleep(2)
            if hud_ok():
                st['login_fails'] = 0
                st['fails'] = 0
                _save(st)
                _release(HALT)
                errlog.fix(i, '登錄 → 一鍵全登 → 進遊戲成功，已做恢復檢查（netwatch.relogin）')
                actlog.add('netwatch', '自動登錄成功')
                log(f'netwatch：登錄成功，{int(time.time() - t0)} 秒回到遊戲')
                time.sleep(2)
                return {'status': 'reconnected', 'relogin': True, 'recover': recover(src, True, True)}
            if _match(SIG_CHARSEL) is True:
                if picked >= 2:
                    break
                picked += 1
                log('netwatch：選擇角色面板 → 一鍵全登')
                gui('click', str(ALL_LOGIN_BTN[0]), str(ALL_LOGIN_BTN[1]), note='一鍵全登')
                continue
            if _match(SIG_DIALOG) is True:
                # 登錄後的提示視窗（密碼錯誤 / 封停 / 維護 / 驗證…）：不點、不重試
                return halt('登錄後出現提示視窗（可能是密碼錯誤 / 封停 / 維護 / 驗證），不處理', src)
        st['login_fails'] = st.get('login_fails', 0) + 1
        _save(st)
        errlog.fix(i, f'登錄後 {LOGIN_TIMEOUT} 秒沒進遊戲（失敗 {st["login_fails"]}/{MAX_FAILS}），停手')
        return halt(f'登錄後 {LOGIN_TIMEOUT} 秒沒進遊戲 / 畫面不明（第 {st["login_fails"]} 次）', src)
    finally:
        _release(ACT_LOCK)


# ---------------- 主流程 ----------------
def check_and_reconnect(shot=None, src: str = 'netwatch', encounter: bool = True, team: bool = True) -> dict:
    """檢查「網路異常」提示 / 登入畫面；有就處理。shot 參數保留相容（目前自己取樣，不用外部截圖）。
    回傳 {'status': 'ok'|'reconnected'|'halt'|'fatal', ...}；status 為 halt / fatal 時呼叫端必須停手。"""
    if HALT.exists():
        if hud_ok():                         # 人類已登入回來
            _release(HALT)
            _save({'fails': 0})
            log('netwatch：偵測到已重新登入（HUD 回來了），清除 halt，做恢復檢查')
            actlog.add('netwatch', '人類登入後恢復')
            return {'status': 'reconnected', 'relogin': True, 'recover': recover(src, encounter, team)}
        return {'status': 'halt', 'reason': '已停手等使用者處理（netwatch.halt 存在；處理完刪掉該檔）'}
    kind = detect()
    if kind is None:
        return {'status': 'ok'}
    if kind == 'login':
        return relogin(src)
    if not _take(ACT_LOCK, 180):
        return {'status': 'ok', 'busy': True}      # 別的腳本正在處理
    try:
        st = _load()
        i = errlog.add('網路斷線：遊戲跳出「網路異常，是否重連?」', source=src)
        log('netwatch：偵測到「網路異常，是否重連?」，點確定')
        gui('click', str(CONFIRM[0]), str(CONFIRM[1]), note='網路異常→確定')
        deadline = time.time() + 45
        while time.time() < deadline:
            time.sleep(2)
            if _match(SIG_LOGIN) is True:
                _release(ACT_LOCK)                  # relogin 自己會拿鎖
                return relogin(src)
            if hud_ok() and _match(SIG_DIALOG) is False:     # 讀不到（None）不宣告成功
                st['fails'] = 0
                _save(st)
                errlog.fix(i, '點確定後回到遊戲，已做恢復檢查（netwatch.py）')
                log('netwatch：重連成功，回到遊戲')
                return {'status': 'reconnected', 'recover': recover(src, encounter, team)}
            if _match(SIG_DIALOG) is True:
                gui('click', str(CONFIRM[0]), str(CONFIRM[1]), note='網路異常→確定（再按）')
        st['fails'] = st.get('fails', 0) + 1
        _save(st)
        log(f'netwatch：點確定後 45 秒沒回到遊戲（連續失敗 {st["fails"]}/{MAX_FAILS}）')
        if st['fails'] >= MAX_FAILS:
            halt(f'連續 {MAX_FAILS} 次重連失敗', src)
            return {'status': 'fatal', 'reason': f'連續 {MAX_FAILS} 次重連失敗'}
        return {'status': 'ok', 'failed': True}
    finally:
        _release(ACT_LOCK)


def guard(src: str, **kw) -> dict:
    """給腳本迴圈用：要停手（halt / fatal）就直接 sys.exit(10 / 11)（會跑 finally），重連成功回傳 dict（呼叫端依 'reconnected' 重設自己的狀態）"""
    r = check_and_reconnect(src=src, **kw)
    if r['status'] == 'halt':
        sys.exit(EXIT_HALT)
    if r['status'] == 'fatal':
        sys.exit(EXIT_FATAL)
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description='網路異常自動重連 / 登入畫面停手')
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--watch', action='store_true', help='常駐；沒有其他腳本在跑時用')
    ap.add_argument('--interval', type=int, default=10)
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--no-team', action='store_true', help='恢復時不檢查隊伍')
    ap.add_argument('--no-encounter', action='store_true', help='恢復時不管原地遇敵')
    a = ap.parse_args()
    if a.status:
        print('halt:', HALT.read_text(encoding='utf-8').strip() if HALT.exists() else '無', '| 狀態:', _load())
        return 0
    if layout.current() != '2880x1659':
        log(f'netwatch 只量過 2880×1659，目前 {layout.current()}')
        return 2
    kw = {'src': 'netwatch', 'team': not a.no_team, 'encounter': not a.no_encounter}
    if not a.watch:
        r = check_and_reconnect(**kw)
        print(json.dumps(r, ensure_ascii=False, default=str))
        return {'halt': EXIT_HALT, 'fatal': EXIT_FATAL}.get(r['status'], 0)
    if not _take(WATCH_LOCK, 120):
        log('已有另一支 netwatch --watch 在跑（tools/.cache/netwatch.lock）')
        return 3
    log(f'netwatch 常駐：每 {a.interval} 秒檢查網路異常提示（其他腳本在跑時它們自己會檢查，這支只在單獨掛機時用）')
    try:
        while True:
            try:
                WATCH_LOCK.touch()
            except OSError:
                pass
            r = check_and_reconnect(**kw)
            if r['status'] in ('halt', 'fatal'):
                return EXIT_HALT if r['status'] == 'halt' else EXIT_FATAL   # 人類登入後重新啟動即可（halt 檔會自動清）
            time.sleep(a.interval)
    except KeyboardInterrupt:
        log('netwatch Ctrl+C，結束')
    finally:
        _release(WATCH_LOCK)
    return 0


if __name__ == '__main__':
    sys.exit(main())
