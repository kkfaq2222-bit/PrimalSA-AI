#!/usr/bin/env python3
"""state.json 的讀寫 API（只用標準函式庫；watch.py 是唯一寫入者，其他人只讀）。

格式見 notes/plan-watch-state.md §2（v1）。重點：
- 時間是 epoch 秒，只給「同平台」讀者參考；跨平台不拿對方的 ts 跟自己時鐘比（用 (token, seq) 判活）。
- **state 只用來顯示 / 決定要不要再看，不能當點擊依據；idle 也不代表沒有驗證視窗**。所以讀取 API 都強制帶 max_age。

  import watchstate
  st = watchstate.fresh(2.0)                # 整份 state（年齡在門檻內且 watcher 還活著），否則 None
  sc = watchstate.screen(1.5, after=t0)     # screen 區段；資料太舊 / 早於 after 回 None
  live = watchstate.Liveness(); live.update(st); live.stalled(10)   # 長期持有的讀者（HUD）用
"""
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'tools' / '.cache'
STATE_FILE = CACHE / 'state.json'
LOCK_FILE = CACHE / 'watch.lock'
STOP_FILE = CACHE / 'watch.stop'
HUD_CFG = CACHE / 'psa-hud.json'
BATTLE_LOCK = CACHE / 'battle.lock'
HALT_FILE = CACHE / 'netwatch.halt'
ACK_FILE = CACHE / 'watch.ack'
QUEST_LOG = ROOT / 'notes' / 'quest-events.log'
VERSION = 1

# 「內容有沒有變」的比較排除這些鍵（任何深度）：時間戳、序號、每輪都會變的量測值、雜訊值。
# gold = 畫面中金黃點個數（classify 的雜訊，每輪都會抖）；不在計畫 §2 的排除清單裡，是實作時加的。
EXCLUDE_KEYS = frozenset({'ts', 'seq', 'cycle_ms', 'ocr_ms', 'age_s', 'hb_p95_s', 'stats_ts', 'cpu_pct', 'gold'})


def _platform() -> str:
    import winenv
    return winenv.platform_kind()


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in EXCLUDE_KEYS}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def content_key(d: dict) -> str:
    """排除 EXCLUDE_KEYS 後的穩定字串；兩次相同 = 內容沒變（不用寫檔，只需要心跳）"""
    return json.dumps(_strip(d), sort_keys=True, ensure_ascii=False, separators=(',', ':'))


# ---------------------------------------------------------------- 讀
def read(path=None, retries: int = 3, sleep=time.sleep) -> dict | None:
    """解析失敗（寫到一半 / 撞上 os.replace）重試 3 次（每次 20 ms）；檔案不存在 / v 主版本不是 1 → None。不認得的鍵一律忽略"""
    path = Path(path or STATE_FILE)
    for i in range(retries + 1):
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            if i < retries:
                sleep(0.02)
            continue
        if isinstance(d, dict) and d.get('v') == VERSION:
            return d
        return None
    return None


def age(state: dict, section: str = 'screen', now: float | None = None, platform: str | None = None) -> float | None:
    """某區段資料的年齡（秒）：同平台 = 寫入當下的 age_s + (現在 − state.ts)；不同平台 / 讀不到 = None（呼叫端自行改用 Liveness）"""
    now = time.time() if now is None else now
    w = state.get('watcher') or {}
    if (platform or _platform()) != w.get('platform') or not isinstance(state.get('ts'), (int, float)):
        return None
    sec = state.get(section) or {}
    base = sec.get('age_s') if isinstance(sec.get('age_s'), (int, float)) else 0.0
    return base + max(0.0, now - state['ts'])


