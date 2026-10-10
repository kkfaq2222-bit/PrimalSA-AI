#!/usr/bin/env python3
"""winenv 常駐 server client 的單元測試（不碰遊戲、不需要 powershell）：用 Python 寫的假 server 模擬協定與各種故障。
  uv run --no-project python tools/gui/test_winenv_server.py
假 server 的行為由請求的 pos[0] 決定：echo / sleep:<秒> / die / noise / bom / stale / big / stderr
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winenv  # noqa: E402

FAKE = r'''
import sys, json, time, os
out = sys.stdout.buffer
def send(o, pre=b'', post=b''):
    out.write(pre + b'\n\x1ePSA ' + json.dumps(o).encode('utf-8') + b'\n' + post); out.flush()
send({'ready': True, 'pid': os.getpid()})
state = sys.argv[1] if len(sys.argv) > 1 else ''
for line in sys.stdin:
    q = json.loads(line)
    if q.get('cmd') == 'quit':
        send({'id': q['id'], 'rc': 0, 'out': 'bye', 'err': ''}); break
    if q.get('cmd') == 'ping':
        send({'id': q['id'], 'rc': 0, 'out': 'pong', 'err': ''}); continue
    pos = q.get('pos') or ['']
    a = pos[0]
    if a.startswith('sleep:'):
        time.sleep(float(a[6:])); send({'id': q['id'], 'rc': 0, 'out': 'slept', 'err': ''})
    elif a == 'die':
        # 第一次死、記在檔案裡；之後正常（模擬 server 被殺後重開）
        flag = state + '.died'
        if not os.path.exists(flag):
            open(flag, 'w').close(); os._exit(3)
        send({'id': q['id'], 'rc': 0, 'out': 'second', 'err': ''})
    elif 'diealways' in pos:
        os._exit(3)
    elif a == 'noise':
        out.write(b'garbage line\n\xef\xbb\xbfmore noise\nPS C:\\> ' ); out.flush()   # 雜訊 + BOM + 標記不在行首
        send({'id': q['id'], 'rc': 0, 'out': 'after noise', 'err': ''}, pre=b'\xef\xbb\xbf')
    elif a == 'stale':
        send({'id': q['id'] - 100, 'rc': 0, 'out': 'STALE', 'err': ''})
        send({'id': q['id'], 'rc': 0, 'out': 'fresh', 'err': ''})
    elif a == 'big':
        send({'id': q['id'], 'rc': 0, 'out': '中文' * 50000, 'err': ''})
    elif a == 'stderr':
        sys.stderr.write('x' * 2000000); sys.stderr.flush()
        send({'id': q['id'], 'rc': 0, 'out': 'ok', 'err': ''})
    else:
        send({'id': q['id'], 'rc': 0, 'out': json.dumps(q, ensure_ascii=False), 'err': 'E\r\n'})
'''
failed = 0


def check(name: str, ok: bool, extra='') -> None:
    global failed
    print(('PASS ' if ok else 'FAIL ') + name + (f'  {extra}' if (extra and not ok) else ''))
    if not ok:
        failed += 1


tmp = Path(tempfile.mkdtemp(prefix='winenv_test_'))
fake = tmp / 'fake_server.py'
fake.write_text(FAKE, encoding='utf-8')


def new_server(tag='x') -> 'winenv.GuiServer':
    return winenv.GuiServer(argv=[sys.executable, str(fake), str(tmp / tag)])


def enable(srv) -> None:
    winenv._srv = srv
    winenv._enabled = True
    winenv._cooldown_until = 0
    winenv._start_fails = 0
    winenv._errlog_last.clear()


# errlog 不要真的寫進專案檔
logged = []
winenv._log_err = lambda kind, msg: logged.append(kind)
os.environ.pop('PSA_GUI_SERVER', None)
winenv.START_TIMEOUT = 5.0
winenv.DEFAULT_ON = True
# server 腳本檢查（路徑判斷）不依賴真實 gui 腳本是否存在；run_ps 的 script 用 gui.ps1（在 GUI_DIR）
G = 'gui.ps1'

# 1) 往返與 named 值一律字串
srv = new_server('t1'); enable(srv)
r = winenv.run_ps('ocr.ps1', '75', '270', '260', '180', '-Zooms', '2,3,4', '-Dark', '150')
q = json.loads(r.stdout)
check('往返：pos 與 named 拆對', q['pos'] == ['75', '270', '260', '180'] and q['named'] == {'Zooms': '2,3,4', 'Dark': '150'} and q['script'] == 'ocr', str(q))
check('named 值是字串', all(isinstance(v, str) for v in q['named'].values()))
check('stderr \\r 已去掉、rc 傳回', r.stderr == 'E\n' and r.returncode == 0, repr(r.stderr))
r = winenv.run_ps(G, 'seq', 'click 1 2; wait 300', '-Note', '中文 備註')
q = json.loads(r.stdout)
check('中文 -Note 往返', q['named'] == {'Note': '中文 備註'} and q['pos'] == ['seq', 'click 1 2; wait 300'], str(q))
check('ping / stats 管理指令', srv.admin('ping')['out'] == 'pong')
# 2) 雜訊 / BOM / 標記不在行首 / id 不符丟棄 / 大輸出
check('雜訊 + BOM + 標記不在行首', winenv.run_ps(G, 'noise').stdout == 'after noise')
check('id 不符的舊回應被丟棄', winenv.run_ps(G, 'stale').stdout == 'fresh')
check('大輸出（中文 10 萬字）', len(winenv.run_ps(G, 'big').stdout) == 100000)
check('server stderr 2 MB 不卡死', winenv.run_ps(G, 'stderr').stdout == 'ok')
srv.close()

# 3) 逾時：丟 TimeoutExpired、server 被殺、下一次自動重開
srv = new_server('t3'); enable(srv); logged.clear()
t0 = time.time()
try:
    winenv.run_ps(G, 'sleep:5', timeout=0.5)
    ok = False
except subprocess.TimeoutExpired:
    ok = True
check('逾時 → TimeoutExpired', ok and time.time() - t0 < 3)
check('逾時後 server 已關、errlog 記一筆', not srv.alive() and logged == ['timeout'], str(logged))
check('逾時後下一次呼叫自動重開', winenv.run_ps(G, 'x').returncode == 0 and srv.alive())
srv.close()

# 4) server 中途死掉：唯讀指令重開重試一次；輸入類不重送；一直死 → 回失敗不無限重試
srv = new_server('t4'); enable(srv); logged.clear()
r = winenv.run_ps(G, 'die')
check('唯讀指令遇 EOF → 重開重試一次成功', r.returncode == 0 and r.stdout == 'second', f'{r.returncode} {r.stdout!r}')
srv.close()
srv = new_server('t4b'); enable(srv)
r = winenv.run_ps(G, 'seq', 'diealways')
check('唯讀指令一直死 → 重試一次後回 rc=125，不無限重試', r.returncode == 125 and not srv.alive(), f'{r.returncode}')
srv.close()
srv = new_server('t4c'); enable(srv)
winenv.run_ps(G, 'x')   # 先起來
r = winenv.run_ps(G, 'click', 'diealways')
check('輸入類（click）遇 EOF 不重送 → rc=125', r.returncode == 125 and 'eof' in logged)
r = winenv.run_ps(G, 'seq', 'click 1 2; wait 10')
check('輸入類失敗後下一次呼叫會重開', r.returncode == 0 and srv.alive())
srv.close()

# 5) 寫入死管線（OSError）：還沒送出 → 重開後再送，不重複執行
srv = new_server('t5'); enable(srv)
winenv.run_ps(G, 'x')
srv.proc.stdin.close()      # 之後 write → ValueError（已關閉檔案）；Windows 原生則是 OSError，都在捕捉範圍
srv.proc.kill(); srv.proc.wait()
r = winenv.run_ps(G, 'click', '5', '6')
check('寫入失敗（server 已死）→ 重開後重送成功', r.returncode == 0 and json.loads(r.stdout)['pos'] == ['click', '5', '6'], r.stdout)
srv.close()

# 6) 起不來：連續 3 次後退回一次性並進入冷卻；冷卻期間不再嘗試
bad = winenv.GuiServer(argv=[sys.executable, '-c', 'import sys; sys.exit(7)'])
enable(bad); logged.clear()
calls = []
orig_oneshot = winenv._oneshot
winenv._oneshot = lambda s, *a, timeout=None: calls.append((s, a)) or subprocess.CompletedProcess([], 0, 'oneshot', '')
rs = [winenv.run_ps(G, 'info') for _ in range(4)]
check('起不來 → 退回一次性（每次都有結果）', all(r.stdout == 'oneshot' for r in rs) and len(calls) == 4)
check('連續 3 次失敗後進入冷卻、errlog 一筆', winenv._cooldown_until > time.time() and logged == ['start'], f'{logged}')
check('冷卻期間 _server_wanted = False', not winenv._server_wanted(G))
winenv._oneshot = orig_oneshot

# 7) 開關與白名單
srv = new_server('t7'); enable(srv)
check('enable 後 gui.ps1 走 server', winenv._server_wanted('gui.ps1'))
os.environ['PSA_GUI_SERVER'] = '0'
check('PSA_GUI_SERVER=0 關閉', not winenv._server_wanted('gui.ps1'))
del os.environ['PSA_GUI_SERVER']
check('非白名單腳本不走 server', not winenv._server_wanted('test_binarize.ps1') and not winenv._server_wanted('serve.ps1'))
check('其他資料夾的同名腳本不走 server', not winenv._server_wanted(str(tmp / 'gui.ps1')))
check('GUI_DIR 絕對路徑走 server', winenv._server_wanted(str(winenv.GUI_DIR / 'ocr.ps1')))
winenv._enabled = False
check('沒呼叫 enable_server() 不走 server', not winenv._server_wanted('gui.ps1'))
winenv._enabled = True; winenv.DEFAULT_ON = False
check('DEFAULT_ON=False 且沒設 PSA_GUI_SERVER=1 → 不走 server', not winenv._server_wanted('gui.ps1'))
os.environ['PSA_GUI_SERVER'] = '1'
check('PSA_GUI_SERVER=1 → 走 server', winenv._server_wanted('gui.ps1'))
del os.environ['PSA_GUI_SERVER']; winenv.DEFAULT_ON = True
srv.close()

# 8) 參數拆解
sp = winenv.split_named
check('split ocr', sp('ocr', ['1', '2', '3', '4', '-Zooms', '2,3', '-Dark', '150']) == (['1', '2', '3', '4'], {'Zooms': '2,3', 'Dark': '150'}))
check('split 大小寫不拘、回正規名稱', sp('ocr', ['-zooms', '2']) == ([], {'Zooms': '2'}))
check('split 負數 / 不在白名單的 -xxx 當位置參數', sp('gui', ['click', '-5', '-Foo', 'x']) == (['click', '-5', '-Foo', 'x'], {}))
check('split 結尾的 -Note 沒有值 → 當位置參數', sp('gui', ['shot', '-Note']) == (['shot', '-Note'], {}))
check('split titlematch', sp('titlematch', ['-Mode', 'match', '-Dir', 'C:\\a b', '-Thr', '0.6']) == ([], {'Mode': 'match', 'Dir': 'C:\\a b', 'Thr': '0.6'}))
# 白名單與 ps1 param 區塊同步
for name, names in winenv.SERVER_NAMED.items():
    txt = (winenv.GUI_DIR / f'{name}.ps1').read_text(encoding='utf-8-sig')
    m = re.search(r'^param\((.*)\)\s*$', txt, re.M)
    got = set(re.findall(r'\$([A-Za-z]+)', m[1])) if m else set()
    if name == 'gui':
        check('gui.ps1 param 具名參數 Scale / Note 都在', {'Scale', 'Note'} <= got)
    else:
        check(f'{name}.ps1 param 與 SERVER_NAMED 一致', got == set(names), f'{got} vs {names}')

# 9) 逾時估算
et = winenv.estimate_timeout
check('唯讀預設 20 s', et('gui', ['info'], {}) == (20.0, False))
check('waitpix +5 s', et('gui', ['seq', 'waitpix 3000 1,2,3,4,5'], {}) == (28.0, False), str(et('gui', ['seq', 'waitpix 3000 1,2,3,4,5'], {})))
check('ocr Zooms 每倍數 +2 s', et('ocr', [], {'Zooms': '2,3,4,5,6,7'}) == (32.0, False))
check('click 是輸入類', et('gui', ['click', '1', '2'], {}) == (30.0, True))
check('seq 內有 click：等待 ×2 + 30', et('gui', ['seq', 'click 1 2; wait 500; waitpix 1500 1,2,3,4,5; ifok click 3 4'], {}) == (34.0, True))
check('seq 只有 ifnok key 也是輸入類', et('gui', ['seq', 'ifnok key {ESC}'], {})[1])

# 10) 熱重載：腳本 mtime 變了 → 重開
srv = new_server('t10'); enable(srv)
winenv.run_ps(G, 'x'); pid1 = srv.proc.pid
srv.mt_checked = 0; srv.mtimes = {'serve': -1}
winenv.run_ps(G, 'x')
check('腳本 mtime 變動 → server 重開', srv.proc.pid != pid1)
srv.close()

# 11) atexit close 不拿鎖（鎖被別的執行緒佔著也不會死鎖）
srv = new_server('t11'); enable(srv); winenv.run_ps(G, 'x')
srv.lock.acquire()
t0 = time.time(); srv.close(); srv.lock.release()
check('close() 不拿鎖、1 秒內完成', time.time() - t0 < 3 and not srv.alive())

print(f'failed={failed}')
sys.exit(1 if failed else 0)
