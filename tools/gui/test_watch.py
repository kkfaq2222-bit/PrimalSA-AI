#!/usr/bin/env python3
"""watch.py / watchstate.py 單元測試（不碰遊戲、不需要 powershell；全部用暫存目錄 + 假 run_ps + 假時鐘）。
  uv run --no-project python tools/gui/test_watch.py
涵蓋：零輸入白名單 / AST、鎖三種情況、token、原子寫、內容不變不寫、seq、心跳、退回一次性間隔、phase=starting、
stop 檔、最小化 / 沒開 / 版面不支援、讀取 API、SIGTERM 清理。
"""
import ast
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import screen_sigs  # noqa: E402
import watch  # noqa: E402
import watchstate  # noqa: E402
import winenv  # noqa: E402

watch.OCR_ON = False      # 既有測試只看 pixel / info；HUD 數值（stat.ps1）的測試在檔尾自己開

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1


TMP = Path(tempfile.mkdtemp(prefix='watchtest-'))
PATHS = ('CACHE', 'STATE_FILE', 'LOCK_FILE', 'STOP_FILE', 'HUD_CFG', 'BATTLE_LOCK', 'HALT_FILE')


def fresh_dir(name):
    """每個測試一個暫存目錄，並把 watchstate 的路徑常數指過去"""
    d = TMP / name
    d.mkdir(parents=True, exist_ok=True)
    watchstate.CACHE = d
    for n, f in (('STATE_FILE', 'state.json'), ('LOCK_FILE', 'watch.lock'), ('STOP_FILE', 'watch.stop'), ('HUD_CFG', 'psa-hud.json'),
                 ('BATTLE_LOCK', 'battle.lock'), ('HALT_FILE', 'netwatch.halt')):
        setattr(watchstate, n, d / f)
    return d


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Fake:
    """假 winenv.run_ps：依「這個指令」回預先設定的結果；記錄每次呼叫"""

    def __init__(self, clk=None):
        self.clk = clk
        self.calls = []
        self.info = (0, 'client=2880x1659 origin=(0,45) scale=2 shot=1440x830 foreground=False\n', '')
        self.pixel = None            # (rc, stdout, stderr) 或 callable
        self.cost = {'info': 0.02, 'pixel': 0.09}   # 假時鐘前進秒數
        self.on_call = None
        self.stat = (0, '{"ok": false}\n', '')   # stat.ps1 的 (rc, stdout, stderr)

    def __call__(self, script, *args, timeout=None):
        self.calls.append((script, args, timeout))
        if self.on_call:
            self.on_call(script, args)
        cmd = args[0] if args else ''
        if self.clk:
            self.clk.t += self.cost.get(cmd, 0.05)
        r = self.info if cmd == 'info' else (self.stat if script == 'stat.ps1' else self.pixel)
        r = r() if callable(r) else r
        if isinstance(r, Exception):
            raise r
        rc, out, err = r
        return subprocess.CompletedProcess(['x'], rc, out, err)


FX = json.loads((HERE / 'fixtures' / 'screen_px.json').read_text(encoding='utf-8'))
PTS = [tuple(p) for p in FX['points']]


def px_out(state):
    """fixture 裡某個狀態的像素 → gui pixel 的 stdout（'r,g,b r,g,b ...'）"""
    smp = next(s for s in FX['samples'] if s['state'] == state)
    h = smp['px']
    return ' '.join(f'{int(h[i*6:i*6+2], 16)},{int(h[i*6+2:i*6+4], 16)},{int(h[i*6+4:i*6+6], 16)}' for i in range(len(PTS)))


def make(name, owner='', server=False):
    """建一個已持鎖的 Watcher + 假時鐘 + 假 run_ps（server=True 模擬「server 要先啟動」）"""
    fresh_dir(name)
    clk = Clock()
    fk = Fake(clk)
    fk.pixel = (0, px_out('idle'), '')
    winenv.run_ps = fk
    winenv._server_wanted = lambda s: server
    winenv.server_alive = lambda: not server
    w = watch.Watcher(owner=owner, clock=clk, mono=clk, sleep=clk.sleep)
    code, _ = w.acquire()
    assert code == 0, code
    return w, clk, fk


real_run_ps, real_wanted, real_alive = winenv.run_ps, winenv._server_wanted, winenv.server_alive

# ---------------------------------------------------------------- 1. 零輸入白名單
w, clk, fk = make('wl')
for bad in ('click', 'dclick', 'drag', 'key', 'max', 'end', 'fg', 'seq', 'waitpix', 'waitstill', 'shot', 'wait', 'ifok', 'ifnok'):
    try:
        watch._gui(bad, '1', '2')
        check(f'_gui 拒絕 {bad}', False)
    except ValueError:
        check(f'_gui 拒絕 {bad}', True)
check('被拒的指令都沒有真的送出', not fk.calls)
for bad in ('gui.ps1', 'findmark.ps1', 'titlematch.ps1', 'serve.ps1', 'x.ps1'):
    try:
        watch._ps(bad)
        check(f'_ps 拒絕 {bad}', False)
    except ValueError:
        check(f'_ps 拒絕 {bad}', True)
