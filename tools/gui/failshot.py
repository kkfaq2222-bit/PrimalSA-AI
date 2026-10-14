#!/usr/bin/env python3
"""失敗現場存圖（2026-10-15 使用者要求：所有停手 / 暫時性失敗都留一張圖，事後看原因）。

圖：tools/.cache/fail/<YYYYmmdd-HHMMSS>-<來源>-<原因雜湊>.png
記錄：tools/.cache/stats-fail.jsonl 一行一筆 {at, src, client, reason, shot}（stats.py errors 讀來對截圖）
保留：同一原因（數字視為相同）只留最近 KEEP_PER_REASON 張、整個資料夾最多 KEEP_TOTAL 張，舊的刪掉。
截圖只讀畫面（gui shot，背景 PrintWindow），不點不按；任何錯誤都吞掉，不影響呼叫端流程。

用法：
  failshot.shot('questflow', '傳送後沒出現 NPC 對話窗')   # 現在存
  failshot.pre('questflow', '...')                       # 要先 ESC 復原畫面再停手時：ESC 前先存，
                                                         # 之後同一程序的下一次 shot() 直接沿用這張（不重拍）
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'
FAIL_DIR = CACHE / 'fail'
LOG = CACHE / 'stats-fail.jsonl'
KEEP_PER_REASON = 3
KEEP_TOTAL = 200
PENDING_S = 300          # pre() 存的圖多久內可被 shot() 沿用
DEDUP_S = 20             # 資料夾裡最新一張比這還新 → 沿用（子程序剛拍過、上層又停手時不重拍同一個畫面）

ENABLED = True           # 離線測試設 False（或環境變數 PSA_FAILSHOT=0）
_pending = None          # (time, path) ← pre()


def norm(reason: str) -> str:
    """同 stats._norm：數字 → #、空白收斂、去頭尾標點，取前 60 字（同一原因歸同一組）"""
    r = re.sub(r'\d+', '#', str(reason))
    r = re.sub(r'\s+', ' ', r).strip(' ：:，,')
    return r[:60]


def key(reason: str) -> str:
    return hashlib.md5(norm(reason).encode('utf-8')).hexdigest()[:8]


def _client() -> str:
    return os.environ.get('PSA_EXE_MATCH', '') or '?'


def _grab(path: Path) -> bool:
    import walk
    import winenv
    walk.gui('shot', winenv.to_windows(path))
    return path.exists()


def prune(folder: Path = None, per_reason: int = KEEP_PER_REASON, total: int = KEEP_TOTAL) -> int:
    """依檔名（時間在前，可直接排序）刪舊圖：每個原因雜湊留最新 per_reason 張，全部留最新 total 張"""
    folder = FAIL_DIR if folder is None else folder
    try:
        files = sorted((f for f in folder.glob('*.png') if f.is_file()), key=lambda f: f.name, reverse=True)
    except OSError:
        return 0
    keep, seen, n = [], {}, 0
    for f in files:
        h = f.stem.rsplit('-', 1)[-1]
        seen[h] = seen.get(h, 0) + 1
        if seen[h] > per_reason or len(keep) >= total:
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
        else:
            keep.append(f)
    return n


def _record(src: str, reason: str, shot) -> None:
    try:
        with open(LOG, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'src': src, 'client': _client(),
                                 'reason': str(reason)[:200], 'shot': shot}, ensure_ascii=False) + '\n')
    except OSError:
        pass


def enabled() -> bool:
    """離線測試（unittest / pytest 已載入）一律不拍，免得測試去截真遊戲畫面、寫記錄"""
    return ENABLED and os.environ.get('PSA_FAILSHOT') != '0' and not ({'unittest', 'pytest'} & set(sys.modules))


def _take(src: str, reason: str):
    if not enabled():
        return None
    try:
        FAIL_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^0-9A-Za-z_]', '_', src)[:20]
        p = FAIL_DIR / f'{time.strftime("%Y%m%d-%H%M%S")}-{safe}-{key(reason)}.png'
        if not _grab(p):
            return None
        prune()
        return str(p.relative_to(ROOT)).replace('\\', '/')
    except Exception:
        return None


def _recent():
    try:
        f = max(FAIL_DIR.glob('*.png'), key=lambda f: f.stat().st_mtime)
        if time.time() - f.stat().st_mtime <= DEDUP_S:
            return f.relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        pass
    return None


def pre(src: str, reason: str = ''):
    """ESC 復原畫面之前先存圖；下一次 shot() 沿用（不記錄，記錄由 shot() 寫，原因以停手訊息為準）"""
    global _pending
    p = _take(src, reason or src)
    _pending = (time.time(), p) if p else None
    return p


def shot(src: str, reason: str):
    """存圖 + 記一行 stats-fail.jsonl；回圖檔相對路徑（失敗 / 停用回 None）"""
    global _pending
    if not enabled():
        return None
    if _pending and time.time() - _pending[0] <= PENDING_S:
        p = _pending[1]
        _pending = None
        # pre() 存檔時不知道最後的原因：改名成停手原因的雜湊，保留規則才會對到同一組
        try:
            old = ROOT / p
            new = old.with_name(old.stem.rsplit('-', 1)[0] + f'-{key(reason)}.png')
            if old != new:
                old.replace(new)
            p = str(new.relative_to(ROOT)).replace('\\', '/')
        except OSError:
            pass
    else:
        _pending = None
        p = _recent() or _take(src, reason)
    _record(src, reason, p)
    return p


def latest_by_reason(log: Path = None) -> dict:
    """stats.py 用：norm(原因) → 最新一張還在的截圖路徑"""
    log = LOG if log is None else log
    out = {}
    try:
        lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get('shot') and (ROOT / d['shot']).exists():
            out[norm(d.get('reason', ''))] = d['shot']
    return out
