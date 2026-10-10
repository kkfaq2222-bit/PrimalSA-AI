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
    elif a == 'byeme':
        send({'id': q['id'], 'rc': 0, 'out': 'last', 'err': '', 'bye': True}); break
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


winenv.PIDS_FILE = tmp / 'gui-server.pids'      # 登記檔也不要寫進專案
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
del os.environ['PSA_GUI_SERVER']
# DEFAULT_ON=None：依平台（WSL 預設開、Windows 原生 / linux 預設關）
winenv.DEFAULT_ON = None
_pk = winenv.platform_kind
try:
    winenv.platform_kind = lambda *a, **k: 'wsl'
    check('DEFAULT_ON=None + WSL → 走 server', winenv._server_wanted('gui.ps1'))
    os.environ['PSA_GUI_SERVER'] = '0'
    check('DEFAULT_ON=None + WSL + PSA_GUI_SERVER=0 → 不走 server', not winenv._server_wanted('gui.ps1'))
    del os.environ['PSA_GUI_SERVER']
    for kind in ('windows', 'linux'):
        winenv.platform_kind = lambda *a, _k=kind, **k: _k
        check(f'DEFAULT_ON=None + {kind} → 不走 server', not winenv._server_wanted('gui.ps1'))
    winenv.platform_kind = lambda *a, **k: 'windows'
    os.environ['PSA_GUI_SERVER'] = '1'
    check('DEFAULT_ON=None + windows + PSA_GUI_SERVER=1 → 走 server', winenv._server_wanted('gui.ps1'))
    del os.environ['PSA_GUI_SERVER']
finally:
    winenv.platform_kind = _pk
winenv.DEFAULT_ON = True
srv.close()

# 8) 參數拆解
sp = winenv.split_named
check('split ocr', sp('ocr', ['1', '2', '3', '4', '-Zooms', '2,3', '-Dark', '150']) == (['1', '2', '3', '4'], {'Zooms': '2,3', 'Dark': '150'}))
check('split 大小寫不拘、回正規名稱', sp('ocr', ['-zooms', '2']) == ([], {'Zooms': '2'}))
check('split 負數 / 不在白名單的 -xxx 當位置參數', sp('gui', ['click', '-5', '-Foo', 'x']) == (['click', '-5', '-Foo', 'x'], {}))
check('split 結尾的 -Note 沒有值 → 當位置參數', sp('gui', ['shot', '-Note']) == (['shot', '-Note'], {}))
check('split gui -NoRestore 1（pixel 帶 -NoRestore）', sp('gui', ['pixel', '1,2 3,4', '-NoRestore', '1']) == (['pixel', '1,2 3,4'], {'NoRestore': '1'}))
check('split titlematch', sp('titlematch', ['-Mode', 'match', '-Dir', 'C:\\a b', '-Thr', '0.6']) == ([], {'Mode': 'match', 'Dir': 'C:\\a b', 'Thr': '0.6'}))
# 白名單與 ps1 param 區塊同步
for name, names in winenv.SERVER_NAMED.items():
    txt = (winenv.GUI_DIR / f'{name}.ps1').read_text(encoding='utf-8-sig')
    m = re.search(r'^param\((.*)\)\s*$', txt, re.M)
    got = set(re.findall(r'\$([A-Za-z]+)', m[1])) if m else set()
    if name == 'gui':
        check('gui.ps1 param 具名參數 Scale / Note / NoRestore 都在', {'Scale', 'Note', 'NoRestore'} <= got)
        check('gui SERVER_NAMED 的每個名稱都在 gui.ps1 param', set(names) <= got, f'{got} vs {names}')
    else:
        check(f'{name}.ps1 param 與 SERVER_NAMED 一致', got == set(names), f'{got} vs {names}')