watch._ps('stat.ps1'); watch._ps('ocr.ps1', '1', '2')
check('_ps 放行 stat / ocr 且帶 timeout', [c[2] for c in fk.calls] == [watch.PS_TIMEOUT] * 2, str(fk.calls))
fk.calls.clear()
for _ in range(6):
    w.cycle()
cmds = {c[1][0] for c in fk.calls if c[0] == 'gui.ps1'}
check('主迴圈只送 pixel / info', cmds == {'pixel', 'info'} and all(c[0] == 'gui.ps1' for c in fk.calls), str(cmds))
check('每個 gui 呼叫都帶 -NoRestore 1', all(c[1][-2:] == ('-NoRestore', '1') for c in fk.calls))
check('每個呼叫都帶 timeout（gui = 3 s）', all(c[2] == watch.GUI_TIMEOUT for c in fk.calls))
# AST：watch.py 裡 run_ps / _oneshot 只出現在 _gui / _ps；沒有其他程序 / 輸入呼叫
tree = ast.parse((HERE / 'watch.py').read_text(encoding='utf-8'))
bad_sites, bad_calls = [], []
for fn in ast.walk(tree):
    if isinstance(fn, ast.FunctionDef):
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('run_ps', '_oneshot') and fn.name not in ('_gui', '_ps'):
                bad_sites.append((fn.name, n.func.attr))
for n in ast.walk(tree):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
        owner = n.func.value.id if isinstance(n.func.value, ast.Name) else ''
        if (owner == 'subprocess' and n.func.attr in ('run', 'Popen', 'call', 'check_call', 'check_output')) or (owner == 'os' and n.func.attr in ('system', 'startfile', 'popen')):
            bad_calls.append((owner, n.func.attr))
runps_in_gui = sum(1 for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and fn.name in ('_gui', '_ps')
                   for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'run_ps')
check('AST：run_ps / _oneshot 只在 _gui / _ps 裡呼叫（各一處）', not bad_sites and runps_in_gui == 2, f'{bad_sites} {runps_in_gui}')
check('AST：沒有 subprocess.run / Popen / os.system 等其他程序呼叫', not bad_calls, str(bad_calls))
check('GUI_ALLOWED == (pixel, info)；PS_ALLOWED == (stat.ps1, ocr.ps1)', watch.GUI_ALLOWED == ('pixel', 'info') and watch.PS_ALLOWED == ('stat.ps1', 'ocr.ps1'))

# ---------------------------------------------------------------- 2. 鎖三種情況 + token
fresh_dir('lock')
me = winenv.platform_kind()
other = 'windows' if me == 'wsl' else 'wsl'
info = {'token': 'aaaa', 'pid': 111, 'platform': me, 'started': 1.0}
code, _ = watch.acquire_lock(info, pid_alive=lambda p: True)
check('無鎖 → 取得（0）', code == 0 and json.loads(watchstate.LOCK_FILE.read_text())['token'] == 'aaaa')
code, msg = watch.acquire_lock({**info, 'token': 'bbbb', 'pid': 222}, pid_alive=lambda p: True)
check('同平台、擁有者活著 → 退出碼 3', code == 3, msg)
check('活鎖沒有被動到', json.loads(watchstate.LOCK_FILE.read_text())['token'] == 'aaaa')
watchstate.LOCK_FILE.write_text(json.dumps({'token': 'cccc', 'pid': 333, 'platform': other, 'started': 1.0}))
code, msg = watch.acquire_lock({**info, 'token': 'dddd'}, pid_alive=lambda p: True)
check('別平台的鎖 → 退出碼 6（不搶）', code == 6 and json.loads(watchstate.LOCK_FILE.read_text())['token'] == 'cccc', msg)
code, _ = watch.acquire_lock({**info, 'token': 'dddd'}, pid_alive=lambda p: False)
check('別平台的鎖即使 pid 判死也不搶（pid 空間不同）', code == 6)
watchstate.LOCK_FILE.write_text(json.dumps({'token': 'eeee', 'pid': 444, 'platform': me, 'started': 1.0}))
code, msg = watch.acquire_lock({**info, 'token': 'ffff', 'pid': 555}, pid_alive=lambda p: False)
check('同平台擁有者已死 → 接手', code == 0 and json.loads(watchstate.LOCK_FILE.read_text())['token'] == 'ffff', msg)
watchstate.LOCK_FILE.write_text('{"tok')
code, msg = watch.acquire_lock({**info, 'token': 'gggg'}, pid_alive=lambda p: True, sleep=lambda s: None)
check('鎖檔剛建立（內容壞）→ 3', code == 3, msg)
old = time.time() - 60
os.utime(watchstate.LOCK_FILE, (old, old))
code, _ = watch.acquire_lock({**info, 'token': 'gggg'}, pid_alive=lambda p: True, sleep=lambda s: None)
check('壞很久的鎖 → 當死鎖接手', code == 0)
# 接手後 seq 續號
fresh_dir('seq')
watchstate.write({'v': 1, 'seq': 777, 'ts': 1.0, 'watcher': {'token': 'old'}}, 'x')
watchstate.LOCK_FILE.write_text(json.dumps({'token': 'old', 'pid': 1, 'platform': me, 'started': 1.0}))
orig_alive = watch.battleguard.pid_alive
watch.battleguard.pid_alive = lambda p: False
winenv.run_ps = Fake(Clock()); winenv._server_wanted = lambda s: False; winenv.server_alive = lambda: True
w2 = watch.Watcher(); code, _ = w2.acquire()
check('同平台死鎖接手、seq 從舊值續號', code == 0 and w2.seq == 777)
w2.flush(force=True)
check('接手後第一次寫入 seq = 舊 + 1', watchstate.read()['seq'] == 778)
watch.battleguard.pid_alive = orig_alive
# release 只刪自己 token 的鎖
fresh_dir('rel')
watchstate.LOCK_FILE.write_text(json.dumps({'token': 'mine', 'pid': 1, 'platform': me, 'started': 1.0}))
check('release：token 不符不刪', not watch.release_lock('other') and watchstate.LOCK_FILE.exists())
check('release：token 相符才刪', watch.release_lock('mine') and not watchstate.LOCK_FILE.exists())
# token 被換走 → 主迴圈以 3 結束，且不再寫 state
w, clk, fk = make('tok')
w.flush(force=True); seq0 = watchstate.read()['seq']
watchstate.LOCK_FILE.write_text(json.dumps({'token': 'stolen', 'pid': 1, 'platform': me, 'started': 1.0}))
try:
    w.cycle(); check('token 被換 → _Exit(3)', False)
