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
"""
import json
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parents[1] / '.cache' / 'errlog.jsonl'
KEEP = 100


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
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
    path.write_text(text, encoding='utf-8', newline='\n')


def add(error: str, fix=None, source=None, ts=None, path: Path = LOG, keep: int = KEEP):
    """寫一筆，回傳 id（失敗回 None）。ts 為毫秒，預設現在。"""
    try:
        rows = _read(path)
        nid = max([r.get('id', 0) for r in rows] + [0]) + 1
        rows.append({'id': nid, 'ts': int(ts if ts is not None else time.time() * 1000),
                     'error': str(error).replace('\n', ' '), 'fix': fix, 'source': source})
        _write(path, rows[-keep:])
        return nid
    except OSError:
        return None


def fix(id_or_last, fix_text: str, path: Path = LOG) -> bool:
    """補上改進；id_or_last 可為 id 或 'last'。找不到回 False。"""
    try:
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
