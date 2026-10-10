#!/usr/bin/env python3
"""平台判斷與路徑換算（只用標準函式庫）：WSL、Windows 原生（含 Git Bash / MSYS）兩邊都能呼叫 powershell.exe 跑 gui.ps1。

  import winenv
  winenv.platform_kind()          # 'wsl' | 'windows' | 'linux'（純 Linux 無法操作遊戲）
  winenv.ROOT                     # 專案根目錄（由本檔位置推算，不寫死）
  winenv.to_windows(path)         # 專案內（或任意）路徑 → Windows 路徑字串，給 powershell.exe 當參數
  winenv.ps_argv('gui.ps1', 'info')   # → ['powershell.exe', '-NoProfile', ..., '-File', <Windows 路徑>, 'info']
  winenv.run_ps('gui.ps1', 'shot')    # 執行並回傳 CompletedProcess（UTF-8、errors=replace、已去掉 \\r）
  winenv.enable_server()          # 長程序（quest / heal / petwatch / walk 主流程）明確呼叫；目前預設關，PSA_GUI_SERVER=1 才走常駐 serve.ps1（=0 一律關）

命令列自測：python tools/gui/winenv.py
"""
import atexit
import json
import os
import posixpath
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / 'tools' / 'gui'
PS_PREFIX = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass']


def platform_kind(plat: str | None = None, proc_version: str | None = None, env: dict | None = None) -> str:
    """'windows'（原生 Python / Git Bash / MSYS / Cygwin）、'wsl'、'linux'。參數供測試時模擬。"""
    plat = sys.platform if plat is None else plat
    env = os.environ if env is None else env
    if plat in ('win32', 'cygwin', 'msys') or env.get('MSYSTEM'):
        return 'windows'
    if proc_version is None:
        try:
            proc_version = Path('/proc/version').read_text(errors='replace')
        except OSError:
            proc_version = ''
    if 'microsoft' in proc_version.lower() or env.get('WSL_DISTRO_NAME'):
        return 'wsl'
    return 'linux'


def to_windows(path, kind: str | None = None, wslpath=None) -> str:
    """路徑 → Windows 路徑字串。windows：原樣轉反斜線（Git Bash 的 /c/x 也會換成 C:\\x）；
    wsl：先試 wslpath -w，失敗改用 /mnt/<磁碟>/ 規則手算。"""
    kind = kind or platform_kind()
    s = str(path)
    if kind == 'windows':
        m = re.match(r'^/(?:cygdrive/|mnt/)?([A-Za-z])(?:/(.*))?$', s)   # Git Bash：/c/games、Cygwin：/cygdrive/c/games
        if m and not re.match(r'^[A-Za-z]:', s):
            s = f'{m[1].upper()}:/{m[2] or ""}'
        return s.replace('/', '\\')
    if kind == 'wsl':
        s = posixpath.abspath(s)
        try:
            run = wslpath or (lambda p: subprocess.run(['wslpath', '-w', p], capture_output=True, text=True, timeout=10).stdout)
            out = run(s).strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
        m = re.match(r'^/mnt/([a-z])(?:/(.*))?$', s)
        if m:
            return f'{m[1].upper()}:\\' + (m[2] or '').replace('/', '\\')
        raise ValueError(f'WSL 無法換算成 Windows 路徑：{s}')
    raise RuntimeError('不是 WSL / Windows，無法操作遊戲視窗')


def ps_argv(script: str, *args: str) -> list[str]:
    """script 可以是檔名（相對 tools/gui）或絕對路徑；回傳 powershell.exe 的完整 argv"""
    p = Path(script)
    if not p.is_absolute():
        p = GUI_DIR / p
    return [*PS_PREFIX, '-File', to_windows(p), *map(str, args)]