except watch._Exit as e:
    check('token 被換 → _Exit(3)', e.code == 3)
w.finish()
check('token 被換後 finish 不刪別人的鎖、不寫 state', json.loads(watchstate.LOCK_FILE.read_text())['token'] == 'stolen' and watchstate.read()['seq'] == seq0)
# finally 只刪自己的鎖並寫 running=false
w, clk, fk = make('fin')
w.cycle(); w.finish()
st = watchstate.read()
check('finish：刪鎖、寫 phase=stopping / running=false', not watchstate.LOCK_FILE.exists() and st['phase'] == 'stopping' and st['watcher']['running'] is False)

# ---------------------------------------------------------------- 3. 內容不變不寫 / seq / 心跳
w, clk, fk = make('hb')
w.cycle()
seq_a = watchstate.read()['seq']
writes = 0
for _ in range(6):                        # 暖機：stable_n 到上限、info 做完，之後內容才真的不變
    clk.sleep(0.39)
    w.cycle()
last_seq = watchstate.read()['seq']
for _ in range(20):                       # 畫面不變：每輪 0.5 s（假時鐘）
    clk.sleep(0.5 - 0.11)
    w.cycle()
    s = watchstate.read()['seq']
    if s != last_seq:
        writes += 1
        last_seq = s
check('畫面不變 20 輪（約 10 s）：只有心跳寫（≈ 每 1 s 一次，不是每輪）', 6 <= writes <= 11, f'writes={writes}')
w.flush(force=True)
check('seq 每次寫入遞增 1', watchstate.read()['seq'] == last_seq + 1)
# 內容變化（idle → battle）馬上寫，且 transitions 有畫面時間 / 寫入時間
seq_b = watchstate.read()['seq']
fk.pixel = (0, px_out('dialog'), '')
w.cycle()
st = watchstate.read()
check('狀態變化立即寫入（idle → dialog）', st['seq'] > seq_b and st['screen']['state'] == 'dialog' and st['screen']['prev'] == 'idle')
tr = st['screen']['transitions'][-1]
check('transitions = [舊, 新, 畫面時間, 寫入時間]，寫入時間 ≥ 畫面時間', tr[0] == 'idle' and tr[1] == 'dialog' and tr[3] >= tr[2], str(tr))
check('label 與 since', st['screen']['label'] == '對話框' and st['screen']['since'] > 0)
# S3：只有排除欄位不同 → key 相同
a = {'v': 1, 'ts': 1, 'seq': 1, 'watcher': {'cycle_ms': 1, 'ocr_ms': 2, 'hb_p95_s': 3, 'cpu_pct': 1, 'x': 1},
     'screen': {'ts': 1, 'age_s': 1, 'gold': 5, 'state': 'idle'}, 'hud': {'hp': {'v': 1, 'ts': 5}}}
