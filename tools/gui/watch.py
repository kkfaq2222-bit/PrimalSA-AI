#!/usr/bin/env python3
"""即時狀態監看：每 0.5 s 唯讀讀一次遊戲畫面像素 → screen_sigs 判斷 → 寫 tools/.cache/state.json（唯一寫入者）。
計畫與格式：notes/plan-watch-state.md（§1.3～1.6、§2、§7 第 2 階段）。

用法（WSL / Windows 原生都一樣）：
  uv run --no-project python tools/gui/watch.py              常駐（單例鎖；通常由 psa-hud 啟動，也可手動跑）
  uv run --no-project python tools/gui/watch.py --get [--max-age 2]   印 state.json（年齡超過 / watcher 不在 → 退出碼 1）
  uv run --no-project python tools/gui/watch.py --status     印鎖與 state 摘要
  uv run --no-project python tools/gui/watch.py --stop       要求常駐 watch 結束（寫 watch.stop 與 psa-hud.json watch=false）
  uv run --no-project python tools/gui/watch.py --ack        清掉 quest 轉述的驗證警報（人工確認過畫面後）
  uv run --no-project python tools/gui/watch.py --set-char DKB0   寫旁路檔 current-char.json（切換角色的工具點完卡片後呼叫；watch 以它為主）
  uv run --no-project python tools/gui/watch.py --learn-pet 迪基格斯  把目前 HUD 的寵物頭像存成這個名字（只讀；沒學過的寵物顯示「?」）
  uv run --no-project python tools/gui/watch.py --unlock     刪鎖（別平台 / 已死擁有者的殘鎖；同平台擁有者還活著要加 --force）
  uv run --no-project python tools/gui/watch.py --once       讀一次畫面、印 state（不寫檔、不上鎖）
  uv run --no-project python tools/gui/watch.py --bench N    跑 N 輪印 cycle_ms 統計（不寫檔、不上鎖）
  --dump-px                                                  （常駐 / --once 搭配）狀態變化時把像素存 tools/.cache/watch-dump/（第 5 階段調 annotate 用）

退出碼：0 正常（含父程序死）/ 2 參數錯 / 3 同平台已有實例（或鎖被換走）/ 5 收到 --stop / 6 鎖屬於另一平台 / 其他 = 異常。

**零輸入**：只送 gui.ps1 的 pixel / info（一律帶 -NoRestore 1：遊戲最小化時不還原視窗）與 stat.ps1 / ocr.ps1 / digitmatch.ps1（每 3 s 一次讀 HUD 數值：digitmatch 樣板比對第一順位，讀不出的欄位才用 stat.ps1 補；每分鐘最多一次用 stat 補學樣板）。
不送任何點擊、按鍵、走路、fg / max / seq / shot / waitpix；test_watch.py 用白名單與 AST 檢查把關。
watch 不上傳截圖，不做驗證視窗判斷（那是 quest 那一層）；state 不能當點擊依據。
"""
import argparse
import json
import os
import secrets
import signal
import statistics
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import battleguard  # noqa: E402
import charname  # noqa: E402
import digitmatch  # noqa: E402
import errlog  # noqa: E402
import screen_sigs  # noqa: E402
import watchstate  # noqa: E402
import winenv  # noqa: E402

INTERVAL = 0.5                    # 使用者決定：固定 0.5 s
SLOW_CYCLE_MS = 300               # 中位數超過 → 判斷退回一次性（server 沒在用 / 起不來），降頻保護 CPU
SLOW_MIN, SLOW_MAX = 2.0, 4.0     # 降頻間隔 = min(4, max(2, 3×cycle))
HEARTBEAT = 1.0                   # 內容沒變也每 1 s 寫一次（seq +1）
INFO_EVERY = 5.0                  # 每 5 s 用 info 看版面
IDLE_INTERVAL = 5.0               # 最小化 / 沒開遊戲：5 s 一次
GUI_TIMEOUT = 3.0                 # pixel / info 單次逾時
PS_TIMEOUT = 8.0                  # stat / ocr
OCR_EVERY = 3.0                   # 每 3 s 跑一次 stat.ps1（HUD 數值）
HUD_STALE_S = 12.0                # 超過這麼久沒成功讀到 → hud.stale
UNKNOWN_LONG_S = 10.0             # screen.state=unknown 連續這麼久 → alerts.unknown_long + verify_suspect（載入畫面 M8 未量，門檻待實機調）
CLEAR_S = 5.0                     # 連續這麼久都是已知畫面 → 清除
QUEST_SCAN_EVERY = 2.0            # 讀 quest-events.log 新增行的間隔
QUEST_PREFIXES = ('警告：Clef 判斷可能是答題 / 驗證視窗', '警告：連續 3 次遇到不認得的畫面')   # quest.py 的兩句警報開頭
OCR_ON = True                     # 測試可關（關了就完全不呼叫 stat.ps1 / digitmatch.ps1）
DIGIT_ON = True                   # HUD 數值第一順位用 digitmatch 樣板比對；False = 一律 stat.ps1 OCR（測試 / 緊急退路）
LEARN_EVERY = 60.0                # 自動補樣板（需要 stat 當標籤 + 多截一張圖）最短間隔：每分鐘最多一次
OCR_STATES = ('idle', 'walking', 'battle')   # 只在這些畫面讀 HUD（battle 僅限非完整戰鬥；對話 / 面板 / 未知畫面可能蓋住 HUD，OCR 會讀到雜訊）
LAYOUT_OK = '2880x1659'
TRANSITIONS_KEEP = 20
STABLE_CAP = 5                    # stable_n 上限（不封頂會每輪都「內容有變」）

GUI_ALLOWED = ('pixel', 'info')               # 零輸入白名單：gui.ps1 只准這兩個指令
PS_ALLOWED = ('stat.ps1', 'ocr.ps1', 'digitmatch.ps1')   # 其他腳本只准這三支（都是唯讀截圖 / 讀像素 / OCR）
NOGAME_STATES = ('no_game', 'minimized')

_stop_flag = {'sig': 0}           # 訊號 / 內部要求停止時設（呼叫前檢查；訊號 handler 另外直接 raise SystemExit）


class _Exit(Exception):
    """主迴圈要求結束：code = 退出碼"""

    def __init__(self, code: int, why: str = ''):
        super().__init__(why)
        self.code = code
        self.why = why


# ---------------------------------------------------------------- 唯一的 PowerShell 呼叫點（白名單包裝）
def _check_stop() -> None:
    if _stop_flag['sig']:
        raise SystemExit(128 + _stop_flag['sig'])


