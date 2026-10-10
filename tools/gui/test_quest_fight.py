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


def run(argv, sim):
    quest.time.time, quest.time.sleep = sim.time, sim.sleep
    quest.read_screen, quest.gui, quest.read_pos = sim.screen, sim.gui, lambda: (5510, 50, 17)
    quest.walk.gui = sim.gui
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

print('(d) 點 NPC 後沒反應')
s = Sim()
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
ok &= check('exit 22', rc == quest.EXIT_NO_NPC, f'rc={rc} t={s.t - 1000:.0f}s')

print('(e) 對話後一直沒開打')
s = Sim(dialog_at=2.0)
rc = run(['--fight', '--npc', '53,17', '--max-seconds', '120'], s)
ok &= check('exit 23', rc == quest.EXIT_NO_BATTLE, f'rc={rc}')

print('全部通過' if ok else '有失敗')
sys.exit(0 if ok else 1)