b = json.loads(json.dumps(a))
b['ts'] = 99; b['seq'] = 99; b['watcher'].update(cycle_ms=9, ocr_ms=9, hb_p95_s=9, cpu_pct=9); b['screen'].update(ts=9, age_s=9, gold=0); b['hud']['hp']['ts'] = 9
check('S3：排除欄位（ts/seq/cycle_ms/ocr_ms/age_s/各欄位 ts/gold…）不同 → content_key 相同', watchstate.content_key(a) == watchstate.content_key(b))
b['screen']['state'] = 'battle'
check('S3：真正內容不同 → key 不同', watchstate.content_key(a) != watchstate.content_key(b))
# 心跳最壞間隔：每次呼叫耗時 8 s（pixel timeout 邊緣）→ 呼叫之後就檢查，寫入間隔不超過 ~9 s
w, clk, fk = make('hb8')
fk.cost = {'info': 8.0, 'pixel': 8.0}
w.flush(force=True)
gaps, last = [], None
orig_write = watchstate.write
def spy(d, token, **kw):
    global last
    r = orig_write(d, token, **kw)
    if r:
        if last is not None:
            gaps.append(clk.t - last)
        last = clk.t
    return r
watchstate.write = spy
for _ in range(5):
    w.cycle()
watchstate.write = orig_write
check('心跳：mock 每個呼叫 8 s，寫入最大間隔 < 10 s', gaps and max(gaps) < 10, f'max={max(gaps) if gaps else None} {gaps}')
check('hb_p95_s 有自記', watchstate.read()['watcher']['hb_p95_s'] > 0)

# ---------------------------------------------------------------- 4. 原子寫 / 暫存檔名 / PermissionError
fresh_dir('atomic')
seen = []
orig_replace = os.replace
def spy_replace(a, b):
    seen.append(Path(a).name)
    return orig_replace(a, b)
os.replace = spy_replace
check('write 成功', watchstate.write({'v': 1, 'seq': 1}, 'tok123'))
os.replace = orig_replace
check('暫存檔名帶 token、用 os.replace', seen == ['state.json.tok123.tmp'] and not (watchstate.CACHE / 'state.json.tok123.tmp').exists())
n = {'c': 0}
def flaky(a, b):
    n['c'] += 1
    if n['c'] < 3:
        raise PermissionError('讀者開著')
    return orig_replace(a, b)
os.replace = flaky
ok = watchstate.write({'v': 1, 'seq': 2}, 'tok123', sleep=lambda s: None)
os.replace = orig_replace
check('PermissionError 重試後成功（第 3 次）', ok and n['c'] == 3 and watchstate.read()['seq'] == 2)
os.replace = lambda a, b: (_ for _ in ()).throw(PermissionError('always'))
ok = watchstate.write({'v': 1, 'seq': 3}, 'tok123', sleep=lambda s: None)
os.replace = orig_replace
check('一直 PermissionError → 5 次後回 False、舊檔不壞、暫存檔清掉', ok is False and watchstate.read()['seq'] == 2 and not (watchstate.CACHE / 'state.json.tok123.tmp').exists())
# 寫失敗時 flush 不更新 last_key，下輪重試
w, clk, fk = make('wfail')
orig_write = watchstate.write
watchstate.write = lambda *a, **k: False
check('寫失敗 → flush 回 False（跳過這輪）', w.flush(force=True) is False)
watchstate.write = orig_write
check('下一輪重試成功', w.flush(force=True) is True)

# ---------------------------------------------------------------- 5. 讀取 API
fresh_dir('api')
check('讀不到檔 → None', watchstate.read() is None)
watchstate.STATE_FILE.write_text(json.dumps({'v': 2, 'x': 1}))
check('v 主版本不是 1 → None', watchstate.read() is None)
watchstate.STATE_FILE.write_text('{broken')
n = {'c': 0}
check('壞 JSON 重試 3 次（每次 sleep）後 None', watchstate.read(sleep=lambda s: n.__setitem__('c', n['c'] + 1)) is None and n['c'] == 3)
t0 = 5000.0
doc = {'v': 1, 'ts': t0, 'seq': 5, 'future_key': {'a': 1}, 'watcher': {'running': True, 'platform': me, 'token': 'T'},
       'screen': {'ts': t0 - 0.2, 'age_s': 0.2, 'state': 'idle'}}
watchstate.STATE_FILE.write_text(json.dumps(doc))
check('不認得的鍵忽略、讀得到', watchstate.read()['screen']['state'] == 'idle')
check('fresh：年齡內 → 回 state', watchstate.fresh(2.0, now=lambda: t0 + 1) is not None)
check('fresh：太舊 → None', watchstate.fresh(2.0, now=lambda: t0 + 3) is None)
check('screen：age_s + 經過時間在門檻內 → 回', watchstate.screen(1.5, now=lambda: t0 + 1.0) is not None)
check('screen：0.2 + 1.5 > 1.5 → None', watchstate.screen(1.5, now=lambda: t0 + 1.5) is None)
check('screen after：畫面時間早於 after → None', watchstate.screen(5, after=t0, now=lambda: t0 + 0.5) is None)
check('screen after：畫面時間晚於 after → 回', watchstate.screen(5, after=t0 - 1, now=lambda: t0 + 0.5) is not None)
doc['watcher']['running'] = False
watchstate.STATE_FILE.write_text(json.dumps(doc))
check('watcher 不在 running → fresh / screen 都 None', watchstate.fresh(99, now=lambda: t0) is None and watchstate.screen(99, now=lambda: t0) is None)
doc['watcher'].update(running=True, platform=other)
watchstate.STATE_FILE.write_text(json.dumps(doc))
check('不同平台：screen 不拿對方 ts 比（None）', watchstate.screen(99, now=lambda: t0) is None)
# 不同平台 fresh：seq 前進才回
cnt = {'n': 0}
def adv(s):
    cnt['n'] += 1
    if cnt['n'] == 3:
        doc['seq'] += 1
        watchstate.STATE_FILE.write_text(json.dumps(doc))
