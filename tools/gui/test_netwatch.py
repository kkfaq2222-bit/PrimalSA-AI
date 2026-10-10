#!/usr/bin/env python3
"""netwatch 三態測試（不碰遊戲）：mock winenv.run_ps，驗證 _match / _dark_count / hud_ok /
login_fields_filled / relogin / check_and_reconnect 在 PowerShell 失敗時不誤判。
用法：uv run --no-project python tools/gui/test_netwatch.py"""
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netwatch  # noqa: E402

tmp = Path(tempfile.mkdtemp())
netwatch.CACHE = tmp
netwatch.HALT = tmp / 'netwatch.halt'
netwatch.STATE = tmp / 'netwatch.json'
netwatch.ACT_LOCK = tmp / 'act.lock'
netwatch.log = lambda *a, **k: None
netwatch.time.sleep = lambda *_: None
ERR: list = []      # errlog.add / fix 紀錄
netwatch.errlog.add = lambda text, **k: (ERR.append(('add', text)), len(ERR))[1]
netwatch.errlog.fix = lambda i, text, **k: ERR.append(('fix', i, text))
netwatch.actlog.add = lambda *a, **k: None

fails = 0


def check(name, cond):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails += 1


def R(rc=0, out='', err=''):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class PS:
    """依序回傳預先排好的回應；用完後重複最後一個。calls 記錄 (script, args)"""
    def __init__(self, *seq):
        self.seq, self.calls = list(seq), []

    def __call__(self, script, *args, **kw):
        self.calls.append((script, args))
        r = self.seq.pop(0) if len(self.seq) > 1 else self.seq[0]
        if isinstance(r, Exception):
            raise r
        return r


def use(*seq):
    ERR.clear()
    netwatch._fail_id.clear()
    ps = PS(*seq)
    netwatch.winenv.run_ps = ps
    return ps


SIG = netwatch.SIG_LOGIN

# ---- _match ----
use(R(0, 'ok 12'))
check('ok → True', netwatch._match(SIG) is True)
use(R(0, 'timeout 3'))
check('timeout → False', netwatch._match(SIG) is False)
ps = use(R(1, '', 'boom'), R(1, '', 'boom'))
check('rc≠0 兩次 → None（重試一次共 2 次呼叫）', netwatch._match(SIG) is None and len(ps.calls) == 2)
check('  errlog 一筆 add', [e[0] for e in ERR] == ['add'])
use(R(0, ''))
check('空輸出 → None', netwatch._match(SIG) is None)
use(R(0, 'pwfail'))
check('pwfail → None', netwatch._match(SIG) is None)
ps = use(R(1, '', 'x'), R(0, 'ok 5'))
check('第一次失敗第二次 ok → True，且無 errlog', netwatch._match(SIG) is True and len(ps.calls) == 2 and not ERR)
use(subprocess.TimeoutExpired('x', 1))
check('逾時例外 → None', netwatch._match(SIG) is None)
use(OSError('no ps'))
check('OSError → None', netwatch._match(SIG) is None)
use(R(1, 'ok 5'))
check('rc≠0 即使輸出 ok 也不採信 → None', netwatch._match(SIG) is None)

# ---- errlog 限頻 ----
use(R(1, '', 'x'))
for _ in range(6):
    netwatch._match(SIG)
check('連續失敗 6 次只記 1 筆 add', [e[0] for e in ERR] == ['add'])
netwatch.winenv.run_ps = PS(R(0, 'timeout 1'))
netwatch._match(SIG)
check('恢復補一筆 fix', [e[0] for e in ERR] == ['add', 'fix'] and ERR[1][1] == 1)
netwatch._match(SIG)
check('恢復後再成功不重複 fix', len(ERR) == 2)
netwatch.winenv.run_ps = PS(R(1))
netwatch._match(SIG)
check('再次失敗又記新的一筆', [e[0] for e in ERR] == ['add', 'fix', 'add'])

# ---- hud_ok ----
import walk  # noqa: E402
netwatch_stat_ok = {'ok': True, 'pos': '1000:1,1', 'level': '0轉1級'}
walk.stat = lambda: netwatch_stat_ok
use(R(0, 'timeout 1'))
check('hud_ok：stat ok 且非登入畫面 → True', netwatch.hud_ok() is True)
use(R(0, 'ok 1'))
check('hud_ok：是登入畫面 → False', netwatch.hud_ok() is False)
use(R(1, '', 'x'))
check('hud_ok：_match 讀不到（None）→ False', netwatch.hud_ok() is False)

# ---- detect ----
use(R(1))
check('detect：全部讀不到 → None（不動作）', netwatch.detect() is None)

