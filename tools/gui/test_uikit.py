#!/usr/bin/env python3
"""uikit / charstate 離線測試（不碰遊戲）：假 gui 模擬畫面像素與點擊。
用法：uv run --no-project python tools/gui/test_uikit.py"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import charstate  # noqa: E402
import screen_sigs  # noqa: E402
import uikit  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1


class Game:
    """假畫面：painted = {(x,y): (r,g,b)}；其餘點回黑色。gui('seq') 只記錄點擊，click 後可由 on_click 改畫面"""

    def __init__(self, hud=True, panel=False, unknown=False):
        self.painted, self.clicks, self.keys, self.t = {}, [], [], 0.0
        self.hud, self.panel, self.unknown = hud, panel, unknown
        self.reads = 0

    def paint(self, sig, on=True):
        for x, y, r, g, b, _ in sig:
            if on:
                self.painted[(x, y)] = (r, g, b)
            else:
                self.painted.pop((x, y), None)

    def sync(self):
        self.paint(screen_sigs.SIG_HUD, self.hud and not self.unknown)
        self.paint(screen_sigs.SIG_PANEL, self.panel)

    def gui(self, *args, note=''):
        if args[0] == 'pixel':
            self.reads += 1
            self.sync()
            pts = [tuple(int(v) for v in p.split(',')) for p in args[1].split()]
            return ' '.join('%d,%d,%d' % self.painted.get(p, (0, 0, 0)) for p in pts)
        if args[0] == 'seq':
            for part in args[1].split(';'):
                w = part.split()
                if w and w[0] == 'click':
                    xy = (int(w[1]), int(w[2]))
                    self.clicks.append(xy)
                    if xy == uikit.SWITCH.open_xy and self.hud:
                        self.panel = True
                    elif xy == uikit.SWITCH.close_xy:
                        self.panel = False
                elif w and w[0] == 'key':
                    self.keys.append(w[1])
                    if w[1] == '{ESC}':
                        self.panel = False
        return ''


def install(g):
    uikit.gui = g.gui
    uikit.sleep = lambda s: setattr(g, 't', g.t + s)
    uikit.clock = lambda: g.t
    return g


# ---- norm_char（與 watch 的 charname 同一套）----
cases = [('DKB0', 'DKB0'), ('DKBO', 'DKB0'), ('0KB0', 'DKB0'), ('0KBO', 'DKB0'), ('dkb02', 'DKB02'), ('DKB 03', 'DKB03'),
         ('0KB05', 'DKB05'), ('DKBO5', 'DKB05'), ('DKB06', None), ('', None), (None, None), ('KB05', None), ('DKB0 2 x', None)]
for src, want in cases:
    got = uikit.norm_char(src)
    check(f'norm_char({src!r}) = {want!r}', got == want, f'got {got!r}')
check('norm_char 與 charname 規則一致（canon）', uikit.norm_char('0KBO') == charstate.norm_char('0KBO'))
check('norm_char 自訂白名單撞名 → None', uikit.norm_char('DKB0', names=['DKB0', 'DKBO']) is None)

# ---- snap_pet ----
names = {'迪基格斯': '迪基格斯', '瑪斯貝卡': '瑪斯貝卡', '金布伊': '金布伊', '火雞': '火雞', '烏力烏力': '烏力烏力', '烏力烏拉': '烏力烏拉', '布魯布魯伊': '布魯布魯伊'}
snaps = [('迪基格斯', '迪基格斯'), (' 迪基 格斯 ', '迪基格斯'), ('布魯布魯尹', '布魯布魯伊'), ('迪基格期', None), ('', None), ('XYZ', None),
         ('烏力烏', None),                        # 兩個都一樣像 → 拒絕
         ('金布', None), ('瑪斯貝卞', None)]      # 太短 / 低於 0.8 → 拒絕（騎寵另用 is_mount_like）
for src, want in snaps:
    got = uikit.snap_pet(src, names=names)
    check(f'snap_pet({src!r}) = {want!r}', got == want, f'got {got!r}')
check('is_mount_like 瑪斯貝卞', uikit.is_mount_like('瑪斯貝卞'))
check('is_mount_like 瑪斯貝卡', uikit.is_mount_like('瑪斯貝卡'))
check('is_mount_like 迪基格斯 = False', not uikit.is_mount_like('迪基格斯'))
real = uikit.pet_names()
check('Monster 表有名字', len(real) > 100, f'{len(real)} 筆')
check('snap_pet 真表：瑪斯貝卡', uikit.snap_pet('瑪斯貝卡') == '瑪斯貝卡')
check('snap_pet 真表：迪基格斯', uikit.snap_pet('迪基格斯') == '迪基格斯')

# ---- FORBIDDEN ----
g = install(Game(panel=True))
for xy, nm in [((708, 565), 'trash'), ((372, 610), 'recycle'), ((708, 630), 'lock'), ((1195, 705), 'depot_expand')]:
    try:
        uikit.safe_click(*xy, uikit.PET)
        check(f'PET 禁區 {nm} 丟 ForbiddenClick', False)
    except uikit.ForbiddenClick:
        check(f'PET 禁區 {nm} 丟 ForbiddenClick', True)
check('禁區不點擊（0 次）', g.clicks == [])
try:
    uikit.safe_click(716, 578, uikit.SWITCH)
    check('SWITCH 全部登錄預設禁止', False)
except uikit.ForbiddenClick:
    check('SWITCH 全部登錄預設禁止', True)
g.clicks.clear()
check('allow=login_all 才放行', uikit.safe_click(716, 578, uikit.SWITCH, allow=('login_all',)) and g.clicks == [(716, 578)])
g.clicks.clear()
check('刷新鈕 910,578 不在禁區', uikit.safe_click(910, 578, uikit.SWITCH) and g.clicks == [(910, 578)])
# 掃：所有 PET 卡片 / 按鈕常用座標不在禁區
for xy in [(250, 200), (390, 702), (532, 702), (672, 702), (82, 322), (1365, 440), (530, 697)]:
    try:
        uikit.check_forbidden(uikit.PET, *xy)
        ok = True
    except uikit.ForbiddenClick:
        ok = False
    check(f'PET 正常座標 {xy} 不在禁區', ok)

# ---- 面板沒開不點 ----
g = install(Game(panel=False))
check('面板沒開 safe_click 回 False', uikit.safe_click(620, 300, uikit.SWITCH) is False)
check('面板沒開 0 次點擊', g.clicks == [])
g = install(Game(panel=False, hud=False))
check('HUD 不在（對話框等）不點開啟鈕、open_panel 失敗', uikit.open_panel(uikit.SWITCH, timeout=2) is False and g.clicks == [], str(g.clicks))
g = install(Game(panel=False, hud=True))
check('HUD 在 → 點開啟鈕開成功', uikit.open_panel(uikit.SWITCH) is True and g.clicks == [uikit.SWITCH.open_xy], str(g.clicks))
check('is_open 開著', uikit.is_open(uikit.SWITCH))
check('close_panel 成功', uikit.close_panel(uikit.SWITCH) is True and not g.panel)
g = install(Game(panel=True))
g.sync()
uikit.SWITCH.close_xy  # noqa: B018
check('已開著 open_panel 不再點', uikit.open_panel(uikit.SWITCH) is True and g.clicks == [])
check('TEAMPANEL 有特徵、✕ 在 1250,77', bool(uikit.TEAMPANEL.sig) and uikit.TEAMPANEL.close_xy == (1250, 77))
check('切換面板開著時 TEAMPANEL 不會誤判開著', uikit.is_open(uikit.TEAMPANEL) is False)
try:
    uikit.safe_click(720, 670, uikit.TEAMPANEL)
    check('TEAMPANEL 解散鈕 720,670 在禁區', False)
except uikit.ForbiddenClick:
    check('TEAMPANEL 解散鈕 720,670 在禁區', True)

# ---- preflight ----
import battleguard  # noqa: E402
import layout  # noqa: E402
import netwatch  # noqa: E402

layout.current = lambda: '2880x1659'
netwatch.guard = lambda src, **kw: {'status': 'ok'}
battleguard.LOCK_FILE = Path(tempfile.mkdtemp()) / 'battle.lock'

g = install(Game(hud=True))
check('preflight 主畫面 = 0', uikit.preflight('t') == 0)
g = install(Game(unknown=True))
rc = uikit.preflight('t')
check('preflight unknown 連 3 次 → 9', rc == 9 and g.reads == 3 and g.t >= 10.0, f'rc={rc} reads={g.reads} t={g.t}')
check('preflight unknown 時 0 點擊', g.clicks == [])


class Flaky(Game):
    """前兩次 unknown、第三次恢復 → 不退 9"""

    def gui(self, *a, **k):
        if a[0] == 'pixel':
            self.unknown = self.reads < 2
        return super().gui(*a, **k)


g = install(Flaky())
check('preflight unknown 2 次後恢復 → 0', uikit.preflight('t') == 0)
layout.current = lambda: '1920x1017'
check('preflight 版面不符 → 2', uikit.preflight('t') == 2)
layout.current = lambda: '2880x1659'
battleguard.LOCK_FILE.write_text(json.dumps({'pid': __import__('os').getpid(), 'start': __import__('time').time(), 'note': 'x'}), encoding='utf-8')
g = install(Game())
check('preflight battle.lock 有效 → 8', uikit.preflight('t') == 8)
battleguard.LOCK_FILE.unlink()

# ---- fail / snap 檔清理 ----
import errlog  # noqa: E402

errlog.LOG = Path(tempfile.mkdtemp()) / 'errlog.jsonl'
check('fail 回 rc 並寫 errlog', uikit.fail('t', 42, '測試') == 42 and errlog.LOG.exists())
d = Path(tempfile.mkdtemp())
(d / 'old.png').write_bytes(b'x')
(d / 'new.png').write_bytes(b'x')
(d / 'keep.txt').write_bytes(b'x')
import os  # noqa: E402
import time  # noqa: E402

os.utime(d / 'old.png', (time.time() - 5 * 86400,) * 2)
check('cleanup_old_shots 只刪舊 png', uikit.cleanup_old_shots(folder=d) == 1 and (d / 'new.png').exists() and (d / 'keep.txt').exists())

# ---- charstate（格式 = watchstate.write_current_char）----
tmp = Path(tempfile.mkdtemp()) / 'current-char.json'
import watchstate  # noqa: E402

watchstate.CURCHAR_FILE = tmp
check('charstate.write 正規化後寫入', charstate.write('0KBO', src='test', path=tmp) and json.loads(tmp.read_text(encoding='utf-8'))['name'] == 'DKB0')
d = charstate.read(path=tmp)
check('charstate.read 欄位 name/ts/src', d and d['name'] == 'DKB0' and d['src'] == 'test' and isinstance(d['ts'], float))
check('watchstate.read_current_char 同格式可讀', watchstate.read_current_char(tmp) == d)
check('charstate.read max_age 過期 → None', charstate.read(max_age=10, path=tmp, now=lambda: d['ts'] + 11) is None and charstate.read(max_age=10, path=tmp, now=lambda: d['ts'] + 5))
check('不在白名單不寫', charstate.write('DKB09', path=tmp) is False and charstate.read(path=tmp)['name'] == 'DKB0')
check('charstate.clear（未知）→ read None；重複 clear 也成功', charstate.clear(tmp) and charstate.read(path=tmp) is None and charstate.clear(tmp))
check('無暫存檔殘留', not list(tmp.parent.glob('*.tmp')))

print('失敗', fails)
sys.exit(1 if fails else 0)