def _gui(cmd: str, *args: str, timeout: float = GUI_TIMEOUT) -> subprocess.CompletedProcess:
    """gui.ps1 只准 pixel / info；自動加 -NoRestore 1（最小化時不還原視窗、回 rc=3）；一定帶 timeout"""
    _check_stop()
    if cmd not in GUI_ALLOWED:
        raise ValueError(f'watch 零輸入白名單：gui 只准 {GUI_ALLOWED}，不准 {cmd!r}')
    return winenv.run_ps('gui.ps1', cmd, *args, '-NoRestore', '1', timeout=timeout)


def _ps(script: str, *args: str, timeout: float = PS_TIMEOUT) -> subprocess.CompletedProcess:
    """stat.ps1 / ocr.ps1 / digitmatch.ps1（唯讀 OCR / 樣板比對）；其他腳本一律拒絕。一定帶 timeout"""
    _check_stop()
    if script not in PS_ALLOWED:
        raise ValueError(f'watch 零輸入白名單：腳本只准 {PS_ALLOWED}，不准 {script!r}')
    return winenv.run_ps(script, *args, timeout=timeout)


# ---------------------------------------------------------------- 單例鎖
def read_lock(path=None, retries: int = 5, sleep=time.sleep):
    """回 (dict | None, 'ok'|'none'|'bad')。剛建立還沒寫完內容的鎖檔會短暫解析失敗 → 重試"""
    path = Path(path or watchstate.LOCK_FILE)
    for i in range(retries):
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(d, dict) and d.get('token'):
                return d, 'ok'
        except FileNotFoundError:
            return None, 'none'
        except (OSError, ValueError):
            pass
        sleep(0.02)
    return None, 'bad'


def _create_lock(info: dict) -> bool:
    """O_EXCL 建鎖；搶輸回 False"""
    p = Path(watchstate.LOCK_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(info, ensure_ascii=False))
    return True


def acquire_lock(info: dict, pid_alive=None, sleep=time.sleep) -> tuple[int, str]:
    """取得單例鎖 → (退出碼, 訊息)；0 = 取得。
    同平台、擁有者活著 → 3；別平台 → 6（WSL 看不到 Windows pid，反之亦然，所以不搶）；同平台擁有者已死 → 刪鎖重建（搶輸 → 3）"""
    pid_alive = pid_alive or battleguard.pid_alive
    if _create_lock(info):
        return 0, ''
    d, kind = read_lock(sleep=sleep)
    if kind == 'bad':
        try:
            age = time.time() - Path(watchstate.LOCK_FILE).stat().st_mtime
        except OSError:
            age = 999
        if age < 3:
            return 3, '鎖檔剛建立，另一個 watch 正在啟動'
        d = None   # 壞掉很久的鎖：當成同平台死鎖處理
    elif kind == 'none':
        return (0, '') if _create_lock(info) else (3, '搶鎖失敗（另一個 watch 剛啟動）')
    if d is not None:
        if d.get('platform') != info['platform']:
            return 6, f'另一平台（{d.get("platform")}）的 watch 正在跑（或留下殘鎖；人工確認後用 --unlock）'
        pid = d.get('pid')
        if isinstance(pid, int) and pid_alive(pid):
            return 3, f'已有 watch 在跑（pid {pid}）'
    try:
        Path(watchstate.LOCK_FILE).unlink()
    except OSError:
        pass
    return (0, '同平台舊擁有者已死，接手') if _create_lock(info) else (3, '搶鎖失敗（另一個 watch 剛接手）')


def release_lock(token: str) -> bool:
    """只刪 token 是自己的鎖"""
    d, kind = read_lock(retries=1)
    if kind == 'ok' and d.get('token') == token:
        try:
            Path(watchstate.LOCK_FILE).unlink()
            return True
        except OSError:
            pass
    return False


# ---------------------------------------------------------------- 主體
def _p95(xs) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * 0.95))] if xs else 0.0