clk = Clock(0.0)
def now2():
    return clk.t
def sl(s):
    clk.t += s; adv(s)
check('不同平台 fresh：seq 前進 → 回 state', watchstate.fresh(2, now=now2, sleep=sl) is not None)
doc['seq'] += 0
watchstate.STATE_FILE.write_text(json.dumps(doc))
clk.t = 0.0
check('不同平台 fresh：seq 不動 → 等滿 2.5 s 後 None', watchstate.fresh(2, now=now2, sleep=lambda s: setattr(clk, 't', clk.t + s)) is None and clk.t >= 2.5)
# Liveness
m = Clock(0.0)
lv = watchstate.Liveness(mono=m)
lv.update(doc); m.t = 11
check('Liveness：(token, seq) 沒變 → stalled', lv.stalled(10))
doc['seq'] += 1; lv.update(doc)
check('Liveness：seq 前進 → 不 stalled', not lv.stalled(10) and abs(lv.age({'screen': {'age_s': 0.3}}) - 0.3) < 1e-6)
doc['watcher']['token'] = 'T2'; m.t = 30; lv.update(doc)
check('Liveness：token 變也算有變', not lv.stalled(10))
# peek_battle_lock：只讀、不判活、不刪
watchstate.BATTLE_LOCK.write_text(json.dumps({'pid': 99999999, 'start': 1.0, 'note': 'quest.py'}))
pk = watchstate.peek_battle_lock()
check('peek_battle_lock：pid 已死也照回、檔案還在', pk == {'pid': 99999999, 'start': 1.0, 'note': 'quest.py'} and watchstate.BATTLE_LOCK.exists())
w, clk, fk = make('flags')
watchstate.BATTLE_LOCK.write_text(json.dumps({'pid': 4242, 'start': 5.0, 'note': 'x'}))
w.cycle()
check('state.flags.battle_lock 取自 peek', watchstate.read()['flags']['battle_lock']['pid'] == 4242 and watchstate.BATTLE_LOCK.exists())
src = (HERE / 'watch.py').read_text(encoding='utf-8')
check('watch.py 不呼叫 battleguard.locked / acquire / release', 'battleguard.locked' not in src and 'battleguard.acquire' not in src and 'battleguard.release' not in src)

# ---------------------------------------------------------------- 6. 最小化 / 沒開 / 版面 / 退回一次性 / starting / stop 檔
w, clk, fk = make('min')
w.cycle()
fk.pixel = (3, 'minimized\n', ''); fk.info = (3, 'minimized\n', '')
w.cycle()
check('最小化：第一輪 pixel rc=3 → state=minimized、game.minimized', watchstate.read()['screen']['state'] == 'minimized' and watchstate.read()['game']['minimized'])
n0 = len(fk.calls)
w.cycle()
st = watchstate.read()
check('最小化期間：之後每輪只送 info（不送 pixel）', st['screen']['state'] == 'minimized' and [c[1][0] for c in fk.calls[n0:]] == ['info'])
check('最小化：間隔 5 s', w.interval == watch.IDLE_INTERVAL)
check('最小化：標籤', st['screen']['label'] == '遊戲視窗最小化')
fk.info = (1, '', 'PrimalSA 沒有在執行'); w.cycle()
check('沒開遊戲：state=no_game', watchstate.read()['screen']['state'] == 'no_game' and not watchstate.read()['game']['running'])
fk.info = (0, 'client=2880x1659 origin=(0,45) scale=2 shot=1440x830 foreground=False\n', ''); fk.pixel = (0, px_out('idle'), '')
w.cycle()
check('遊戲回來：恢復 idle、prev 記錄', watchstate.read()['screen']['state'] == 'idle' and watchstate.read()['screen']['prev'] == 'no_game' and w.interval == watch.INTERVAL)
# 最小化期間任何呼叫都沒有還原視窗的指令（gui.ps1 的行為由 -NoRestore 保證；這裡檢查 watch 一律帶它）
check('所有呼叫都帶 -NoRestore 1', all(c[1][-2:] == ('-NoRestore', '1') for c in fk.calls))
# 版面不支援
w, clk, fk = make('lay')
fk.info = (0, 'client=1920x1017 origin=(0,0) scale=2\n', '')
n0 = len(fk.calls)
w.cycle()
st = watchstate.read()
check('1920×1017：unsupported、不送 pixel', st['screen']['state'] == 'unsupported' and not st['game']['screen_supported']
      and all(c[1][0] == 'info' for c in fk.calls[n0:]))
