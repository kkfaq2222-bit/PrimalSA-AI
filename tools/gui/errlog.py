#!/usr/bin/env python3
"""錯誤 / 改進紀錄（只用標準函式庫）：tools/.cache/errlog.jsonl，只留最新 100 筆，psa-hud pane 會顯示。

遇到錯誤、失誤、卡關時記一筆；改進（改程式 / 改流程 / 補文件）後補 fix。
  import errlog
  i = errlog.add('quest.py 領完獎勵空等 77 秒', source='quest')   # 回傳 id
  errlog.fix(i, '閒置 5 秒就結束')                                 # fix('last', ...) = 最後一筆
命令列：
  python tools/gui/errlog.py add "錯誤描述" [--fix "改進"] [--source quest]
  python tools/gui/errlog.py fix <id|last> "改進"
  python tools/gui/errlog.py list
每行一筆 JSON：{id, ts(毫秒), error, fix, source}；fix 為 null = 待改進。寫入失敗一律忽略。
多程序同時寫：讀改寫整檔期間持 O_EXCL 鎖檔（errlog.jsonl.lock）+ 暫存檔 os.replace 原子寫，不會互蓋。
"""
import contextlib
import json
import os
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / '.cache' / 'errlog.jsonl'
KEEP = 100
LOCK_STALE_S = 5.0     # 鎖檔超過這麼久沒釋放 = 殘留（寫入者中途死掉），接管
LOCK_WAIT_S = 3.0      # 等鎖最久這麼久；等不到也照做（寫入失敗比互蓋好不到哪去，維持「寫入失敗一律忽略」的承諾）


def _read(path: Path) -> list:
    try:
        out = []
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out
    except OSError:
        return []


def _write(path: Path, rows: list) -> None:
    """原子寫：先寫同目錄暫存檔再 os.replace（讀者不會讀到寫一半的檔）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    tmp.write_text(text, encoding='utf-8', newline='\n')
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


@contextlib.contextmanager
def _lock(path: Path):
    """讀改寫整檔的互斥：O_EXCL 鎖檔（<檔名>.lock）。多個程序（quest / watch / heal / winenv …）同時寫不會互蓋。
    鎖檔超過 LOCK_STALE_S 視為殘留接管；等超過 LOCK_WAIT_S 就不等了、照寫（不丟例外）"""
    lock = path.with_name(path.name + '.lock')
    got = False
    t_end = time.monotonic() + LOCK_WAIT_S
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            got = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.monotonic() >= t_end:
                break
            time.sleep(0.01)
        except OSError:
            break
    try:
        yield
    finally:
        if got:
            try:
                lock.unlink()
            except OSError:
                pass


def add(error: str, fix=None, source=None, ts=None, path: Path | None = None, keep: int = KEEP):
    """寫一筆，回傳 id（失敗回 None）。ts 為毫秒，預設現在。"""
    path = path or LOG
    try:
        with _lock(path):
            rows = _read(path)
            nid = max([r.get('id', 0) for r in rows] + [0]) + 1
            rows.append({'id': nid, 'ts': int(ts if ts is not None else time.time() * 1000),
                         'error': str(error).replace('\n', ' '), 'fix': fix, 'source': source})
            _write(path, rows[-keep:])
        return nid
    except OSError:
        return None


def fix(id_or_last, fix_text: str, path: Path | None = None) -> bool:
    """補上改進；id_or_last 可為 id 或 'last'。找不到回 False。"""
    path = path or LOG
    try:
        with _lock(path):
            rows = _read(path)
            if not rows:
                return False
            if str(id_or_last) == 'last':
                row = rows[-1]
            else:
                row = next((r for r in rows if r.get('id') == int(id_or_last)), None)
            if row is None:
                return False
            row['fix'] = fix_text
            _write(path, rows)
        return True
    except (OSError, ValueError):
        return False


def main(argv) -> int:
    if len(argv) < 2 or argv[1] not in ('add', 'fix', 'list'):
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == 'list':
        for r in _read(LOG):
            t = time.strftime('%m-%d %H:%M', time.localtime(r['ts'] / 1000))
            print(f"#{r['id']} {t} [{r.get('source') or '-'}] {r['error']} -> {r['fix'] or '待改進'}")
        return 0
    if cmd == 'fix':
        if len(argv) < 4:
            print('用法：errlog.py fix <id|last> "改進"')
            return 2
        ok = fix(argv[2], ' '.join(argv[3:]))
        print('已補上' if ok else '找不到該筆')
        return 0 if ok else 1
    a = argv[2:]
    opts = {'--fix': None, '--source': None}
    words = []
    i = 0
    while i < len(a):
        if a[i] in opts and i + 1 < len(a):
            opts[a[i]] = a[i + 1]
            i += 2
        else:
            words.append(a[i])
            i += 1
    if not words:
        print('用法：errlog.py add "錯誤描述" [--fix "改進"] [--source quest]')
        return 2
    nid = add(' '.join(words), opts['--fix'], opts['--source'])
    print(f'已記錄 #{nid}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