# gui.ps1 -NoRestore：最小化分支必須先判 NoRestore 再 ShowWindow（真機最小化情境無法在單元測試重現，只做靜態檢查）
_g = (winenv.GUI_DIR / 'gui.ps1').read_text(encoding='utf-8-sig')
_m = re.search(r"if \(\[W\]::IsIconic\(\$h\)\) \{(.*?)\n\}", _g, re.S)
check('gui.ps1 最小化分支：NoRestore=1 → minimized + exit 3，且在 ShowWindow 之前', bool(_m) and "$NoRestore -eq '1'" in _m[1] and 'exit 3' in _m[1]
      and _m[1].index("$NoRestore -eq '1'") < _m[1].index('ShowWindow'))
# gui.ps1 handle 快取：只給 pixel / info、命中要核對 IsWindow + PID、變數用 $global:__psa_ 前綴（靜態檢查；實機行為已手動驗過）
check('gui.ps1 handle 快取只限 pixel / info 且核對 IsWindow + PID', "$Cmd -eq 'pixel' -or $Cmd -eq 'info'" in _g and '[W]::IsWindow(' in _g and '$global:__psa_pid' in _g
      and re.search(r'\$global:(?!__psa_)\w+', _g) is None)
check('gui.ps1 保留 UTF-8 BOM', (winenv.GUI_DIR / 'gui.ps1').read_bytes()[:3] == b'\xef\xbb\xbf')

# 9) 逾時估算
et = winenv.estimate_timeout
check('唯讀預設 20 s', et('gui', ['info'], {}) == (20.0, False))
check('waitpix +5 s', et('gui', ['seq', 'waitpix 3000 1,2,3,4,5'], {}) == (28.0, False), str(et('gui', ['seq', 'waitpix 3000 1,2,3,4,5'], {})))
check('ocr Zooms 每倍數 +2 s', et('ocr', [], {'Zooms': '2,3,4,5,6,7'}) == (32.0, False))
check('click 是輸入類', et('gui', ['click', '1', '2'], {}) == (30.0, True))
check('seq 內有 click：等待 ×2 + 30', et('gui', ['seq', 'click 1 2; wait 500; waitpix 1500 1,2,3,4,5; ifok click 3 4'], {}) == (34.0, True))
check('seq 只有 ifnok key 也是輸入類', et('gui', ['seq', 'ifnok key {ESC}'], {})[1])
check('ifok / ifnok 前綴剝掉後再算等待', et('gui', ['seq', 'ifok wait 2000'], {}) == (27.0, False) and et('gui', ['seq', 'ifnok waitpix 1000 1,2,3,4,5'], {}) == (26.0, False), str(et('gui', ['seq', 'ifok wait 2000'], {})))
check('fg 前綴：輸入類且等待照算', et('gui', ['seq', 'fg click 1 2; fg wait 1000'], {}) == (32.0, True), str(et('gui', ['seq', 'fg click 1 2; fg wait 1000'], {})))
check('ifok fg click 疊前綴也是輸入類', et('gui', ['seq', 'ifok fg click 1 2'], {}) == (30.0, True))
check('waitstill 兩個參數相加', et('gui', ['seq', 'waitstill 3000 600'], {}) == (28.6, False) and et('gui', ['seq', 'waitstill 3000'], {}) == (28.0, False), str(et('gui', ['seq', 'waitstill 3000 600'], {})))

# 9b) 閒置快到期先重開 server；server 回 bye 時 client 主動關
srv = new_server('t9b'); enable(srv)
winenv.run_ps(G, 'x'); pid1 = srv.proc.pid
srv.last_resp = time.time() - (winenv.SERVER_IDLE_MIN * 60 - winenv.IDLE_MARGIN + 1)
r = winenv.run_ps(G, 'click', '1', '2')
check('閒置超過 (IDLE-15s) → 送輸入類前先重開 server', r.returncode == 0 and srv.proc.pid != pid1, f'{r.returncode}')
pid2 = srv.proc.pid
srv.last_resp = time.time() - 60
winenv.run_ps(G, 'x')
check('閒置未到門檻 → 不重開', srv.proc.pid == pid2)
r = winenv.run_ps(G, 'byeme')
check('回應帶 bye → 回應照常回傳、client 主動 close', r.returncode == 0 and r.stdout == 'last' and not srv.alive(), f'{r.returncode} {r.stdout!r}')
r = winenv.run_ps(G, 'click', '3', '4')
check('bye 之後下一次呼叫自動重開（不是 rc=125）', r.returncode == 0 and srv.alive())
srv.close()

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