# ---- _dark_count / login_fields_filled ----
box = netwatch.ACCT_BOX
n = len(range(box[2], box[3], 3)) * len(range(box[0], box[1], 3))
dark = ' '.join(['50,40,30'] * n)
light = ' '.join(['240,230,200'] * n)
use(R(0, dark))
check('_dark_count 全深色 = 點數', netwatch._dark_count(box) == n)
use(R(0, light))
check('_dark_count 全淺色 = 0（確定是空）', netwatch._dark_count(box) == 0)
use(R(0, ' '.join(['50,40,30'] * (n - 1))))
check('_dark_count 點數少於預期 → None', netwatch._dark_count(box) is None)
use(R(1, '', 'x'))
check('_dark_count PS 失敗 → None', netwatch._dark_count(box) is None)
ps = use(R(1), R(0, dark))
check('_dark_count 第一次失敗第二次成功', netwatch._dark_count(box) == n and len(ps.calls) == 2)
pn = len(range(netwatch.PWD_BOX[2], netwatch.PWD_BOX[3], 3)) * len(range(netwatch.PWD_BOX[0], netwatch.PWD_BOX[1], 3))
use(R(0, dark), R(0, ' '.join(['50,40,30'] * pn)))
check('login_fields_filled 兩欄有字 → True', netwatch.login_fields_filled() is True)
use(R(0, light))
check('login_fields_filled 帳號欄空 → False', netwatch.login_fields_filled() is False)
use(R(1))
check('login_fields_filled 讀不到 → None（不是 False）', netwatch.login_fields_filled() is None)

# ---- relogin：讀不到不 halt、不點登錄；超過上限才 halt ----
netwatch.STATE.unlink() if netwatch.STATE.exists() else None
use(R(1))
clicks = []
netwatch.gui = lambda *a, **k: clicks.append(a) or ''
r = None
for i in range(netwatch.READ_FAIL_MAX - 1):
    r = netwatch.relogin('t')
    check(f'relogin 讀不到第 {i + 1} 輪：status ok + failed，不 halt', r == {'status': 'ok', 'failed': True})
check('  期間沒有點任何東西', not clicks)
check('  halt 檔不存在', not netwatch.HALT.exists())
r = netwatch.relogin('t')
check('relogin 連續讀不到達上限 → halt 且理由是「讀不到」非「空的」',
      r['status'] == 'halt' and '讀不到' in r['reason'] and '空的' not in r['reason'] and netwatch.HALT.exists())
check('  仍沒點任何東西', not clicks)
netwatch.HALT.unlink()
netwatch.STATE.write_text('{"fails": 0, "read_fails": 3}')
use(R(0, light))
r = netwatch.relogin('t')
check('relogin 欄位確定空 → halt「空的」並清掉 read_fails', r['status'] == 'halt' and '空的' in r['reason'])
netwatch.HALT.unlink()

# ---- check_and_reconnect：不宣告成功 ----
# 對話框出現 → 點確定 → 之後 _match 全部讀不到（None）：不能當作重連成功
netwatch.STATE.write_text('{"fails": 0}')
netwatch.time.time = lambda it=iter(range(0, 10000, 20)): float(next(it))   # 加速 45 秒期限
seq = [R(0, 'ok 1')]          # detect：SIG_DIALOG → ok（OCR 另行 mock）
netwatch._ocr = lambda *a, **k: []
ERR.clear()
n_calls = {'k': 0}


def ps_dialog_then_blind(script, *args, **kw):
    n_calls['k'] += 1
    if n_calls['k'] == 1:
        return R(0, 'ok 1')
    return R(1, '', 'blind')


netwatch.winenv.run_ps = ps_dialog_then_blind
walk.stat = lambda: {'ok': True, 'pos': '1000:1,1', 'level': 'x'}
clicks.clear()
netwatch.recover = lambda *a, **k: {'stub': 1}
r = netwatch.check_and_reconnect()
check('點確定後一直讀不到 → 不宣告 reconnected', r.get('status') != 'reconnected')
check('  有點確定（只點確定，不亂點）', clicks and all(c[0] == 'click' and (c[1], c[2]) == ('715', '557') for c in clicks))

# HALT 存在時 hud_ok 讀不到 → 維持 halt，不清檔
netwatch.HALT.write_text('x')
use(R(1))
r = netwatch.check_and_reconnect()
check('HALT 存在且讀不到畫面 → 仍 halt、不清 halt 檔', r['status'] == 'halt' and netwatch.HALT.exists())
netwatch.HALT.unlink()

# ---- gui.ps1 / 呼叫點靜態檢查 ----
src = Path(netwatch.__file__).read_text(encoding='utf-8')
check('netwatch 沒有「not _match(」的二態寫法', 'not _match(' not in src)
ps1 = (Path(netwatch.__file__).parent / 'gui.ps1').read_text(encoding='utf-8-sig')
check('gui.ps1 waitpix / waitstill 有 pwfail', ps1.count("'pwfail'") >= 2)
check('gui.ps1 維持 BOM', (Path(netwatch.__file__).parent / 'gui.ps1').read_bytes()[:3] == b'\xef\xbb\xbf')

print('全部通過' if not fails else f'{fails} 項失敗')
sys.exit(1 if fails else 0)
