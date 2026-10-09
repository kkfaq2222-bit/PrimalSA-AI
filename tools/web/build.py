# -*- coding: utf-8 -*-
"""
精靈王石器 知識庫 → 靜態查詢網站（只用 Python 標準函式庫，只讀 knowledge/）

用法（在專案根目錄）：
  uv run --no-project python tools/web/build.py [--out site]
  本機預覽：uv run --no-project python -m http.server -d site 8000

輸出（預設 site/）：
  index.html、app.js、style.css     由 tools/web/static/ 複製
  data/index.json                   搜尋索引：[類型, ID, 繁中, 簡中, 韓文, 附註]
  data/<類型>.json                  各類詳情（交叉關聯在建置時算好）：{ID: 詳情}
  data/docs.json、kb/**.md          knowledge/ 的 Markdown 文件（前端用 marked 顯示）
  data/maps.bin                     地圖通行格（格式見 tools/query/psa.py）

詳情格式：{"n": 名稱, "c": 簡中, "k": 韓文, "f": [[欄位, 片段列]], "d": 說明, "s": [[段落標題, [片段列, ...]]]}
片段列 = [字串 | [類型, ID] | ["pos", 地圖, x, y] | ["doc", 路徑, 文字]]，前端把參照轉成連結。
"""
import os, sys, json, re, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path[:0] = [os.path.join(ROOT, 'tools', 'query'), os.path.join(ROOT, 'tools', 'extract')]
import psa
from psa import T, by_id, nm, kr, clean, L
from docs import ITEM_TYPE, QUALITY, CURRENCY, TASK_TYPE, MAP_TYPE, NPC_FUNC, STAT, FIX, ELEM, PET_TYPE_LANG

KB = os.path.join(ROOT, 'knowledge')

def cur(t, v):
    return '%s %s' % (format(v, ','), CURRENCY.get(t) or '貨幣%s' % t)

def pos(m, x, y): return ['pos', m, x, y]

def sb_id(sid, lv=1):
    """skillId + 等級 → SkillBattle ID（找不到該等級就退回 Lv1 / 原 ID）"""
    sbs = by_id('SkillBattle')
    for k in (sid * 1000 + (lv or 1), sid * 1000 + 1, sid):
        if k in sbs: return k
    return None

def skill_ref(sid, lv=1):
    k = sb_id(sid, lv)
    return ['skill', k] if k else '技能%s' % sid

def req(lst):
    """需求 / 材料清單 → 片段列"""
    out = []
    for x in lst or []:
        if not isinstance(x, dict): continue
        if x.get('itemId'): out += [['item', x['itemId']], '×%d' % x.get('itemNum', 1), '、']
        if x.get('petId'): out += ['寵物 ', ['pet', x['petId']], '×%d' % x.get('petNum', 1), '、']
        if x.get('currencyType'): out += [cur(x['currencyType'], x.get('currencyValue', 0)), '、']
    return out[:-1]

def ent(r, f=None, d='', s=None, base='name'):
    e = {'n': nm(r, base), 'c': clean(r.get(base + 'Cn')), 'k': kr(r, base)}
    if f: e['f'] = [x for x in f if x[1]]
    if d: e['d'] = d
    s = [x for x in (s or []) if x[1]]
    if s: e['s'] = s
    return e