# 12) 結束後 server 一定結束（2026-10-10 追查 serve.ps1 殘留後加固）
STUBBORN = r'''
import sys, json, time, os
sys.stdout.buffer.write(b"\n\x1ePSA " + json.dumps({"ready": True, "pid": 424242}).encode() + b"\n"); sys.stdout.buffer.flush()
time.sleep(600)   # 不理 quit、不理 stdin EOF（模擬卡住的 powershell.exe）
'''
killed = []
orig_taskkill = winenv._taskkill
winenv._taskkill = lambda pid: killed.append(pid) or True
winenv.CLOSE_WAIT = 0.5
stub = winenv.GuiServer(argv=[sys.executable, '-c', STUBBORN]); enable(stub)
check('卡住的 server 能啟動、記下 ready 的 PID；假 server 不寫登記檔（避免 reap 拿 Linux PID 去殺 Windows 行程）', stub.start() and stub.win_pid == 424242 and not winenv._pids_load(), str(winenv._pids_load()))
winenv._pids_add(os.getpid(), 424242)     # 手動登記，測 close() 會移除
t0 = time.time(); stub.close()
check('不理 quit / EOF 的 server：CLOSE_WAIT 後 kill 代理 + 用 Windows PID taskkill、登記移除', not stub.alive() and killed == [424242] and time.time() - t0 < 5 and not winenv._pids_load(), f'{killed} {time.time() - t0:.1f}s')
killed.clear()
srv = new_server('t12'); enable(srv); winenv.run_ps(G, 'x')
proc = srv.proc
srv.close()
check('正常 server：quit 後自行退出，不需要 kill / taskkill', proc.poll() is not None and not killed)
srv.close()   # 重複呼叫不出錯
winenv.shutdown_server()
check('shutdown_server() 關掉 _srv，可重複呼叫', not srv.alive())
srv = new_server('t12b'); enable(srv); winenv.run_ps(G, 'x'); proc = srv.proc
winenv.shutdown_server()
check('shutdown_server() 明確送 quit 並等到結束', proc.poll() is not None)