class Watcher:
    """一個監看實例。clock / mono / sleep 可替換給測試"""

    def __init__(self, owner: str = '', clock=time.time, mono=time.monotonic, sleep=time.sleep, dump_px: bool = False):
        self.clock, self.mono, self.sleep = clock, mono, sleep
        self.token = secrets.token_hex(8)
        self.owner = owner
        self.started = clock()
        self.seq = 0
        self.phase = 'starting'
        self.owns_lock = False
        self.dump_px = dump_px
        # 畫面狀態
        self.cur = None                  # 目前 screen.state（None = 還沒讀過）
        self.prev = None
        self.last_good = None            # 最後一個「讀得到」的狀態（不含 error）
        self.since = self.started
        self.stable_n = 0
        self.transitions: list = []      # [舊, 新, 畫面時間, 寫入時間]
        self.screen_ts = self.started
        self.cls = {'full': False, 'cmd': False, 'auto_off': False, 'gold': 0}
        self.annot: list = []
        self.layout = None
        self.minimized = False
        self.game_running = False
        self.last_info = -1e9
        self.errors = 0
        self.interval = INTERVAL
        self.server_ok = False
        # 寫檔 / 量測
        self.last_key = None
        self.last_write = -1e9
        self.hb_intervals: deque = deque(maxlen=100)
        self.cycle_ms: deque = deque(maxlen=60)
        self.cur_cycle_ms = 0
        self.cpu_pct = 0.0
        self._cpu_t = (mono(), time.process_time())
        self.ppid = os.getppid()
        self.last_ppid_check = mono()
        self.pts = screen_sigs.points() + screen_sigs.annot_points()    # classify 用 points()；annot_points() 是 annotate / enc_on 另外要的點
        self.pts_arg = ' '.join(f'{x},{y}' for x, y in self.pts)
        self.last_px = None
        self._flags_cache = None
        self.call_t0 = self.started
        # HUD 數值（stat.ps1 OCR 合併）：欄位級 {v, ts}；讀不到 / 被蓋住時保留舊值並標 stale
        self.ocr_on = OCR_ON
        self.hud: dict = {}              # 欄位名 -> {'v':..., 'ts':...}
        self.hud_raw: list = []
        self.hud_ts = None               # 最近一次成功（有資料）的時間
        self.hud_fail = True             # 最近一次嘗試是否失敗 / 跳過
        self.last_ocr = -1e9
        self.ocr_ms = 0
        self.hud_src: dict = {}          # 欄位名 -> 'digit' | 'ocr'（除錯用：這個值是樣板比對還是 stat OCR 讀的）
        self.dm_n = {'digit': 0, 'mixed': 0, 'ocr': 0, 'learned': 0}   # 每輪 HUD 讀取的來源計數 + 自動補的樣板數
        self.last_learn = -1e9
        self._tpl: dict = {}             # 版面 -> 樣板 dict（記憶體快取，補樣板後直接更新）
        # 警示（§5）：unknown 連續 N 秒、quest 事件 log 轉述
        self.enc_on = None
        self.unknown_since = None        # 本地 monotonic
        self.known_since = None
        self.unk_alert = None            # {'kind','since','msg','shot'} + 內部 'err_id'
        self.q_alerts: list = []
        self.q_off = self._qlog_size()   # 啟動時記下檔案大小，只看之後新增的行
        self.last_qscan = mono()
        # 人物名 / 寵物名（第 7 階段）
        self.names = charname.NameTracker(watchstate.load_config().get('chars'))
        self.side = None                 # current-char.json 內容（旁路）
        self._side_mt = None
        self._cfg_mt = None
        self.pet_lib: dict = {}
        self._pet_mt = None
        self.pet_name = None             # {'v','ts','src'}

    # ---- 啟動 / 結束 ----
    def lock_info(self) -> dict:
        return {'token': self.token, 'pid': os.getpid(), 'platform': winenv.platform_kind(), 'started': self.started}

    def acquire(self) -> tuple[int, str]:
        code, msg = acquire_lock(self.lock_info())
        if code == 0:
            self.owns_lock = True
            old = watchstate.read()
            if old and isinstance(old.get('seq'), int):
                self.seq = old['seq']        # 接續舊 seq（新 token，讀者也會當成「有變」）
        return code, msg

    def finish(self) -> None:
        """finally：token 還是自己的才寫 stopping 與刪鎖（鎖被換走 = 別人是寫入者，不再碰）"""
        if not self.owns_lock:
            return
        d, kind = read_lock(retries=1)
        if kind == 'ok' and d.get('token') == self.token:
            self.phase = 'stopping'
            try:
                self.flush(force=True)
            except Exception:
                pass
            release_lock(self.token)
        self.owns_lock = False

    # ---- 唯讀偵測 ----
    def _housekeeping(self) -> None:
        # 鎖是不是還是自己的（只有人手動刪鎖 / 換鎖才會發生）
        d, kind = read_lock(retries=2, sleep=self.sleep)
        if kind != 'ok' or d.get('token') != self.token:
            self.owns_lock = False
            raise _Exit(3, '鎖已被換走或刪除，結束（不再寫 state）')
        # watch.stop：時間早於自己啟動的是殘留，忽略
        st = self._stop_time()
        if st is not None and st >= self.started:
            try:
                Path(watchstate.STOP_FILE).unlink()
            except OSError:
                pass
            raise _Exit(5, '收到 --stop')
        self._scan_quest_log()
        self._check_ack()
        self._read_side()
        # 父程序看門狗（只有 hud 啟動時）
        if self.owner == 'hud' and self.mono() - self.last_ppid_check >= (5.0 if sys.platform == 'win32' else 0.0):
            self.last_ppid_check = self.mono()
            gone = (not winenv._owner_alive(self.ppid)) if sys.platform == 'win32' else (os.getppid() != self.ppid)
            if gone:
                raise _Exit(0, '父程序已結束')

    def _stop_time(self):
        p = Path(watchstate.STOP_FILE)
        try:
            txt = p.read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            v = json.loads(txt)
            return float(v['ts'] if isinstance(v, dict) else v)
        except (ValueError, KeyError, TypeError):
            try:
                return p.stat().st_mtime
            except OSError:
                return None

    def _call(self, fn, *a):
        """呼叫前若 server 沒在跑（第一次 / 逾時重開後）先寫 phase=starting；回 (result | None, 'ok'|'timeout'|'err', 耗時 ms)"""
        if winenv._server_wanted('gui.ps1') and not winenv.server_alive():
            self.phase = 'starting'
            self.flush()
        t = self.mono()
        self.call_t0 = self.clock()      # 畫面時間 = 呼叫開始時間（PrintWindow 發生在呼叫之內；取開始 = 延遲只會量大不會量小）
        try:
            r = fn(*a)
            res = (r, 'ok')
        except subprocess.TimeoutExpired:
            res = (None, 'timeout')
        except (OSError, ValueError) as e:
            if isinstance(e, ValueError) and 'watch 零輸入白名單' in str(e):
                raise
            res = (None, 'err')
        ms = int((self.mono() - t) * 1000)
        if self.phase == 'starting':
            self.phase = 'running'
        self.server_ok = winenv.server_alive()
        self.flush()                     # 每個呼叫之後檢查「變化或心跳」
        return res[0], res[1], ms

    @staticmethod
    def _kind(r) -> str:
        """gui rc → 'ok' | 'minimized' | 'no_game' | 'error'"""
        out = (r.stdout or '').strip()
        if r.returncode == 3 or out == 'minimized':
            return 'minimized'
        if r.returncode == 0:
            return 'ok'
        if r.returncode == 1 and 'PrimalSA' in ((r.stderr or '') + out):   # gui.ps1：「PrimalSA 沒有在執行」
            return 'no_game'
        return 'error'

    def _do_info(self) -> str:
        r, how, ms = self._call(_gui, 'info')
        self.last_info = self.mono()
        if r is None:
            return 'error'
        k = self._kind(r)
        if k == 'ok':
            import re
            m = re.search(r'client=(\d+)x(\d+)', r.stdout or '')
            if not m:
                return 'error'
            self.layout = f'{m[1]}x{m[2]}'
        return k

    def _read_pixels(self):
        """→ (kind, px)：kind = ok / minimized / no_game / error"""
        r, how, ms = self._call(_gui, 'pixel', self.pts_arg)
        if r is None:
            return 'error', None
        k = self._kind(r)
        if k != 'ok':
            return k, None
        cols = []
        for c in (r.stdout or '').split():
            try:
                cols.append(tuple(int(v) for v in c.split(',')))
            except ValueError:
                return 'error', None
        if len(cols) != len(self.pts) or any(len(c) != 3 for c in cols):
            return 'error', None
        return 'ok', dict(zip(self.pts, cols))

    def cycle(self) -> None:
        """一輪：housekeeping → （info）→ pixel → classify → 寫檔判斷"""
        t0 = self.mono()
        self._housekeeping()
        kind, px = 'ok', None
        info_due = self.layout is None or self.cur in NOGAME_STATES or self.mono() - self.last_info >= INFO_EVERY
        if info_due:
            kind = self._do_info()
            if kind == 'ok' and self.layout != LAYOUT_OK:
                kind = 'unsupported'
        elif self.layout != LAYOUT_OK:
            kind = 'unsupported'
        if kind == 'ok':
            kind, px = self._read_pixels()
        if kind == 'no_game':
            self.layout = None           # 重開遊戲後版面可能不同：下一輪先 info
        self._apply(kind, px)
        self.cur_cycle_ms = int((self.mono() - t0) * 1000)
        if kind == 'ok':
            self.cycle_ms.append(self.cur_cycle_ms)
        self._update_interval()
        self._update_alerts()
        self._maybe_ocr(kind)
        self.flush()

    def _apply(self, kind: str, px) -> None:
        """依這輪的讀取結果更新畫面狀態與 transitions"""
        now = self.clock()
        self.game_running = kind not in ('no_game',) and (kind != 'error' or self.game_running)
        self.minimized = kind == 'minimized'
        if kind == 'ok':
            c = screen_sigs.classify(px)
            new = c['state']
            self.cls = {k: c[k] for k in ('full', 'cmd', 'auto_off', 'gold')}
            self.annot = screen_sigs.annotate(px, c)
            self.enc_on = screen_sigs.enc_on(px, c)
            self.last_px = px
        else:
            new = kind                    # minimized / no_game / error / unsupported
            if kind != 'error':
                self.enc_on = None
            if kind in ('no_game', 'minimized', 'unsupported'):
                self.cls = {'full': False, 'cmd': False, 'auto_off': False, 'gold': 0}
                self.annot = []
        if kind == 'error':
            self.errors += 1
        self.screen_ts = self.call_t0 if kind in ('ok', 'minimized', 'no_game', 'error') else now
        if new != self.cur:
            old = self.cur
            if old is not None:
                self.transitions.append([old, new, self.screen_ts, None])
                del self.transitions[:-TRANSITIONS_KEEP]
            self.prev = self.last_good if (new == 'error' or old == 'error') else old
            self.since = self.screen_ts
            self.stable_n = 1
            if self.dump_px and px is not None:
                self._dump(new, px)
        else:
            self.stable_n = min(self.stable_n + 1, STABLE_CAP)
        if new != 'error':
            self.last_good = new
        self.cur = new

    def _dump(self, state: str, px: dict) -> None:
        """--dump-px：狀態變化時存像素（格式同 fixtures/screen_px.json 的 px：每點 6 位 hex）"""
        d = Path(watchstate.CACHE) / 'watch-dump'
        try:
            d.mkdir(parents=True, exist_ok=True)
            hexs = ''.join('%02x%02x%02x' % px[pt] for pt in self.pts)
            (d / f'{int(self.clock())}_{state}.json').write_text(
                json.dumps({'ts': self.clock(), 'state': state, 'points': [list(p) for p in self.pts], 'px': hexs}), encoding='utf-8')
            files = sorted(d.glob('*.json'))
            for f in files[:-200]:
                f.unlink()
        except OSError:
            pass

    def _update_interval(self) -> None:
        """正常 0.5 s；退回一次性（最近 5 輪 cycle_ms 中位數 > 300）降頻 min(4, max(2, 3×cycle))；最小化 / 沒開遊戲 5 s"""
        if self.cur in NOGAME_STATES:
            self.interval = IDLE_INTERVAL
            return
        recent = list(self.cycle_ms)[-5:]
        if len(recent) >= 3 and statistics.median(recent) > SLOW_CYCLE_MS:
            self.interval = min(SLOW_MAX, max(SLOW_MIN, 3 * statistics.median(recent) / 1000.0))
        else:
            self.interval = INTERVAL

    # ---- 警示（§5）：只標出、不點任何東西；不存截圖 ----
    def _alerts(self) -> list:
        out = []
        if self.unk_alert:
            out.append({k: v for k, v in self.unk_alert.items() if k != 'err_id'})
        out.extend({k: v for k, v in a.items() if k != 'err_id'} for a in self.q_alerts)
        return out

    def _update_alerts(self) -> None:
        """unknown 連續 UNKNOWN_LONG_S 秒 → alerts.unknown_long + errlog（不論有沒有 battle.lock）；
        連續 CLEAR_S 秒都是已知畫面（或沒開遊戲 / 最小化）→ 清除並補 fix。error / unsupported 不計（既不累積也不清除）。
        登入 / 選角畫面（annot login / charsel）算已知畫面（那是 netwatch 的範圍）。"""
        now = self.mono()
        st = self.cur
        unknown = st == 'unknown' and not any(k in self.annot for k in screen_sigs.ANNOT_KNOWN)
        if unknown:
            self.known_since = None
            if self.unknown_since is None:
                self.unknown_since = now
                self.unknown_wall = self.clock()
            if self.unk_alert is None and now - self.unknown_since >= UNKNOWN_LONG_S:
                eid = errlog.add(f'疑似驗證視窗：畫面連續 {int(UNKNOWN_LONG_S)} 秒以上不認得（watch 偵測；不碰、請人工確認）', source='watch')
                self.unk_alert = {'kind': 'unknown_long', 'since': self.unknown_wall, 'shot': None, 'err_id': eid,
                                  'msg': f'不認得的畫面超過 {int(UNKNOWN_LONG_S)} 秒（可能是驗證視窗，請人工確認）'}
        elif st in NOGAME_STATES:
            self.unknown_since = self.known_since = None
            self._clear_unknown(st)
        elif st in (None, 'error', 'unsupported'):
            pass
        else:
            self.unknown_since = None
            if self.unk_alert is not None:
                if self.known_since is None:
                    self.known_since = now
                elif now - self.known_since >= CLEAR_S:
                    self.known_since = None
                    self._clear_unknown(st)
            else:
                self.known_since = None

    def _clear_unknown(self, st) -> None:
        a, self.unk_alert = self.unk_alert, None
        if a and a.get('err_id'):
            errlog.fix(a['err_id'], f'畫面已恢復為「{screen_sigs.label({"state": st}, self.annot)}」，警報自動清除')

    @staticmethod
    def _qlog_size() -> int:
        try:
            return Path(watchstate.QUEST_LOG).stat().st_size
        except OSError:
            return 0

    def _scan_quest_log(self) -> None:
        """讀 quest-events.log 啟動後新增的行；比對 quest 的兩句警報開頭（Clef 判斷 / 連續 3 次不認得）→ alerts.kind=verify。
        檔案變小 = 被輪替 → offset 歸零；只消化到最後一個換行（寫到一半的行下次再讀）"""
        if self.mono() - self.last_qscan < QUEST_SCAN_EVERY:
            return
        self.last_qscan = self.mono()
        try:
            size = Path(watchstate.QUEST_LOG).stat().st_size
        except OSError:
            return
        if size < self.q_off:
            self.q_off = 0
        if size == self.q_off:
            return
        try:
            with open(watchstate.QUEST_LOG, 'rb') as f:
                f.seek(self.q_off)
                data = f.read(256 * 1024)
        except OSError:
            return
        cut = data.rfind(b'\n')
        if cut < 0:
            return
        self.q_off += cut + 1
        for ln in data[:cut + 1].decode('utf-8', errors='replace').splitlines():
            msg = ln[20:] if len(ln) > 20 and ln[4:5] == '-' and ln[10:11] == ' ' else ln     # 去掉 'YYYY-MM-DD HH:MM:SS ' 前綴
            if msg.startswith(QUEST_PREFIXES):
                if not any(a.get('line') == ln[:200] for a in self.q_alerts):
                    eid = errlog.add(f'quest 警報轉述：{msg[:100]}（疑似驗證視窗，請人工確認）', source='watch')
                    self.q_alerts.append({'kind': 'verify', 'src': 'quest', 'line': ln[:200], 'msg': msg[:120], 'err_id': eid})
                    del self.q_alerts[:-3]

    def _check_ack(self) -> None:
        """watch.py --ack（/psa-hud ack）：清掉 quest 轉述的警報（unknown_long 靠畫面恢復自動清）。ack 檔時間早於啟動的忽略"""
        p = Path(watchstate.ACK_FILE)
        try:
            t = p.stat().st_mtime
        except OSError:
            return
        if t >= self.started:
            for a in self.q_alerts:
                if a.get('err_id'):
                    errlog.fix(a['err_id'], '使用者確認（/psa-hud ack）')
            self.q_alerts.clear()
        try:
            p.unlink()
        except OSError:
            pass

    # ---- HUD 數值（digitmatch 樣板比對 → stat.ps1 補）----
    def _maybe_ocr(self, kind: str) -> None:
        """每 OCR_EVERY 秒跑一次 stat.ps1；畫面不是主畫面類（對話 / 面板 / 完整戰鬥 / 沒開遊戲…）就不跑，只標 stale"""
        if not self.ocr_on:
            return
        ok_screen = kind == 'ok' and self.cur in OCR_STATES and not (self.cur == 'battle' and self.cls.get('full'))
        if not ok_screen:
            self.hud_fail = True
            return
        if self.mono() - self.last_ocr < OCR_EVERY:
            return
        self.last_ocr = self.mono()
        if DIGIT_ON:
            self._read_hud_digit()
        else:
            r, how, ms = self._call(_ps, 'stat.ps1')
            self.ocr_ms = ms
            self.merge_stat(self._parse_stat(r), self.call_t0, 'ocr')
        self._read_names()

    def _tpl_for(self, layout: str) -> dict:
        if layout not in self._tpl:
            self._tpl[layout] = digitmatch.load_tpl(layout)
        return self._tpl[layout]

    def _read_hud_digit(self) -> None:
        """HUD 數值：digitmatch 樣板比對第一順位；有欄位回 None（或這個版面沒樣板）才呼叫 stat.ps1 補那些欄位。
        另外每 LEARN_EVERY 秒最多一次：呼叫 stat 當標籤 + 再截一張圖，把新字形補進樣板（見 digitmatch.learn_from 的採用條件）。
        1920×1017 等沒有樣板的版面：全部退回 stat，並靠同一個補學機制在背景累積樣板（不動視窗）。"""
        t_all = self.mono()
        r, how, ms = self._call(_ps, 'digitmatch.ps1')
        t0 = self.call_t0
        cap = digitmatch.parse_capture(r.stdout) if r is not None else {'ok': False}
        dm = None
        if cap.get('ok'):
            try:
                dm = digitmatch.read_fields(cap, self._tpl_for(cap['layout']))
            except (KeyError, ValueError, IndexError):
                dm = None
        learn_due = cap.get('ok') and self.mono() - self.last_learn >= LEARN_EVERY
        need_stat = dm is None or bool(dm['unsure']) or learn_due
        st = None
        if need_stat:
            r2, how2, ms2 = self._call(_ps, 'stat.ps1')
            st = self._parse_stat(r2)
            if st is not None and not st.get('ok'):
                st = None
        merged, src = {}, {}
        for k in self.HUD_SRC:
            if dm is not None and dm.get(k) not in (None, ''):
                merged[k], src[k] = dm[k], 'digit'
            elif st is not None and st.get(k) not in (None, ''):
                merged[k], src[k] = st[k], 'ocr'
        if merged:
            merged['ok'] = True
            if dm is not None:
                merged['raw'] = [str(dm['raw'].get(k) or '') for k in ('lv', 'hp', 'mp', 'plv', 'php', 'pos')]
            elif st is not None and isinstance(st.get('raw'), list):
                merged['raw'] = st['raw']
            self.merge_stat(merged, t0, src)
            used = set(src.values())
            self.dm_n['digit' if used == {'digit'} else ('ocr' if used == {'ocr'} else 'mixed')] += 1
        else:
            self.merge_stat(None, t0)
        self.ocr_ms = int((self.mono() - t_all) * 1000)
        # 自動補樣板：stat 有值 + 兩次截圖夾住 stat（確認畫面沒在變）；失敗 / 無效不改 last_learn 以外的任何東西
        if learn_due and st is not None:
            self.last_learn = self.mono()
            r3, how3, ms3 = self._call(_ps, 'digitmatch.ps1')
            cap2 = digitmatch.parse_capture(r3.stdout) if r3 is not None else {'ok': False}
            if cap2.get('ok') and cap2.get('layout') == cap['layout']:
                tpl = self._tpl_for(cap['layout'])
                n = digitmatch.learn_from(cap, cap2, st, tpl, dm)
                if n:
                    self.dm_n['learned'] += n
                    try:
                        digitmatch.save_tpl(cap['layout'], tpl)
                    except OSError:
                        pass
    # ---- 人物名 / 寵物名 ----
    @staticmethod
    def _mtime(p):
        try:
            return Path(p).stat().st_mtime_ns
        except OSError:
            return None

    def _read_side(self) -> None:
        """旁路 current-char.json（切換角色的工具寫）：mtime 變了才重讀"""
        mt = self._mtime(watchstate.CURCHAR_FILE)
        if mt != self._side_mt:
            self._side_mt = mt
            self.side = watchstate.read_current_char()

    def _reload_cfg(self) -> None:
        mt = self._mtime(watchstate.CONFIG_FILE)
        if mt != self._cfg_mt:
            self._cfg_mt = mt
            self.names.set_chars(watchstate.load_config().get('chars'))
        mt = self._mtime(watchstate.PET_AVATARS_FILE)
        if mt != self._pet_mt:
            self._pet_mt = mt
            self.pet_lib = charname.load_avatars(watchstate.PET_AVATARS_FILE)

    def _read_names(self) -> None:
        """stat 之後（同樣只在主畫面類、非完整戰鬥）：頭頂名牌 OCR 核對白名單 + 寵物頭像取樣比對。讀不到都沿用舊值"""
        self._reload_cfg()
        if self.names.cmap:
            r, how, ms = self._call(_ps, 'ocr.ps1', *map(str, charname.NAME_BOX), *charname.NAME_OCR_OPTS)
            d = self._parse_stat(r)
            if d and d.get('ok'):
                texts = [str(ln.get('text', '')) for ln in d.get('lines', []) if isinstance(ln, dict)]
                self.names.feed(texts, self.clock(), self.side['ts'] if self.side else None)
        if self.pet_lib:
            r, how, ms = self._call(_gui, 'pixel', charname.avatar_arg())
            if r is not None and self._kind(r) == 'ok':
                fp = charname.parse_avatar(r.stdout)
                if fp:
                    self.pet_name = {'v': charname.match_avatar(fp, self.pet_lib) or '?', 'ts': self.clock(), 'src': 'learn'}

    @staticmethod
    def _parse_stat(r):
        """stat.ps1 的最後一行 JSON → dict；失敗回 None"""
        if r is None:
            return None
        line = ((r.stdout or '').strip().splitlines() or [''])[-1]
        try:
            d = json.loads(line)
        except ValueError:
            return None
        return d if isinstance(d, dict) else None

    HUD_SRC = ('level', 'hp', 'hpPct', 'mp', 'mpPct', 'petLevel', 'petHp', 'map', 'pos')

    def merge_stat(self, d, t: float, src=None) -> bool:
        """把一次 stat 結果併進 self.hud；回 True = 有資料。
        ok=False（最小化 / 沒開）或 ok=True 但全空（登入 / 選角畫面等被蓋住）→ 保留舊值，標 stale，不寫空值。
        有資料時只更新「這次有值」的欄位（沒讀到的欄位保留舊值與舊 ts）"""
        if not d or not d.get('ok'):
            self.hud_fail = True
            return False
        got = {k: d.get(k) for k in self.HUD_SRC if d.get(k) not in (None, '')}
        if not got:
            self.hud_fail = True
            return False
        for k, v in got.items():
            self.hud[k] = {'v': v, 'ts': t}
            self.hud_src[k] = src.get(k, 'ocr') if isinstance(src, dict) else (src or 'ocr')
        raw = d.get('raw')
        if isinstance(raw, list):
            self.hud_raw = [str(x) for x in raw][:8]
        self.hud_ts = t
        self.hud_fail = False
        return True

    def _hud_section(self, now: float) -> dict:
        h = self.hud
        out: dict = {'ts': self.hud_ts, 'age_s': round(max(0.0, now - self.hud_ts), 2) if self.hud_ts else None,
                     'ok': self.hud_ts is not None and not self.hud_fail,
                     'stale': self.hud_ts is None or self.hud_fail or now - self.hud_ts > HUD_STALE_S}
        for k in ('level', 'hp', 'hpPct', 'mp', 'mpPct'):
            if k in h:
                out[k] = dict(h[k])
        pet = {}
        for src, dst in (('petLevel', 'level'), ('petHp', 'hp')):
            if src in h:
                pet[dst] = dict(h[src])
        if pet:
            out['pet'] = pet
        if 'map' in h or 'pos' in h:
            pos = h.get('pos')
            if 'map' in h:
                m = {'v': h['map']['v'], 'ts': h['map']['ts']}
                if pos:
                    try:
                        m['id'] = int(str(pos['v']).split(':')[0])
                    except ValueError:
                        pass
                out['map'] = m
            if pos:
                try:
                    xy = str(pos['v']).split(':')[1].split(',')
                    out['pos'] = {'v': [int(xy[0]), int(xy[1])], 'ts': pos['ts']}
                except (IndexError, ValueError):
                    pass
        if self.hud_raw:
            out['raw'] = self.hud_raw
        if self.hud_src:
            out['src'] = dict(self.hud_src)               # 每欄來源：digit = 樣板比對、ocr = stat.ps1
            out['dm'] = dict(self.dm_n)
        nm = self.names.resolve(self.side, now)
        out['name'] = nm or {'v': '?', 'ts': None, 'src': None, 'stale': True}
        if pet or self.pet_name:
            pn = dict(self.pet_name) if self.pet_name else {'v': '?', 'ts': None, 'src': None}
            pn['stale'] = pn.get('ts') is None or now - pn['ts'] > charname.NAME_STALE_S
            out.setdefault('pet', {})['name'] = pn
        return out

    # ---- state 組裝 / 寫檔 ----
    def build(self) -> dict:
        now = self.clock()
        mono = self.mono()
        wall, cpu = mono - self._cpu_t[0], time.process_time() - self._cpu_t[1]
        if wall >= 10:
            self.cpu_pct = round(100.0 * cpu / wall, 1)
            self._cpu_t = (mono, time.process_time())
        d = {
            'v': watchstate.VERSION, 'ts': now, 'seq': self.seq, 'phase': self.phase,
            'watcher': {'running': self.phase != 'stopping', 'token': self.token, 'pid': os.getpid(), 'platform': winenv.platform_kind(),
                        'started': self.started, 'interval': self.interval, 'server': bool(self.server_ok),
                        'cycle_ms': self.cur_cycle_ms, 'ocr_ms': self.ocr_ms, 'ocr_every': OCR_EVERY, 'errors': self.errors, 'owner': self.owner,
                        'hb_p95_s': round(_p95(self.hb_intervals), 2), 'cpu_pct': self.cpu_pct},
            'game': {'ts': self.screen_ts, 'running': bool(self.game_running), 'minimized': self.minimized,
                     'layout': self.layout, 'screen_supported': self.layout == LAYOUT_OK},
            'screen': {'ts': self.screen_ts, 'age_s': round(max(0.0, now - self.screen_ts), 3), 'state': self.cur or 'starting',
                       'prev': self.prev, 'annot': self.annot,
                       'label': screen_sigs.label({'state': self.cur, **self.cls}, self.annot) if self.cur else '啟動中',
                       'since': self.since, 'transitions': [list(t[:3]) + [t[3] if t[3] is not None else now] for t in self.transitions],
                       'full': self.cls['full'], 'cmd': self.cls['cmd'], 'auto_off': self.cls['auto_off'], 'gold': self.cls['gold'],
                       'enc_on': self.enc_on, 'stable_n': self.stable_n, 'src': 'pixel'},
            'hud': self._hud_section(now),
            'flags': dict(self._flags(mono), verify_suspect=bool(self._alerts())),
            'alerts': self._alerts(),
        }
        return d

    def _flags(self, mono: float) -> dict:
        """battle_lock（只讀 peek）/ netwatch_halt；0.4 s 內重複 build 不重讀檔（每輪 build 2～3 次）"""
        c = self._flags_cache
        if c is None or mono - c[0] > 0.4:
            c = self._flags_cache = (mono, {'battle_lock': watchstate.peek_battle_lock(), 'netwatch_halt': Path(watchstate.HALT_FILE).exists()})
        return c[1]

    def flush(self, force: bool = False) -> bool:
        """內容有變（排除時間戳等欄位）或距上次寫 ≥ 1 s（心跳）才寫；seq 每次寫 +1。回 True = 有寫。
        只在持鎖時寫（沒拿到鎖 / 鎖被換走一律不寫 state）"""
        if not self.owns_lock:
            return False
        d = self.build()
        changed = watchstate.content_key(d) != self.last_key
        mono = self.mono()
        if not (force or changed or mono - self.last_write >= HEARTBEAT):
            return False
        d['seq'] = self.seq + 1
        if not watchstate.write(d, self.token):
            return False                 # 寫失敗：跳過這輪（不更新 last_key，下次再試）
        self.seq += 1
        if self.last_write > -1e8:
            self.hb_intervals.append(mono - self.last_write)
        self.last_write = mono
        self.last_key = watchstate.content_key(d)
        wt = d['ts']
        for t in self.transitions:
            if t[3] is None:
                t[3] = wt
        return True

    def run(self) -> int:
        """主迴圈（已持鎖）。回退出碼；SystemExit / 例外照常往外丟（finish() 在 main 的 finally）"""
        self.phase = 'starting'
        self.flush(force=True)
        try:
            while True:
                t = self.mono()
                self.cycle()
                self.sleep(max(0.05, self.interval - (self.mono() - t)))
        except _Exit as e:
            if e.why:
                print(f'watch 結束：{e.why}（退出碼 {e.code}）', flush=True)
            return e.code


