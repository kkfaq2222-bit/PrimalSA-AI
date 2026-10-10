#!/usr/bin/env python3
"""errlog 多程序同時寫測試（不碰遊戲）：兩個程序各寫 200 筆 → 400 筆不掉；殘留鎖會被接管；fix 與 add 同時也不互蓋。
  uv run --no-project python tools/gui/test_errlog.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import errlog  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1


if len(sys.argv) > 1 and sys.argv[1] == 'worker':
    path, tag, n = Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
    for i in range(n):
        errlog.add(f'{tag}-{i}', source=tag, path=path, keep=10000)
    sys.exit(0)

tmp = Path(tempfile.mkdtemp(prefix='errlogtest-'))
log = tmp / 'errlog.jsonl'
t0 = time.time()
ps = [subprocess.Popen([sys.executable, __file__, 'worker', str(log), tag, '200']) for tag in ('A', 'B')]
rcs = [p.wait(timeout=120) for p in ps]
rows = errlog._read(log)
ids = [r['id'] for r in rows]
check('兩個程序各寫 200 筆 → 共 400 筆不掉', rcs == [0, 0] and len(rows) == 400, f'{len(rows)} 筆 {time.time() - t0:.1f}s')
check('id 連號且不重複', ids == list(range(1, 401)))
check('各 200 筆都在', sum(r['source'] == 'A' for r in rows) == 200 and sum(r['source'] == 'B' for r in rows) == 200)
check('沒有殘留鎖 / 暫存檔', not list(tmp.glob('*.lock')) and not list(tmp.glob('*.tmp')))
# 殘留鎖（寫入者死掉）> 5 s 會被接管
lock = tmp / 'errlog.jsonl.lock'
lock.write_text('')
os.utime(lock, (time.time() - 60, time.time() - 60))
t0 = time.time()
i = errlog.add('殘留鎖後的一筆', path=log, keep=10000)
check('殘留鎖被接管、寫入成功且不久等', i == 401 and time.time() - t0 < 1.5 and not lock.exists(), f'{time.time() - t0:.2f}s')
# 新鎖（別人正在寫）最多等 LOCK_WAIT_S 後照寫、不丟例外
lock.write_text('')
errlog.LOCK_WAIT_S = 0.3
t0 = time.time()
i = errlog.add('等不到鎖照寫', path=log, keep=10000)
check('等不到鎖：超過 LOCK_WAIT_S 後照寫、不丟例外', i == 402 and 0.25 < time.time() - t0 < 2.0, f'{time.time() - t0:.2f}s')
lock.unlink()
# fix
check('fix 補上改進並持久化', errlog.fix(402, '已改', path=log) and errlog._read(log)[-1]['fix'] == '已改')
# 原子寫：讀者在寫入期間永遠讀到完整 JSON 行
bad = 0
reader_stop = time.time() + 1.5
p = subprocess.Popen([sys.executable, __file__, 'worker', str(log), 'C', '150'])
while time.time() < reader_stop and p.poll() is None:
    try:
        for ln in log.read_text(encoding='utf-8').splitlines():
            json.loads(ln)
    except ValueError:
        bad += 1
    except OSError:
        pass
p.wait(timeout=60)
check('寫入期間讀者沒讀到壞行（原子寫）', bad == 0, str(bad))
print('\n全部通過' if not fails else f'\n{fails} 項失敗')
sys.exit(1 if fails else 0)
