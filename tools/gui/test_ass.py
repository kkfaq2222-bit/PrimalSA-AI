#!/usr/bin/env python3
"""ass.py 模擬測試（不碰遊戲）：假 gui（pixel / seq）模擬外掛面板，驗證讀 / 設 / 確認失敗 / 面板沒開。
用法：uv run --no-project python tools/gui/test_ass.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ass  # noqa: E402


class Game:
    def __init__(self, panel=False, hud=True, role='DKB0', checks=None, stuck=(), hud_after=None):
        self.panel, self.hud, self.role = panel, hud, role
        self.checks = {r: dict(checks or {}) for r in ass.ROLES}
        for r in ass.ROLES:
            for i in ass.ITEMS:
                self.checks[r].setdefault(i, False)
        self.stuck = set(stuck)         # 點了不會變的項目（模擬禁止快速戰鬥）
        self.clicks, self.t = [], 0.0
        self.ground_clicks = 0          # 面板沒開時點到面板內座標 = 穿透到地面
        self.pet = {'first_on': False, 'first': '攻擊', 'normal': '攻擊'}
        self.dd = None                  # 目前展開的下拉 'first' / 'normal'
        self.scrolled = False           # 右半面板被捲離頂端
        self.dd_stuck = False           # 選了選項沒生效

    def sleep(self, d):
        self.t += d

    def time(self):
        return self.t

    def color(self, x, y):
        if (x, y) == (ass.X_SIG[0], ass.X_SIG[1]):
            return (195, 127, 8) if self.panel else (159, 109, 51)
        if (x, y) == ass.HUD_PROBE[:2]:
            return (254, 0, 0) if (self.hud and not self.panel) else (50, 50, 50)
        for r, xy in ass.ROLES.items():
            if (x, y) == xy:
                if not self.panel:
                    return (0, 0, 0)    # 黑洞窟地圖（實機就是這樣）
                return (0, 0, 0) if r == self.role else (197, 227, 255)
        if (x, y) == ass.PET_FIRST_CHK:
            return (30, 30, 30) if self.pet['first_on'] and self.panel else (255, 255, 255)
        for i, xy in ass.ITEMS.items():
            if (x, y) == xy:
                if not self.panel:
                    return (90, 80, 60)
                return (30, 30, 30) if self.checks[self.role][i] else (255, 255, 255)
        return (1, 2, 3)

    def gui(self, *args, note=''):
        if args[0] == 'pixel':
            return ' '.join('%d,%d,%d' % self.color(*map(int, p.split(','))) for p in args[1].split())
        if args[0] == 'seq':
            for m in re.finditer(r'click (\d+) (\d+)', args[1]):
                self.click(int(m[1]), int(m[2]))
        return ''

    def click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == ass.ASS_BTN:
            if self.hud:
                self.panel = True
            return
        if (x, y) == ass.CLOSE_BTN:
            self.panel = False
            return
        if not self.panel:
            self.ground_clicks += (x, y) in (list(ass.PET_DD.values()) + [ass.PET_FIRST_CHK])
        elif self.dd:
            idx = round((y - ass.PET_DD[self.dd][1]) / ass.PET_OPT_DY) - 1
            if x == ass.PET_OPT_X and 0 <= idx < len(ass.PET_OPTS) and not self.dd_stuck:
                self.pet[self.dd] = ass.PET_OPTS[idx]
            self.dd = None
            return
        elif (x, y) in ass.PET_DD.values():
            self.dd = [k for k, v in ass.PET_DD.items() if v == (x, y)][0]
            return
        elif (x, y) == ass.PET_FIRST_CHK:
            self.pet['first_on'] = not self.pet['first_on']
            return
        hit = [r for r, xy in ass.ROLES.items() if xy == (x, y)]
        hit_i = [i for i, xy in ass.ITEMS.items() if xy == (x, y)]
        if not self.panel:
            self.ground_clicks += hit != [] or hit_i != []
            return
        if hit:
            self.role = hit[0]
        if hit_i and hit_i[0] not in self.stuck:
            c = self.checks[self.role]
            c[hit_i[0]] = not c[hit_i[0]]


def setup(g):
    ass.gui, ass.sleep, ass.clock = g.gui, g.sleep, g.time
    ass._ocr = g.ocr


def _ocr_impl(self, box, *opts):
    if box == ass.PET_TITLE_BOX:
        return '' if self.scrolled else '戰寵動作一'
    for k, b in ass.PET_FIELD.items():
        if box == b:
            return self.pet[k]
    return ''


Game.ocr = _ocr_impl


ok = True


def check(name, cond, extra=''):
    global ok
    ok &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name + (' ' + extra if extra else ''))


print('(1) get：面板沒開 → 開 → 讀 → 關')
g = Game(checks={'原地遇敵': True, '自動戰鬥': True})
setup(g)
rc, st, _ = ass.get_states('DKB0')
check('rc 0 且五項正確', rc == 0 and st == {'原地遇敵': True, '自動逃跑': False, '快速戰鬥': False, '自動戰鬥': True, '夥伴助戰': False}, str(st))
check('面板已關、沒點到地面', not g.panel and g.ground_clicks == 0)
print('(2) get 其他角色：會選角色')
g = Game(role='DKB0', checks={'自動逃跑': True})
setup(g)
rc, st, _ = ass.get_states('DKB03')
check('選了 DKB03 且讀到', rc == 0 and ass.ROLES['DKB03'] in g.clicks and st['自動逃跑'], str(g.clicks))
print('(3) set：只點與目標不同的，再讀確認')
g = Game(checks={'自動戰鬥': True, '快速戰鬥': True})
setup(g)
rc, st, _ = ass.set_states('DKB0', {'快速戰鬥': False, '自動戰鬥': True, '自動逃跑': True})
item_clicks = [c for c in g.clicks if c in ass.ITEMS.values()]
check('rc 0', rc == 0, str(st))
check('只點快速戰鬥與自動逃跑（自動戰鬥已開不點）', sorted(item_clicks) == sorted([ass.ITEMS['快速戰鬥'], ass.ITEMS['自動逃跑']]), str(item_clicks))
check('結果正確、面板已關', st['自動逃跑'] and not st['快速戰鬥'] and st['自動戰鬥'] and not g.panel)
print('(4) set 已是目標：一次都不點')
g = Game(checks={'自動逃跑': True})
setup(g)
rc, st, _ = ass.set_states('DKB0', {'自動逃跑': True})
check('rc 0 且沒點勾選框', rc == 0 and not [c for c in g.clicks if c in ass.ITEMS.values()])
print('(5) 確認失敗（點了沒變）→ 退出碼 4，不補點，面板仍關閉')
g = Game(stuck=['快速戰鬥'])
setup(g)
rc, st, msg = ass.set_states('DKB0', {'快速戰鬥': True})
check('rc 4', rc == ass.EXIT_CONFIRM, msg)
check('只點一次、面板關', g.clicks.count(ass.ITEMS['快速戰鬥']) == 1 and not g.panel)
print('(6) 面板打不開（外掛鈕被擋 / 對話中）→ 退出碼 2，不點任何面板座標')
g = Game(hud=False)
setup(g)
rc, st, msg = ass.get_states('DKB0')
check('rc 2', rc == ass.EXIT_NO_PANEL, msg)
check('沒有任何點擊（不穿透到地面）', g.clicks == [] and g.ground_clicks == 0, str(g.clicks))
check('等待有上限', 38 <= g.t <= 50, f't={g.t:.0f}')
print('(7) 戰鬥擋住一陣子後恢復 → 重試後開成功')
g = Game(hud=False)
setup(g)
orig = g.sleep
def sleep_then_hud(d):
    orig(d)
    if g.t > 9:
        g.hud = True
g.sleep = sleep_then_hud
ass.sleep = sleep_then_hud
rc, st, _ = ass.get_states('DKB0')
check('rc 0', rc == 0, str(st))
print('(8) 點外掛鈕沒反應（面板沒開）→ 重試有上限、不點面板座標')
g = Game(hud=True)
g.click_orig = g.click
g.click = lambda x, y: g.clicks.append((x, y))      # 點了不開
setup(g)
rc, st, msg = ass.get_states('DKB0')
check('rc 2', rc == ass.EXIT_NO_PANEL)
check('外掛鈕最多點 6 次，沒點任何面板座標', set(g.clicks) == {ass.ASS_BTN} and len(g.clicks) <= 6, str(len(g.clicks)))
print('(9) 選角色失敗（點了沒切）→ 退出碼 3，沒動勾選框')
g = Game()
g.click_orig = g.click
def noswitch(x, y):
    if (x, y) in ass.ROLES.values():
        g.clicks.append((x, y))
        return
    g.click_orig(x, y)
g.click = noswitch
setup(g)
rc, st, msg = ass.set_states('DKB02', {'自動逃跑': True})
check('rc 3 且沒點勾選框、面板已關', rc == ass.EXIT_NO_ROLE and not [c for c in g.clicks if c in ass.ITEMS.values()] and not g.panel, msg)
print('(10) CLI 參數')
g = Game(checks={'自動逃跑': True})
setup(g)
ass.layout.current = lambda: '2880x1659'
check('get 英文別名', ass.main(['get', 'dkb0', 'flee', 'auto']) == 0)
check('set 成對錯誤 → 1', ass.main(['set', 'DKB0', '自動逃跑']) == 1)
check('未知角色 → 1', ass.main(['get', 'DKB9']) == 1)
check('set on/off', ass.main(['set', 'DKB0', '自動逃跑', 'off', '自動戰鬥', 'on']) == 0 and g.checks['DKB0']['自動戰鬥'] and not g.checks['DKB0']['自動逃跑'])
print('(11) pet get / set：首次動作 防禦 + 勾選，一般動作不動')
g = Game()
setup(g)
rc, st, _ = ass.get_pet('DKB0')
check('get 現值', rc == 0 and st == {'first_on': False, 'first': '攻擊', 'normal': '攻擊'}, str(st))
rc, st, _ = ass.set_pet('DKB0', {'first': '防禦', 'first_on': True})
check('設成 勾 / 防禦', rc == 0 and g.pet == {'first_on': True, 'first': '防禦', 'normal': '攻擊'} and not g.panel, str(g.pet))
check('防禦點在欄位 +84', (ass.PET_OPT_X, 463 + 84) in g.clicks, str(g.clicks))
n = len(g.clicks)
rc, st, _ = ass.set_pet('DKB0', {'first': '防禦', 'first_on': True})
check('已是目標 → 不點戰寵座標', rc == 0 and not [c for c in g.clicks[n:] if c in ass.PET_DD.values() or c == ass.PET_FIRST_CHK])
rc, st, _ = ass.set_pet('DKB0', {'first': '攻擊', 'first_on': False, 'normal': '忠犬'})
check('改回 不勾 / 攻擊、一般 忠犬', rc == 0 and g.pet == {'first_on': False, 'first': '攻擊', 'normal': '忠犬'}, str(g.pet))
print('(12) pet 選項沒生效 → 退出碼 4、不補點')
g = Game()
g.dd_stuck = True
setup(g)
rc, st, msg = ass.set_pet('DKB0', {'first': '防禦', 'first_on': True})
check('rc 4、只開一次下拉、沒點勾選框、面板關', rc == ass.EXIT_CONFIRM and g.clicks.count(ass.PET_DD['first']) == 1 and ass.PET_FIRST_CHK not in g.clicks and not g.panel, msg)
print('(13) pet 面板被捲動 → 退出碼 7、沒點戰寵座標')
g = Game()
g.scrolled = True
setup(g)
rc, st, msg = ass.set_pet('DKB0', {'first': '防禦'})
check('rc 7', rc == ass.EXIT_NOT_TOP and not [c for c in g.clicks if c in ass.PET_DD.values() or c == ass.PET_FIRST_CHK] and not g.panel, msg)
print('(14) pet 面板打不開 → 退出碼 2；CLI 參數')
g = Game(hud=False)
setup(g)
rc, _, _ = ass.get_pet('DKB0')
check('rc 2 且沒點', rc == 2 and g.clicks == [])
g = Game()
setup(g)
check('CLI pet first 防禦 normal 攻擊', ass.main(['pet', 'dkb0', 'first', '防禦', 'normal', '攻擊']) == 0 and g.pet['first'] == '防禦' and g.pet['first_on'])
check('CLI pet first off', ass.main(['pet', 'DKB0', 'first', 'off']) == 0 and not g.pet['first_on'])
check('CLI pet 參數錯 → 1', ass.main(['pet', 'DKB0', 'first', '亂寫']) == 1 and ass.main(['pet', 'DKB0']) == 1)
print('全部通過' if ok else '有失敗')
sys.exit(0 if ok else 1)