# 13) 殘留 server 清理：擁有者已死的登記項 → 清掉；擁有者還活著的不碰
ME = winenv.platform_kind()
OTHER = 'windows' if ME != 'windows' else 'wsl'
winenv._pids_save([{'owner': 111, 'win': 5001, 'plat': ME, 't': 0}, {'owner': 222, 'win': 5002, 'plat': ME, 't': 0}, {'owner': os.getpid(), 'win': 5003, 'plat': ME, 't': 0}])
killed.clear()
n = winenv.reap_orphans(alive=lambda pid: pid in (222, os.getpid()), kill=lambda w: killed.append(w) or True)
check('只殺擁有者已死的（111 → 5001），活著的 / 自己的不碰', n == 1 and killed == [5001], f'{n} {killed}')
check('登記檔只剩活著擁有者的項目', sorted(e['win'] for e in winenv._pids_load()) == [5002, 5003], str(winenv._pids_load()))
winenv._pids_save([{'owner': 111, 'win': 5001, 'plat': ME, 't': 0}])
check('殺不掉（kill 回 False）→ 回 0', winenv.reap_orphans(alive=lambda p: False, kill=lambda w: False) == 0)
PIDS_BAD = tmp / 'bad.pids'; PIDS_BAD.write_text('not json', encoding='utf-8'); winenv.PIDS_FILE = PIDS_BAD
check('登記檔壞掉 → 當空的，不丟例外', winenv._pids_load() == [] and winenv.reap_orphans() == 0)
winenv.PIDS_FILE = tmp / 'gui-server.pids'
# 13b) 跨平台：不同平台的登記，即使 alive 判成已死也不殺、不移除；舊格式（無 plat）只丟登記不殺
winenv._pids_save([{'owner': 111, 'win': 6001, 'plat': OTHER, 't': 0}, {'owner': 111, 'win': 6002, 't': 0}, {'owner': 111, 'win': 6003, 'plat': ME, 't': 0}])
killed.clear()
n = winenv.reap_orphans(alive=lambda p: False, kill=lambda w: killed.append(w) or True)
check('不同平台的登記不回收、舊格式不殺；只殺同平台已死擁有者', killed == [6003] and n == 1, str(killed))
check('不同平台登記仍留在檔內、舊格式已移除', [e['win'] for e in winenv._pids_load()] == [6001], str(winenv._pids_load()))
winenv._pids_save([{'owner': 333, 'win': 6101, 'plat': ME, 't': 0}])
killed.clear()
check('擁有者活著不回收', winenv.reap_orphans(alive=lambda p: True, kill=lambda w: killed.append(w) or True) == 0 and not killed and len(winenv._pids_load()) == 1)
winenv._pids_save([])
winenv._pids_add(os.getpid(), 7001)
check('_pids_add 記平台與擁有者', winenv._pids_load()[0].get('plat') == ME and winenv._pids_load()[0]['owner'] == os.getpid())
winenv._pids_remove(7001)
# 鎖檔：殘留的舊鎖會被接管；多執行緒同時登記不掉項目
import threading
lk = winenv.PIDS_FILE.with_name(winenv.PIDS_FILE.name + '.lock'); lk.write_text('x'); os.utime(lk, (1, 1))
winenv._pids_add(1, 7002)
check('殘留舊鎖被接管、鎖已釋放', [e['win'] for e in winenv._pids_load()] == [7002] and not lk.exists())
ths = [threading.Thread(target=winenv._pids_add, args=(1, 8000 + i)) for i in range(20)]
[t.start() for t in ths]; [t.join() for t in ths]
check('20 筆並行登記不掉項目', len(winenv._pids_load()) == 21, str(len(winenv._pids_load())))
winenv._pids_save([])
winenv._taskkill = orig_taskkill
winenv.CLOSE_WAIT = 2.0

# 14) 真 serve.ps1 的啟動指令帶閒置看門狗
argv = winenv.GuiServer()._argv()
check('serve.ps1 帶 -IdleMin（縮短殘留時間）', '-IdleMin' in argv and argv[argv.index('-IdleMin') + 1] == str(winenv.SERVER_IDLE_MIN) and winenv.SERVER_IDLE_MIN <= 5, str(argv))