# ---------------------------------------------------------------- CLI
def _install_signals() -> None:
    """在 enable_server() 之前裝：SIGTERM / SIGHUP 一律 raise SystemExit（不只設旗標，否則卡在 PowerShell 呼叫裡不會停）。
    winenv 的 _on_signal 之後會先關 server 再串接呼叫這裡的 handler"""
    def handler(signum, frame):
        _stop_flag['sig'] = int(signum)
        raise SystemExit(128 + int(signum))
    for name in ('SIGTERM', 'SIGHUP', 'SIGBREAK'):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def cmd_stop() -> int:
    """--stop：寫 psa-hud.json {watch:false}（HUD 不會在它停下後又拉起來）+ watch.stop（帶時間），等常駐實例結束（最多 6 s）"""
    cfg = {}
    try:
        cfg = json.loads(Path(watchstate.HUD_CFG).read_text(encoding='utf-8'))
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        pass
    cfg['watch'] = False
    Path(watchstate.CACHE).mkdir(parents=True, exist_ok=True)
    Path(watchstate.HUD_CFG).write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
    d, kind = read_lock(retries=1)
    if kind == 'none':
        print('沒有常駐 watch（已寫 psa-hud.json watch=false）')
        return 0
    Path(watchstate.STOP_FILE).write_text(json.dumps({'ts': time.time()}), encoding='utf-8')
    for _ in range(60):
        time.sleep(0.1)
        if read_lock(retries=1)[1] == 'none':
            print('watch 已停止')
            return 0
    print('已要求停止，但鎖還在（watch 可能卡住 / 在別平台）；可 --status 查看，必要時 --unlock', file=sys.stderr)
    return 1