# 逾時 → error 並保留 prev
w, clk, fk = make('err')
w.cycle()
fk.pixel = subprocess.TimeoutExpired('x', 3); clk.t += 6   # 讓 info 到期不影響
w.cycle()
st = watchstate.read()
check('pixel 逾時 → state=error、prev 保留最後讀得到的狀態、errors+1', st['screen']['state'] == 'error' and st['screen']['prev'] == 'idle' and st['watcher']['errors'] == 1)
fk.pixel = (0, px_out('idle'), ''); w.cycle()
check('恢復後 error → idle', watchstate.read()['screen']['state'] == 'idle')
fk.pixel = (0, 'garbage', ''); w.cycle()
check('輸出點數不對 → error', watchstate.read()['screen']['state'] == 'error')
# 退回一次性降頻
w, clk, fk = make('slow')
fk.cost = {'info': 0.2, 'pixel': 0.45}
for _ in range(5):
    w.cycle()
check('cycle_ms 中位數 > 300 → 降頻 min(4, max(2, 3×cycle))', 2.0 <= w.interval <= 4.0 and abs(w.interval - min(4, max(2, 3 * 0.45))) < 0.1, str(w.interval))
fk.cost = {'info': 0.2, 'pixel': 2.0}
for _ in range(5):
    w.cycle()
check('降頻上限 4 s', w.interval == 4.0, str(w.interval))
fk.cost = {'info': 0.02, 'pixel': 0.06}
for _ in range(8):
    w.cycle()
check('server 恢復快後回 0.5 s', w.interval == watch.INTERVAL, str(w.interval))
# phase=starting 寫在 server 啟動前（呼叫當下 state.json 已是 starting）
w, clk, fk = make('starting', server=True)
phases = []
state_alive = {'v': False}
winenv.server_alive = lambda: state_alive['v']
def on_call(script, args):
    s = watchstate.read()
    phases.append(s['phase'] if s else None)
    state_alive['v'] = True          # 呼叫後 server 活了
fk.on_call = on_call
w.cycle()
check('server 沒在跑 → 呼叫前先寫 phase=starting', phases and phases[0] == 'starting', str(phases))
check('呼叫成功後 phase 回 running', watchstate.read()['phase'] == 'running')
# stop 檔：早於啟動 → 忽略；晚於啟動 → 5
w, clk, fk = make('stop')
watchstate.STOP_FILE.write_text(json.dumps({'ts': w.started - 100}))
w.cycle()
check('watch.stop 時間早於啟動 → 忽略（檔案保留）', watchstate.STOP_FILE.exists())
watchstate.STOP_FILE.write_text(json.dumps({'ts': w.started + 1}))
try:
    w.cycle(); check('watch.stop 晚於啟動 → _Exit(5)', False)
except watch._Exit as e:
    check('watch.stop 晚於啟動 → _Exit(5) 並刪檔', e.code == 5 and not watchstate.STOP_FILE.exists())
# run() 迴圈：stop 檔 → 回傳 5（並用假 sleep 前進）
w, clk, fk = make('runstop')
n = {'c': 0}
def sl2(s):
    clk.t += s; n['c'] += 1
    if n['c'] == 3:
        watchstate.STOP_FILE.write_text(json.dumps({'ts': clk.t}))
w.sleep = sl2
check('run()：收到 stop 檔 → 退出碼 5', w.run() == 5)
w.finish()
check('stop 結束後鎖已釋放、state running=false', not watchstate.LOCK_FILE.exists() and watchstate.read()['watcher']['running'] is False)
# --stop CLI：寫 psa-hud.json 與 watch.stop
fresh_dir('stopcli')
check('--stop 沒有常駐 watch → 0，並寫 psa-hud.json watch=false', watch.cmd_stop() == 0 and json.loads(watchstate.HUD_CFG.read_text())['watch'] is False)
# label 不准出現「安全」「無驗證」
labels = [screen_sigs.label({'state': s}) for s in ('idle', 'walking', 'dialog', 'reward', 'select', 'panel', 'unknown', 'no_game', 'minimized', 'error', 'unsupported')]
labels += [screen_sigs.label({'state': 'battle', 'full': f, 'cmd': c}) for f in (0, 1) for c in (0, 1)] + [screen_sigs.label({'state': 'idle'}, ['popup'])]
check('label：沒有任何「安全」「無驗證」字樣；idle = 未偵測到已知視窗', not any('安全' in l or '無驗證' in l for l in labels) and labels[0] == '主畫面（未偵測到已知視窗）', str(labels))

