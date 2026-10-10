#!/usr/bin/env python3
"""quest.py --fight / --solo 的戰鬥分類模擬測試（不碰遊戲）：假時鐘 + 假 read_screen / gui，驗證 BOSS 戰 / 小怪判斷與退出碼。
用法：uv run --no-project python tools/gui/test_quest_fight.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quest  # noqa: E402

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


ASS = {'rc': 0, 'st': {'原地遇敵': False, '自動逃跑': False, '快速戰鬥': False, '自動戰鬥': True, '夥伴助戰': False}, 'calls': 0}


def fake_ass(role):
    ASS['calls'] += 1
    return ASS['rc'], (dict(ASS['st']) if ASS['rc'] == 0 else None), 'fake'


def run(argv, sim):
    quest.time.time, quest.time.sleep = sim.time, sim.sleep
    quest.read_screen, quest.gui, quest.read_pos = sim.screen, sim.gui, lambda: (5510, 50, 17)
    quest.walk.gui = sim.gui
    quest.ass.get_states = fake_ass
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
rc = run(['--fight', '--no-click', '--manual-escape', '--max-seconds', '60'], s)
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
rc = run(['--fight', '--no-click', '--manual-escape', '--max-seconds', '60'], s)
seq = [c[1] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 1283 168'))]
ok &= check('順序：關自動 → 逃跑', seq == ['click 1380 600', 'click 1283 168'], str(seq))
print('(c2) --solo 同樣情境')
s = Sim(battle_at=5.0, auto_on=True)
rc = run(['--solo', '--no-track', '--manual-escape', '--max-seconds', '40'], s)
seq = [c[1] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 1283 168'))]
ok &= check('--solo 順序：關自動 → 逃跑', seq == ['click 1380 600', 'click 1283 168'], str(seq))

print('(c3) --solo 預設：外掛自動逃跑，腳本不按任何戰鬥鈕、戰鬥 12 秒後結束')
ASS['st']['自動逃跑'] = True
s = Sim(battle_at=5.0, auto_on=True, boss_ends=12.0)
ASS['calls'] = 0
rc = run(['--solo', '--no-track', '--max-seconds', '40'], s)
ok &= check('讀過外掛設定', ASS['calls'] == 1)
ok &= check('沒按逃跑 / 自動戰鬥鈕', not has(s, 'click 1283 168') and not has(s, 'click 1380 600'), str(s.clicks))
ok &= check('exit 0（時間到，沒超時）', rc == 0, f'rc={rc}')
print('(c4) --solo 戰鬥 40 秒不結束 → 退出碼 27')
s = Sim(battle_at=5.0, auto_on=True, boss_ends=400.0)
rc = run(['--solo', '--no-track', '--max-seconds', '200'], s)
ok &= check('exit 27，約 35 秒', rc == quest.EXIT_ESCAPE_TIMEOUT and 34 <= s.t - 1000 <= 40, f'rc={rc} t={s.t - 1000:.0f}')
ok &= check('沒按任何鈕', not has(s, 'click 1283 168') and not has(s, 'click 1380 600'))
print('(c5) --solo 外掛設定不符 / 讀不到 → 29，沒動作')
for desc, patch in (('自動逃跑關', {'自動逃跑': False}), ('自動戰鬥關', {'自動戰鬥': False})):
    s = Sim(battle_at=5.0)
    ASS['st'].update(patch)
    rc = run(['--solo', '--no-track', '--max-seconds', '40'], s)
    ok &= check(f'{desc} → 29 且沒點任何東西', rc == quest.EXIT_ASS_SETUP and not s.clicks, f'rc={rc}')
    ASS['st'].update({'自動逃跑': True, '自動戰鬥': True})
ASS['rc'] = 2
s = Sim(battle_at=5.0)
rc = run(['--solo', '--no-track', '--max-seconds', '40'], s)
ok &= check('讀不到 → 29', rc == quest.EXIT_ASS_SETUP and not s.clicks, f'rc={rc}')
ASS['rc'] = 0
s = Sim(battle_at=5.0, boss_ends=5.0)
ASS['calls'] = 0
rc = run(['--solo', '--no-track', '--skip-ass-check', '--max-seconds', '20'], s)
ok &= check('--skip-ass-check 不讀外掛', ASS['calls'] == 0 and rc == 0, f'rc={rc}')
print('(c6) --fight 自動逃跑開著 → 28，不點 NPC')
s = Sim()
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '60'], s)
ok &= check('exit 28、沒任何點擊', rc == quest.EXIT_ESCAPE_ON and not s.clicks, f'rc={rc} clicks={s.clicks}')
print('(c7) --fight（--no-click，自動逃跑關）：小怪（20 秒後才進戰鬥）用自動戰鬥打完、不逃跑')
ASS['st']['自動逃跑'] = False
s = Sim(battle_at=20.0, auto_on=False, boss_ends=10.0)
rc = run(['--fight', '--no-click', '--max-seconds', '60'], s)
ok &= check('小怪：按自動戰鬥、沒按逃跑', len(has(s, 'click 1380 600')) == 1 and not has(s, 'click 1283 168'), str(s.clicks))
print('(c8) --fight --no-click --manual-escape：舊行為（小怪先關自動再逃）')
ASS['st']['自動逃跑'] = True
s = Sim(battle_at=20.0, auto_on=True)
ASS['calls'] = 0
rc = run(['--fight', '--no-click', '--manual-escape', '--max-seconds', '60'], s)
seq = [c[1] for c in s.clicks if c[1].startswith(('click 1380 600', 'click 1283 168'))]
ok &= check('不讀外掛、關自動 → 逃跑', ASS['calls'] == 0 and seq == ['click 1380 600', 'click 1283 168'], f'{seq} calls={ASS["calls"]}')
ASS['st']['自動逃跑'] = True

print('(d) 點 NPC 後沒反應')
ASS['st']['自動逃跑'] = False
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

print('全部通過' if ok else '有失敗')
sys.exit(0 if ok else 1)