def _oneshot(script: str, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    """一次性：每次啟動一個 powershell.exe -File（原本的做法）"""
    r = subprocess.run(ps_argv(script, *args), capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    r.stdout = (r.stdout or '').replace('\r', '')
    r.stderr = (r.stderr or '').replace('\r', '')
    return r


def run_ps(script: str, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    """跑 .ps1；stdout / stderr 以 UTF-8 解碼（gui.ps1 有設 UTF-8 輸出），\\r 去掉。
    呼叫過 enable_server() 的程序、且是 tools/gui 底下五支白名單腳本 → 走常駐 server（GuiServer），否則一次性。
    逾時一律丟 subprocess.TimeoutExpired（與一次性相同，呼叫端不用改）。"""
    if _server_wanted(script):
        r = _server().call(script, [str(a) for a in args], timeout)
        if r is not None:
            return r
        # None = server 起不來 / 指令還沒送出：退回一次性（安全，沒有任何動作被執行過）
    return _oneshot(script, *args, timeout=timeout)


# ---------------------------------------------------------------------------------------------
# 常駐 server（serve.ps1）client。協定與設計見 notes/plan-gui-speedup.md 3.3 / 3.4。
# 每個 Python 程序各自一個 server（lazily 啟動）。「程序結束後 server 一定要結束」靠五層保險（2026-10-10 追查 serve.ps1 殘留後加固）：
#   ① atexit / quest.main 的 finally 明確呼叫 close()：送 quit → 關 stdin → 等 CLOSE_WAIT 秒 → 還活著就 kill WSL 這側的 interop 代理，
#      並用記下的 Windows PID `taskkill /f`（殺代理不保證 Windows 側的 powershell.exe 跟著死）；
#   ② SIGTERM / SIGHUP 先 close() 再 raise SystemExit（讓 finally / atexit 跑；呼叫端自裝 handler 則串接）；
#   ③ 父程序死掉 → stdin EOF → server 自己結束；
#   ④ serve.ps1 閒置看門狗 SERVER_IDLE_MIN 分鐘（舊 15 分鐘；到期無聲結束，所以 client 閒置超過 IDLE−15 s 先重開再送）；
#      serve.ps1 記憶體 / GDI 自保要退出時，最後一個回應帶 bye=true，client 收到就主動 close；
#   ⑤ gui-server.pids 登記「擁有者 Python PID ↔ server Windows PID」：下次有程序起 server 時，擁有者已死的殘留 server 一併清掉（reap_orphans；登記含平台，只回收同平台）。
# ---------------------------------------------------------------------------------------------
SERVER_SCRIPTS = {'gui', 'ocr', 'stat', 'findmark', 'titlematch'}
# 各腳本 param 區塊裡「具名」參數（五支腳本都沒有 [switch]，所以「-名稱 值」成對拆進 named，其餘當位置參數）。
# 腳本改 param 時要同步這裡（test_winenv_server.py 的「白名單與 ps1 param 區塊同步」會檢查；_selftest 只測路徑換算）。
SERVER_NAMED = {
    'gui': ('Scale', 'Note', 'NoRestore'),
    'ocr': ('X', 'Y', 'Wd', 'Ht', 'Zoom', 'Dark', 'Zooms', 'Light'),
    'stat': ('Shot', 'ShotWidth'),
    'findmark': ('Crop', 'Out', 'Zoom'),
    'titlematch': ('Mode', 'Dir', 'Image', 'Out', 'Y', 'Thr'),
}
INPUT_CMDS = {'click', 'dclick', 'drag', 'key', 'max', 'end', 'fg'}   # 會動到輸入 / 前景的 gui 指令：逾時不重送
START_TIMEOUT = 20.0
IDLE_MARGIN = 15.0          # client 閒置超過 (SERVER_IDLE_MIN*60 − 此秒數) 就先重開 server
SERVER_IDLE_MIN = 3         # serve.ps1 閒置看門狗（分鐘）：長程序每秒都有請求，不會誤殺；殘留的 server 最多活這麼久
CLOSE_WAIT = 2.0            # close()：送 quit + 關 stdin 後等 server 自己退出的秒數，逾時才 kill
PIDS_FILE = ROOT / 'tools' / '.cache' / 'gui-server.pids'   # 登記擁有者 / server PID，給 reap_orphans 用
START_FAILS_MAX = 3         # 連續起不來幾次就退回一次性
COOLDOWN = 300.0            # 退回一次性的冷卻秒數
DEFAULT_ON = False          # 預設關：完整跑過一次真實任務、使用者同意後才改 True；在此之前用環境變數 PSA_GUI_SERVER=1 試用
_enabled = False
_cooldown_until = 0.0
_start_fails = 0
_srv = None
_errlog_last: dict = {}


def enable_server() -> None:
    """長程序明確呼叫一次：標記「這個程序適合用常駐 server」。短命程序不要呼叫（起 server 要 ~0.5 秒）。
    實際是否啟用還要看 DEFAULT_ON 或環境變數 PSA_GUI_SERVER=1（=0 一律關閉）。"""
    global _enabled
    _enabled = True


def split_named(script: str, args) -> tuple[list[str], dict[str, str]]:
    """argv → (位置參數, 具名參數)。「-Name 值」且 Name 在該腳本白名單 → named（值一律字串，原樣傳）；其餘為位置參數"""
    names = {n.lower(): n for n in SERVER_NAMED.get(script, ())}
    pos: list[str] = []
    named: dict[str, str] = {}
    a = list(args)
    i = 0
    while i < len(a):
        m = re.fullmatch(r'-([A-Za-z]+)', a[i])
        if m and m[1].lower() in names and i + 1 < len(a):
            named[names[m[1].lower()]] = a[i + 1]
            i += 2
        else:
            pos.append(a[i])
            i += 1
    return pos, named


def _server_wanted(script: str) -> bool:
    env = os.environ.get('PSA_GUI_SERVER')
    if not _enabled or env == '0' or not (DEFAULT_ON or env == '1') or time.time() < _cooldown_until:
        return False
    p = Path(script)
    if p.is_absolute() and p.parent != GUI_DIR:
        return False
    return p.stem in SERVER_SCRIPTS and p.suffix == '.ps1' and platform_kind() != 'linux'


def _log_err(kind: str, msg: str) -> None:
    """errlog 限頻：同一種錯 5 分鐘最多一筆（psa-hud 會顯示 errlog，不能洗版）"""
    now = time.time()
    if now - _errlog_last.get(kind, 0) < 300:
        return
    _errlog_last[kind] = now
    try:
        sys.path.insert(0, str(GUI_DIR))
        import errlog
        errlog.add(msg, source='winenv')
    except Exception:
        pass


def estimate_timeout(script: str, pos: list[str], named: dict[str, str]) -> tuple[float, bool]:
    """(逾時秒數, 是否輸入類)。唯讀預設 20 s；waitpix / waitstill = 指令逾時 + 5 s；ocr -Zooms 每倍數 +2 s；
    輸入類（click / dclick / drag / key / max / end / fg，含 seq 裡有這些）= seq 內等待毫秒總和 ×2 + 30 s"""
    if script != 'gui':
        n = len([z for z in named.get('Zooms', '').split(',') if z.strip()])
        return 20.0 + 2.0 * n, False
    cmd = pos[0] if pos else ''
    steps = [s.split() for s in (pos[1].split(';') if cmd == 'seq' and len(pos) > 1 else [' '.join(pos)])]
    waits = 0
    is_input = False
    for t in steps:
        while t and t[0] in ('ifok', 'ifnok', 'fg') and len(t) > 1:   # 剝掉條件 / 前景前綴再判斷真正的指令
            t = t[1:]
        if not t:
            continue
        if t[0] in INPUT_CMDS:
            is_input = True
        if t[0] in ('wait', 'waitpix') and len(t) > 1 and t[1].isdigit():
            waits += int(t[1])
        elif t[0] == 'waitstill':          # waitstill <逾時> [開始等待]：兩個參數相加（最壞情況）
            waits += sum(int(x) for x in t[1:3] if x.isdigit())
    if is_input:
        return waits / 1000.0 * 2 + 30.0, True
    return 20.0 + waits / 1000.0 + (5.0 if waits else 0.0), False


def is_input_call(script: str, args) -> bool:
    """這個呼叫是不是輸入類（會動到輸入 / 前景）：給呼叫端決定逾時後能不能當「讀圖失敗」略過"""
    name = Path(script).stem
    pos, named = split_named(name, [str(a) for a in args])
    return estimate_timeout(name, pos, named)[1]


class GuiServer:
    """一個 serve.ps1 子程序 + 讀取執行緒。call() 一次一個請求（lock 序列化）"""

    def __init__(self, argv: list[str] | None = None) -> None:
        self.argv = argv            # 測試用：指定啟動指令（假 server / 壞掉的 serve.ps1）；None = 真的 serve.ps1
        self.proc = None
        self.win_pid = None         # server（Windows 側 powershell.exe）的 PID，ready 訊息帶回；close() 殺不掉代理時用它 taskkill
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.next_id = 0
        self.mtimes: dict = {}
        self.mt_checked = 0.0
        self.last_resp = 0.0        # 上次收到回應的時間：閒置快到期的 server 先重開，避免輸入類請求被看門狗無聲吃掉

    # ---- 啟動 / 關閉 ----
    def _argv(self) -> list[str]:
        if self.argv:
            return self.argv
        return ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', to_windows(GUI_DIR / 'serve.ps1'), '-IdleMin', str(SERVER_IDLE_MIN)]

    def _reader(self, proc, q) -> None:
        """逐行讀 server stdout（bytes）；每行去 U+FEFF、整行找 \\x1ePSA 標記（不要求行首）；EOF 放哨兵 None"""
        try:
            for raw in iter(proc.stdout.readline, b''):
                line = raw.decode('utf-8', errors='replace').replace('\ufeff', '')
                i = line.find('\x1ePSA ')
                if i < 0:
                    continue   # 雜訊行（除錯用可在這裡記）
                try:
                    q.put(json.loads(line[i + 5:]))
                except ValueError:
                    pass
        except (OSError, ValueError):
            pass
        q.put(None)

    def _watch_files(self) -> dict:
        d = {}
        for n in ['serve', *SERVER_SCRIPTS]:
            try:
                d[n] = (GUI_DIR / f'{n}.ps1').stat().st_mtime
            except OSError:
                d[n] = 0
        return d

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> bool:
        global _start_fails, _cooldown_until
        self.close()
        if self.argv is None:
            reap_orphans()           # 先清掉擁有者已死的舊 server（測試用假 server 不碰）
        err = None
        try:
            ep = ROOT / 'tools' / '.cache' / 'gui-server.err'
            ep.parent.mkdir(parents=True, exist_ok=True)
            if ep.exists() and ep.stat().st_size > 200_000:
                ep.write_bytes(b'')
            err = open(ep, 'ab')
            kw = {'creationflags': 0x08000000} if platform_kind() == 'windows' else {}   # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, **kw)
        except (OSError, ValueError, RuntimeError) as e:
            self.proc = None
            return self._start_failed(f'無法啟動 serve.ps1：{e}')
        finally:
            if err:
                err.close()   # 子程序已繼承
        self.q = queue.Queue()
        threading.Thread(target=self._reader, args=(self.proc, self.q), daemon=True).start()
        try:
            ready = self.q.get(timeout=START_TIMEOUT)
        except queue.Empty:
            ready = None
        if not ready or not ready.get('ready'):
            self.close()
            return self._start_failed('serve.ps1 沒有在時限內回 ready')
        self.win_pid = ready.get('pid') if isinstance(ready.get('pid'), int) else None
        if self.argv is None:
            _pids_add(os.getpid(), self.win_pid)      # 只登記真的 serve.ps1（測試用假 server 的 pid 是 Linux 側的，不能讓 reap 拿去殺 Windows 行程）
        _start_fails = 0
        self.mtimes = self._watch_files()
        self.mt_checked = time.time()
        self.last_resp = time.time()
        return True

    def _start_failed(self, why: str) -> bool:
        global _start_fails, _cooldown_until
        _start_fails += 1
        if _start_fails >= START_FAILS_MAX:
            _cooldown_until = time.time() + COOLDOWN
            _start_fails = 0
            _log_err('start', f'常駐 server 連續起不來（{why}），退回一次性執行 {int(COOLDOWN)} 秒')
        return False

    def close(self) -> None:
        """關閉 server：送 quit、關 stdin、等 CLOSE_WAIT 秒；還活著就 kill 代理並用 Windows PID taskkill。不拿鎖（atexit 時主執行緒可能卡在 call）。
        回來時保證 server 已結束（或已盡力殺過）"""
        p, self.proc = self.proc, None
        wpid, self.win_pid = self.win_pid, None
        if not p:
            return
        exited = False
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(b'{"id":0,"cmd":"quit"}\n')
                    p.stdin.flush()
                except (OSError, ValueError):
                    pass
                try:
                    p.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    p.wait(timeout=CLOSE_WAIT)
                    exited = True
                except subprocess.TimeoutExpired:
                    p.kill()
                    try:
                        p.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
            else:
                exited = True
        except OSError:
            pass
        if not exited and wpid:
            _taskkill(wpid)          # 代理被殺 ≠ Windows 側 powershell.exe 一定跟著死
        if wpid:
            _pids_remove(wpid)

    # ---- 呼叫 ----
    def _ensure(self) -> bool:
        now = time.time()
        if self.alive() and now - self.mt_checked >= 1.0:       # 熱重載：腳本改了就重開（stat 走 9P，每秒最多一次）
            self.mt_checked = now
            if self._watch_files() != self.mtimes:
                self.close()
        if self.alive() and self.last_resp and now - self.last_resp > SERVER_IDLE_MIN * 60 - IDLE_MARGIN:
            self.close()           # serve.ps1 閒置看門狗快到期（到期直接 Exit、不通知）：趁還沒送請求先重開
        return self.alive() or self.start()

    def _request(self, req: dict, timeout: float):
        """送一個請求並等對應 id 的回應。回 (狀態, 回應 dict)：狀態 'ok' / 'notsent' / 'eof' / 'timeout'"""
        self.next_id += 1
        rid = self.next_id
        req['id'] = rid
        try:
            self.proc.stdin.write((json.dumps(req, ensure_ascii=True) + '\n').encode('ascii'))
            self.proc.stdin.flush()
        except (OSError, ValueError):       # Windows 原生寫死管線常是 OSError(EINVAL)，不一定是 BrokenPipeError
            return 'notsent', None
        q = self.q
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                return 'timeout', None
            try:
                m = q.get(timeout=left)
            except queue.Empty:
                return 'timeout', None
            if m is None:
                return 'eof', None
            if m.get('id') == rid:
                self.last_resp = time.time()
                return 'ok', m
            # id 不符（逾時後晚到的舊回應）→ 丟棄

    def call(self, script: str, args: list[str], timeout: float | None):
        """回 CompletedProcess；回 None = 請呼叫端退回一次性（server 起不來，或請求確定沒送出）。
        逾時丟 subprocess.TimeoutExpired。server 中途死掉：唯讀指令重開重試一次；輸入類不重送（回 rc=125）"""
        name = Path(script).stem
        pos, named = split_named(name, args)
        est, is_input = estimate_timeout(name, pos, named)
        tmo = timeout if timeout is not None else est
        req = {'script': name, 'pos': pos, 'named': named}
        with self.lock:
            for attempt in (1, 2):
                if not self._ensure():
                    return None
                st, m = self._request(dict(req), tmo)
                if st == 'ok':
                    break
                if st == 'timeout':
                    self.close()
                    _log_err('timeout', f'常駐 server 請求逾時（{name} {" ".join(pos)[:40]}，{tmo:.0f}s），已重開')
                    raise subprocess.TimeoutExpired(self._argv(), tmo)
                if st == 'notsent':
                    self.close()
                    if attempt == 1:
                        continue      # 還沒送出，重開後再送（不會重複執行）
                    return None
                # eof：server 在處理請求時死了（可能被 kill）
                self.close()
                _log_err('eof', f'常駐 server 中途結束（{name} {" ".join(pos)[:40]}）')
                if is_input or attempt == 2:
                    return subprocess.CompletedProcess(self._argv(), 125, '', 'server 中途結束，輸入類指令不重送\n')
            r = subprocess.CompletedProcess(self._argv(), int(m.get('rc', 1)), m.get('out', '') or '', m.get('err', '') or '')
            r.stdout = r.stdout.replace('\r', '')
            r.stderr = r.stderr.replace('\r', '')
            if m.get('bye'):
                self.close()       # server 自保（記憶體 / GDI）要退出：回應已拿到，主動關掉，下次呼叫重開
            return r

    def admin(self, cmd: str, timeout: float = 10.0) -> dict | None:
        """管理指令（ping / stats），給 bench / 除錯用"""
        with self.lock:
            if not self._ensure():
                return None
            st, m = self._request({'cmd': cmd}, timeout)
            return m if st == 'ok' else None


def _taskkill(pid: int) -> bool:
    """強制結束 Windows 行程 pid（WSL：taskkill.exe 經 interop；Windows 原生：taskkill）。失敗回 False，不丟例外"""
    try:
        subprocess.run(['taskkill.exe', '/pid', str(int(pid)), '/f'], capture_output=True, timeout=8)
        return True
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _kill_if_serve(pid: int) -> bool:
    """殺殘留 server 前先確認該 PID 現在真的還是 serve.ps1（PID 可能已被別的程式重用）：命令列含 serve.ps1 才 Stop-Process。
    回 True = 已處理（殺了，或該 PID 已不存在 / 已不是 serve.ps1，不必再追）；False = 呼叫 powershell 失敗，保留登記下次再試"""
    cmd = (f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' -ErrorAction SilentlyContinue; "
           f"if ($p -and $p.CommandLine -match 'serve\\.ps1') {{ Stop-Process -Id {int(pid)} -Force; 'killed' }} else {{ 'gone' }}")
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', cmd], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and r.stdout.strip() in ('killed', 'gone')
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _pids_load() -> list:
    try:
        d = json.loads(PIDS_FILE.read_text(encoding='utf-8'))
        return [e for e in d if isinstance(e, dict) and isinstance(e.get('owner'), int) and isinstance(e.get('win'), int)] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _pids_save(entries: list) -> None:
    """原子寫（先寫暫存檔再 os.replace），避免讀到寫一半的檔"""
    try:
        PIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PIDS_FILE.with_name(f'{PIDS_FILE.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(entries), encoding='utf-8')
        os.replace(tmp, PIDS_FILE)
    except OSError:
        pass


def _pids_update(fn) -> None:
    """鎖檔下讀 → fn(entries) 回傳新清單 → 寫回（read-modify-write 不掉項目）。
    鎖 = O_EXCL 建立 .lock；鎖超過 5 秒視為殘留強制接管；等不到鎖也照做（只是回到無鎖行為，不卡住）"""
    lock = PIDS_FILE.with_name(PIDS_FILE.name + '.lock')
    have = False
    try:
        PIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        while time.time() - t0 < 3.0:
            try:
                os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                have = True
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 5.0:
                        lock.unlink()
                        continue
                except OSError:
                    pass
                time.sleep(0.02)
            except OSError:
                break
        _pids_save(fn(_pids_load()))
    finally:
        if have:
            try:
                lock.unlink()
            except OSError:
                pass


def _pids_add(owner: int, win: int | None) -> None:
    """登記 server：記平台（wsl / windows）與擁有者 PID；PID 空間依平台不同，reap 只認同平台的"""
    if win:
        ent = {'owner': owner, 'win': win, 'plat': platform_kind(), 't': int(time.time())}
        _pids_update(lambda es: [e for e in es if e['win'] != win] + [ent])


def _pids_remove(win: int) -> None:
    if any(e['win'] == win for e in _pids_load()):
        _pids_update(lambda es: [e for e in es if e['win'] != win])


def _owner_alive(pid: int) -> bool:
    """擁有者 Python 是否還活著（Windows 原生用 OpenProcess，其他平台 kill 0；WSL 的 PID 是 Linux 側的）"""
    if pid == os.getpid():
        return True
    if sys.platform == 'win32':
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_orphans(alive=None, kill=None, plat: str | None = None) -> int:
    """清掉「擁有者 Python 已死」的殘留 serve.ps1（登記在 PIDS_FILE）。alive / kill / plat 可替換給測試。回清掉幾個。
    只殺：同平台登記的（WSL 與 Windows 原生的 PID 空間不同，不能互查）、擁有者確定已死、且該 PID 現在命令列仍是 serve.ps1（_kill_if_serve）。
    不同平台的、擁有者還活著的一律不碰；沒記平台的舊格式項目無法判斷 → 只從登記檔移除、不殺（靠 server 閒置看門狗收尾）"""
    alive = alive or _owner_alive
    kill = kill or _kill_if_serve
    me = plat or platform_kind()
    n = 0

    def fn(es):
        nonlocal n
        keep = []
        for e in es:
            if not e.get('plat'):
                continue                      # 舊格式：丟掉登記
            if e['plat'] != me or alive(e['owner']):
                keep.append(e)
            elif e['win'] > 0 and kill(e['win']):
                n += 1
            else:
                keep.append(e)                # 殺失敗，下次再試
        return keep

    if _pids_load():
        _pids_update(fn)
    return n


def server_alive() -> bool:
    """唯讀：本程序的常駐 server 現在是否在跑（watch 用來判斷「下一次呼叫會不會要先重開 server」）"""
    return _srv is not None and _srv.alive()


def shutdown_server() -> None:
    """明確關掉本程序的常駐 server（長程序結束前呼叫，例如 quest.main 的 finally；不依賴 atexit）。沒開過 = 不做事；可重複呼叫"""
    if _srv is not None:
        _srv.close()


def _on_signal(signum, frame) -> None:
    """SIGTERM / SIGHUP：先關 server，再讓程序照常結束（Python 預設直接死、不跑 atexit / finally）。
    呼叫端先裝了自己的 handler → 關完 server 串接呼叫它（由它決定怎麼結束）；原本是忽略 → 只關 server；
    否則 raise SystemExit(128+訊號)，讓呼叫端的 finally / atexit 清理照跑"""
    try:
        if _srv is not None:
            _srv.close()
    finally:
        prev = _prev_handlers.get(signum)
        if callable(prev):
            prev(signum, frame)
        elif prev == signal.SIG_IGN:
            pass
        else:
            raise SystemExit(128 + int(signum))


_prev_handlers: dict = {}


def _install_signal_handlers() -> None:
    """只在主執行緒裝（signal.signal 的限制）；已被別人裝過自訂 handler 的會在 close 後轉呼叫原 handler"""
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ('SIGTERM', 'SIGHUP'):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            _prev_handlers[sig] = signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass


def _server() -> GuiServer:
    global _srv
    if _srv is None:
        _srv = GuiServer()
        atexit.register(_srv.close)
        _install_signal_handlers()
    return _srv


def _selftest() -> None:
    # 模擬 Windows 原生（Python 的路徑本來就是 C:\...；Git Bash 風格 /c/... 也要通）
    assert platform_kind('win32', '', {}) == 'windows'
    assert platform_kind('linux', '', {'MSYSTEM': 'MINGW64'}) == 'windows'
    assert to_windows(r'C:\games\PrimalSA-AI\tools\gui\gui.ps1', 'windows') == r'C:\games\PrimalSA-AI\tools\gui\gui.ps1'
    assert to_windows('C:/games/PrimalSA-AI/x.png', 'windows') == r'C:\games\PrimalSA-AI\x.png'
    assert to_windows('/c/games/PrimalSA-AI/x.png', 'windows') == r'C:\games\PrimalSA-AI\x.png'
    # 模擬 WSL（wslpath 可用 / 不可用兩種）
    assert platform_kind('linux', 'Linux 6.1 microsoft-standard-WSL2', {}) == 'wsl'
    assert platform_kind('linux', 'Linux 6.1 generic', {}) == 'linux'
    fake = lambda p: 'C:\\' + p[len('/mnt/c/'):].replace('/', '\\')
    assert to_windows('/mnt/c/games/PrimalSA-AI/a.ps1', 'wsl', fake) == r'C:\games\PrimalSA-AI\a.ps1'
    def broken(p): raise OSError('no wslpath')
    assert to_windows('/mnt/d/x/y.png', 'wsl', broken) == r'D:\x\y.png'
    # 實際環境
    k = platform_kind()
    print('實際環境：', k, '| ROOT =', ROOT)
    if k != 'linux':
        print('gui.ps1 →', ps_argv('gui.ps1')[-1])
    print('winenv 自測通過')


if __name__ == '__main__':
    _selftest()
