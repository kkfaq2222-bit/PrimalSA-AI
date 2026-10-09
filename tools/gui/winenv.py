#!/usr/bin/env python3
"""平台判斷與路徑換算（只用標準函式庫）：WSL、Windows 原生（含 Git Bash / MSYS）兩邊都能呼叫 powershell.exe 跑 gui.ps1。

  import winenv
  winenv.platform_kind()          # 'wsl' | 'windows' | 'linux'（純 Linux 無法操作遊戲）
  winenv.ROOT                     # 專案根目錄（由本檔位置推算，不寫死）
  winenv.to_windows(path)         # 專案內（或任意）路徑 → Windows 路徑字串，給 powershell.exe 當參數
  winenv.ps_argv('gui.ps1', 'info')   # → ['powershell.exe', '-NoProfile', ..., '-File', <Windows 路徑>, 'info']
  winenv.run_ps('gui.ps1', 'shot')    # 執行並回傳 CompletedProcess（UTF-8、errors=replace、已去掉 \\r）

命令列自測：python tools/gui/winenv.py
"""
import os
import posixpath
import re
import subprocess
import sys
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


def run_ps(script: str, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    """跑 .ps1；stdout / stderr 以 UTF-8 解碼（gui.ps1 有設 UTF-8 輸出），\\r 去掉"""
    r = subprocess.run(ps_argv(script, *args), capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    r.stdout = (r.stdout or '').replace('\r', '')
    r.stderr = (r.stderr or '').replace('\r', '')
    return r


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
