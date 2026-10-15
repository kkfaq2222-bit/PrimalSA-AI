#!/usr/bin/env python3
"""OCR 改善階段 1b / 1c / 1d + 追蹤欄補讀的離線測試（不碰遊戲、不跑 OCR）：
ocrfix.fix、dailyquest1920 的淺色字讀法 / 數字框（digitmatch 先、OCR 備援與補學）、digitmatch.learn_digits / read_digits、
questflow1920 追蹤欄 match_track / match_track_light / locate_track / top_is_other、bag1920.classify、uikit.snap_pet。
OCR 行的內容取自 tools/.cache 截圖實際讀到的結果（ocrbench --track -v）。
用法：uv run --no-project python tools/gui/test_ocr_stage1.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bag1920  # noqa: E402
import dailyquest1920 as dq  # noqa: E402
import digitmatch  # noqa: E402
import ocrbench  # noqa: E402
import ocrfix  # noqa: E402
import questflow1920 as qf  # noqa: E402
import uikit  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


# ---- 1c：ocrfix ----
check('雙字：蛋氵十 → 蛋汁', ocrfix.fix('蛋氵十'), '蛋汁')
check('雙字 + 單字：有氵睪的地瓜 → 有澤的地瓜', ocrfix.fix('有氵睪的地瓜'), '有澤的地瓜')
check('雙字：氵罙氵每魚 → 深海魚', ocrfix.fix('氵罙氵每魚'), '深海魚')
check('單字：盬 → 鹽', ocrfix.fix('盬'), '鹽')
check('None → 空字串', ocrfix.fix(None), '')
check('沒有要修的字不變', ocrfix.fix('普通的米'), '普通的米')
check('dailyquest 舊名指向同一張表', (dq.OCR_FIX is ocrfix.CHAR_FIX, dq.STR_FIX is ocrfix.PAIR_FIX), (True, True))
check('dailyquest.fix_text = ocrfix.fix', dq.fix_text('蛋氵十'), '蛋汁')
check('match_known 套全表（蛋氵十 → 蛋汁）', dq.match_known('蛋氵十', ['蛋汁', '普通的米']), '蛋汁')
check('title_matches 套全表', dq.title_matches('蛋汁', '蛋氵十', ['蛋汁', '普通的米', '蛋黃']), True)
_lists = (bag1920.KEEP_FOREVER, bag1920.PUBLIC_STORE, bag1920.STORE, bag1920.DELETE)
bag1920.KEEP_FOREVER, bag1920.PUBLIC_STORE, bag1920.STORE, bag1920.DELETE = ['蛋汁'], [], ['梅花餅'], []
check('bag1920.classify：拆字修正後認得', bag1920.classify('蛋氵十'), 'keep')
check('bag1920.classify：原字串先比（梅 不被改成 海）', bag1920.classify('梅花餅'), 'store')
check('bag1920.classify：都認不得 → unknown', bag1920.classify('石頭'), 'unknown')
bag1920.KEEP_FOREVER, bag1920.PUBLIC_STORE, bag1920.STORE, bag1920.DELETE = _lists
check('snap_pet：原字串完全相同優先', uikit.snap_pet('梅花', {'梅花': '梅花', '海花': '海花'}), '梅花')
check('snap_pet：原字串對不上 → 修正後比對', uikit.snap_pet('氵每龜', {'海龜': '海龜'}), '海龜')


# ---- 1b：淺色字讀法（假 uikit：記錄參數）----
class FakeUikit:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def ocr(self, box, *opts):
        self.calls.append((box, opts))
        return self.answers.get(opts, [])


u = FakeUikit({dq.TITLE_OPTS: ['普通的米', '普通的米'], ('-Zooms', '2,3'): ['的米']})
check('shop_title 先用 -Dark 0', (dq.shop_title(u), u.calls[0][1]), ('普通的米普通的米', ('-Zooms', '2,3', '-Dark', '0')))
check('shop_title -Dark 0 有字就不再讀舊讀法', len(u.calls), 1)
u = FakeUikit({('-Zooms', '2,3'): ['的米']})
check('shop_title -Dark 0 沒字 → 舊讀法', dq.shop_title(u), '的米')
u = FakeUikit({dq.NAME_OPTS: ['素材屋(石、木)']})
check('npc_name 預設名字框', (dq.npc_name(u), u.calls[0][0]), ('素材屋(石、木)', dq.NAME_BOX))
u = FakeUikit({})
check('npc_name 兩種都讀不到 → 空字串（讀 2 次）', (dq.npc_name(u, (1, 2, 3, 4)), len(u.calls)), ('', 2))


# ---- 1d：digitmatch 自訂框（合成字形）----
def glyph(rows_):
    return [r.replace('.', '0').replace('#', '1') for r in rows_]


G = {
    '0': ['########', '#......#', '#......#', '#......#', '#......#', '#......#', '#......#', '#......#', '#......#', '########'],
    '5': ['########', '#.......', '#.......', '#.......', '########', '.......#', '.......#', '.......#', '.......#', '########'],
    '1': ['..##....', '..##....', '..##....', '..##....', '..##....', '..##....', '..##....', '..##....', '..##....', '..##....'],
}


def field(text, gap=3):
    """字串 → 二值化列（上下各留 2 列空白）"""
    h = 10
    out = ['0' * (len(text) * (8 + gap) + 4)] * 2
    for y in range(h):
        out.append('00' + ''.join(glyph(G[c])[y] + '0' * gap for c in text) + '00')
    return out + [out[0]] * 2


tpl = {}
check('沒樣板 → None（交給 OCR）', digitmatch.read_digits(field('500'), tpl), None)
check('切字數不符不學', digitmatch.learn_digits(field('500'), '5000', tpl), 0)
check('非數字標籤不學', digitmatch.learn_digits(field('500'), '5o0', tpl), 0)
check('學 500 → 新增 2 個字元樣板', digitmatch.learn_digits(field('500'), '500', tpl), 2)
check('學過再學同樣的 → 不重複', digitmatch.learn_digits(field('500'), '500', tpl), 0)
check('讀 5005', digitmatch.read_digits(field('5005'), tpl), '5005')
check('有沒學過的字（1）→ None', digitmatch.read_digits(field('150'), tpl), None)
check('標籤與既有樣板衝突（把 0 標成 5）→ 整欄不學', digitmatch.learn_digits(field('0'), '5', tpl), 0)
check('整框沒墨 → None', digitmatch.read_digits(['0' * 20] * 14, tpl), None)
check('樣板另存 shopnum（不混進 HUD）', digitmatch.SHOP_TPL, '1920x1017-shopnum')

saved = (dq.shopnum, dq.shopnum_learn)
learned = []
dq.shopnum_learn = lambda box, rows, label: learned.append((box, label))
dq.shopnum = lambda box: ('4838000', ['x'])
u = FakeUikit({})
check('石幣：digitmatch 認得 → 不跑 OCR', (dq.coins(u), len(u.calls)), (4838000, 0))
dq.shopnum = lambda box: (None, ['x'])
u = FakeUikit({('-Zooms', '2,3'): ['4838000', '4838000']})
check('石幣：認不出 → OCR，兩次一致 → 補學', (dq.coins(u), learned[-1]), (4838000, (dq.COIN_BOX, '4838000')))
learned.clear()
u = FakeUikit({('-Zooms', '2,3'): ['483800', '4838000']})
check('石幣：OCR 兩次不一致 → 取第一個、不學', (dq.coins(u), learned), (483800, []))
u = FakeUikit({('-Zooms', '2,3'): ['1000', '1000']})
dq.shopnum = lambda box: ('1000', ['x'])
check('花費欄：digitmatch 認得 → [值]', dq.price_reads(u, 1000), ['1000'])
dq.shopnum = lambda box: (None, ['x'])
for z in ('2,3', '3,4', '4,5'):
    u.answers[('-Zooms', z)] = ['1000', '1000']
check('花費欄：OCR 3 次 + 等於預期 → 補學', (dq.price_reads(u, 1000), learned[-1][1]), (['1000'] * 3, '1000'))
learned.clear()
check('花費欄：不等於預期 → 不學', (dq.price_reads(u, 500), learned), (['1000'] * 3, []))
dq.shopnum, dq.shopnum_learn = saved
import os  # noqa: E402
os.environ['PSA_SHOPNUM_DM'] = '0'
check('PSA_SHOPNUM_DM=0 → 不用 digitmatch', dq.shopnum(dq.COIN_BOX), (None, None))
del os.environ['PSA_SHOPNUM_DM']


# ---- 追蹤欄（OCR 行 = 截圖實際讀到的）----
CUR_UU2 = [('碧洞', 194), ('漆黑洞窟(-轉)', 268), ('碧洞窟', 194), ('漆黑洞窟(一轉)', 267)]          # uu2.png 現行讀法
LIGHT_UU2 = [('碧青洞窟', 194), ('通青兆戰', 214), ('漆黑洞窟(一轉)', 267), ('碧青洞窟', 194), ('漆黑洞窟(一轉)', 267)]
LIGHT_K7 = [('玄黃洞窟', 194), ('進入夢德', 214), ('漆黑洞窟(一轉)', 267)]                                # k7.png：副標題提到夢德
CUR_102329 = [('漆洞窟(四轉)', 194), ('工的比賽', 268)]                                                   # 22222 礦工的比賽
LIGHT_102329 = [('漆黑洞窟(四轉)', 194), ('!守人', 214), ('礦工的比賽', 268)]
CUR_M1 = []                                                                                              # m1.png 成人儀式整條讀不到
LIGHT_M1 = [('成人儀式', 194), ('獲取成人勾玉', 214)]

check('track_titles 去掉副標題', qf.track_titles(LIGHT_K7), [('玄黃洞窟', 194), ('漆黑洞窟(一轉)', 267)])
check('現行讀法讀不到碧青', qf.match_track('碧青洞窟', CUR_UU2, fallback=False), None)
check('補讀找到碧青', qf.match_track_light('碧青洞窟', LIGHT_UU2), 194)
check('補讀不認副標題「進入夢德」', qf.match_track_light('夢德洞窟', LIGHT_K7), None)
check('補讀漆黑不分 N 轉', qf.match_track_light('漆黑洞窟(二轉)', LIGHT_102329), 194)
check('補讀支線跳過漆黑列', qf.match_track_light('礦工的比賽', LIGHT_102329), 268)
check('補讀找到成人儀式', qf.match_track_light('成人儀式', LIGHT_M1), 194)


def loc(name, cur, light):
    calls = []

    def read_light(*o):
        calls.append(o)
        return light
    return qf.locate_track(name, lambda: cur, read_light), len(calls)


check('locate：現行找得到就不補讀', loc('漆黑洞窟(一轉)', CUR_UU2, LIGHT_UU2), (268, 0))
check('locate：現行找不到 → 補讀（用 -Dark 0）', loc('碧青洞窟', CUR_UU2, LIGHT_UU2), (194, 1))
check('locate：成人儀式整條讀不到 → 補讀找到', loc('成人儀式', CUR_M1, LIGHT_M1)[0], 194)
check('locate：畫面上沒有的「XX洞窟」不再被保底認成最上面那格', loc('玄黃洞窟', CUR_UU2, LIGHT_UU2)[0], None)
check('舊行為：只用現行讀法 + 保底會誤認', qf.match_track('玄黃洞窟', [('洞窟(一轉)', 196)]) is not None, True)
check('top_is_other：最上面是漆黑', qf.top_is_other('玄黃洞窟', LIGHT_102329), True)
check('top_is_other：補讀也讀不出 → False（保留保底）', qf.top_is_other('猜謎三兄弟', [('4--0', 196)]), False)
check('locate：補讀讀不出最上面 → 保底照舊（猜謎三兄弟碎字）',
      loc('猜謎三兄弟', [('兄', 196)], [('4--0', 196)])[0], 196)
check('TRACK_LIGHT_OPTS 不二值化', qf.TRACK_LIGHT_OPTS, ('-Zooms', '3,4', '-Dark', '0'))

# ---- ocrbench 樣本集 ----
ts = json.loads(ocrbench.TRACK.read_text(encoding='utf-8'))
check('track_samples：每筆都有 img / expect 且名字都在 names',
      all(s['img'] and s['expect'] and set(s['expect']) <= set(ts['names']) for s in ts['samples']), True)
check('track_samples >= 200 張', len(ts['samples']) >= 200, True)
spec = json.loads(ocrbench.SAMPLES.read_text(encoding='utf-8'))
kinds = {g['kind']: len(g['samples']) for g in spec['groups']}
check('ocr_samples：便利店標題 24、名字框 37', (kinds.get('便利店標題（黃字紅底）'), kinds.get('NPC 對話名字框（淺色字棕底）')), (24, 37))
fake = {'現行（-Zooms 2,3，含保底）', '只用 -Dark 0 補讀', '新：現行 → -Dark 0 補讀 → 保底'}
check('ocrbench.track_found 三種讀法', set(ocrbench.track_found(['碧青洞窟'], lambda: CUR_UU2, lambda *o: LIGHT_UU2)), fake)

print(f'failed={fails}')
sys.exit(1 if fails else 0)