class Liveness:
    """長期持有的讀者用：記「(token, seq) 上次變化的本地 monotonic 時間」。存活 = (token, seq) 在門檻內有變，不看 ts（不怕時鐘漂移 / 跨平台）"""

    def __init__(self, mono=time.monotonic):
        self._mono = mono
        self.key = None
        self.changed_at = mono()

    def update(self, state: dict | None) -> bool:
        """傳入剛讀到的 state（或 None）。回傳 (token, seq) 是否變了"""
        if not state:
            return False
        w = state.get('watcher') or {}
        k = (w.get('token'), state.get('seq'))
        if k != self.key:
            self.key = k
            self.changed_at = self._mono()
            return True
        return False

    def stalled(self, threshold: float) -> bool:
        return self._mono() - self.changed_at > threshold

    def age(self, state: dict, section: str = 'screen') -> float:
        """跨平台安全的年齡：寫入當下的 age_s + 本地第一次看到這個 (token, seq) 起經過的時間"""
        sec = state.get(section) or {}
        base = sec.get('age_s') if isinstance(sec.get('age_s'), (int, float)) else 0.0
        return base + (self._mono() - self.changed_at)


def fresh(max_age: float = 2.0, path=None, wait: float = 2.5, now=time.time, sleep=time.sleep, platform: str | None = None) -> dict | None:
    """一次性讀者（watch.py --get）。同平台：state.ts 在 max_age 內且 watcher.running → 回 state。
    不同平台（不能比時鐘）：最多等 wait 秒看 (token, seq) 有沒有前進，前進了才回。
    注意：心跳是 1 s 一次（內容沒變也寫），所以 max_age < 1.5 時有可能讀到「剛好超過」而回 None；
    max_age 預設 2 s 涵蓋一個心跳週期 + 一輪讀取。"""
    st = read(path, sleep=sleep)
    if not st:
        return None
    w = st.get('watcher') or {}
    if not w.get('running'):
        return None
    if (platform or _platform()) == w.get('platform'):
        ts = st.get('ts')
        return st if isinstance(ts, (int, float)) and now() - ts <= max_age else None
    k0 = (w.get('token'), st.get('seq'))
    t_end = now() + wait
    while now() < t_end:
        sleep(0.1)
        s2 = read(path, sleep=sleep)
        if s2 and s2.get('watcher', {}).get('running') and (s2['watcher'].get('token'), s2.get('seq')) != k0:
            return s2
    return None


def screen(max_age: float = 1.5, after: float | None = None, path=None, now=time.time, sleep=time.sleep, platform: str | None = None) -> dict | None:
    """screen 區段。資料年齡 > max_age，或（同平台時）screen.ts < after → None。
    after = 呼叫端自己做完某個動作的時間（例：點擊後要等「之後」的畫面）；跨平台讀者拿不到可比的 ts，一律回 None。
    注意畫面穩定時 state.ts 只每 1 s 更新（心跳），age 以 state.ts + age_s 算，所以 max_age 太小會常拿不到。"""
    st = read(path, sleep=sleep)
    if not st or not (st.get('watcher') or {}).get('running'):
        return None
    a = age(st, 'screen', now(), platform)
    sc = st.get('screen')
    if a is None or not isinstance(sc, dict) or a > max_age:
        return None
    if after is not None and not (isinstance(sc.get('ts'), (int, float)) and sc['ts'] >= after):
        return None
    return sc


def hud_field(name: str, max_age: float = 5.0, path=None, now=time.time, platform: str | None = None):
    """hud 區段的某欄位值（{v, ts} 取 v）；欄位太舊 / 沒有 / watcher 不在 → None（第 3 階段才有資料）"""
    st = read(path)
    if not st or not (st.get('watcher') or {}).get('running'):
        return None
    f = (st.get('hud') or {}).get(name)
    if isinstance(f, dict) and isinstance(f.get('ts'), (int, float)) and (platform or _platform()) == st['watcher'].get('platform') \
            and now() - f['ts'] <= max_age:
        return f.get('v')
    return None


