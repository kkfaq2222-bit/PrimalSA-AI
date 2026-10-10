#!/usr/bin/env python3
"""screen_sigs 測試（不碰遊戲）：
1. fixture 等價：fixtures/screen_px.json 是重構前（quest.read_screen 舊邏輯）對已存截圖凍結的像素與分類，classify 必須 0 差異。
   （樣本是 1440×830 縮圖，只證明重構前後等價，不證明實機容差；實機容差靠 2 的邊界測試 + --dump-px）
2. 邊界：每組特徵在 tol 命中、tol+1 不命中（合成像素）。
3. netwatch / heal 的 waitpix 字串與重構前逐字相同；screen_sigs 不 import winenv。
用法：uv run --no-project python tools/gui/test_screen_sigs.py"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import screen_sigs as S  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails += 1


# ---- 1. fixture 等價 ----
fx = json.loads((HERE / 'fixtures' / 'screen_px.json').read_text(encoding='utf-8'))
pts = [tuple(p) for p in fx['points']]
check('fixture 取樣點順序 == screen_sigs.points()', pts == S.points())
diff = []
for smp in fx['samples']:
    h = smp['px']
    px = {pt: (int(h[i * 6:i * 6 + 2], 16), int(h[i * 6 + 2:i * 6 + 4], 16), int(h[i * 6 + 4:i * 6 + 6], 16)) for i, pt in enumerate(pts)}
    got = S.classify(px)
    want = {k: smp[k] for k in ('state', 'gold', 'full', 'cmd', 'auto_off')}
    if got != want:
        diff.append((smp['name'], want, got))
check(f'fixture {len(fx["samples"])} 筆新舊判斷 0 差異', not diff, str(diff[:3]))
states = {}
for smp in fx['samples']:
    states[smp['state']] = states.get(smp['state'], 0) + 1
check('fixture 涵蓋 dialog/reward/battle/panel/select/walking/idle/unknown', set(states) >= {'dialog', 'reward', 'battle', 'panel', 'select', 'walking', 'idle', 'unknown'}, str(states))


# ---- 2. 邊界 ----
def shifted(c, d):
    """每個通道往遠離 0 / 255 較遠的一側偏 d（保證在 0～255 內且差值剛好 d）"""
    return tuple(v + d if v + d <= 255 else v - d for v in c)


def px_of(sig, delta=0, who=None):
    """sig 全部點 = 參考色；第 who 個點偏 delta"""
    px = {}
    for i, (x, y, r, g, b, tol) in enumerate(sig):
        px[(x, y)] = shifted((r, g, b), delta) if i == who else (r, g, b)
    return px


GROUPS = {'DIALOG': S.SIG_DIALOG, 'REWARD': S.SIG_REWARD, 'PANEL': S.SIG_PANEL, 'SELECT': S.SIG_SELECT, 'HUD': S.SIG_HUD,
          'BATTLE': S.SIG_BATTLE, 'CMD': S.SIG_CMD, 'AUTO_OFF': S.SIG_AUTO_OFF, 'CLOSE_ROW': S.SIG_CLOSE_ROW,
          'NET_DIALOG': S.NET_DIALOG, 'NET_LOGIN': S.NET_LOGIN, 'NET_CHARSEL': S.NET_CHARSEL, 'ENC_ON': S.ENC_ON}
EXPECT_TOL = {'DIALOG': 40, 'REWARD': 40, 'PANEL': 40, 'SELECT': 40, 'HUD': 40, 'BATTLE': 25, 'CMD': 25, 'AUTO_OFF': 20,
              'CLOSE_ROW': 22, 'NET_DIALOG': 25, 'NET_LOGIN': 25, 'NET_CHARSEL': 25, 'ENC_ON': 50}
for name, sig in GROUPS.items():
    tol = EXPECT_TOL[name]
    check(f'{name} 容差原值 {tol}', all(t[5] == tol for t in sig))
    ok_all = S.match(px_of(sig), sig) and S.match(px_of(sig, tol, who=-1), sig)
    check(f'{name} tol 命中（全部點各偏 tol）', ok_all and all(S.match(px_of(sig, tol, who=i), sig) for i in range(len(sig))))
    check(f'{name} tol+1 不命中（任一點偏 tol+1）', all(not S.match(px_of(sig, tol + 1, who=i), sig) for i in range(len(sig))))
# VS 牌（40）
vs = {S.VS_PROBE: S.VS_COLOR}
check('VS 牌 tol 命中', S.close(shifted(S.VS_COLOR, 40), S.VS_COLOR, S.VS_TOL))
check('VS 牌 tol+1 不命中', not S.close(shifted(S.VS_COLOR, 41), S.VS_COLOR, S.VS_TOL))


# classify 層級：空白畫面 + 疊上單一特徵
def blank():
    return {pt: (0, 0, 0) for pt in S.points()}


def with_sig(*sigs, delta=0, who=None):
    px = blank()
    for sig in sigs:
        px.update(px_of(sig, delta, who))
    return px


check('classify：空白 = unknown', S.classify(blank())['state'] == 'unknown')
for st, sig in (('dialog', S.SIG_DIALOG), ('reward', S.SIG_REWARD), ('panel', S.SIG_PANEL), ('select', S.SIG_SELECT), ('idle', S.SIG_HUD)):
    check(f'classify：{st} tol 命中', S.classify(with_sig(sig, delta=40, who=0))['state'] == st)
    check(f'classify：{st} tol+1 不命中', S.classify(with_sig(sig, delta=41, who=0))['state'] == 'unknown')
b = S.classify(with_sig(S.SIG_BATTLE, delta=25, who=0))
check('classify：battle(full) tol 25', b['state'] == 'battle' and b['full'] and not b['cmd'] and not b['auto_off'])
check('classify：battle tol+1 不命中', S.classify(with_sig(S.SIG_BATTLE, delta=26, who=0))['state'] == 'unknown')
check('classify：cmd 全中', S.classify(with_sig(S.SIG_BATTLE, S.SIG_CMD))['cmd'] is True)
p = with_sig(S.SIG_BATTLE); p.update(px_of(S.SIG_CMD, 25, 0))
check('classify：cmd 偏 25 命中', S.classify(p)['cmd'] is True)
p = with_sig(S.SIG_BATTLE); p.update(px_of(S.SIG_CMD, 26, 0))
check('classify：cmd 偏 26 不命中', S.classify(p)['cmd'] is False)
p = with_sig(S.SIG_BATTLE); p.update(px_of(S.SIG_AUTO_OFF, 20, 0))
check('classify：auto_off 偏 20 命中', S.classify(p)['auto_off'] is True)
p = with_sig(S.SIG_BATTLE); p.update(px_of(S.SIG_AUTO_OFF, 21, 0))
check('classify：auto_off 偏 21 不命中', S.classify(p)['auto_off'] is False)
p = blank(); p[S.VS_PROBE] = shifted(S.VS_COLOR, 40)
check('classify：VS 牌偏 40 = battle（非 full）', S.classify(p)['state'] == 'battle' and not S.classify(p)['full'])
p[S.VS_PROBE] = shifted(S.VS_COLOR, 41)
check('classify：VS 牌偏 41 不命中', S.classify(p)['state'] == 'unknown')
p = blank()
for pt in S.AW_POINTS[:S.AW_MIN]:
    p[pt] = (230, 180, 10)
check('classify：金黃點 = AW_MIN → walking', S.classify(p)['state'] == 'walking')
p[S.AW_POINTS[0]] = (0, 0, 0)
check('classify：金黃點 AW_MIN-1 → unknown', S.classify(p)['state'] == 'unknown')
# 優先序：戰鬥 + HUD 紅字 → battle；選擇面板 + HUD → select
check('classify：戰鬥 + HUD 紅字 = battle', S.classify(with_sig(S.SIG_BATTLE, S.SIG_HUD))['state'] == 'battle')
check('classify：選擇面板 + HUD 紅字 = select', S.classify(with_sig(S.SIG_SELECT, S.SIG_HUD))['state'] == 'select')

# ---- 3. 字串逐字相同、不 import winenv ----
check('SIG_DIALOG(net) 字串', S.sig_str(S.NET_DIALOG) == '520,570,245,217,179/880,570,245,217,179/600,300,243,213,175/600,557,243,213,175/830,557,243,213,175/640,557,61,106,167')
check('SIG_LOGIN 字串', S.sig_str(S.NET_LOGIN) == '500,570,179,127,63/760,565,93,137,187/440,520,243,217,179')
check('SIG_CHARSEL 字串', S.sig_str(S.NET_CHARSEL) == '640,640,197,134,70/500,250,241,213,179/1186,190,196,72,48/350,330,169,117,70')
check('ENC_ON / OFF 字串', S.sig_str(S.ENC_ON) == '1380,630,129,6,0/1360,632,179,12,0' and S.sig_str(S.ENC_ON, neg=True) == '1380,630,129,6,0!/1360,632,179,12,0!')
check('quest 面板 waitpix 字串', S.sig_str(S.SIG_PANEL) == '1064,208,197,69,41/880,590,55,67,13')
import ast  # noqa: E402
mods = set()
for n in ast.walk(ast.parse((HERE / 'screen_sigs.py').read_text(encoding='utf-8'))):
    if isinstance(n, ast.Import):
        mods |= {a.name for a in n.names}
    elif isinstance(n, ast.ImportFrom):
        mods.add(n.module)
check('screen_sigs 不 import winenv', 'winenv' not in mods, str(mods))
check('annotate 殼：回空清單', S.annotate({}, {}) == [])
print('\n全部通過' if not fails else f'\n{fails} 項失敗')
sys.exit(1 if fails else 0)
