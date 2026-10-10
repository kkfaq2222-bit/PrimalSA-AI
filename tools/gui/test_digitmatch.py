#!/usr/bin/env python3
"""digitmatch.py 離線測試（不碰遊戲）：用 fixtures/digitmatch_cap.json（2880x1659 實機裁出的二值化欄位，數值已與 stat.ps1 / 肉眼核對）
與 fixtures/digitmatch_tpl.json（樣板）。執行：uv run --no-project python tools/gui/test_digitmatch.py"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digitmatch as d  # noqa: E402

FX = Path(__file__).resolve().parent / 'fixtures'
fails = 0


def check(name, ok, info=''):
    global fails
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok or not info else f'  [{info}]'))
    fails += 0 if ok else 1


raw = json.loads((FX / 'digitmatch_cap.json').read_text(encoding='utf-8'))
tpl = json.loads((FX / 'digitmatch_tpl.json').read_text(encoding='utf-8'))
cap = {'ok': True, 'layout': raw['layout'], 'hpPct': raw['hpPct'], 'mpPct': raw['mpPct'], 'fields': {k: v.split(',') for k, v in raw['fields'].items()}}
exp = raw['expect']

r = d.read_fields(cap, tpl)
for k, v in exp.items():
    check(f'讀值 {k} = {v}', r[k] == v)
check('沒有 unsure', r['unsure'] == [])
check('地圖名由 pos 查表', r['map'] == '庫塔伊洞窟地下二樓')
check('血條掃描 -1 → None 並列入 unsure', d.read_fields({**cap, 'hpPct': -1}, tpl)['unsure'] == ['hpPct'])

# 雜訊：座標欄兩端的場景雜訊、數字上方的血條殘邊都要被濾掉（fixture 的 pos / php 本來就帶）
check('pos 欄切出 11 字（含 : ,）', len(d.segment(cap['fields']['pos'], True)) == 11)
check('php 欄切出 3 字（血條殘邊不橋接）', len(d.segment(cap['fields']['php'])) == len(str(exp['petHp'])))
check('lv 欄切出 6 字（轉 / 級 多元件合併）', len(d.segment(cap['fields']['lv'])) == 6)

# 保守：缺字元樣板 → None
t2 = copy.deepcopy(tpl)
t2.pop('3', None)
r2 = d.read_fields(cap, t2)
check('缺樣板「3」→ 含 3 的欄位為 None', all(r2[k] is None for k in ('level', 'petLevel')) or r2['hp'] is None)
check('unsure 列出 None 欄位', set(r2['unsure']) == {k for k in exp if k != 'map' and r2[k] is None} and r2['unsure'])

# 保守：把 hp 欄的一個字糊掉 → None，而不是亂猜
c3 = copy.deepcopy(cap)
rows = c3['fields']['hp']
x0 = d.segment(rows)[0][0]
c3['fields']['hp'] = [row[:x0] + '0' * 6 + row[x0 + 6:] for row in rows]
check('字被破壞 → 該欄 None', d.read_fields(c3, tpl)['hp'] is None)
check('其他欄不受影響', d.read_fields(c3, tpl)['mp'] == exp['mp'])

# 空欄位 / 沒有樣板
check('沒樣板全 None', d.read_fields(cap, {})['unsure'] != [])
check('空欄位', d.segment(['0' * 20] * 10) == [] and d.parse_num('') is None)
check('parse_level 缺轉數當 0 轉', d.parse_level('轉42級') == '0轉42級' and d.parse_level('3轉105級') == '3轉105級')
check('parse_pos', d.parse_pos('60050:24,24') == '60050:24,24' and d.parse_pos('abc') is None)

# ---- learn_from：自動補樣板的採用 / 拒絕條件 ----
STAT = {k: exp[k] for k in ('level', 'hp', 'mp', 'petLevel', 'petHp', 'pos')}
cap_b = copy.deepcopy(cap)
n_all = sum(len(v) for v in tpl.values())
# 1. 已有的樣板 + 一致 → 重複不加
t = copy.deepcopy(tpl)
n1 = d.learn_from(cap, cap_b, STAT, t, d.read_fields(cap, t))
check('dm 與 stat 一致：只補相似度偏低的字形（<= 3 個）', n1 <= 3, str(n1))
check('同一張圖再學一次 → 新增 0（冪等）', d.learn_from(cap, cap_b, STAT, t, d.read_fields(cap, t)) == 0)
# 2. 空樣板 + stat 有值（dm 全 None）→ 學到全部字元
t = {}
n = d.learn_from(cap, cap_b, STAT, t, d.read_fields(cap, t))
check('空樣板：stat 有值、兩張圖相同 → 學到字元', n > 20 and set('0123456789:,轉級') <= set(t) | set('0123456789:,轉級') and '3' in t, f'n={n} {sorted(t)}')
r_after = d.read_fields(cap, t)
check('學完後 digitmatch 讀得出來', all(r_after[k] == exp[k] for k in STAT), str(r_after['raw']))
# 3. 前後畫面不同 → 該欄不學
cap_c = copy.deepcopy(cap)
cap_c['fields']['hp'] = ['0' * len(cap['fields']['hp'][0])] * len(cap['fields']['hp'])
t = {}
d.learn_from(cap, cap_c, STAT, t, None)
check('前後截圖不同的欄位不學（hp 欄的字只出現在其他欄時仍可學；這裡只檢查沒有以 hp 標籤誤學）', all(len(v) <= 6 for v in t.values()))
t2 = {}
d.learn_from(cap, cap_c, {'hp': 363}, t2, None)
check('只給 hp 標籤、hp 欄前後不同 → 0 個樣板', t2 == {})
# 4. 標籤字數不符（OCR 漏字）→ 不學
t = {}
check('標籤少一位（OCR 讀成 36）→ 不學', d.learn_from(cap, cap_b, {'hp': 36}, t, None) == 0 and t == {})
# 5. dm 有值但與 stat 不同 → 不學
t = copy.deepcopy(tpl)
dm = d.read_fields(cap, t)
check('dm 與 stat 不一致 → 該欄不學', d.learn_from(cap, cap_b, {'petHp': 999}, {}, dm) == 0)
# 6. 標籤衝突：既有樣板把這個字認成別的 → 不學
t = copy.deepcopy(tpl)
wrong = d.learn_from(cap, cap_b, {'hp': 100 + (exp['hp'] % 10)}, t, None)     # 字數相同但數字全錯
check('標籤與既有樣板衝突 → 不學（不污染）', wrong == 0 and sum(len(v) for v in t.values()) == n_all)
# 7. 變體上限：'3' 已有 MAX_VARIANTS 個不同變體 → 不再新增
g3 = d.segment(cap['fields']['hp'])[0][2]
t = {'3': [[row + '0' * (i + 1) for row in ['1' * 3] * 4] for i in range(d.MAX_VARIANTS)]}
d.learn_from(cap, cap_b, {'level': exp['level']}, t, None)
check('每字元變體數不超過 MAX_VARIANTS', all(len(v) <= d.MAX_VARIANTS for v in t.values()), str({k: len(v) for k, v in t.items()}))

# ---- walk.pos()：現場 digitmatch 優先，None 才退回 stat ----
import tempfile  # noqa: E402
import walk  # noqa: E402
real_tpl_dir, real_cap, real_stat = d.TPL_DIR, d.capture, walk.stat
tmpd = Path(tempfile.mkdtemp(prefix='dmwalk-'))
d.TPL_DIR = tmpd
d.tpl_path(cap['layout']).write_text(json.dumps(tpl, ensure_ascii=False), encoding='utf-8')
calls = {'stat': 0}
walk.stat = lambda: (calls.__setitem__('stat', calls['stat'] + 1), {'ok': True, 'pos': '1000:5,6'})[1]
d.capture = lambda image=None: cap
check('live_pos 讀出座標', d.live_pos() == exp['pos'])
check('walk.pos 用 digitmatch、不呼叫 stat', walk.pos() == (60050, 24, 24) and calls['stat'] == 0)
d.tpl_path(cap['layout']).unlink()
check('沒有樣板 → live_pos None → walk.pos 退回 stat', d.live_pos() is None and walk.pos() == (1000, 5, 6) and calls['stat'] == 1)
d.tpl_path(cap['layout']).write_text(json.dumps(tpl, ensure_ascii=False), encoding='utf-8')
d.capture = lambda image=None: {'ok': False, 'error': 'x'}
check('截圖失敗 → 退回 stat', walk.pos() == (1000, 5, 6) and calls['stat'] == 2)
def _raise(image=None):
    import subprocess
    raise subprocess.TimeoutExpired('ps', 1)
d.capture = _raise
check('截圖逾時 → 不丟例外、退回 stat', walk.pos() == (1000, 5, 6) and calls['stat'] == 3)
c_bad = copy.deepcopy(cap)
c_bad['fields']['pos'] = ['0' * len(r) for r in cap['fields']['pos']]
c_bad['fields'].pop('pos2', None)
d.capture = lambda image=None: c_bad
check('座標欄空 / 認不出 → 退回 stat', walk.pos() == (1000, 5, 6) and calls['stat'] == 4)
walk.stat = lambda: {'ok': True, 'pos': ''}
check('兩邊都讀不到 → None', walk.pos() is None)
d.TPL_DIR, d.capture, walk.stat = real_tpl_dir, real_cap, real_stat
import shutil; shutil.rmtree(tmpd, ignore_errors=True)
print(f'failed={fails}')
sys.exit(1 if fails else 0)
