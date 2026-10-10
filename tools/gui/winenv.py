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
# 每個 Python 程序各自一個 server（lazily 啟動）；父程序結束 → stdin EOF → server 自己結束（另有 15 分鐘閒置看門狗）。
# ---------------------------------------------------------------------------------------------
SERVER_SCRIPTS = {'gui', 'ocr', 'stat', 'findmark', 'titlematch'}
# 各腳本 param 區塊裡「具名」參數（五支腳本都沒有 [switch]，所以「-名稱 值」成對拆進 named，其餘當位置參數）。
# 腳本改 param 時要同步這裡（_selftest 有檢查）。
SERVER_NAMED = {
    'gui': ('Scale', 'Note'),
    'ocr': ('X', 'Y', 'Wd', 'Ht', 'Zoom', 'Dark', 'Zooms', 'Light'),
    'stat': ('Shot', 'ShotWidth'),
    'findmark': ('Crop', 'Out', 'Zoom'),
    'titlematch': ('Mode', 'Dir', 'Image', 'Out', 'Y', 'Thr'),
}
INPUT_CMDS = {'click', 'dclick', 'drag', 'key', 'max', 'end', 'fg'}   # 會動到輸入 / 前景的 gui 指令：逾時不重送
START_TIMEOUT = 20.0
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
        if not t:
            continue
        if t[0] in INPUT_CMDS or (t[0] in ('ifok', 'ifnok') and len(t) > 1 and t[1] in INPUT_CMDS):
            is_input = True
        if t[0] in ('wait', 'waitpix', 'waitstill') and len(t) > 1 and t[1].isdigit():
            waits += int(t[1])
        if t[0] == 'ocr':
            waits += 0
    if is_input:
        return waits / 1000.0 * 2 + 30.0, True
    return 20.0 + waits / 1000.0 + (5.0 if waits else 0.0), False


class GuiServer:
    """一個 serve.ps1 子程序 + 讀取執行緒。call() 一次一個請求（lock 序列化）"""

    def __init__(self, argv: list[str] | None = None) -> None:
        self.argv = argv            # 測試用：指定啟動指令（假 server / 壞掉的 serve.ps1）；None = 真的 serve.ps1
        self.proc = None
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.next_id = 0
        self.mtimes: dict = {}
        self.mt_checked = 0.0

    # ---- 啟動 / 關閉 ----
    def _argv(self) -> list[str]:
        if self.argv:
            return self.argv
        return ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                '-File', to_windows(GUI_DIR / 'serve.ps1')]

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
        _start_fails = 0
        self.mtimes = self._watch_files()
        self.mt_checked = time.time()
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
        """關閉 server：送 quit、等 1 秒、不行就 kill。不拿鎖（atexit 時主執行緒可能卡在 call）"""
        p, self.proc = self.proc, None
        if not p:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(b'{"id":0,"cmd":"quit"}\n')
                    p.stdin.flush()
                    p.stdin.close()
                except (OSError, ValueError):
                    pass
                try:
                    p.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    p.kill()
        except OSError:
            pass

    # ---- 呼叫 ----
    def _ensure(self) -> bool:
        now = time.time()
        if self.alive() and now - self.mt_checked >= 1.0:       # 熱重載：腳本改了就重開（stat 走 9P，每秒最多一次）
            self.mt_checked = now
            if self._watch_files() != self.mtimes:
                self.close()
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
            return r

    def admin(self, cmd: str, timeout: float = 10.0) -> dict | None:
        """管理指令（ping / stats），給 bench / 除錯用"""
        with self.lock:
            if not self._ensure():
                return None
            st, m = self._request({'cmd': cmd}, timeout)
            return m if st == 'ok' else None


def _server() -> GuiServer:
    global _srv
    if _srv is None:
        _srv = GuiServer()
        atexit.register(_srv.close)
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