# ---------------- 反向索引（一次算好，避免每筆都掃全表） ----------------
def build_indexes():
    ix = collections.defaultdict(lambda: collections.defaultdict(list))
    for n in T('Npc'):
        for a in n.get('npcArgs') or []:
            if a.get('itemId') and a.get('price') is not None: ix['sell'][a['itemId']].append((n, a))
            if a.get('skillId'): ix['teach'][a['skillId']].append((n, a))
        if n.get('map') is not None: ix['npc_map'][n['map']].append(n)
    for x in T('ExchangeItem'):
        if x.get('targetType', 1) == 1: ix['make'][x.get('targetId')].append(x)
        elif x.get('targetType') == 2: ix['make_pet'][x.get('targetId')].append(x)
        for q in x.get('requireInfos') or []:
            if q.get('itemId'): ix['use'][q['itemId']].append(x)
            if q.get('petId'): ix['use_pet'][q['petId']].append(x)
    for x in T('ItemBook'):
        if x.get('itemId') and x.get('needItem'): ix['book'][x['itemId']].append(x)
        for q in x.get('needItem') or []:
            if q.get('itemId'): ix['book_use'][q['itemId']].append(x)
    for x in T('Lottery'):
        for q in x.get('Item') or []:
            if q.get('itemId'): ix['lottery'][q['itemId']].append((x, q))
    for t in T('Task'):
        for c in (t.get('condition') or []) + (t.get('waitItem') or []):
            if c.get('itemId'): ix['task_need'][c['itemId']].append(t)
            if c.get('monsterId'): ix['task_kill'][c['monsterId']].append(t)
            if c.get('petId'): ix['task_pet'][c['petId']].append(t)
        for c in t.get('reward') or []:
            if c.get('itemId'): ix['task_reward'][c['itemId']].append(t)
            if c.get('petId'): ix['task_reward_pet'][c['petId']].append(t)
        for k in ('startNpc', 'endNpc'):
            if t.get(k): ix[k][t[k]].append(t)
        ix['task_group'][t.get('group')].append(t)
    for m in T('Monster'):
        for s in m.get('skills') or []:
            if s.get('skillId'): ix['pet_skill'][s['skillId']].append((m, s))
    for it in T('Item'):
        for s in it.get('skill') or []:
            if s.get('skillId'): ix['item_skill'][s['skillId']].append(it)
    for x in T('PetData'):
        for t in x.get('TxtTn') or []:
            if t.get('petId'): ix['pet_src'][t['petId']].append(clean(t.get('aruaStr')))
    for x in T('PetBaby'):
        if x.get('petId'): ix['pet_baby'][x['petId']].append(x)
    for x in T('Ride'):
        if x.get('petId'): ix['ride'][x['petId']].append(x)
    for w in T('MapWarp'):
        if w.get('isNotUse'): continue
        ix['exit'][w.get('fMap')].append(w)
        if w.get('tMap') != w.get('fMap'): ix['enter'][w.get('tMap')].append(w)
    for sb in T('SkillBattle'):
        ix['skill_lv'][sb['ID'] // 1000].append(sb['ID'])
    return ix

def dedup(rows):
    seen, out = set(), []
    for r in rows:
        if id(r) not in seen: seen.add(id(r)); out.append(r)
    return out

def task_line(t, pre=''):
    return [pre, ['task', t['ID']], '（%s）' % TASK_TYPE.get(t.get('type'), t.get('type'))] if pre else [['task', t['ID']]]

# ---------------- 各類詳情 ----------------
def stats_line(r):
    st = []
    for k, lab in STAT:
        a, b = r.get(k + 'Min', 0), r.get(k + 'Max', 0)
        if a or b: st.append('%s%+d' % (lab, a) if a == b else '%s%+d~%+d' % (lab, a, b))
    for k, lab in FIX:
        if r.get(k): st.append('%s%+d' % (lab, r[k]))
    return ' '.join(st)

def elem_line(d):
    return ' '.join('%s%d' % (ELEM[i], d.get(k, 0)) for i, k in enumerate(('earth', 'water', 'fire', 'wind')) if d.get(k, 0))

def item_detail(r, ix):
    i = r['ID']
    q = r.get('quality')
    sk = []
    for s in r.get('skill') or []:
        if s.get('skillId'): sk += [skill_ref(s['skillId'], s.get('skillLevel', 1)), '、']
    f = [['類型', ['%s（%s）' % (ITEM_TYPE.get(r.get('type'), '?'), r.get('type'))]],
         ['品質', ['%s（%s）' % (QUALITY[q], q)] if isinstance(q, int) and 0 <= q < len(QUALITY) else []],
         ['能力', [stats_line(r)] if stats_line(r) else []],
         ['屬性', [elem_line(r)] if elem_line(r) else []],
         ['需求', ['Lv%s' % r['level']] if r.get('level') else []],
         ['轉生', ['%s 轉以上' % r['transLimit']] if r.get('transLimit') else []],
         ['附帶技能', sk[:-1]],
         ['可堆疊', [str(r['overlay'])] if r.get('overlay') else []],
         ['圖號', [str(r.get('imageId'))] if r.get('imageId') else []]]
    s = [['販售 NPC', [[['npc', n['ID']], ' @ ', pos(n.get('map'), n.get('x'), n.get('y')), '　' + cur(a.get('currency', 3), a.get('price', 0))]
                     for n, a in ix['sell'].get(i, [])]],
         ['怎麼做出來（合成）', [['合成#%d 成功率 %.1f%%：' % (x['ID'], x.get('rate', 1000) / 10)] + req(x.get('requireInfos')) for x in ix['make'].get(i, [])]],
         ['材料圖鑑製作', [['圖鑑#%d：' % x['ID']] + req(x['needItem']) for x in ix['book'].get(i, [])]],
         ['拿去合成什麼', [['合成#%d → ' % x['ID'], ['item' if x.get('targetType', 1) == 1 else 'pet', x.get('targetId')]] for x in dedup(ix['use'].get(i, []))]],
         ['拿去做圖鑑', [['圖鑑#%d → ' % x['ID'], ['item', x['itemId']]] for x in dedup(ix['book_use'].get(i, []))]],
         ['抽獎', [['「%s」(ID %d) 權重 %s' % (nm(x), x['ID'], q.get('rate'))] for x, q in ix['lottery'].get(i, [])]],
         ['任務需要', [task_line(t) for t in dedup(ix['task_need'].get(i, []))]],
         ['任務獎勵', [task_line(t) for t in dedup(ix['task_reward'].get(i, []))]]]
    return ent(r, f, clean(r.get('descriptionTn') or r.get('descriptionCn')), s)

def pet_type_name(ty):
    if 0 <= ty < 30: return L(PET_TYPE_LANG + ty) or '系別%s' % ty
    return '敵方 / NPC' if ty == 100 else '系別%s' % ty

def pet_doc(ty):
    if 0 <= ty <= 28: return 'pets/type-%02d.md' % ty
    if ty == 120: return 'pets/type-120.md'
    return None

def pet_detail(r, ix):
    i = r['ID']
    g = r.get('growArg') or {}; p = r.get('property') or {}
    tot = sum(g.get(k, 0) for k in ('vitArg', 'atkArg', 'defArg', 'dexArg'))
    ty = r.get('petType', -1)
    doc = pet_doc(ty)
    sk = []
    for s in r.get('skills') or []:
        if s.get('skillId'): sk += [skill_ref(s['skillId'], s.get('skillLevel', 1)), '、']
    f = [['系別', [['doc', doc, pet_type_name(ty)]] if doc else [pet_type_name(ty)]],
         ['品質', [str(r.get('quality'))]],
         ['成長', ['初始 %s，每級 %s' % (g.get('initArg'), g.get('levelUpArg'))]],
         ['成長檔', ['體 %s / 腕 %s / 耐 %s / 速 %s，總檔 %d' % (g.get('vitArg'), g.get('atkArg'), g.get('defArg'), g.get('dexArg'), tot)]],
         ['屬性', [elem_line(p) or '無']],
         ['天生技能', sk[:-1]],
         ['圖號', [str(r.get('imageId'))]]]
    s = [['取得', [[t] for t in ix['pet_src'].get(i, [])]],
         ['領取點', [['領取點 ', pos((x.get('point') or {}).get('map'), (x.get('point') or {}).get('x'), (x.get('point') or {}).get('y'))]
                    + (['　費用 '] + req(x.get('condtion')) if x.get('condtion') else []) for x in ix['pet_baby'].get(i, [])]],
         ['騎乘', [['坐騎圖號 %s，%s' % (x['ID'], '需要先學騎乘' if x.get('needlearn') else '不用學騎乘')] for x in ix['ride'].get(i, [])]],
         ['合成得到', [['合成#%d：' % x['ID']] + req(x.get('requireInfos')) for x in ix['make_pet'].get(i, [])]],
         ['拿去合成', [['合成#%d → ' % x['ID'], ['item' if x.get('targetType', 1) == 1 else 'pet', x.get('targetId')]] for x in dedup(ix['use_pet'].get(i, []))]],
         ['任務要打倒', [task_line(t) for t in dedup(ix['task_kill'].get(i, []))]],
         ['任務需要', [task_line(t) for t in dedup(ix['task_pet'].get(i, []))]],
         ['任務獎勵', [task_line(t) for t in dedup(ix['task_reward_pet'].get(i, []))]]]
    return ent(r, f, '', s)

def npc_detail(r, ix):
    i = r['ID']
    f = [['位置', [pos(r.get('map'), r.get('x'), r.get('y'))]],
         ['方向', [str(r.get('dir'))]],
         ['圖號', [str(r.get('imageId'))]],
         ['狀態', ['隱藏（visable=0）'] if not r.get('visable', 1) else []],
         ['開啟介面', [r['openUIName']] if r.get('openUIName') else []],
         ['交通路線', sum([[pos(p.get('map'), p.get('x'), p.get('y')), ' → '] for p in r.get('airBusWay') or []], [])[:-1]]]
    sell, teach = [], []
    for a in r.get('npcArgs') or []:
        if a.get('itemId') and a.get('price') is not None: sell.append([['item', a['itemId']], '　' + cur(a.get('currency', 3), a['price'])])
        if a.get('skillId'): teach.append([skill_ref(a['skillId'], a.get('skillLevel', 1)), '　Lv%s　%s' % (a.get('skillLevel', 1), cur(a.get('skillCostType', 3), a.get('skillCost', 0)))])
    s = [['販售', sell], ['教技能', teach]]
    for sid in r.get('script') or []:
        sc = by_id('NpcScript').get(sid)
        if not sc: continue
        fn = (sc.get('script') or {}).get('func')
        title = '腳本 %d：%s' % (sid, nm(sc) or '') + ('（%s）' % NPC_FUNC.get(fn, fn) if fn else '')
        lines = [['> ' + clean(x)] for x in (sc.get('msgTn') or sc.get('msgCn') or []) if clean(x)]
        s.append([title, lines or [['（無對話）']]])
    s += [['接任務', [task_line(t) for t in ix['startNpc'].get(i, [])]],
          ['回報任務', [task_line(t) for t in ix['endNpc'].get(i, [])]]]
    return ent(r, f, clean(r.get('defaultMsgTw') or r.get('defaultMsg')), s)

def map_detail(r, ix, maps):
    i = r['ID']
    info = maps.get(i)
    f = [['類型', ['%s（%s）' % (MAP_TYPE.get(r.get('type'), '?'), r.get('type'))] if r.get('type') is not None else []],
         ['大小', ['%d × %d' % (info[0], info[1])] if info else ['沒有通行格資料']]]
    npcs = sorted(ix['npc_map'].get(i, []), key=lambda n: (n.get('x', 0), n.get('y', 0)))
    s = [['NPC', [[['npc', n['ID']], '　(%s, %s)' % (n.get('x'), n.get('y'))] for n in npcs]],
         ['出口', [['(%s, %s) → ' % (w.get('fX'), w.get('fY')), pos(w.get('tMap'), w.get('tX'), w.get('tY'))] for w in ix['exit'].get(i, [])]],
         ['從哪裡進來', [[pos(w.get('fMap'), w.get('fX'), w.get('fY')), ' → (%s, %s)' % (w.get('tX'), w.get('tY'))] for w in ix['enter'].get(i, [])]]]
    e = ent(r, f, '', s)
    if info:
        # 前端畫地圖用：NPC 與出口標記
        e['g'] = {'npc': [[n.get('x'), n.get('y'), n['ID']] for n in npcs],
                  'exit': [[w.get('fX'), w.get('fY'), w.get('tMap')] for w in ix['exit'].get(i, [])]}
    return e

def skill_detail(r, ix):
    sid, lv = divmod(r['ID'], 1000)
    sk = by_id('Skill').get(sid) or {}
    c = r.get('costNum') or {}
    f = [['技能 ID', ['skillId %d，Lv%d（SkillBattle %d）' % (sid, lv, r['ID'])]],
         ['類型', [{1: '物理', 2: '魔法'}.get(sk.get('skillType'), str(sk.get('skillType', '?')))]] if sk else [],
         ['被動', ['是'] if sk.get('isPassive') else []],
         ['群體', ['是'] if sk.get('groupMagic') or sk.get('groupPhysical') else []],
         ['MP', ['%s ~ %s' % (c.get('min', 0), c.get('max', 0))] if c.get('min') or c.get('max') else []],
         ['其他等級', sum([[['skill', k], '、'] for k in sorted(ix['skill_lv'].get(sid, [])) if k != r['ID']], [])[:-1]]]
    s = [['天生擁有的寵物', [[['pet', m['ID']], '　Lv%s' % s.get('skillLevel', 1)] for m, s in ix['pet_skill'].get(sid, [])]],
         ['NPC 教', [[['npc', n['ID']], ' @ ', pos(n.get('map'), n.get('x'), n.get('y')), '　Lv%s　%s' % (a.get('skillLevel', 1), cur(a.get('skillCostType', 3), a.get('skillCost', 0)))]
                    for n, a in ix['teach'].get(sid, [])]],
         ['道具附帶', [[['item', it['ID']]] for it in dedup(ix['item_skill'].get(sid, []))]]]
    return ent(r, [x for x in f if x], clean(r.get('desInfoTn') or r.get('desInfoCn')), s)

def buff_detail(r, ix):
    f = [['ID', [str(r['ID'])]], ['類別', [str(r.get('buffType'))] if r.get('buffType') is not None else []]]
    return ent(r, f, clean(r.get('descTn') or r.get('descCn')))

COND = {'level': '角色 Lv%s 以上', 'trans': '%s 轉以上', 'stone': '%s 石幣', 'fightCount': '戰鬥 %s 次', 'petDna': '寵物 DNA %s'}

def task_cond(lst):
    out = []
    for c in lst or []:
        if c.get('itemId'): out.append([['item', c['itemId']], '×%s' % c.get('itemNum', 1)])
        if c.get('monsterId'): out.append(['打倒 ', ['pet', c['monsterId']], '×%s' % c.get('monsterNum', 1)])
        if c.get('petId'): out.append(['寵物 ', ['pet', c['petId']]])
        for k, fmt in COND.items():
            if c.get(k): out.append([fmt % c[k]])
    return out

def task_reward(lst):
    out = []
    for c in lst or []:
        if c.get('itemId'): out.append([['item', c['itemId']], '×%s' % c.get('itemNum', 1)])
        if c.get('petId'): out.append(['寵物 ', ['pet', c['petId']]])
        if c.get('exp'): out.append(['經驗 %s' % c['exp']])
        if c.get('stone'): out.append(['石幣 %s' % format(c['stone'], ',')])
        if c.get('lockDenar'): out.append(['綁定鑽石 %s' % c['lockDenar']])
        if c.get('transAdd'): out.append(['轉生 +%s' % c['transAdd']])
        if c.get('aruaStr'): out.append(['光環 %s' % clean(c['aruaStr'])])
        if c.get('skinStr'): out.append(['外觀 %s' % clean(c['skinStr'])])
        if c.get('partnerId'): out.append(['夥伴 %s' % c['partnerId']])
    return out

def task_detail(r, ix):
    f = [['類型', ['%s（%s）' % (TASK_TYPE.get(r.get('type'), '?'), r.get('type'))]],
         ['任務鏈', ['group %s 第 %s 步' % (r.get('group'), r.get('step'))]],
         ['接取', [['npc', r['startNpc']], ' @ ', pos(*npc_pos(r['startNpc']))] if r.get('startNpc') and npc_pos(r['startNpc']) else []],
         ['回報', [['npc', r['endNpc']], ' @ ', pos(*npc_pos(r['endNpc']))] if r.get('endNpc') and npc_pos(r['endNpc']) else []],
         ['可重複', ['是'] if r.get('loop') else []]]
    chain = sorted(ix['task_group'].get(r.get('group'), []), key=lambda t: t.get('step', 0))
    s = [['條件', task_cond(r.get('condition')) + task_cond(r.get('waitItem'))],
         ['獎勵', task_reward(r.get('reward'))],
         ['導航點', [[pos(p.get('map'), p.get('x'), p.get('y'))] for p in r.get('taskNavigate') or []]],
         ['同一任務鏈', [['第 %s 步　' % t.get('step'), ['task', t['ID']]] + (['（本頁）'] if t is r else []) for t in chain] if len(chain) > 1 else []]]
    d = clean(r.get('explandTn') or r.get('explandCn'))
    return ent(r, f, d, s)

def npc_pos(nid):
    n = by_id('Npc').get(nid)
    return (n.get('map'), n.get('x'), n.get('y')) if n else None

# ---------------- 輸出 ----------------
def doc_list():
    """標題用各文件自己的 H1；說明取 knowledge/README.md「全部文件」清單（去掉與標題重複的開頭）"""
    meta = {}
    for line in open(os.path.join(KB, 'README.md'), encoding='utf-8'):
        m = re.match(r'- \[([^\]]+)\]\([^)]+\) — (.*)', line.strip())
        if m: meta[m.group(1)] = m.group(2)
    out = [['README.md', '知識庫索引', '分類目錄、全部文件清單、查詢方法']]
    for dp, _, fs in sorted(os.walk(KB)):
        for fn in sorted(fs):
            if not fn.endswith('.md'): continue
            rel = os.path.relpath(os.path.join(dp, fn), KB).replace(os.sep, '/')
            if rel == 'README.md': continue
            with open(os.path.join(dp, fn), encoding='utf-8') as f:
                h1 = next((l[2:].strip() for l in f if l.startswith('# ')), '')
            d = meta.get(rel, '')
            t = h1 or d.partition('：')[0] or fn[:-3]
            if d.startswith(t): d = d[len(t):].lstrip('：: ')
            out.append([rel, t, d])
    return out

def dump(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    return os.path.getsize(path)

def main():
    out = os.path.join(ROOT, 'site')
    if '--out' in sys.argv: out = os.path.abspath(sys.argv[sys.argv.index('--out') + 1])
    if os.path.exists(out): shutil.rmtree(out)
    shutil.copytree(os.path.join(HERE, 'static'), out)
    data = os.path.join(out, 'data'); os.makedirs(data)

    ix = build_indexes()
    maps = {k: v[:2] for k, v in psa.load_maps().items()}
    index = []
    sizes = {}

    def emit(typ, table, fn, sub):
        det = {}
        for r in T(table):
            if r.get('ID') is None: continue
            det[r['ID']] = e = fn(r)
            index.append([typ, r['ID'], e['n'], e['c'] if e['c'] != e['n'] else '', e['k'], sub(r)])
        sizes[typ] = dump(os.path.join(data, typ + '.json'), det)

    emit('item', 'Item', lambda r: item_detail(r, ix), lambda r: ITEM_TYPE.get(r.get('type'), ''))
    emit('pet', 'Monster', lambda r: pet_detail(r, ix), lambda r: pet_type_name(r.get('petType', -1)))
    emit('npc', 'Npc', lambda r: npc_detail(r, ix), lambda r: '%s %s,%s' % (psa.map_name(r.get('map')), r.get('x'), r.get('y')))
    emit('map', 'MapName', lambda r: map_detail(r, ix, maps), lambda r: MAP_TYPE.get(r.get('type'), ''))
    emit('skill', 'SkillBattle', lambda r: skill_detail(r, ix), lambda r: 'Lv%d' % (r['ID'] % 1000))
    emit('buff', 'SkillStatus', lambda r: buff_detail(r, ix), lambda r: '')
    emit('task', 'Task', lambda r: task_detail(r, ix), lambda r: TASK_TYPE.get(r.get('type'), ''))
    # 沒有名稱的列（例如任務某一步沒填名稱）用 ID 代替，搜尋結果才不會空白
    for row in index:
        if not row[2]: row[2] = '#%s' % row[1]
    sizes['index'] = dump(os.path.join(data, 'index.json'), index)

    docs = doc_list()
    for rel, _, _ in docs:
        dst = os.path.join(out, 'kb', rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(KB, rel), dst)
    readme = open(os.path.join(KB, 'README.md'), encoding='utf-8').read()
    m = re.search(r'產生時間：([^；\n]+)；遊戲資料版本（Config\.MD5Version）：(\w+)', readme)
    dump(os.path.join(data, 'docs.json'), {'docs': docs, 'built': m.group(1) if m else '', 'version': m.group(2) if m else ''})
    shutil.copyfile(os.path.join(KB, 'data', 'maps.bin'), os.path.join(data, 'maps.bin'))
    open(os.path.join(out, '.nojekyll'), 'w').close()

    print('輸出到 %s' % out)
    for k, v in sizes.items(): print('  data/%s.json  %.1f KB' % (k, v / 1024))
    print('  搜尋索引 %d 筆，文件 %d 份' % (len(index), len(docs)))

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