# ---------------------------------------------------------------- 7. 真實訊號：SIGTERM 在阻塞呼叫中結束、清理鎖與 state（只在 POSIX 跑）
if sys.platform != 'win32' and hasattr(signal, 'SIGTERM'):
    d = fresh_dir('sig')
    launcher = TMP / 'launch.py'
    launcher.write_text(textwrap.dedent(f'''
        import sys, time, subprocess
        sys.path.insert(0, {str(HERE)!r})
        import watch, watchstate, winenv
        d = __import__('pathlib').Path({str(d)!r})
        watchstate.CACHE = d
        for n, f in (('STATE_FILE','state.json'),('LOCK_FILE','watch.lock'),('STOP_FILE','watch.stop'),('HUD_CFG','psa-hud.json'),('BATTLE_LOCK','battle.lock'),('HALT_FILE','netwatch.halt')):
            setattr(watchstate, n, d / f)
        winenv.platform_kind = lambda *a, **k: 'wsl'
        winenv._server_wanted = lambda s: False
        n = {{'c': 0}}
        def fake(script, *args, timeout=None):
            n['c'] += 1
            if args[0] == 'info':
                return subprocess.CompletedProcess(['x'], 0, 'client=2880x1659\\n', '')
            print('BLOCK', flush=True)
            time.sleep(60)          # 阻塞呼叫：SIGTERM 必須能打斷
        winenv.run_ps = fake
        sys.exit(watch.main([]))
    '''), encoding='utf-8')
    p = subprocess.Popen([sys.executable, str(launcher)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t_end = time.time() + 10
    line = ''
    while time.time() < t_end and 'BLOCK' not in line:
        line = p.stdout.readline()
    check('子程序已卡在阻塞呼叫中', 'BLOCK' in line)
    lock_before = json.loads((d / 'watch.lock').read_text())['token'] if (d / 'watch.lock').exists() else None
    check('常駐期間有鎖、鎖 token 16 hex', bool(lock_before) and len(lock_before) == 16)
    # 第二個實例 → 退出碼 3（同平台、擁有者活著）
    p2 = subprocess.run([sys.executable, str(launcher)], capture_output=True, text=True, timeout=20)
    check('第二個實例 → 退出碼 3', p2.returncode == 3, p2.stderr.strip()[:80])
    t0 = time.time()
    p.send_signal(signal.SIGTERM)
    try:
        rc = p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill(); rc = None
    check('SIGTERM 在阻塞呼叫中 < 3 s 結束（退出碼 143）', rc == 143 and time.time() - t0 < 3, f'rc={rc} {time.time() - t0:.2f}s')
    st = json.loads((d / 'state.json').read_text()) if (d / 'state.json').exists() else {}
    check('SIGTERM 後鎖已刪、state phase=stopping / running=false', not (d / 'watch.lock').exists() and st.get('phase') == 'stopping' and st.get('watcher', {}).get('running') is False)
    check('SIGTERM 後沒有殘留暫存檔', not list(d.glob('*.tmp')))
else:
    print('SKIP SIGTERM 實測（非 POSIX；Windows 原生未測）')

# ---------------------------------------------------------------- 第 3 階段：HUD 數值（stat.ps1 合併）
STAT_OK = {'ok': True, 'level': '0轉77級', 'hp': 208, 'mp': 45, 'hpPct': 80, 'mpPct': 100, 'petLevel': '0轉77級', 'petHp': 434,
           'map': '奇努伊的海底通路', 'pos': '31401:91,29', 'raw': ['一0轉77級', '208', '45', '0轉77級', '434', '31401:91,29']}
STAT_EMPTY = {'ok': True, 'level': '', 'hp': None, 'mp': None, 'hpPct': None, 'mpPct': None, 'petLevel': '', 'petHp': None, 'map': '', 'pos': '', 'raw': ['', '', '', '', '', '']}


def run_cycles(w, clk, n, step=0.5):
    for _ in range(n):
        w.cycle()
        clk.t += step


watch.OCR_ON = True
w, clk, fk = make('hud')
fk.stat = (0, json.dumps(STAT_OK, ensure_ascii=False) + '\n', '')
run_cycles(w, clk, 8)
n_stat = sum(1 for c in fk.calls if c[0] == 'stat.ps1')
check('stat.ps1 約每 3 s 一次（8 輪 ≈ 4~5 s → 2 次）', n_stat == 2, str(n_stat))
check('stat 呼叫帶 timeout 8 s', all(c[2] == watch.PS_TIMEOUT for c in fk.calls if c[0] == 'stat.ps1'))
st = watchstate.read()
h = st['hud']
check('hud 欄位：level / hp / hpPct / mp / mpPct / pet / map / pos',
      h['level']['v'] == '0轉77級' and h['hp']['v'] == 208 and h['hpPct']['v'] == 80 and h['mp']['v'] == 45 and h['mpPct']['v'] == 100
      and h['pet']['level']['v'] == '0轉77級' and h['pet']['hp']['v'] == 434 and h['map']['v'] == '奇努伊的海底通路' and h['map']['id'] == 31401
      and h['pos']['v'] == [91, 29], json.dumps(h, ensure_ascii=False)[:200])
check('hud.ok = True、stale = False、每欄位帶 ts', h['ok'] is True and h['stale'] is False and all('ts' in h[k] for k in ('level', 'hp', 'pos')))
check('hud.raw 保留', h['raw'][1] == '208')
check('watcher.ocr_ms / ocr_every 有寫', 'ocr_ms' in st['watcher'] and st['watcher']['ocr_every'] == 3.0)
# 蓋住：ok:false → 保留舊值並標 stale
fk.stat = (0, json.dumps({'ok': False, 'error': '遊戲視窗最小化'}) + '\n', '')
clk.t += 3.1
w.cycle()
h = watchstate.read()['hud']
check('stat ok:false → 保留舊值、stale = True、ok = False', h['hp']['v'] == 208 and h['stale'] is True and h['ok'] is False, str(h.get('stale')))
# ok:true 但全空 → 同樣保留舊值（N6）
fk.stat = (0, json.dumps(STAT_EMPTY) + '\n', '')
clk.t += 3.1
w.cycle()
h = watchstate.read()['hud']
check('stat ok:true 全空（登入 / 選角）→ 保留舊值、不寫空值、stale', h['hp']['v'] == 208 and h['level']['v'] == '0轉77級' and h['stale'] is True)
# 部分欄位讀到：只更新有值的欄位，其餘保留舊值與舊 ts
t_old = h['mp']['ts']
fk.stat = (0, json.dumps({**STAT_EMPTY, 'hp': 150, 'hpPct': 60}) + '\n', '')
clk.t += 3.1
w.cycle()
h = watchstate.read()['hud']
check('部分欄位：hp 更新、mp 保留舊值與舊 ts', h['hp']['v'] == 150 and h['mp']['v'] == 45 and h['mp']['ts'] == t_old and h['hp']['ts'] > t_old and h['stale'] is False)
# stat 壞輸出 / 逾時 → 保留舊值
fk.stat = (0, 'garbage\n', '')
clk.t += 3.1
w.cycle()
check('stat 輸出不是 JSON → 保留舊值、stale', watchstate.read()['hud']['hp']['v'] == 150 and watchstate.read()['hud']['stale'] is True)
fk.stat = subprocess.TimeoutExpired('stat', 8)
clk.t += 3.1
w.cycle()
check('stat 逾時 → 保留舊值、stale、主迴圈照走', watchstate.read()['hud']['hp']['v'] == 150 and watchstate.read()['hud']['stale'] is True)
# 超過 12 s 沒成功 → stale（即使最近一次沒失敗紀錄）
fk.stat = (0, json.dumps(STAT_OK) + '\n', '')
clk.t += 3.1
w.cycle()
check('恢復後 stale = False', watchstate.read()['hud']['stale'] is False)
w.ocr_on = False
clk.t += 20
w.cycle()
check('超過 12 s 沒更新 → stale = True（值保留）', watchstate.read()['hud']['stale'] is True and watchstate.read()['hud']['hp']['v'] == 208)
# 對話 / 面板 / 完整戰鬥 / 最小化時不呼叫 stat
for sname, full_ok in (('dialog', True), ('panel', True), ('reward', True), ('battle', True)):
    w, clk, fk = make('hudskip_' + sname)
    fk.stat = (0, json.dumps(STAT_OK) + '\n', '')
    try:
        fk.pixel = (0, px_out(sname), '')
    except StopIteration:
        continue
    w.ocr_on = True
    run_cycles(w, clk, 4)
    cur = w.cur
    is_full_battle = cur == 'battle' and w.cls.get('full')
    n = sum(1 for c in fk.calls if c[0] == 'stat.ps1')
    check(f'畫面 {sname}（判成 {cur}{"/full" if is_full_battle else ""}）：{"不" if (cur not in watch.OCR_STATES or is_full_battle) else ""}呼叫 stat', (n == 0) == (cur not in watch.OCR_STATES or is_full_battle), str(n))
w, clk, fk = make('hudmin')
fk.info = (3, 'minimized\n', '')
fk.stat = (0, json.dumps(STAT_OK) + '\n', '')
w.ocr_on = True
run_cycles(w, clk, 3)
check('最小化 → 不呼叫 stat.ps1', not any(c[0] == 'stat.ps1' for c in fk.calls))
# 零輸入：加了 stat 之後仍只有 pixel / info / stat
w, clk, fk = make('hudwl')
fk.stat = (0, json.dumps(STAT_OK) + '\n', '')
w.ocr_on = True
run_cycles(w, clk, 10)
check('加入 stat 後：gui 只送 pixel / info、腳本只有 gui.ps1 / stat.ps1',
      {c[1][0] for c in fk.calls if c[0] == 'gui.ps1'} <= {'pixel', 'info'} and {c[0] for c in fk.calls} == {'gui.ps1', 'stat.ps1'})
# 內容不變不重寫：只有 hud ts / age_s 變不算變更
w, clk, fk = make('hudkey')
fk.stat = (0, json.dumps(STAT_OK) + '\n', '')
w.ocr_on = True
run_cycles(w, clk, 2)
k1 = watchstate.content_key(w.build())
clk.t += 0.2
w.hud['hp']['ts'] += 5; w.hud_ts += 5
check('hud 只有時間戳變 → content_key 不變', watchstate.content_key(w.build()) == k1)
watch.OCR_ON = False

winenv.run_ps, winenv._server_wanted, winenv.server_alive = real_run_ps, real_wanted, real_alive
print('\n全部通過' if not fails else f'\n{fails} 項失敗')
sys.exit(1 if fails else 0)
