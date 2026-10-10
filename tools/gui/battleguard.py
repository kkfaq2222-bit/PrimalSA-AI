#!/usr/bin/env python3
"""戰鬥中保護的共用零件（quest.py 與 ass.py 都 import；只用標準庫）：
1. 戰鬥畫面像素特徵（SIG_BATTLE / VS 牌）與 screen_in_battle()：一次 gui pixel 判斷現在是不是戰鬥畫面。
2. 戰鬥鎖檔 tools/.cache/battle.lock：quest.py 在戰鬥中寫入（pid + 開始時間），戰鬥結束 / 程式結束刪除；
   ass.py 看到「pid 還活著且不是太舊」的鎖檔就視為戰鬥中，不開外掛面板、不改勾選（2026-10-10 碧青洞窟事故：
   BOSS 戰開始 1 秒後外掛「自動逃跑」被打開 → 隊長脫隊、進度不一致）。
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_FILE = ROOT / 'tools' / '.cache' / 'battle.lock'
LOCK_MAX_AGE = 1800.0                # 鎖檔超過 30 分鐘一律當作過期（防 pid 被別的程式重用、程式被強殺沒清）

# 完整戰鬥畫面（2026-10-10 實測）：上方中央棕框外框 9 點，同時符合（容差 25）才算；下指令 / 播放中兩種畫面像素相同
SIG_BATTLE = [(650, 25, 99, 77, 57), (780, 38, 252, 234, 200), (645, 38, 99, 57, 31), (790, 38, 250, 227, 194), (645, 12, 244, 225, 182),
              (790, 12, 255, 230, 192), (660, 45, 200, 172, 139), (770, 45, 236, 209, 174), (643, 25, 242, 217, 181)]
VS_PROBE = (706, 295)                # 頭上 VS 牌綠框（快速戰鬥沒有戰鬥畫面，只有這個）
VS_COLOR = (122, 227, 0)


def _close(c, ref, tol):
    return all(abs(a - b) <= tol for a, b in zip(c, ref))


def classify_pixels(px: dict) -> bool:
    """px = {(x,y): (r,g,b)}（至少含 SIG_BATTLE 與 VS_PROBE 的點）→ 是不是戰鬥畫面（完整戰鬥 9 點全中，或 VS 牌綠框）"""
    if all(_close(px[(x, y)], (r, g, b), 25) for x, y, r, g, b in SIG_BATTLE):
        return True
    return _close(px[VS_PROBE], VS_COLOR, 40)


def screen_in_battle(gui) -> bool | None:
    """gui = walk.gui 之類的函式；一次 pixel 讀完 → True / False；讀不到回 None"""
    pts = [(x, y) for x, y, *_ in SIG_BATTLE] + [VS_PROBE]
    try:
        out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
        cols = [tuple(int(v) for v in c.split(',')) for c in out]
    except Exception:
        return None
    if len(cols) != len(pts):
        return None
    return classify_pixels(dict(zip(pts, cols)))


def pid_alive(pid: int) -> bool:
    """pid 是否還活著。Windows 的 os.kill(pid, 0) 會送 CTRL_C_EVENT（危險），所以 Windows 用 OpenProcess"""
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259          # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(note: str = '') -> None:
    """寫鎖檔（pid + 開始時間 + 註記）"""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(json.dumps({'pid': os.getpid(), 'start': time.time(), 'note': note}, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def release() -> None:
    """只刪自己寫的鎖（pid 相同才刪）"""
    try:
        d = json.loads(LOCK_FILE.read_text(encoding='utf-8'))
        if d.get('pid') == os.getpid():
            LOCK_FILE.unlink()
    except (OSError, ValueError):
        pass


def locked(now: float | None = None) -> dict | None:
    """有效鎖檔（pid 活著、不超過 LOCK_MAX_AGE）→ 回內容 dict；沒有 / 過期 / pid 已死 → None（死鎖順手清掉）"""
    now = time.time() if now is None else now
    try:
        d = json.loads(LOCK_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    ok = isinstance(d, dict) and isinstance(d.get('pid'), int) and now - float(d.get('start', 0)) <= LOCK_MAX_AGE and pid_alive(d['pid'])
    if not ok:
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass
        return None
    return d