# 15) SIGTERM：程序被 terminate 時先關 server（Python 預設直接死、不跑 atexit）
if sys.platform != 'win32':
    import signal
    child_code = f'''
import sys, time
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
import winenv
srv = winenv.GuiServer(argv=[sys.executable, {str(fake)!r}, {str(tmp / "t15")!r}])
winenv._srv = srv
winenv.PIDS_FILE = type(winenv.PIDS_FILE)({str(tmp / "t15.pids")!r})
import atexit; atexit.register(srv.close)
winenv._install_signal_handlers()
srv.start()
print(srv.proc.pid, flush=True)
time.sleep(60)
'''
    ch = subprocess.Popen([sys.executable, '-c', child_code], stdout=subprocess.PIPE, text=True)
    spid = int(ch.stdout.readline())
    ch.send_signal(signal.SIGTERM)
    ch.wait(timeout=10)
    time.sleep(0.5)
    try:
        os.kill(spid, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    check('SIGTERM 結束的程序：server 已一起結束，程序以 SystemExit(143) 結束', not alive and ch.returncode == 128 + signal.SIGTERM, f'alive={alive} rc={ch.returncode}')
    if alive:
        os.kill(spid, signal.SIGKILL)

    # 16) SIGTERM 後呼叫端的 finally / atexit 要跑；呼叫端自裝 handler 時串接
    for mode in ('default', 'chain'):
        mark = tmp / f't16_{mode}.txt'
        child_code = f'''
import sys, time, signal, atexit
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
import winenv
srv = winenv.GuiServer(argv=[sys.executable, {str(fake)!r}, {str(tmp / "t16")!r}])
winenv._srv = srv
winenv.PIDS_FILE = type(winenv.PIDS_FILE)({str(tmp / "t16.pids")!r})
mark = {str(mark)!r}
atexit.register(lambda: open(mark, 'a').write('atexit '))
if {mode!r} == 'chain':
    signal.signal(signal.SIGTERM, lambda s, f: (open(mark, 'a').write('mine '), sys.exit(7)))
winenv._install_signal_handlers()
srv.start()
print(srv.proc.pid, flush=True)
try:
    time.sleep(60)
finally:
    open(mark, 'a').write('finally ')
'''
        ch = subprocess.Popen([sys.executable, '-c', child_code], stdout=subprocess.PIPE, text=True)
        spid = int(ch.stdout.readline())
        ch.send_signal(signal.SIGTERM)
        ch.wait(timeout=10)
        got = mark.read_text() if mark.exists() else ''
        if mode == 'default':
            check('SIGTERM 後呼叫端 finally 與 atexit 都有跑', 'finally' in got and 'atexit' in got, got)
        else:
            check('呼叫端自裝 handler：關 server 後串接呼叫它（rc=7）、atexit 有跑', 'mine' in got and 'atexit' in got and ch.returncode == 7, f'{got} rc={ch.returncode}')
        try:
            os.kill(spid, signal.SIGKILL)
        except ProcessLookupError:
            pass

# 13) 呼叫端：walk.gui 對 rc=125 / 唯讀逾時 / 輸入類逾時的處理（monkeypatch run_ps，不碰遊戲）
import walk  # noqa: E402
_logs = []
_orig_log, _orig_run = walk.log, winenv.run_ps
walk.log = lambda msg, act=True: _logs.append(msg)
try:
    def _fake_run(kind):
        def f(script, *a, timeout=None):
            if kind == '125':
                return subprocess.CompletedProcess(['x'], 125, '', 'server 中途結束，輸入類指令不重送\n')
            raise subprocess.TimeoutExpired(['x'], 1)
        return f
    winenv.run_ps = _fake_run('125')
    out = walk.gui('click', '1', '2')
    check('walk.gui rc=125 → 寫警告事件、回錯誤文字', len(_logs) == 1 and 'rc=125' in _logs[0] and '中途結束' in out, str(_logs))
    winenv.run_ps = _fake_run('to'); _logs.clear()
    check('walk.gui 唯讀逾時 → 回空字串、不丟例外', walk.gui('pixel', '1,2') == '' and len(_logs) == 1)
    check('walk.gui seq 無輸入類逾時也回空', walk.gui('seq', 'waitpix 1000 1,2,3,4,5') == '')
    try:
        walk.gui('seq', 'click 1 2; wait 100'); ok = False
    except subprocess.TimeoutExpired:
        ok = True
    check('walk.gui 輸入類逾時 → 仍丟 TimeoutExpired（動作狀態不明）', ok)
    check('walk.stat 逾時 → ok=False 字典', walk.stat().get('ok') is False)
finally:
    walk.log, winenv.run_ps = _orig_log, _orig_run

print(f'failed={failed}')
sys.exit(1 if failed else 0)