def cmd_ack() -> int:
    """--ack：告訴常駐 watch「quest 轉述的驗證警報我看過了」（寫 watch.ack；watch 下一輪清掉並補 errlog fix）"""
    Path(watchstate.CACHE).mkdir(parents=True, exist_ok=True)
    Path(watchstate.ACK_FILE).write_text(json.dumps({'ts': time.time()}), encoding='utf-8')
    print('已送出 ack（watch 下一輪清掉 quest 轉述的警報）')
    return 0


def cmd_set_char(name: str) -> int:
    """--set-char：手動 / 切換角色的工具寫旁路檔（當前角色 = name）。有白名單時名字要在白名單內（正規化後比對）"""
    chars = watchstate.load_config().get('chars')
    if chars:
        hit = charname.match_texts([name], charname.canon_map(chars))
        if not hit:
            print(f'{name!r} 不在白名單（watch-config.json 的 chars）：{chars}', file=sys.stderr)
            return 2
        name = hit
    if not watchstate.write_current_char(name, src='set-char'):
        print('寫入 current-char.json 失敗', file=sys.stderr)
        return 1
    print(f'當前角色 = {name}（已寫 current-char.json；watch 以它為主，頭頂名牌 OCR 核對）')
    return 0


def cmd_learn_pet(name: str) -> int:
    """--learn-pet：把「現在 HUD 上的寵物頭像」存成這個名字（只讀 pixel；畫面必須是主畫面 / 行走中，否則頭像可能被蓋住）"""
    r = _gui('pixel', ' '.join(f'{x},{y}' for x, y in screen_sigs.points()))
    if r.returncode != 0:
        print(f'讀不到畫面（rc={r.returncode}）：遊戲沒開 / 最小化', file=sys.stderr)
        return 1
    try:
        cols = [tuple(int(v) for v in c.split(',')) for c in r.stdout.split()]
        st = screen_sigs.classify(dict(zip(screen_sigs.points(), cols)))['state']
    except (ValueError, KeyError):
        print('畫面讀取失敗', file=sys.stderr)
        return 1
    if st not in ('idle', 'walking'):
        print(f'目前畫面是 {st}，不是主畫面 / 行走中（頭像可能被蓋住），不取樣', file=sys.stderr)
        return 1
    r = _gui('pixel', charname.avatar_arg())
    fp = charname.parse_avatar(r.stdout) if r.returncode == 0 else None
    if not fp:
        print('頭像取樣失敗', file=sys.stderr)
        return 1
    lib = charname.load_avatars(watchstate.PET_AVATARS_FILE)
    old = charname.match_avatar(fp, lib)
    lib = charname.learn_avatar(lib, name, fp)
    Path(watchstate.CACHE).mkdir(parents=True, exist_ok=True)
    Path(watchstate.PET_AVATARS_FILE).write_text(json.dumps(lib, ensure_ascii=False), encoding='utf-8')
    print(f'已學習寵物頭像「{name}」（庫內 {len(lib)} 隻、此隻 {len(lib[name])} 個樣本）' + (f'；注意：先前這個頭像比對到「{old}」' if old and old != name else ''))
    return 0