# ---------------------------------------------------------------- 寫（只有 watch.py 用）
def write(d: dict, token: str, path=None, retries: int = 5, sleep=time.sleep) -> bool:
    """原子寫：暫存檔名帶 token（不同實例不互踩）→ os.replace。Windows 撞上讀者開檔會 PermissionError：重試 5×10 ms，失敗回 False（跳過這輪）"""
    path = Path(path or STATE_FILE)
    tmp = path.with_name(f'{path.name}.{token}.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    except OSError:
        return False
    for i in range(retries):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            sleep(0.01)
        except OSError:
            break
    try:
        tmp.unlink()
    except OSError:
        pass
    return False


def peek_battle_lock(path=None) -> dict | None:
    """唯讀看 battle.lock → {pid, start, note}；**不呼叫 battleguard.locked()、不判 pid 活死、不刪檔**
    （locked() 會刪死鎖，跨平台 pid 又不可信；這裡只是把鎖檔內容轉給讀者參考）"""
    try:
        d = json.loads(Path(path or BATTLE_LOCK).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get('pid'), int):
        return None
    return {'pid': d['pid'], 'start': d.get('start'), 'note': d.get('note', '')}


# ---------------------------------------------------------------- 消費端：疑似驗證視窗時暫停（heal --watch / petwatch）
def verify_suspect(max_age: float = 5.0, path=None, now=time.time, sleep=time.sleep, platform: str | None = None):
    """True = watch 標了疑似驗證視窗（flags.verify_suspect 或 alerts 有 kind=verify / unknown_long）；False = 沒標；
    None = state 不可用（watch 沒跑 / 太舊）。注意「False」不代表沒有驗證視窗（watch 只認得有限幾種畫面）"""
    st = fresh(max_age, path=path, now=now, sleep=sleep, platform=platform)
    if not st:
        return None
    fl = st.get('flags') or {}
    kinds = {a.get('kind') for a in (st.get('alerts') or []) if isinstance(a, dict)}
    return bool(fl.get('verify_suspect')) or bool(kinds & {'verify', 'unknown_long'})


class VerifyGuard:
    """長程序（heal --watch / petwatch）每輪呼叫 check()：疑似驗證視窗 → 暫停（不動作、印警告）直到解除；
    暫停超過 limit_s（預設 10 分鐘，使用者 2026-10-10 同意）→ 寫 errlog、check() 回 'timeout'，呼叫端要結束（不自動恢復）。
    state 不可用 → 一律放行（行為與沒有 watch 時相同）。"""
    LIMIT_S = 600.0
    POLL_S = 5.0

    def __init__(self, source: str, log=print, limit_s: float | None = None, reader=None, sleep=time.sleep, mono=time.monotonic):
        self.source, self.log = source, log
        self.limit_s = self.LIMIT_S if limit_s is None else limit_s
        self.reader = reader or verify_suspect
        self.sleep, self.mono = sleep, mono

    def check(self) -> str:
        """'ok' = 可以動作；'timeout' = 暫停超過上限，呼叫端應停止"""
        if self.reader() is not True:
            return 'ok'
        t0 = self.mono()
        self.log(f'警告：watch 標出疑似答題 / 驗證視窗，{self.source} 暫停動作（請人工檢查畫面；最多等 {int(self.limit_s // 60)} 分鐘）')
        while self.reader() is True:
            if self.mono() - t0 >= self.limit_s:
                import errlog
                errlog.add(f'因疑似驗證視窗暫停超過 {int(self.limit_s // 60)} 分鐘，已停止 {self.source}，請檢查畫面', source=self.source)
                self.log(f'疑似驗證視窗暫停超過 {int(self.limit_s // 60)} 分鐘，停止 {self.source}（已寫 errlog，不自動恢復）')
                return 'timeout'
            self.sleep(self.POLL_S)
        self.log(f'疑似驗證視窗警報已解除，{self.source} 繼續（暫停 {int(self.mono() - t0)} 秒）')
        return 'ok'
