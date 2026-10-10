#!/usr/bin/env python3
"""quest.py --fight / --solo 的戰鬥分類模擬測試（不碰遊戲）：假時鐘 + 假 read_screen / gui，驗證 BOSS 戰 / 小怪判斷與退出碼。
用法：uv run --no-project python tools/gui/test_quest_fight.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quest  # noqa: E402
import battleguard  # noqa: E402
import tempfile as _tf
battleguard.LOCK_FILE = Path(_tf.mkdtemp()) / 'battle.lock'      # 測試用鎖檔位置，不碰真正的 tools/.cache/battle.lock
REAL_READ_SCREEN = quest.read_screen                             # 同上：真的 read_screen（測像素分類）
REAL_CHECK_TEAM = quest.check_team                               # run() 會把 quest.check_team 換成假的；真函式留著測像素邏輯

IDLE = {'state': 'idle', 'gold': 0, 'full': False, 'cmd': False, 'auto_off': False}
DIALOG = dict(IDLE, state='dialog')


class Sim:
    """假遊戲：phase 依虛擬時間排程；點 1380,600 切換自動戰鬥、點逃跑 1283,168 結束小怪戰"""

    def __init__(self, battle_at=None, auto_on=False, dialog_at=None, boss_ends=8.0):
        self.t = 1000.0
        self.clicks = []
        self.battle_at, self.dialog_at = battle_at, dialog_at
        self.auto_on, self.battle_end = auto_on, None
        self.boss_ends = boss_ends
        self.fled = False
        self.dialog_given = False

    def time(self):
        return self.t

    def sleep(self, d):
        self.t += d

    def gui(self, *args, note=''):
        cmd = args[1] if args[0] == 'seq' else ''
        self.clicks.append((round(self.t - 1000, 1), cmd))
        if cmd.startswith('click 1380 600'):
            self.auto_on = not self.auto_on
        if cmd.startswith('click 1283 168'):
            self.fled = True
        return ''

    def screen(self):
        rel = self.t - 1000
        if self.dialog_at is not None and rel >= self.dialog_at and not self.dialog_given and (self.battle_at is None or rel < self.battle_at):
            self.dialog_given = True                     # 對話框出現一輪，按鈕被按掉後消失
            return dict(DIALOG)
        if self.battle_at is not None and rel >= self.battle_at and not self.fled:
            if self.battle_end is None:
                self.battle_end = rel + self.boss_ends
            if rel < self.battle_end:
                cmd = not self.auto_on
                return {'state': 'battle', 'gold': 0, 'full': True, 'cmd': cmd, 'auto_off': not self.auto_on}
        return dict(IDLE)


TEAM = {'ret': (True, 'fake 隊伍完整'), 'calls': []}


def fake_team(size, tag=''):
    TEAM['calls'].append((size, tag))
    return TEAM['ret']


def run(argv, sim):
    quest.time.time, quest.time.sleep = sim.time, sim.sleep
    quest.read_screen, quest.gui, quest.read_pos = sim.screen, sim.gui, lambda: (5510, 50, 17)
    quest.walk.gui = sim.gui
    quest.check_team = fake_team
    quest.snap = lambda tag: 'sim.png'
    quest.event = lambda m, shot=None: print(f'   [{sim.t - 1000:5.1f}s] {m}')
    quest.layout.current = lambda: '2880x1659'
    quest.clef.available = lambda: False
    quest.netwatch.guard = lambda *_: {'status': 'ok'}
    sys.argv = ['quest.py'] + argv
    return quest.main()


def check(name, cond, extra=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' ' + extra if extra else ''))
    return cond


def has(sim, prefix):
    return [c for c in sim.clicks if c[1].startswith(prefix)]


ok = True
print('(a) 沒點 NPC 就進戰鬥（20 秒後）：逃跑、不開自動戰鬥')
s = Sim(battle_at=20.0, auto_on=False)
rc = run(['--fight', '--no-click', '--max-seconds', '60'], s)
ok &= check('exit 0（時間到）', rc == 0, f'rc={rc}')
ok &= check('有按逃跑', bool(has(s, 'click 1283 168')))
ok &= check('沒按自動戰鬥', not has(s, 'click 1380 600'))

print('(b) 點 NPC 後 3 秒進戰鬥：開自動戰鬥、打完退出')
s = Sim(battle_at=3.0, auto_on=False, boss_ends=10.0)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
ok &= check('exit 0（BOSS 戰結束）', rc == 0 and s.t - 1000 < 60, f'rc={rc} t={s.t - 1000:.0f}s')
ok &= check('先點 NPC', bool(s.clicks) and s.clicks[0][1].startswith('click 1215 18; wait 100; click '), str(s.clicks[:1]))
ok &= check('按了自動戰鬥、沒逃跑', len(has(s, 'click 1380 600')) == 1 and not has(s, 'click 1283 168'))

print('(b2) 點 NPC → 對話框 → 戰鬥：BOSS 戰')
s = Sim(dialog_at=2.0, battle_at=6.0, auto_on=False)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
ok &= check('exit 0', rc == 0, f'rc={rc}')
ok &= check('按對話左鈕 + 自動戰鬥、沒逃跑', bool(has(s, 'click 948 461')) and len(has(s, 'click 1380 600')) == 1 and not has(s, 'click 1283 168'))

print('(c) 自動戰鬥開著遇小怪：先關再逃')
s = Sim(battle_at=20.0, auto_on=True)
rc = run(['--fight', '--no-click', '--max-seconds', '60'], s)
seq = [c[1] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 1283 168'))]
ok &= check('順序：關自動 → 逃跑', seq == ['click 1380 600', 'click 1283 168'], str(seq))
print('(c2) --solo 同樣情境')
s = Sim(battle_at=5.0, auto_on=True)
rc = run(['--solo', '--no-track', '--max-seconds', '40'], s)
seq = [c[1] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 1283 168'))]
ok &= check('--solo 順序：關自動 → 逃跑', seq == ['click 1380 600', 'click 1283 168'], str(seq))

print('(c3) 外掛自動逃跑相關已全部移除：沒有 --manual-escape / --skip-ass-check、退出碼 27 / 28 / 29、讀外掛的程式')
for flag in ('--manual-escape', '--skip-ass-check'):
    s = Sim()
    try:
        run(['--solo', '--no-track', flag, '--max-seconds', '10'], s)
        rejected = False
    except SystemExit as e:
        rejected = e.code == 2
    ok &= check(f'{flag} 已移除（argparse 拒絕）', rejected)
ok &= check('沒有 EXIT_ESCAPE_TIMEOUT / EXIT_ESCAPE_ON / EXIT_ASS_SETUP / SOLO_BATTLE_MAX / check_ass_setup / import ass',
            not any(hasattr(quest, n) for n in ('EXIT_ESCAPE_TIMEOUT', 'EXIT_ESCAPE_ON', 'EXIT_ASS_SETUP', 'SOLO_BATTLE_MAX', 'check_ass_setup', 'ass')))
print('(c4) --solo 戰鬥 400 秒不結束：不再有 27 超時，只到 --max-seconds 結束（0）；第一輪就逃跑，不刷新角色')
s = Sim(battle_at=5.0, auto_on=False, boss_ends=400.0)
rc = run(['--solo', '--no-track', '--max-seconds', '100'], s)
ok &= check('exit 0（時間到）、有逃跑', rc == 0 and bool(has(s, 'click 1283 168')), f'rc={rc}')
ok &= check('--solo 不刷新角色（沒點切換 850,765 / 763,760）', not has(s, 'click 850 765') and not has(s, 'click 763 760'), str(s.clicks))
print('(c5) --fight --no-click：路上小怪（20 秒後才進戰鬥，不在 15 秒時間窗）→ 手動逃跑、不開自動、不刷新')
s = Sim(battle_at=20.0, auto_on=False, boss_ends=10.0)
rc = run(['--fight', '--no-click', '--max-seconds', '60'], s)
ok &= check('小怪：按逃跑、沒按自動戰鬥、沒刷新', bool(has(s, 'click 1283 168')) and not has(s, 'click 1380 600') and not has(s, 'click 850 765'), str(s.clicks))
print('(c6) --fight 任務 / BOSS 戰（點 NPC 後 3 秒開打）：自動戰鬥 + 刷新角色（完整戰鬥切換 850,765；打完前每 REFRESH_GAP 秒一次）')
s = Sim(battle_at=3.0, auto_on=False, boss_ends=20.0)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
seq = [c[1].split(';')[0] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 850 765', 'click 1283 168'))]
ok &= check('順序：先自動戰鬥，再刷新；沒逃跑', seq[:2] == ['click 1380 600', 'click 850 765'] and 'click 1283 168' not in seq, str(seq))
ok &= check('20 秒的戰鬥刷新 2~3 次（不是每秒一次）', 2 <= seq.count('click 850 765') <= 3, str(seq))
ok &= check('刷新用 waitpix + ifok click 910 578', any('waitpix' in c[1] and 'ifok click 910 578' in c[1] for c in s.clicks))
s = Sim(battle_at=3.0, auto_on=False, boss_ends=10.0)
rc = run(['--fight', '--npc', '53,17', '--no-refresh', '--max-seconds', '120'], s)
ok &= check('--no-refresh 不刷新（仍開自動戰鬥）', not has(s, 'click 850 765') and len(has(s, 'click 1380 600')) == 1)
print('(d) 點 NPC 後沒反應')
s = Sim()
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
ok &= check('exit 22', rc == quest.EXIT_NO_NPC, f'rc={rc} t={s.t - 1000:.0f}s')

print('(e) 對話後一直沒開打')
s = Sim(dialog_at=2.0)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
ok &= check('exit 23', rc == quest.EXIT_NO_BATTLE, f'rc={rc}')

# ---- 新增：--stop-after-dialog 跨步 / 組隊完整戰鬥 / --disband-after ----
class Script:
    """依序回傳預先排好的畫面（每次 read_screen 取下一個，最後一個重複）；gui 只記錄點擊"""

    def __init__(self, seq, pixel=None):
        self.seq, self.i, self.t, self.clicks = seq, 0, 1000.0, []
        self.pixel = pixel or (lambda args: '')

    def time(self):
        return self.t

    def sleep(self, d):
        self.t += d

    def screen(self):
        s = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return dict(s)

    def gui(self, *args, note=''):
        if args[0] == 'seq':
            self.clicks.append((round(self.t - 1000, 1), args[1]))
            return ''
        if args[0] == 'pixel':
            return self.pixel(args)
        return ''


def run2(argv, sim, clef_ret=None):
    quest.time.time, quest.time.sleep = sim.time, sim.sleep
    quest.read_screen, quest.gui, quest.read_pos = sim.screen, sim.gui, lambda: None
    quest.walk.gui = sim.gui
    quest.snap = lambda tag: 'sim.png'
    quest.event = lambda m, shot=None: print(f'   [{sim.t - 1000:5.1f}s] {m}')
    quest.layout.current = lambda: '2880x1659'
    quest.check_team = fake_team
    quest.clef.available = lambda: clef_ret is not None
    if clef_ret is not None:
        quest.clef_shot_bytes = lambda: b'x'
        quest.clef.classify_scene = lambda img: dict(clef_ret)
    quest.netwatch.guard = lambda *_: {'status': 'ok'}
    quest.find_marker = lambda: (_ for _ in ()).throw(AssertionError('不該找黃問號'))
    quest.track_task = lambda *a, **k: (_ for _ in ()).throw(AssertionError('不該點追蹤'))
    sys.argv = ['quest.py'] + argv
    return quest.main()


REWARD = dict(IDLE, state='reward')
WALK = dict(IDLE, state='walking')
FULL_CMD_OFF = {'state': 'battle', 'gold': 0, 'full': True, 'cmd': True, 'auto_off': True}

print('(f) --stop-after-dialog：步 1 對話完（含獎勵）→ 閒置滿 2.5 秒就停，沒點追蹤 / 黃問號（深紅事故）')
s = Script([DIALOG, DIALOG, REWARD, IDLE, IDLE, IDLE, IDLE, DIALOG, DIALOG])   # 預設 --every 1.0：閒置要滿 2.5 秒（第 4 個閒置畫面）才停
rc = run2(['--stop-after-dialog', '--task', '深紅洞窟', '--max-seconds', '120'], s)
ok &= check('exit 0', rc == 0, f'rc={rc}')
ok &= check('停在步 1：只用掉 7 個畫面（沒看到步 2 的對話）、花 6 秒', s.i == 7 and s.t - 1000 == 6.0, f'i={s.i} t={s.t - 1000}')
ok &= check('沒有任何追蹤 / 問號點擊（只有對話左鈕 + 獎勵確認）', all(c[1].startswith(('click 948 461', 'click 720 572')) for c in s.clicks), str(s.clicks))

print('(f1) 預設輪詢間隔 = 1.0 秒')
s = Script([DIALOG, IDLE, IDLE, IDLE, IDLE, IDLE])
rc = run2(['--stop-after-dialog', '--task', 'x', '--max-seconds', '120'], s)
ok &= check('每輪 sleep 1.0（點擊時間 0.0 / 之後每秒一輪）', quest.DEFAULT_EVERY == 1.0 and s.t - 1000 == 4.0, f't={s.t - 1000}')
print('(f2) --stop-after-dialog：步完成後遊戲自己開始 Auto Walking → 退出碼 24')
s = Script([DIALOG, IDLE, WALK])
rc = run2(['--stop-after-dialog', '--task', '深紅洞窟', '--max-seconds', '120'], s)
ok &= check('exit 24', rc == quest.EXIT_AUTOWALK, f'rc={rc}')

print('(g) 組隊預設模式完整戰鬥、自動戰鬥關：按 1380,600（不逃跑）')
s = Script([FULL_CMD_OFF, FULL_CMD_OFF, dict(FULL_CMD_OFF, cmd=False, auto_off=False), IDLE], None)
rc = run2(['--no-track', '--max-seconds', '30'], s)
ok &= check('有按自動戰鬥、沒按逃跑', len(has(s, 'click 1380 600')) == 1 and not has(s, 'click 1283 168'), str(s.clicks))
print('(g2) 按了 4 次仍關 → 退出碼 25')
s = Script([FULL_CMD_OFF])
rc = run2(['--no-track', '--max-seconds', '120'], s)
ok &= check('exit 25', rc == quest.EXIT_BATTLE_STUCK and len(has(s, 'click 1380 600')) == quest.AUTO_STUCK_MAX, f'rc={rc} n={len(has(s, "click 1380 600"))}')

print('(h) --disband-after（分頁 / 隊長紅標像素用 2026-10-10 實機量測值）')
TAB_TEAM_PX = {'130,222': '87,68,41', '130,250': '85,65,41', '270,222': '215,185,139', '270,250': '205,173,131'}   # 組隊分頁選中
TAB_TASK_PX = {'130,222': '213,179,128', '130,250': '211,179,128', '270,222': '90,69,41', '270,250': '87,70,41'}   # 任務分頁選中
BADGE_RED, BADGE_NONE = '217,33,33', '245,223,187'


def px_fake(tab=TAB_TEAM_PX, badges=(True, False)):
    """gui('pixel') 假回應：4 點分頁探針 / 4 點隊長紅標（依序消耗 badges；讀不到用 'err'）"""
    it = iter(badges)

    def pixel(args):
        pts = args[1].split()
        if pts[0] == '130,222':
            return ' '.join(tab[p] for p in pts)
        if pts[0] == '100,306':
            b = next(it, False)
            return 'err' if b == 'err' else ' '.join([BADGE_RED if b else BADGE_NONE] * 4)
        return ''
    return pixel


print('(h0) tab_state / has_leader_badge 像素判斷')
for nm, tab, want in [('組隊選中', TAB_TEAM_PX, 'team'), ('任務選中', TAB_TASK_PX, 'task'),
                      ('舊探針式混雜（y=225 邊緣一點不準）', dict(TAB_TEAM_PX, **{'130,250': '213,181,131'}), None)]:
    quest.gui = Script([IDLE], px_fake(tab)).gui
    ok &= check(f'tab_state {nm} → {want}', quest.tab_state() == want, str(quest.tab_state()))
quest.gui = Script([IDLE], px_fake(badges=(True, False))).gui
ok &= check('has_leader_badge 紅標 True', quest.has_leader_badge() is True)
ok &= check('has_leader_badge 米色 False', quest.has_leader_badge() is False)
quest.gui = Script([IDLE], px_fake(badges=('err',))).gui
ok &= check('has_leader_badge 讀不到 None', quest.has_leader_badge() is None)


def disband_case(name, tab, badges, sigs, want_rc, want_btn, want_leader):
    s = Script([IDLE], px_fake(tab, badges))
    quest.time.time, quest.time.sleep = s.time, s.sleep
    quest.gui, quest.snap = s.gui, lambda tag: 'sim.png'
    quest.event = lambda m, shot=None: print(f'   {m}')
    sig_seq(*sigs)
    rc = quest.disband_team()
    ok_ = rc == want_rc and bool(has(s, 'click 200 372')) == want_btn and bool(has(s, 'click 210 320')) == want_leader
    return check(f'disband {name}', ok_, f'rc={rc} {[c[1][-14:] for c in s.clicks]}')


def sig_seq(*vals):
    it = iter(vals)
    quest.list_signature = lambda: next(it)


ok &= disband_case('成功（紅標消失、面板有變）', TAB_TEAM_PX, (True, False), ('a', 'b', 'c'), 0, True, True)
ok &= disband_case('分頁沒切過去 → 不點隊長列也不點解散', TAB_TASK_PX, (True, False), ('a', 'b', 'c'), quest.EXIT_DISBAND_FAIL, False, False)
ok &= disband_case('已是單人（無紅標）→ 不點任何東西、退出碼 0', TAB_TEAM_PX, (False,), ('a', 'b', 'c'), 0, False, False)
ok &= disband_case('紅標讀不到 → 26 不點', TAB_TEAM_PX, ('err',), ('a', 'b', 'c'), quest.EXIT_DISBAND_FAIL, False, False)
ok &= disband_case('選單沒彈出 → 不點解散', TAB_TEAM_PX, (True, False), ('a', 'a', 'c'), quest.EXIT_DISBAND_FAIL, False, True)
ok &= disband_case('解散後畫面沒變 → 未確認', TAB_TEAM_PX, (True, False), ('a', 'b', 'b'), quest.EXIT_DISBAND_FAIL, True, True)
ok &= disband_case('解散後紅標還在 → 未確認', TAB_TEAM_PX, (True, True), ('a', 'b', 'c'), quest.EXIT_DISBAND_FAIL, True, True)

print('(h2) --stop-after-dialog --disband-after：停止後才解散；分頁沒切過去 → 26')
s = Script([DIALOG, IDLE, IDLE, IDLE, IDLE], px_fake(TAB_TASK_PX))
rc = run2(['--stop-after-dialog', '--disband-after', '--task', 'x', '--max-seconds', '60'], s)
ok &= check('exit 26 且沒點解散', rc == quest.EXIT_DISBAND_FAIL and not has(s, 'click 200 372') and not has(s, 'click 210 320'), f'rc={rc} {s.clicks}')

print('(i) 清理 3 天前截圖（暫存資料夾）')
import os, tempfile
from pathlib import Path as _P
with tempfile.TemporaryDirectory() as d:
    d = _P(d)
    now = 10_000_000.0
    def mk(n, age_days):
        (d / n).write_bytes(b'x')
        os.utime(d / n, (now - age_days * 86400, now - age_days * 86400))
    mk('old.png', 4)
    mk('old2.jpg', 10)
    mk('new.png', 1)
    mk('edge.png', 2.9)
    mk('old.json', 30)                                  # 非圖檔不碰
    (d / 'sub').mkdir()
    (d / 'sub' / 'deep.png').write_bytes(b'x')
    os.utime(d / 'sub' / 'deep.png', (now - 99 * 86400, now - 99 * 86400))   # 子資料夾內的不碰
    n = quest.cleanup_old_shots(3, d, now)
    left = sorted(f.name for f in d.iterdir())
    ok &= check('刪 2 張（old.png / old2.jpg）', n == 2 and left == ['edge.png', 'new.png', 'old.json', 'sub'], f'n={n} left={left}')
    ok &= check('子資料夾內檔案還在', (d / 'sub' / 'deep.png').exists())
ok &= check('資料夾不存在 → 0、不丟例外', quest.cleanup_old_shots(3, _P('/nonexistent-psa-dir'), 1.0) == 0)
calls = []
quest.cleanup_old_shots = lambda *a, **k: (calls.append(1), 7)[1]
s = Script([DIALOG, IDLE, IDLE, IDLE, IDLE])
run2(['--stop-after-dialog', '--task', 'x', '--max-seconds', '60'], s)
ok &= check('main 啟動時呼叫清理', len(calls) == 1)

print('(j) Clef 驗證視窗門檻：低信心當不認得，高信心停手')
import clef as _clef
_clef.available = lambda: True
_clef.prepare = lambda png, box=None, width=None: b'img'


def fake_run(vp, scene_p=0.5):
    def run(model, state, qs, imgs):
        return {'scene': {'probabilities': {'戰鬥中': scene_p, '其他': 1 - scene_p}}, 'verify': {'noul': vp}}
    return run


for vp, want in [(0.105, False), (0.3, False), (0.6, True), (0.9, True)]:
    _clef.run = fake_run(vp)
    ok &= check(f'classify_scene verify={vp} → alarm {want}', _clef.classify_scene(b'x')['alarm'] is want)
_clef.run = lambda *a: {'scene': {'probabilities': {'答題或驗證視窗': 0.95, '其他': 0.05}}, 'verify': {'noul': 0.01}}
ok &= check('場景判驗證窗（p>=0.85）仍 alarm', _clef.classify_scene(b'x')['alarm'] is True)

UNK = dict(IDLE, state='unknown')
print('(k) quest.py：Clef verify=0.105 不立刻停手，照 3 次不認得（滿 5 秒）才停 → 鐵則 5')
s = Script([UNK])
rc = run2(['--no-track', '--max-seconds', '60'], s, clef_ret={'scene': None, 'p': 0.4, 'model': 'clef', 'verify_p': 0.105, 'alarm': False})
ok &= check('exit 2 且不是第 1 次就停（>= 5 秒）', rc == 2 and s.t - 1000 >= quest.UNKNOWN_CONFIRM_SECS, f'rc={rc} t={s.t - 1000}')
print('(k2) verify=0.9（alarm）→ 第 1 次就停')
s = Script([UNK])
rc = run2(['--no-track', '--max-seconds', '60'], s, clef_ret={'scene': None, 'p': 0.4, 'model': 'clef', 'verify_p': 0.9, 'alarm': True})
ok &= check('exit 2 立刻', rc == 2 and s.t - 1000 < 1, f'rc={rc} t={s.t - 1000}')
print('(k3) 沒有 Clef：連續 3 次不認得但沒滿 5 秒不停；滿 5 秒才停')
s = Script([UNK])
rc = run2(['--no-track', '--max-seconds', '60'], s)
ok &= check('exit 2，t >= 5', rc == 2 and s.t - 1000 >= 5.0, f'rc={rc} t={s.t - 1000}')
print('(k4) Clef 載入 / 戰鬥判斷：最多連續 CLEF_WAIT_SECS 秒不算不認得，之後照舊停手')
s = Script([UNK])
rc = run2(['--no-track', '--max-seconds', '300'], s, clef_ret={'scene': '戰鬥中', 'p': 0.9, 'model': 'clef-flash', 'verify_p': 0.0, 'alarm': False})
ok &= check('exit 2，約 50 秒後', rc == 2 and quest.CLEF_WAIT_SECS <= s.t - 1000 <= quest.CLEF_WAIT_SECS + 8, f'rc={rc} t={s.t - 1000}')


# ---- 事故後新增：隊伍檢查 / 戰鬥鎖檔 / --npc auto 取目前步驟 ----
import argparse
import os
print('(m) 隊伍標籤像素判斷（隊長紅、隊員黃、底深棕；2026-10-10 實機：隊長紅點 30、隊員黃點 42~44）')
RED, YEL, BG = (217, 33, 33), (240, 200, 60), (78, 66, 59)
n_s = len(quest.TEAM_SAMPLE)
ok &= check('紅點 >= 8 → leader', quest.classify_team_label([RED] * 12 + [BG] * (n_s - 12)) == 'leader')
ok &= check('黃點 >= 8 → member', quest.classify_team_label([YEL] * 12 + [BG] * (n_s - 12)) == 'member')
ok &= check('只有底色 / 白字 → other', quest.classify_team_label([BG] * n_s) == 'other' and quest.classify_team_label([(240, 240, 240)] * 12 + [BG] * (n_s - 12)) == 'other')
ok &= check('紅點太少（<8）→ other', quest.classify_team_label([RED] * 3 + [BG] * (n_s - 3)) == 'other')
ALL5 = {'DKB0': 'leader', 'DKB02': 'member', 'DKB03': 'member', 'DKB04': 'member', 'DKB05': 'member'}
ok &= check('judge 5 人隊 OK', quest.judge_team(ALL5, 5)[0])
four = dict(ALL5, DKB04='other')
j = quest.judge_team(four, 5)
ok &= check('judge 4 人（DKB04 單人）不符且說明點名 DKB04', (not j[0]) and 'DKB04' in j[1].split('不在隊')[1], j[1])
ok &= check('judge 兩個隊長 / 無隊長 不符', not quest.judge_team(dict(ALL5, DKB02='leader'), 5)[0] and not quest.judge_team(dict(ALL5, DKB0='member'), 5)[0])
ok &= check('--team-size 4：4 人隊 + 另 1 人單人（DKB04 other）→ 通過（單人卡片不算錯）', quest.judge_team(four, 4)[0])
ok &= check('--team-size 5 + 1 人單人 → 仍不符（5 人都要在隊）', not quest.judge_team(four, 5)[0])
ok &= check('--team-size 4 但只有 3 人在隊 → 不符', not quest.judge_team(dict(four, DKB05='other'), 4)[0])
ok &= check('--team-size 2：隊長 + 1 隊員，其餘 3 張單人 → 通過', quest.judge_team({'DKB0': 'leader', 'DKB02': 'member', 'DKB03': 'other', 'DKB04': 'other', 'DKB05': 'other'}, 2)[0])
ok &= check('隊長是單人（全 other，沒有隊長）→ 不符', not quest.judge_team({r: 'other' for r in ALL5}, 4)[0])


class PanelGame:
    """假遊戲：點切換 763,760 開面板；點 ✕ 1064,208 關；pixel 回隊伍標籤顏色（其餘點回 SIG_PANEL 色 / 0）"""

    def __init__(self, kinds, opens=True):
        self.kinds, self.opens, self.panel, self.clicks = kinds, opens, False, []

    def gui(self, *args, note=''):
        if args[0] == 'seq':
            self.clicks.append(args[1])
            if args[1].startswith('click 763 760') and self.opens:
                self.panel = True
            if args[1].startswith('click 1064 208'):
                self.panel = False
            return ''
        if args[0] == 'key':
            self.clicks.append('key ' + args[1])
            self.panel = False
            return ''
        if args[0] == 'pixel':
            return team_px(self.kinds)(args)
        return ''

    def screen(self):
        return dict(IDLE, state='panel' if self.panel else 'idle')


def team_px(kinds):
    col = {'leader': RED, 'member': YEL, 'other': BG}
    return lambda args: ' '.join(' '.join(['%d,%d,%d' % col[kinds[r]]] * n_s) for r in quest.TEAM_CARDS)


print('(m2) check_team（真函式 + 假面板）：5 人 OK / 4 人不符 / 面板沒開；每次都關面板、沒開就不讀')
for nm, kinds, opens, want in [('5 人', ALL5, True, True), ('4 人', four, True, False), ('面板打不開', ALL5, False, None)]:
    pg = PanelGame(kinds, opens)
    quest.gui, quest.read_screen = pg.gui, pg.screen
    res = REAL_CHECK_TEAM(5, '測試：')
    ok &= check(f'{nm} → {want}', res[0] is want and not pg.panel, str(res))
    if opens:
        ok &= check(f'{nm}：用 ✕ 1064,208 關面板', any(c.startswith('click 1064 208') for c in pg.clicks), str(pg.clicks))

print('(n) --fight 4 人隊 → 不點 NPC，退出碼 30；5 人 → 照常點')
TEAM['ret'], TEAM['calls'] = (False, "隊長 ['DKB0']、隊員 ['DKB02', 'DKB03', 'DKB05']、不在隊 / 單人 / 離線 ['DKB04']"), []
s = Sim(battle_at=3.0)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '60'], s)
ok &= check('exit 30、沒任何點擊、檢查人數 5', rc == quest.EXIT_TEAM_MISMATCH and not s.clicks and TEAM['calls'] == [(5, '--fight 點 NPC 前：')], f'rc={rc} clicks={s.clicks} calls={TEAM["calls"]}')
TEAM['ret'], TEAM['calls'] = (None, '切換面板沒打開'), []
s = Sim(battle_at=3.0)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '60'], s)
ok &= check('讀不到隊伍 → 也不點 NPC（30）', rc == 30 and not s.clicks)
TEAM['ret'], TEAM['calls'] = (True, 'ok'), []
s = Sim(battle_at=3.0, boss_ends=8.0)
rc = run(['--fight', '--npc', '53,17', '--team-size', '4', '--max-seconds', '60'], s)
ok &= check('--team-size 4 傳給檢查；通過 → 點 NPC、BOSS 戰結束 0', rc == 0 and TEAM['calls'][0][0] == 4 and bool(s.clicks) and s.clicks[0][1].startswith('click 1215 18'), f'rc={rc} {TEAM["calls"]}')
TEAM['ret'], TEAM['calls'] = (False, 'x'), []
s = Sim(battle_at=3.0, boss_ends=8.0)
rc = run(['--fight', '--npc', '53,17', '--team-size', '0', '--max-seconds', '60'], s)
ok &= check('--team-size 0 跳過檢查', rc == 0 and not TEAM['calls'])
s = Sim(battle_at=3.0, boss_ends=8.0)
rc = run(['--fight', '--no-click', '--max-seconds', '60'], s)
ok &= check('--no-click 不檢查隊伍', rc == 0 and not TEAM['calls'])
TEAM['ret'] = (True, 'ok')

print('(n2) 預設模式（要點追蹤）：開跑前檢查；脫隊 → 退出碼 32，沒點追蹤 / 黃問號；--solo / --no-track 不檢查')
TEAM['calls'] = []
s = Script([IDLE, IDLE])
TEAM['ret'] = (False, "不在隊 ['DKB03']")
rc = run2(['--task', 'x', '--max-seconds', '60'], s)
ok &= check('exit 32 且沒有點擊（find_marker / track_task 沒被呼叫）', rc == quest.EXIT_TEAM_LOST and not s.clicks and len(TEAM['calls']) == 1, f'rc={rc} {s.clicks}')
for extra in (['--no-track'], ['--solo', '--no-track']):
    TEAM['calls'] = []
    s = Script([IDLE, IDLE, IDLE, IDLE])
    rc = run2(extra + ['--max-seconds', '4'], s)
    ok &= check(f'{" ".join(extra)} 不檢查隊伍', not TEAM['calls'] and rc == 0, f'rc={rc}')
print('(n3) 預設模式：兩次檢查間隔 >= TEAM_CHECK_GAP（通過後不每秒都開面板）')
TEAM['ret'], TEAM['calls'] = (True, 'ok'), []
tracked_n = []
s = Script([IDLE] * 3)
quest.find_marker = lambda: None
quest.track_task = lambda *a, **k: (tracked_n.append(1), None)[1]       # None = 畫面變了，交回主迴圈（不計 task_miss）
rc = None
quest.time.time, quest.time.sleep = s.time, s.sleep
quest.read_screen, quest.gui, quest.read_pos = s.screen, s.gui, lambda: None
quest.walk.gui = s.gui
quest.snap = lambda tag: 'sim.png'
quest.event = lambda m, shot=None: None
quest.layout.current = lambda: '2880x1659'
quest.clef.available = lambda: False
quest.netwatch.guard = lambda *_: {'status': 'ok'}
sys.argv = ['quest.py', '--task', 'x', '--max-seconds', '8']
rc = quest.main()
ok &= check('8 秒內只檢查 1 次、追蹤點了多次', len(TEAM['calls']) == 1 and len(tracked_n) >= 3, f'checks={len(TEAM["calls"])} tracks={len(tracked_n)}')

print('(o) 戰鬥鎖檔：戰鬥中存在（含 pid）、戰鬥結束 / 程式結束後刪除')
seen = []


class LockSim(Sim):
    def screen(self):
        r = super().screen()
        seen.append((r['state'], battleguard.locked() is not None))
        return r


s = LockSim(battle_at=3.0, auto_on=False, boss_ends=8.0)
rc = run(['--fight', '--no-click', '--max-seconds', '60'], s)
bat = [x for st_, x in seen if st_ == 'battle']
ok &= check('戰鬥畫面第 2 次讀起鎖檔都有效（第 1 次讀到戰鬥時才剛寫鎖）', len(bat) >= 2 and all(bat[1:]), str(bat))
ok &= check('戰鬥結束後鎖檔已刪', not battleguard.LOCK_FILE.exists())
idle_after = [x for st_, x in seen[seen.index(next(e for e in seen if e[0] == 'battle')):] if st_ == 'idle']
ok &= check('戰鬥後第一次看到閒置時鎖已刪', idle_after and not idle_after[-1], str(idle_after[:2]))
battleguard.acquire('x')
d = battleguard.locked()
ok &= check('locked() 回 pid = 自己', d and d['pid'] == os.getpid())
battleguard.LOCK_FILE.write_text('{"pid": 99999999, "start": %f}' % __import__('time').time())
ok &= check('死 pid 的鎖 → 視為無鎖並清掉', battleguard.locked() is None and not battleguard.LOCK_FILE.exists())
battleguard.LOCK_FILE.write_text('{"pid": %d, "start": 1}' % os.getpid())
ok &= check('超過 30 分鐘的鎖 → 無效', battleguard.locked(now=1e9) is None)
s = Sim(battle_at=3.0, boss_ends=1000.0)
try:
    run(['--fight', '--no-click', '--max-seconds', '30'], s)
except Exception:
    pass
ok &= check('--max-seconds 到時（戰鬥中）程式結束 → 鎖檔刪除', not battleguard.LOCK_FILE.exists())

print('(p) --npc auto 取「目前步驟」：追蹤說明文字對 Task 表（任務 碧青洞窟 2002）')


def ns(**kw):
    d = dict(npc='auto', task='碧青洞窟', step=0, at='', npc_map=None)
    d.update(kw)
    return argparse.Namespace(**d)


def with_ocr(lines):
    quest.ps_json = lambda script, *args: {'ok': True, 'lines': [{'text': t, 'y': y, 'x': 200} for t, y in lines]}


quest.event = lambda m, shot=None: None
with_ocr([('碧青洞窟', 309), ('找菲伊拿群青的水', 341), ('漆黑洞窟(一轉)', 426)])
a_ = ns()
ok &= check('說明「找菲伊拿群青的水」→ 步 6 菲伊 31302:27,31', quest.resolve_npc(a_) == (27, 31) and a_.npc_map == 31302)
with_ocr([('碧青洞窟', 309), ('獲取深藍色的石頭', 341)])
a_ = ns()
ok &= check('說明「獲取深藍色的石頭」→ 步 5（30305:57,48），不是第一個戰鬥步（8 樓）', quest.resolve_npc(a_) == (57, 48) and a_.npc_map == 30305)
with_ocr([('碧青洞窟', 309), ('獲取深籃色的石頭', 341), ('獲取深藍色的石頭', 341)])
ok &= check('OCR 錯 1 字也能對到（相似度 >= 0.8）', quest.resolve_npc(ns()) == (57, 48))
with_ocr([('碧青洞窟', 309), ('通過碧青9樓的挑戰', 341)])
ok &= check('步 2 / 7 同文字同 NPC（21208:30,16）→ 可判定', quest.resolve_npc(ns()) == (30, 16))
for nm, lines in [('說明文字對不到', [('碧青洞窟', 309), ('完全不相干的文字', 341)]),
                  ('讀不到說明行', [('碧青洞窟', 309)]),
                  ('標題不在這一頁', [('漆黑洞窟(一轉)', 309), ('找菲伊拿群青的水', 341)]),
                  ('兩步同文字但 NPC 不同（步 9 / 10）', [('碧青洞窟', 309), ('尋找水蒼洞窟賢者', 341)]),
                  ('OCR 整個空', [])]:
    with_ocr(lines)
    a_ = ns()
    r = quest.resolve_npc(a_)
    ok &= check(f'{nm} → None + 退出碼 31', r is None and a_.resolve_rc == quest.EXIT_STEP_UNKNOWN, f'r={r} rc={a_.resolve_rc}')
with_ocr([])
a_ = ns(step=9)
ok &= check('--step 9 不用 OCR → 賢者看門人 21308:20,10', quest.resolve_npc(a_) == (20, 10))
ok &= check('--step 99 不存在 → 31', quest.resolve_npc(ns(step=99)) is None)
a_ = ns(task='')
ok &= check('沒給 --task → None（退出碼 4）', quest.resolve_npc(a_) is None and a_.resolve_rc == 4)
a_ = ns(task='不存在的任務名xyz')
ok &= check('任務表找不到 → 31', quest.resolve_npc(a_) is None and a_.resolve_rc == 31)
print('(p2) main：--fight --npc auto 讀不到步驟 → 退出碼 31，沒任何點擊')
with_ocr([('碧青洞窟', 309), ('亂七八糟', 341)])
s = Sim(battle_at=3.0)
rc = run(['--fight', '--npc', 'auto', '--task', '碧青洞窟', '--max-seconds', '30'], s)
ok &= check('exit 31 且沒點擊', rc == quest.EXIT_STEP_UNKNOWN and not s.clicks, f'rc={rc}')
s = Sim(battle_at=3.0)
rc = run(['--fight', '--step', '5', '--at', '57,47', '--task', '碧青洞窟', '--max-seconds', '30'], s)
ok &= check('--step 5（隱含 --npc auto）→ 通過隊伍檢查後點 NPC', rc == 0 and bool(s.clicks), f'rc={rc}')


# ---- 2026-10-10 外掛自動逃跑移除後新增：OCR 步驟比對 / 選擇對象面板 / 底部關閉列 / 刷新角色規則 ----
print('(q) --npc auto：OCR 把「9樓」讀成「婁」（2026-10-10 17:30 事故，相似度 0.67 → 退出碼 31）')
quest.event = lambda m, shot=None: None
INCIDENT = [('碧青洞窟', 309), ('通過碧青婁的', 341), ('通過碧青婁的扌覜戈', 341)]
with_ocr(INCIDENT)
quest.read_pos = lambda: (21208, 31, 16)
a_ = ns()
ok &= check('在 8 樓 21208 → 步 2（水的守護獸 30,16）', quest.resolve_npc(a_) == (30, 16) and a_.npc_map == 21208)
quest.read_pos = lambda: (21214, 30, 41)
a_ = ns()
ok &= check('在 14 樓 21214 → 步 3（NPC 不同的相似步驟，用所在地圖分辨）→ 30,40', quest.resolve_npc(a_) == (30, 40) and a_.npc_map == 21214)
quest.read_pos = lambda: (21215, 25, 31)
a_ = ns()
ok &= check('在第三張圖（兩個候選的地圖都不符）→ 31，不誤配', quest.resolve_npc(a_) is None and a_.resolve_rc == 31)
quest.read_pos = lambda: None
a_ = ns()
ok &= check('讀不到所在地圖 → 31', quest.resolve_npc(a_) is None and a_.resolve_rc == 31)
quest.read_pos = lambda: (21208, 31, 16)
a_ = ns(at='31,16')
ok &= check('手動給 --at（不知地圖）+ 相似步驟 NPC 不同 → 31', quest.resolve_npc(a_) is None and a_.resolve_rc == 31)
with_ocr([('碧青洞窟', 309), ('通過碧青9樓的', 341)])
quest.read_pos = lambda: None
ok &= check('被截斷但數字讀對「通過碧青9樓的」→ 步 2，不需要地圖', quest.resolve_npc(ns()) == (30, 16))
with_ocr([('碧青洞窟', 309), ('通過碧青14樓的', 341)])
ok &= check('被截斷「通過碧青14樓的」→ 步 3（30,40）', quest.resolve_npc(ns()) == (30, 40))
with_ocr([('碧青洞窟', 309), ('尋找水蒼洞窟賢', 341)])
quest.read_pos = lambda: (21308, 20, 11)
a_ = ns()
ok &= check('步 9 / 10 同文字同地圖、NPC 不同（賢者看門人 / 賢者）→ 仍 31（地圖分不出）', quest.resolve_npc(a_) is None and a_.resolve_rc == 31)
with_ocr([('碧青洞窟', 309), ('通過碧青婁的', 341)])
quest.read_pos = lambda: (21208, 31, 16)
ok &= check('step_score：完整相符 1.0 > 骨架相符；骨架相同的步 2/3 差 < 0.05（平手）',
            quest.step_score('通過碧青9樓的挑戰', '通過碧青9樓的挑戰') == 1.0 and abs(quest.step_score('通過碧青婁的', '通過碧青9樓的挑戰') - quest.step_score('通過碧青婁的', '通過碧青14樓的挑戰')) < 0.05)
ok &= check('step_score：太短的前綴（< 5 字）不當前綴用', quest.step_score('尋找女神', '尋找女神艾妮基') < 0.8)
ok &= check('step_score：不相干文字低分', quest.step_score('完全不相干的文字', '通過碧青9樓的挑戰') < 0.5)

print('(r) 選擇對象面板（樣本 tools/.cache/quest-log/172356-no-npc.png 離線算出的黃色色塊）')
SAMPLE_BLOBS = [dict(x=775, y=62, w=4, h=6, n=8), dict(x=720, y=292, w=7, h=9, n=22), dict(x=1353, y=265, w=4, h=3, n=6),
                dict(x=1171, y=331, w=14, h=4, n=21), dict(x=1208, y=337, w=15, h=15, n=50), dict(x=1138, y=337, w=11, h=14, n=37),
                dict(x=1154, y=337, w=15, h=14, n=71), dict(x=1189, y=336, w=2, h=7, n=10), dict(x=1193, y=335, w=2, h=6, n=9),
                dict(x=1131, y=338, w=5, h=9, n=18), dict(x=1172, y=339, w=15, h=11, n=41), dict(x=1185, y=342, w=5, h=5, n=15),
                dict(x=1193, y=342, w=9, h=4, n=19), dict(x=1174, y=364, w=4, h=3, n=8), dict(x=1264, y=364, w=5, h=3, n=7),
                dict(x=205, y=451, w=24, h=15, n=124), dict(x=261, y=582, w=18, h=18, n=233), dict(x=760, y=747, w=44, h=18, n=329)]
pt = quest.pick_select_card(SAMPLE_BLOBS)
ok &= check('黃字名字「水的守護獸」→ 點第 1 張卡片頭像（x≈1170、y≈289），場景 / UI 的黃色塊都不算', pt is not None and abs(pt[0] - 1171) <= 6 and abs(pt[1] - 289) <= 4, str(pt))
second = [dict(b, x=b['x'] + 90) for b in SAMPLE_BLOBS if 1100 < b['x'] < 1250 and 320 < b['y'] < 350]
pt2 = quest.pick_select_card(second)
ok &= check('NPC 在第 2 格（黃字右移 90）→ 點第 2 格，不寫死第一格', pt2 is not None and abs(pt2[0] - 1261) <= 6 and pt2[1] == pt[1], str(pt2))
row2 = [dict(b, y=b['y'] + 100) for b in SAMPLE_BLOBS if 1100 < b['x'] < 1250 and 320 < b['y'] < 350]
pt3 = quest.pick_select_card(row2)
ok &= check('NPC 在第 2 排（y+100）→ y 跟著下移', pt3 is not None and pt3[1] == pt[1] + 100, str(pt3))
ok &= check('沒有黃字（全是隊友白字）→ None，不亂點', quest.pick_select_card([b for b in SAMPLE_BLOBS if not (1100 < b['x'] < 1250 and 320 < b['y'] < 350)]) is None and quest.pick_select_card([]) is None)

SELECT_COL = {(x, y): (r, g, b) for x, y, r, g, b in quest.SIG_SELECT}
HUD_COL = {(x, y): (r, g, b) for x, y, r, g, b in quest.SIG_HUD}


def fake_pixel_gui(colors):
    return lambda *args, **k: ' '.join('%d,%d,%d' % colors.get(tuple(int(v) for v in p.split(',')), (60, 90, 60)) for p in args[1].split()) if args[0] == 'pixel' else ''


quest.gui = fake_pixel_gui({**SELECT_COL, **HUD_COL})
ok &= check('read_screen：選擇面板 + HUD 紅字 → state select（不是 idle）', REAL_READ_SCREEN()['state'] == 'select')
quest.gui = fake_pixel_gui(dict(HUD_COL))
ok &= check('read_screen：只有 HUD 紅字 → idle', REAL_READ_SCREEN()['state'] == 'idle')
quest.gui = fake_pixel_gui({**{k: v for k, v in list(SELECT_COL.items())[:-1]}, **HUD_COL})
ok &= check('read_screen：選擇面板少 1 點 → 不判 select', REAL_READ_SCREEN()['state'] == 'idle')

SELECT = dict(IDLE, state='select')
quest.ps_json = lambda script, *args: {'ok': True, 'blobs': SAMPLE_BLOBS}


def clicks_at(s, x, y):
    return [c for c in s.clicks if c[1] == f'click {x} {y}']


print('(r2) 對話步：點 NPC / 黃問號後跳出選擇面板 → 點黃字卡片，再按對話框')
s = Script([IDLE, SELECT, IDLE, DIALOG, IDLE, IDLE, IDLE, IDLE, IDLE])
rc = run2(['--no-track', '--stop-after-dialog', '--max-seconds', '60'], s)
card = [c for c in s.clicks if c[1].startswith('click 117')]
ok &= check('點了黃字卡片，之後按對話左鈕，exit 0', rc == 0 and len(card) == 1 and bool(has(s, 'click 948 461')) and s.clicks.index(card[0]) < s.clicks.index(has(s, 'click 948 461')[0]), f'rc={rc} {s.clicks}')
print('(r3) --fight：點 NPC 後跳出選擇面板（不是 22「沒點到 NPC」）；點了之後 NPC_WAIT 重新計時')
s = Script([IDLE] * 10 + [SELECT] + [IDLE] * 8 + [DIALOG] + [IDLE] * 20)
rc = run2(['--fight', '--npc', '53,17', '--at', '50,17', '--max-seconds', '120'], s)
ok &= check('有點卡片、有按對話左鈕、退出碼不是 22（沒面板處理的話第 12 秒就會 22）', bool(card_ := [c for c in s.clicks if c[1].startswith('click 117')]) and bool(has(s, 'click 948 461')) and rc != quest.EXIT_NO_NPC, f'rc={rc} {len(s.clicks)}')
print('(r4) 找不到黃字 → 不點任何卡片，當不認得，3 次 + 5 秒後退出碼 2（交給使用者）')
quest.ps_json = lambda script, *args: {'ok': True, 'blobs': []}
s = Script([SELECT])
rc = run2(['--no-track', '--max-seconds', '60'], s)
ok &= check('exit 2、沒點任何東西', rc == 2 and not s.clicks, f'rc={rc} {s.clicks}')
quest.ps_json = lambda script, *args: {'ok': True, 'blobs': SAMPLE_BLOBS}
print('(r5) 點了面板還在（連續 > SELECT_MAX_TRIES 輪）→ 不再一直點，改走不認得（退出碼 2）')
s = Script([SELECT])
rc = run2(['--no-track', '--max-seconds', '60'], s)
ok &= check(f'最多點 {quest.SELECT_MAX_TRIES} 次，exit 2', rc == 2 and len([c for c in s.clicks if c[1].startswith('click 117')]) == quest.SELECT_MAX_TRIES, f'rc={rc} n={len(s.clicks)}')

print('(s) 底部「關閉」列 + 5 頭像：刷新前先點左側關閉 510,745')
ROW_BTN = {(x, y): (r, g, b) for x, y, r, g, b in quest.SIG_CLOSE_ROW}


class RowGame:
    """假遊戲：底部關閉列可見 / 不可見；點關閉 510,745 隱藏（eat = 前幾下被吃掉）"""

    def __init__(self, visible=True, eat=0, stuck=False):
        self.visible, self.eat, self.stuck, self.clicks = visible, eat, stuck, []

    def gui(self, *args, note=''):
        if args[0] == 'seq':
            self.clicks.append(args[1])
            if args[1].startswith('click 510 745'):
                if self.eat > 0:
                    self.eat -= 1
                elif not self.stuck:
                    self.visible = False
            return ''
        if args[0] == 'pixel':
            out = []
            for p in args[1].split():
                xy = tuple(int(v) for v in p.split(','))
                if xy in ROW_BTN:
                    out.append(ROW_BTN[xy] if self.visible else (30, 120, 60))
                elif xy in quest.CLOSE_ROW_DARK:
                    out.append((50, 46, 37) if self.visible else (200, 200, 200))
                else:
                    out.append((0, 0, 0))
            return ' '.join('%d,%d,%d' % c for c in out)
        return ''


for nm, g, want_close, want_switch in [('有列 → 點關閉後才按切換', RowGame(True), 1, True), ('第一下被吃掉 → 點第 2 下', RowGame(True, eat=1), 2, True),
                                       ('沒有列 → 不點關閉直接切換', RowGame(False), 0, True), ('關不掉 → 不點切換（會點到頭像）', RowGame(True, stuck=True), quest.REFRESH_GAP and 2, False)]:
    quest.gui = g.gui
    r = quest.refresh_characters(True)
    cl = [i for i, c in enumerate(g.clicks) if c.startswith('click 510 745')]
    sw = [i for i, c in enumerate(g.clicks) if c.startswith('click 850 765')]
    ok &= check(nm, len(cl) == want_close and bool(sw) == want_switch and r == want_switch and (not sw or not cl or cl[-1] < sw[0]), f'{g.clicks}')
g = RowGame(False)
quest.gui = g.gui
quest.refresh_characters(False)
ok &= check('快速戰鬥（主畫面）刷新用 763,760', any(c.startswith('click 763 760') for c in g.clicks) and not any(c.startswith('click 850 765') for c in g.clicks))
quest.gui = RowGame(True).gui
ok &= check('close_row_visible：有列 True / 讀不到 None', quest.close_row_visible() is True and (setattr(quest, 'gui', lambda *a, **k: 'x') or quest.close_row_visible() is None))

print('(t) 刷新角色規則（should_refresh 純函式 + 整合）')
A = argparse.Namespace


def sr(a, boss, full=True, auto_off=False, since=99):
    return quest.should_refresh(a, boss, full, auto_off, since)


ok &= check('組隊預設：每場（路上遇敵 boss=False 也刷新）', sr(A(solo=False, fight=False, no_refresh=False), False))
ok &= check('--solo：任務戰鬥（boss）也不會有（solo 不當 boss）；路上小怪不刷新', not sr(A(solo=True, fight=False, no_refresh=False), False))
ok &= check('--fight：路上小怪不刷新、任務 / BOSS 戰刷新', not sr(A(solo=False, fight=True, no_refresh=False), False) and sr(A(solo=False, fight=True, no_refresh=False), True))
ok &= check('--no-refresh 全部不刷新', not sr(A(solo=False, fight=False, no_refresh=True), False) and not sr(A(solo=False, fight=True, no_refresh=True), True))
ok &= check('完整戰鬥自動戰鬥還關著 → 先不刷新；快速戰鬥沒有自動戰鬥鈕 → 照刷', not sr(A(solo=False, fight=False, no_refresh=False), False, True, True) and sr(A(solo=False, fight=False, no_refresh=False), False, False, False))
ok &= check('同一場未滿 REFRESH_GAP 秒不重刷', not sr(A(solo=False, fight=False, no_refresh=False), False, since=3.0))
QUICK = dict(IDLE, state='battle', full=False)
FULL_ON = {'state': 'battle', 'gold': 0, 'full': True, 'cmd': False, 'auto_off': False}
quest.gui = lambda *a, **k: ''
print('(t2) 預設模式整合：完整戰鬥（自動戰鬥先開、再刷新）/ 快速戰鬥 / 兩場各刷新一次')
s = Script([IDLE, FULL_CMD_OFF, FULL_CMD_OFF, FULL_ON, FULL_ON, IDLE, IDLE, QUICK, QUICK, IDLE])
rc = run2(['--no-track', '--max-seconds', '12'], s)
seq = [c[1].split(';')[0] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 850 765', 'click 763 760'))]
ok &= check('完整戰鬥：先按自動戰鬥、自動開了才刷新（850,765）一次；第二場快速戰鬥刷新（763,760）一次', seq == ['click 1380 600', 'click 850 765', 'click 763 760'], str(seq))
s = Script([IDLE, FULL_ON, IDLE, IDLE, IDLE])
rc = run2(['--no-track', '--no-refresh', '--max-seconds', '4'], s)
ok &= check('--no-refresh 預設模式不刷新', not has(s, 'click 850 765'))
print('(t3) --solo / --fight 快速戰鬥（只看到 VS 牌）：--solo 只能等；--fight 任務戰鬥刷新、路上小怪不刷新')
s = Script([IDLE, QUICK, QUICK, IDLE, IDLE, IDLE, IDLE])
rc = run2(['--solo', '--no-track', '--max-seconds', '6'], s)
ok &= check('--solo 快速戰鬥：不刷新也不逃（沒有點擊）', not s.clicks, str(s.clicks))
s = Script([IDLE, QUICK, QUICK, IDLE, IDLE, IDLE, IDLE])
rc = run2(['--fight', '--no-click', '--max-seconds', '6'], s)
ok &= check('--fight --no-click（任務時間窗內）快速戰鬥 → 刷新 763,760 一次', len(has(s, 'click 763 760')) == 1, str(s.clicks))
s = Script([IDLE] * 20 + [QUICK, QUICK, IDLE, IDLE, IDLE])
rc = run2(['--fight', '--no-click', '--max-seconds', '25'], s)
ok &= check('--fight --no-click 20 秒後的路上小怪（快速戰鬥）→ 不刷新', not has(s, 'click 763 760') and not has(s, 'click 850 765'), str(s.clicks))

print('全部通過' if ok else '有失敗')
sys.exit(0 if ok else 1)