def cmd_unlock(force: bool) -> int:
    d, kind = read_lock(retries=1)
    if kind == 'none':
        print('沒有鎖')
        return 0
    if d and d.get('platform') == winenv.platform_kind() and isinstance(d.get('pid'), int) and battleguard.pid_alive(d['pid']) and not force:
        print(f'同平台擁有者 pid {d["pid"]} 還活著；確定要刪請加 --force（或先 --stop）', file=sys.stderr)
        return 3
    try:
        Path(watchstate.LOCK_FILE).unlink()
    except OSError as e:
        print(f'刪鎖失敗：{e}', file=sys.stderr)
        return 1
    print(f'已刪鎖（原擁有者：{d and d.get("platform")} pid {d and d.get("pid")}）')
    return 0


def cmd_status() -> int:
    d, kind = read_lock(retries=1)
    print('鎖：' + (f'{d.get("platform")} pid {d.get("pid")} 啟動 {time.strftime("%H:%M:%S", time.localtime(d.get("started", 0)))}' if d else kind))
    st = watchstate.read()
    if not st:
        print('state.json：沒有 / 讀不到')
        return 1
    w, sc = st.get('watcher', {}), st.get('screen', {})
    a = watchstate.age(st)
    print(f'state：phase={st.get("phase")} seq={st.get("seq")} running={w.get("running")} 年齡={"?" if a is None else round(a, 1)}s '
          f'cycle_ms={w.get("cycle_ms")} hb_p95_s={w.get("hb_p95_s")} cpu_pct={w.get("cpu_pct")} errors={w.get("errors")}')
    print(f'畫面：{sc.get("state")}（{sc.get("label")}） since={sc.get("since")}')
    return 0


