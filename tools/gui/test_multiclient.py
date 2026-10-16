#!/usr/bin/env python3
"""多視窗 / 帳號對照 / 斷線改帳號重登 離線測試（不碰遊戲）：假的 gui / run_ps / stat，驗證
  - clients：主視窗沿用 tools/.cache/、其他視窗 clients/<資料夾名>/、代號對照、危險字元
  - accounts：check 不印帳號、格式錯誤訊息不含內容
  - netwatch.retype_account / relogin：
      鎖逾時不繼續打字、帳號欄清不掉不打字、密碼欄空 / 變空停手、絕不點密碼欄、
      多視窗沒對照不自動登入、別的視窗在打字時等待、非 2880 版面停手、全程 log 不含帳號
用法：uv run --no-project python tools/gui/test_multiclient.py
退出碼：0 全部通過、1 有失敗。
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import accounts  # noqa: E402
import clients  # noqa: E402
import netwatch  # noqa: E402
import walk  # noqa: E402

SECRET = 'SECRETacct9876'
fails = 0


def check(name, cond):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails += 1


tmp = Path(tempfile.mkdtemp())

# ---------------- clients ----------------
clients.CACHE = tmp
clients.CLIENTS_JSON = tmp / 'clients.json'
(tmp / 'clients.json').write_text(json.dumps({'kkfaq22222': 'PrimalSA222'}), encoding='utf-8')
os.environ.pop('PSA_EXE_MATCH', None)
check('沒設定 = 主視窗 → name None', clients.name() is None)
check('主視窗狀態資料夾 = cache 根目錄（沿用原路徑）', clients.state_dir() == tmp)
os.environ['PSA_EXE_MATCH'] = 'kkfaq22222'
check('代號經 clients.json 解析成資料夾名', clients.name() == 'PrimalSA222')
check('其他視窗 → clients/<資料夾名>/', clients.state_dir() == tmp / 'clients' / 'PrimalSA222' and clients.state_dir().is_dir())
os.environ['PSA_EXE_MATCH'] = '..\\..\\evil'
check('危險字元不會跳出 clients/', clients.state_dir().parent == tmp / 'clients')
os.environ.pop('PSA_EXE_MATCH', None)

# ---------------- accounts ----------------
af = tmp / 'accounts.local.json'
os.environ['PSA_ACCOUNTS_FILE'] = str(af)
check('設定檔不存在 → 沒有設定', accounts.load() == {} and not accounts.has_account('PrimalSA222'))
af.write_text(json.dumps({'kkfaq22222': SECRET, 'gameClient': 'other1'}), encoding='utf-8')
buf = io.StringIO()
with redirect_stdout(buf):
    rc = accounts.main(['check'])
out = buf.getvalue()
check('check 退出碼 0', rc == 0)
check('check 列出視窗與長度', 'kkfaq22222' in out and f'{len(SECRET)} 字' in out and 'PrimalSA222' in out)
check('check 不印帳號', SECRET not in out and 'other1' not in out)
check('has_account 代號 / 資料夾名都認', accounts.has_account('kkfaq22222') and accounts.has_account('gameClient'))
af.write_text('{"x": "' + SECRET + '", broken', encoding='utf-8')
try:
    accounts.load()
    msg = ''
except accounts.AccountsError as e:
    msg = f'{e}{e.__cause__ or ""}{e.__context__ if not e.__suppress_context__ else ""}'
check('壞 JSON → AccountsError 且訊息 / 原因不含帳號', msg and SECRET not in msg)
af.write_text(json.dumps({'w': {'account': SECRET, 'password': 'x'}}), encoding='utf-8')
try:
    accounts.load()
    msg = ''
except accounts.AccountsError as e:
    msg = str(e)
check('值不是字串（像放了密碼物件）→ 拒絕且不含內容', msg and SECRET not in msg)
check('accounts.check 用法錯誤 → 2', accounts.main(['show']) == 2)

# ---------------- netwatch：假畫面 ----------------
LOGS: list = []
netwatch.CACHE = tmp
netwatch.HALT = tmp / 'netwatch.halt'
netwatch.STATE = tmp / 'netwatch.json'
netwatch.ACT_LOCK = tmp / 'act.lock'
netwatch.LOGIN_LOCK = tmp / 'login-input.lock'
netwatch.log = lambda m, **k: LOGS.append(m)
netwatch.time.sleep = lambda *_: None
netwatch.errlog.add = lambda text, **k: (LOGS.append(text), len(LOGS))[1]
netwatch.errlog.fix = lambda i, text, **k: LOGS.append(text)
netwatch.actlog.add = lambda *a, **k: LOGS.append(' '.join(map(str, a)))
netwatch.recover = lambda *a, **k: {'stub': 1}
netwatch._ocr = lambda *a, **k: []
netwatch.layout.resolve = lambda: '2880x1659'

DARK, LIGHT = '50,40,30', '240,230,200'


def R(rc=0, out=''):
    return SimpleNamespace(returncode=rc, stdout=out, stderr='')


class Screen:
    """假遊戲：登入畫面 / 帳號欄 / 密碼欄 / 進遊戲。gui()、run_ps() 都接到這裡"""
    def __init__(self, acct=True, pwd=True, clearable=True, has=True, procs=2, lock_on=None,
                 pwd_drop_after_clear=False):
        self.acct, self.pwd, self.clearable = acct, pwd, clearable
        self.has, self.procs, self.lock_on = has, procs, lock_on
        self.pwd_drop_after_clear = pwd_drop_after_clear
        self.login, self.hud = True, False
        self.calls: list = []

    # winenv.run_ps
    def ps(self, script, *args, **kw):
        a0 = args[0] if args else ''
        if a0 == 'acctinfo':
            return R(0, f'client=PrimalSA222 acct={"yes" if self.has else "no"} len={len(SECRET) if self.has else 0} procs={self.procs}')
        if a0 == 'pixel':
            pts = args[1].split()
            y = int(pts[0].split(',')[1])
            filled = self.acct if y < 450 else self.pwd
            return R(0, ' '.join([DARK if filled else LIGHT] * len(pts)))
        if a0 == 'seq' and 'waitpix' in args[1]:
            if netwatch.SIG_LOGIN in args[1]:
                return R(0, 'ok 1' if self.login else 'timeout 1')
            return R(0, 'timeout 1')          # 對話框 / 選角都沒有
        return R(1)

    # walk.gui / netwatch.gui
    def gui(self, *a, note=''):
        self.calls.append(a)
        cmd = a[0]
        if cmd == 'seq' and 'key' in a[1]:                     # 點帳號欄 + 清空
            if self.lock_on == 'clear':
                return 'locktimeout'
            if self.clearable:
                self.acct = False
            if self.pwd_drop_after_clear:
                self.pwd = False
            return 'click ok\nkey ok'
        if cmd == 'typeacct':
            if self.lock_on == 'type':
                return 'locktimeout'
            self.acct = True
            return f'typeacct {len(SECRET)}'
        if cmd == 'click' and (a[1], a[2]) == tuple(map(str, netwatch.LOGIN_BTN)):
            if self.lock_on == 'login':
                return 'locktimeout'
            self.login, self.hud = False, True
        return f'{cmd} ok'

    def clicked_pwd(self) -> bool:
        pts = []
        for c in self.calls:
            if c[0] == 'click':
                pts.append((int(c[1]), int(c[2])))
            elif c[0] == 'seq':
                for step in c[1].split(';'):
                    t = step.split()
                    if t and t[0] in ('click', 'dclick'):
                        pts.append((int(t[1]), int(t[2])))
        return any(netwatch._in_box(p, netwatch.PWD_BOX, 0) for p in pts)

    def cmds(self):
        return [c[0] for c in self.calls]


def run(sc: Screen, fn='relogin'):
    for f in (netwatch.HALT, netwatch.STATE, netwatch.ACT_LOCK):
        f.unlink(missing_ok=True)
    netwatch._fail_id.clear()
    netwatch.winenv.run_ps = sc.ps
    netwatch.gui = sc.gui
    walk.stat = lambda: {'ok': True, 'pos': '1000:1,1', 'level': 'x'} if sc.hud else {'ok': True}
    buf = io.StringIO()
    with redirect_stdout(buf):
        r = netwatch.relogin('t')
    LOGS.append(buf.getvalue())
    return r


# 1) 正常：帳號欄是別的帳號 → 清空 → 打帳號 → 登錄 → 進遊戲
sc = Screen()
r = run(sc)
check('正常流程 → reconnected', r.get('status') == 'reconnected')
c = sc.cmds()
check('  順序：清空 → typeacct → 按登錄', c.index('seq') < c.index('typeacct') < len(c) - 1 and c[-1] == 'click')
check('  沒點密碼欄', not sc.clicked_pwd())
check('  登入輸入鎖已放', not netwatch.LOGIN_LOCK.exists())
check('  本視窗動作鎖已放', not netwatch.ACT_LOCK.exists())
check('  typeacct 不帶任何參數（帳號不經 Python）', all(len(x) == 1 for x in sc.calls if x[0] == 'typeacct'))

# 2) 帳號欄本來就空 → 直接點欄位打字（不清）
sc = Screen(acct=False)
r = run(sc)
check('帳號欄空 → 不清空，點欄位後直接打', r.get('status') == 'reconnected' and 'seq' not in sc.cmds() and 'typeacct' in sc.cmds())

# 3) 清不掉 → 不打字、halt
sc = Screen(clearable=False)
r = run(sc)
check('帳號欄清不掉 → halt、沒 typeacct、沒按登錄',
      r['status'] == 'halt' and '清不掉' in r['reason'] and 'typeacct' not in sc.cmds() and sc.cmds().count('click') == 0)
check('  halt 檔只寫在本視窗資料夾', netwatch.HALT.exists())

# 4) 密碼欄一開始就空 → halt，什麼都不點
sc = Screen(pwd=False)
r = run(sc)
check('密碼欄空 → halt、沒有任何點擊', r['status'] == 'halt' and '密碼欄' in r['reason'] and not sc.calls)

# 5) 清空後密碼欄變空（可能點錯欄位）→ 不打字
sc = Screen(pwd_drop_after_clear=True)
r = run(sc)
check('清空後密碼欄變空 → halt、沒 typeacct', r['status'] == 'halt' and 'typeacct' not in sc.cmds())

# 6) 點擊鎖逾時
sc = Screen(lock_on='clear')
r = run(sc)
check('清空時鎖逾時 → 不打字、不按登錄、下輪再試', r == {'status': 'ok', 'failed': True} and 'typeacct' not in sc.cmds())
check('  登入輸入鎖已放', not netwatch.LOGIN_LOCK.exists())
sc = Screen(lock_on='type')
r = run(sc)
check('打帳號時鎖逾時 → halt、不按登錄', r['status'] == 'halt' and sc.cmds()[-1] == 'typeacct')
sc = Screen(lock_on='login')
r = run(sc)
check('按登錄時鎖逾時 → 不宣告成功', r.get('status') != 'reconnected')

# 7) 多視窗、本視窗沒對照 → 不自動登入
sc = Screen(has=False, procs=2)
r = run(sc)
check('多視窗沒對照 → halt、沒有任何點擊', r['status'] == 'halt' and '沒有帳號對照' in r['reason'] and not sc.calls)
# 單視窗沒對照 → 舊行為（帳密欄都有字就只按登錄，不打字）
sc = Screen(has=False, procs=1)
r = run(sc)
check('單視窗沒對照 → 只按登錄、不打字', r.get('status') == 'reconnected' and sc.cmds() == ['click'])

# 8) 別的視窗正在打字 → 等待，不動作
netwatch.LOGIN_LOCK.write_text('999 0')
sc = Screen()
r = run(sc)
check('登入輸入鎖被佔 → busy、沒有任何點擊', r.get('busy') and not sc.calls)
netwatch.LOGIN_LOCK.unlink()

# 9) 非 2880 版面 → 不打帳號
netwatch.layout.resolve = lambda: '1920x1017'
sc = Screen()
r = run(sc)
check('1920 版面（帳號欄座標未量）→ halt、沒有任何點擊', r['status'] == 'halt' and not sc.calls)
netwatch.layout.resolve = lambda: '2880x1659'

# 10) 讀不到帳號欄 → 不點、不 halt（下輪重試）
sc = Screen()
orig = sc.ps


def blind_acct(script, *args, **kw):
    if args and args[0] == 'pixel' and int(args[1].split()[0].split(',')[1]) < 450:
        return R(1)
    return orig(script, *args, **kw)


sc.ps = blind_acct
r = run(sc)
check('讀不到帳號欄 → ok/failed、沒點擊', r == {'status': 'ok', 'failed': True} and not sc.calls)

# 11) 全程 log / errlog / 印出 都不含帳號
check('全部 log 不含帳號', all(SECRET not in str(x) for x in LOGS))
src = Path(netwatch.__file__).read_text(encoding='utf-8')
check('netwatch 不 import accounts / 不讀帳號檔（帳號只在 gui.ps1 typeacct 裡）',
      'import accounts' not in src and 'PSA_ACCOUNTS_FILE' not in src and 'read_text' not in src.split('def _acct_info', 1)[1].split('def hud_ok', 1)[0])
check('.gitignore 排除 accounts.local.json',
      'accounts.local.json' in (Path(__file__).resolve().parents[2] / '.gitignore').read_text(encoding='utf-8'))

print('全部通過' if not fails else f'{fails} 項失敗')
sys.exit(1 if fails else 0)