def cmd_get(max_age: float) -> int:
    st = watchstate.fresh(max_age)
    if not st:
        print('state 不可用（watch 沒在跑，或資料超過 max-age）', file=sys.stderr)
        return 1
    print(json.dumps(st, ensure_ascii=False))
    return 0


def cmd_once(dump_px: bool) -> int:
    w = Watcher(dump_px=dump_px)
    w.owns_lock = False
    winenv.enable_server()
    try:
        w._housekeeping = lambda: None
        w.cycle()
        d = w.build()
        print(json.dumps(d, ensure_ascii=False, indent=1))
    finally:
        winenv.shutdown_server()
    return 0


def cmd_bench(n: int) -> int:
    w = Watcher()
    w._housekeeping = lambda: None
    winenv.enable_server()
    ms = []
    try:
        for _ in range(n):
            t = time.monotonic()
            w.cycle()
            ms.append((time.monotonic() - t) * 1000)
            time.sleep(max(0.0, w.interval - (time.monotonic() - t)))
    finally:
        winenv.shutdown_server()
    print(f'{n} 輪 cycle_ms 中位數 {statistics.median(ms):.0f} / p95 {_p95(ms):.0f} / 最大 {max(ms):.0f}；state 分佈 '
          f'{ {s: [t[1] for t in w.transitions].count(s) for s in set(t[1] for t in w.transitions)} }；interval {w.interval}')
    h = w._hud_section(w.clock())
    print(f'HUD 來源 {h.get("src")}；每輪來源計數 {w.dm_n}；最近一次 HUD 讀取 {w.ocr_ms} ms')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='即時狀態監看（唯讀）')
    g = ap.add_mutually_exclusive_group()
    g.add_argument('--get', action='store_true')
    g.add_argument('--status', action='store_true')
    g.add_argument('--stop', action='store_true')
    g.add_argument('--unlock', action='store_true')
    g.add_argument('--ack', action='store_true')
    g.add_argument('--set-char', metavar='NAME')
    g.add_argument('--learn-pet', metavar='NAME')
    g.add_argument('--once', action='store_true')
    g.add_argument('--bench', type=int, metavar='N')
    ap.add_argument('--max-age', type=float, default=2.0)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--dump-px', action='store_true')
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if a.get:
        return cmd_get(a.max_age)
    if a.status:
        return cmd_status()
    if a.stop:
        return cmd_stop()
    if a.unlock:
        return cmd_unlock(a.force)
    if a.ack:
        return cmd_ack()
    if a.set_char:
        return cmd_set_char(a.set_char)
    if a.learn_pet:
        return cmd_learn_pet(a.learn_pet)
    if winenv.platform_kind() == 'linux':
        print('不是 WSL / Windows，無法讀遊戲視窗', file=sys.stderr)
        return 2
    _install_signals()                                  # 先裝訊號 handler，再 enable_server()（winenv 會串接）
    os.environ.setdefault('PSA_GUI_SERVER', '1')        # watch 強制走常駐 server（Windows 原生預設關也強制開；使用者顯式 =0 仍尊重）
    if a.once:
        return cmd_once(a.dump_px)
    if a.bench:
        return cmd_bench(a.bench)
    w = Watcher(owner=os.environ.get('PSA_WATCH_OWNER', ''), dump_px=a.dump_px)
    code, msg = w.acquire()
    if code:
        print(msg, file=sys.stderr, flush=True)
        return code
    winenv.enable_server()
    print(f'watch 啟動 pid={os.getpid()} token={w.token}' + (f'（{msg}）' if msg else ''), flush=True)
    try:
        return w.run()
    finally:
        w.finish()
        winenv.shutdown_server()
        print('watch 已結束', flush=True)


if __name__ == '__main__':
    sys.exit(main())
