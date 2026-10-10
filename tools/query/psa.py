# -*- coding: utf-8 -*-
"""
精靈王石器 知識庫查詢工具（只讀 knowledge/data，只用 Python 標準函式庫）

用法：uv run --no-project python tools/query/psa.py <指令> [參數]
  find  <關鍵字>                       搜尋道具 / 寵物 / NPC / 地圖 / 技能 / 任務 / 狀態 名稱（繁中、簡中、韓文皆可）
  item  <名稱|ID>                      道具詳情：能力、販售 NPC、合成配方（怎麼做 / 拿去做什麼）、抽獎、任務用途
  pet   <名稱|ID>                      寵物 / 怪物詳情：成長檔、屬性、技能、取得方式、騎乘
  npc   <名稱|ID>                      NPC 詳情：位置、販售、教技能、腳本對話
  map   <名稱|ID>                      地圖詳情：大小、NPC、出口、哪些地圖通到這裡
  skill <名稱|ID>                      技能詳情（SkillBattle），以及哪些寵物天生有、哪個 NPC 教
  task  <名稱|ID>                      任務詳情
  steps <任務組ID|任務名>              任務每一步分類：NPC @ 地圖座標、對話 / 戰鬥 / 打怪、判斷依據（解任務逃跑風格用）
  route <起點地圖> <x> <y> <終點地圖> [x y]   跨地圖路線（只算地圖出口，不含付費傳送 / 交通 NPC）
  grid  <地圖> <x> <y> [半徑=15]        印出座標附近通行格：. 可走  ~ 水/懸崖  # 障礙  (空白) 無地面  @ 目標  N NPC  W 出口
  petimg <名稱|ID>                     寵物圖檔路徑（頭像 / 靜態圖，猜謎比對用；先跑 tools/extract/pet_images.py 匯出）
  raw   <表名> <ID>                    印出某表某 ID 的原始 JSON

maps.bin 格式：'PSAMAP1' + int32 數量 + [int32 id, uint16 寬, uint16 高, int32 長度, raw deflate(每格 1 byte，索引 = y*寬+x)]
  格子值：0 = 無地面, 1 = 可通行, 2 = 不可通行地面(水/懸崖), 3 = 物件阻擋
"""
import sys, os, json, re, struct, zlib, heapq, collections

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
DATA = os.path.join(ROOT, 'knowledge', 'data')
CUR = {1: '鑽石', 2: '金幣', 3: '石幣', 8: '綁定鑽石', 10: '活躍度', 11: '積分'}

_T = {}
def T(name):
    if name not in _T:
        p = os.path.join(DATA, 'tables', name + '.jsonl')
        _T[name] = [json.loads(l) for l in open(p, encoding='utf-8')] if os.path.exists(p) else []
    return _T[name]

_IDX = {}
def by_id(name):
    if name not in _IDX: _IDX[name] = {r.get('ID'): r for r in T(name)}
    return _IDX[name]

def clean(s):
    if isinstance(s, list): s = ''.join(map(str, s))
    return re.sub(r'</?(color|size)[^>]*>', '', str(s or '')).replace('\\n', ' ').strip()

def nm(r, base='name'):
    return clean(r.get(base + 'Tn') or r.get(base + 'Cn') or '') if r else ''

def kr(r, base='name'):
    return clean(r.get(base + 'Kr') or r.get(base + 'Krn') or '') if r else ''

_LANG = None
def L(i):
    global _LANG
    if _LANG is None:
        _LANG = {}
        for r in T('NewLanguage'): _LANG[r['ID']] = clean(r.get('tcn') or r.get('scn'))
        for r in T('NewLanguagePublic'): _LANG[r['ID']] = clean(r.get('StrTn') or r.get('StrCn'))
    return _LANG.get(i, '') if isinstance(i, int) else ''

def item_name(i): return nm(by_id('Item').get(i)) or '#%s' % i
def mon_name(i): return nm(by_id('Monster').get(i)) or '#%s' % i
def npc_name(i): return nm(by_id('Npc').get(i)) or '#%s' % i
def map_name(i):
    r = by_id('MapName').get(i)
    return (clean(r.get('nameTn') or r.get('nameCn')) if r else '') or '地圖%s' % i
def skill_name(sid, lv=1):
    r = by_id('SkillBattle').get(sid * 1000 + (lv or 1)) or by_id('SkillBattle').get(sid)
    return nm(r) or '技能%s' % sid
def pos(m, x, y): return '%s(%s) %s,%s' % (map_name(m), m, x, y)
def cur(t, v): return '%s %s' % (v, CUR.get(t, '貨幣%s' % t)) if t else str(v)

def resolve(table, key, names=('name',)):
    """ID 或名稱 → 列（名稱完全相符優先，其次包含）"""
    rows = T(table)
    if re.fullmatch(r'-?\d+', key):
        r = by_id(table).get(int(key))
        if r: return [r]
    k = key.lower()
    def fields(r):
        for b in names:
            for suf in ('Tn', 'Cn', 'Kr', 'Krn', ''):
                v = r.get(b + suf)
                if isinstance(v, str): yield v.lower()
    exact = [r for r in rows if any(v == k for v in fields(r))]
    return exact or [r for r in rows if any(k in v for v in fields(r))]

def pick(table, key, names=('name',)):
    rs = resolve(table, key, names)
    if not rs: print('找不到：%s' % key); return None
    if len(rs) > 1:
        print('符合 %d 筆，顯示第一筆；其他：%s' % (len(rs), '、'.join('%s(%s)' % (nm(r, names[0]), r.get('ID')) for r in rs[1:15])))
    return rs[0]

# ---------------- 指令 ----------------
def cmd_find(key):
    for table, label, names in (('Item', '道具', ('name',)), ('Monster', '寵物/怪物', ('name',)), ('Npc', 'NPC', ('name',)),
                                ('MapName', '地圖', ('name',)), ('SkillBattle', '技能', ('name',)), ('SkillStatus', '狀態', ('name',)),
                                ('Task', '任務', ('name',)), ('NpcScript', '腳本', ('name',))):
        rs = resolve(table, key, names)
        if not rs: continue
        print('== %s（%d）' % (label, len(rs)))
        for r in rs[:30]:
            extra = ''
            if table == 'Npc': extra = ' @ ' + pos(r.get('map'), r.get('x'), r.get('y'))
            print('  %s  %s  %s%s' % (r.get('ID'), nm(r), kr(r), extra))
        if len(rs) > 30: print('  …還有 %d 筆' % (len(rs) - 30))

STAT = [('physicalAttack', '攻'), ('physicalDefense', '防'), ('agile', '敏'), ('hp', 'HP'), ('mp', 'MP'), ('luck', '運'), ('charm', '魅'),
        ('physicalDodge', '閃避'), ('physicalCrit', '爆擊'), ('attackCount', '攻擊次數'), ('poisonResist', '抗毒'), ('paralysisResist', '抗麻'),
        ('sleepResist', '抗睡'), ('stoneResist', '抗石'), ('drunkResist', '抗醉'), ('chaosResist', '抗亂'), ('dizzinessResist', '抗暈'), ('barrierResist', '抗結界')]

def req(lst):
    out = []
    for x in lst or []:
        if not isinstance(x, dict): continue
        if x.get('itemId'): out.append('%s(%d)×%d' % (item_name(x['itemId']), x['itemId'], x.get('itemNum', 1)))
        if x.get('petId'): out.append('寵物%s(%d)×%d' % (mon_name(x['petId']), x['petId'], x.get('petNum', 1)))
        if x.get('currencyType'): out.append(cur(x['currencyType'], x.get('currencyValue', 0)))
    return '、'.join(out)

def cmd_item(key):
    r = pick('Item', key)
    if not r: return
    i = r['ID']
    print('%s (ID %d) 韓文:%s  type=%s 品質=%s imageId=%s' % (nm(r), i, kr(r), r.get('type'), r.get('quality', ''), r.get('imageId')))
    st = []
    for k, lab in STAT:
        a, b = r.get(k + 'Min', 0), r.get(k + 'Max', 0)
        if a or b: st.append('%s%+d' % (lab, a) if a == b else '%s%+d~%+d' % (lab, a, b))
    if st: print('能力：' + ' '.join(st))
    el = [r.get(k, 0) for k in ('earth', 'water', 'fire', 'wind')]
    if any(el): print('屬性：地%d 水%d 火%d 風%d' % tuple(el))
    if r.get('level') or r.get('transLimit'): print('需求：Lv%s %s轉' % (r.get('level', 0), r.get('transLimit', 0)))
    if r.get('skill'): print('附帶技能：' + '、'.join(skill_name(s['skillId'], s.get('skillLevel', 1)) for s in r['skill'] if s.get('skillId')))
    d = clean(r.get('descriptionTn') or r.get('descriptionCn'))
    if d: print('說明：' + d)
    print('-- 販售 NPC：')
    for n in T('Npc'):
        for a in n.get('npcArgs', []) or []:
            if a.get('itemId') == i and a.get('price') is not None:
                print('   %s(%d) @ %s  %s' % (nm(n), n['ID'], pos(n.get('map'), n.get('x'), n.get('y')), cur(a.get('currency', 3), a.get('price', 0))))
    print('-- 怎麼做出來：')
    for x in T('ExchangeItem'):
        if x.get('targetId') == i and x.get('targetType', 1) == 1:
            print('   合成#%d 成功率%.1f%%：%s' % (x['ID'], x.get('rate', 1000) / 10, req(x.get('requireInfos'))))
    for x in T('ItemBook'):
        if x.get('itemId') == i and x.get('needItem'): print('   材料圖鑑#%d：%s' % (x['ID'], req(x['needItem'])))
    print('-- 拿去做什麼：')
    for x in T('ExchangeItem'):
        if any(q.get('itemId') == i for q in x.get('requireInfos', []) or []):
            tgt = item_name(x.get('targetId')) if x.get('targetType', 1) == 1 else '寵物' + mon_name(x.get('targetId'))
            print('   合成#%d → %s(%s)' % (x['ID'], tgt, x.get('targetId')))
    for x in T('Lottery'):
        for q in x.get('Item', []) or []:
            if q.get('itemId') == i: print('-- 抽獎「%s」(ID %d) 權重 %s' % (nm(x), x['ID'], q.get('rate')))
    for t in T('Task'):
        if any(c.get('itemId') == i for c in (t.get('condition') or []) + (t.get('waitItem') or [])):
            print('-- 任務需要：%s(ID %d)' % (nm(t), t['ID']))
        if any(c.get('itemId') == i for c in (t.get('reward') or [])):
            print('-- 任務獎勵：%s(ID %d)' % (nm(t), t['ID']))

def cmd_pet(key):
    r = pick('Monster', key)
    if not r: return
    g = r.get('growArg', {}) or {}; p = r.get('property', {}) or {}
    tot = sum(g.get(k, 0) for k in ('vitArg', 'atkArg', 'defArg', 'dexArg'))
    ty = r.get('petType', -1)
    print('%s (ID %d) 韓文:%s 系別:%s(%s) 品質:%s 圖號:%s' % (nm(r), r['ID'], kr(r), L(200000019 + ty) if 0 <= ty < 30 else ('敵方/NPC' if ty == 100 else ''), ty, r.get('quality'), r.get('imageId')))
    print('成長：初始 %s 每級 %s  體%s 腕%s 耐%s 速%s 總檔 %d' % (g.get('initArg'), g.get('levelUpArg'), g.get('vitArg'), g.get('atkArg'), g.get('defArg'), g.get('dexArg'), tot))
    print('屬性：地%s 水%s 火%s 風%s' % (p.get('earth', 0), p.get('water', 0), p.get('fire', 0), p.get('wind', 0)))
    if r.get('skills'): print('天生技能：' + '、'.join('%s(%d)' % (skill_name(s['skillId'], s.get('skillLevel', 1)), s['skillId']) for s in r['skills'] if s.get('skillId')))
    for x in T('PetData'):
        for t in x.get('TxtTn', []) or []:
            if t.get('petId') == r['ID']: print('取得：' + clean(t.get('aruaStr')))
    for x in T('PetBaby'):
        if x.get('petId') == r['ID']:
            pt = x.get('point') or {}; print('領取點：%s 費用 %s' % (pos(pt.get('map'), pt.get('x'), pt.get('y')), req(x.get('condtion'))))
    for x in T('Ride'):
        if x.get('petId') == r['ID']: print('可騎乘：坐騎圖號 %s needlearn=%s' % (x['ID'], x.get('needlearn', 0)))
    for x in T('ExchangeItem'):
        if x.get('targetType') == 2 and x.get('targetId') == r['ID']: print('合成得到：合成#%d %s' % (x['ID'], req(x.get('requireInfos'))))
    for t in T('Task'):
        if any(c.get('monsterId') == r['ID'] for c in t.get('condition') or []): print('任務要打倒：%s(ID %d)' % (nm(t), t['ID']))

def cmd_npc(key):
    r = pick('Npc', key)
    if not r: return
    print('%s (ID %d) 韓文:%s @ %s 方向%s 圖號%s %s' % (nm(r), r['ID'], kr(r), pos(r.get('map'), r.get('x'), r.get('y')), r.get('dir'), r.get('imageId'), '' if r.get('visable', 1) else '（隱藏）'))
    m = clean(r.get('defaultMsgTw') or r.get('defaultMsg'))
    if m: print('對話：' + m)
    for a in r.get('npcArgs', []) or []:
        if a.get('itemId') and a.get('price') is not None: print('  販售 %s(%d) %s' % (item_name(a['itemId']), a['itemId'], cur(a.get('currency', 3), a['price'])))
        if a.get('skillId'): print('  教技能 %s Lv%s %s' % (skill_name(a['skillId'], a.get('skillLevel', 1)), a.get('skillLevel', 1), cur(a.get('skillCostType', 3), a.get('skillCost', 0))))
    if r.get('airBusWay'): print('交通路線：' + ' → '.join(pos(p.get('map'), p.get('x'), p.get('y')) for p in r['airBusWay']))
    if r.get('openUIName'): print('開啟介面：' + r['openUIName'])
    for s in r.get('script', []) or []:
        sc = by_id('NpcScript').get(s)
        if not sc: continue
        print('-- 腳本 %d：%s  func=%s %s' % (s, nm(sc), (sc.get('script') or {}).get('func'), json.dumps({k: v for k, v in (sc.get('script') or {}).items() if k != 'func'}, ensure_ascii=False)))
        for line in sc.get('msgTn') or sc.get('msgCn') or []: print('   > ' + clean(line))
    for t in T('Task'):
        if t.get('startNpc') == r['ID']: print('-- 接任務：%s(ID %d)' % (nm(t), t['ID']))
        if t.get('endNpc') == r['ID']: print('-- 回報任務：%s(ID %d)' % (nm(t), t['ID']))

def cmd_map(key):
    rs = resolve('MapName', key)
    mid = rs[0]['ID'] if rs else (int(key) if key.isdigit() else None)
    if mid is None: print('找不到地圖：' + key); return
    if len(rs) > 1: print('符合 %d 筆：%s' % (len(rs), '、'.join('%s(%s)' % (nm(r), r['ID']) for r in rs[:15])))
    info = load_maps().get(mid)
    mr = by_id('MapName').get(mid, {})
    print('%s (ID %s) 韓文:%s 類型:%s 大小:%s' % (map_name(mid), mid, kr(mr), mr.get('type'), '%dx%d' % (info[0], info[1]) if info else '?'))
    print('-- NPC：')
    for n in T('Npc'):
        if n.get('map') == mid: print('   %s(%d) @ %s,%s' % (nm(n), n['ID'], n.get('x'), n.get('y')))
    print('-- 出口：')
    for w in T('MapWarp'):
        if w.get('fMap') == mid and not w.get('isNotUse'): print('   (%s,%s) → %s' % (w.get('fX'), w.get('fY'), pos(w.get('tMap'), w.get('tX'), w.get('tY'))))
    print('-- 從哪裡進來：')
    for w in T('MapWarp'):
        if w.get('tMap') == mid and w.get('fMap') != mid and not w.get('isNotUse'): print('   %s → (%s,%s)' % (pos(w.get('fMap'), w.get('fX'), w.get('fY')), w.get('tX'), w.get('tY')))

def cmd_skill(key):
    r = pick('SkillBattle', key)
    if not r: return
    sid, lv = divmod(r['ID'], 1000)
    sk = by_id('Skill').get(sid, {})
    c = r.get('costNum') or {}
    print('%s (SkillBattle %d = skillId %d Lv%d) 韓文:%s' % (nm(r), r['ID'], sid, lv, kr(r)))
    print('類型:%s 被動:%s 群體:%s 目標:%s MP:%s~%s' % ({1: '物理', 2: '魔法'}.get(sk.get('skillType'), sk.get('skillType')), sk.get('isPassive', 0), sk.get('groupMagic') or sk.get('groupPhysical') or 0, sk.get('target'), c.get('min', 0), c.get('max', 0)))
    print('說明：' + clean(r.get('desInfoTn') or r.get('desInfoCn')))
    for m in T('Monster'):
        if any(s.get('skillId') == sid for s in m.get('skills', []) or []): print('-- 天生擁有：%s(%d)' % (nm(m), m['ID']))
    for n in T('Npc'):
        for a in n.get('npcArgs', []) or []:
            if a.get('skillId') == sid: print('-- NPC 教：%s(%d) @ %s Lv%s %s' % (nm(n), n['ID'], pos(n.get('map'), n.get('x'), n.get('y')), a.get('skillLevel', 1), cur(a.get('skillCostType', 3), a.get('skillCost', 0))))
    for it in T('Item'):
        if any(s.get('skillId') == sid for s in it.get('skill', []) or []): print('-- 道具附帶：%s(%d)' % (nm(it), it['ID']))

def cmd_task(key):
    r = pick('Task', key)
    if not r: return
    print(json.dumps(r, ensure_ascii=False, indent=1)[:4000])
    for k in ('startNpc', 'endNpc'):
        n = by_id('Npc').get(r.get(k))
        if n: print('%s：%s(%d) @ %s' % (k, nm(n), n['ID'], pos(n.get('map'), n.get('x'), n.get('y'))))

# 解任務步驟分類（單人逃跑風格用）：戰鬥步 = 該步 endScript 的 NpcScript func 為 taskBattle / fightBattle，或 Task.type == 4（BATTLE）。
# 2024 龍的巢穴資料是 taskBattle 但實際沒打，所以語意是「可能戰鬥」，一律當戰鬥處理。type == 2（MONSTER）= 打怪步（不能逃，需人工規劃）。
BATTLE_FUNCS = ('taskBattle', 'fightBattle')

def classify_step(t):
    """一個 Task 列 → (類別 'talk'|'battle'|'monster', 依據文字)"""
    sc = by_id('NpcScript').get(t.get('endScript'))
    func = ((sc or {}).get('script') or {}).get('func')
    ty = t.get('type')
    if ty == 2:
        return 'monster', 'type=2(MONSTER)' + (' condition=%s' % json.dumps(t.get('condition'), ensure_ascii=False) if t.get('condition') else '')
    if func in BATTLE_FUNCS:
        return 'battle', 'func=%s group=%s' % (func, sc['script'].get('group')) + (' type=4' if ty == 4 else '')
    if ty == 4:
        return 'battle', 'type=4(BATTLE)'
    return 'talk', 'func=%s type=%s' % (func, ty)

def task_steps(key):
    """任務組 ID 或任務名 → (group, [Task 列依 step 排序])；名稱不唯一時回傳第一組，其他組放第三個值"""
    rows = T('Task')
    if re.fullmatch(r'\d+', key) and any(r.get('group') == int(key) for r in rows):
        g = int(key); others = []
    else:
        rs = resolve('Task', key)
        if not rs: return None, [], []
        gs = []
        for r in rs:
            if r['group'] not in gs: gs.append(r['group'])
        g, others = gs[0], gs[1:]
    return g, sorted((r for r in rows if r.get('group') == g), key=lambda r: r.get('step', 0)), others

def cmd_steps(key):
    g, ts, others = task_steps(key)
    if not ts: print('找不到：%s' % key); return
    print('任務組 %s：%s（%d 步）' % (g, nm(ts[0]), len(ts)))
    if others: print('其他同名組：%s' % '、'.join(map(str, others[:10])))
    kind = {'talk': '對話', 'battle': '戰鬥', 'monster': '打怪(人工)'}
    for t in ts:
        c, why = classify_step(t)
        n = by_id('Npc').get(t.get('endNpc'))
        where = '%s(%s) @ %s' % (nm(n), n['ID'], pos(n.get('map'), n.get('x'), n.get('y'))) if n else '（無 endNpc）'
        extra = ''
        if t.get('startNpc'):
            sn = by_id('Npc').get(t['startNpc'])
            if sn: extra = '；接任務 %s(%s) @ %s' % (nm(sn), sn['ID'], pos(sn.get('map'), sn.get('x'), sn.get('y')))
        note = ' ※類型%s非一般對話，需人工確認' % t.get('type') if c == 'talk' and t.get('type') not in (1, None) else ''
        print('%s 步 %d [%s] %s  | %s | %s%s%s' % (t.get('step'), t['ID'], kind[c], where, why, clean(t.get('explandTn') or t.get('explandCn')), extra, note))

def cmd_raw(table, key):
    r = by_id(table).get(int(key) if key.lstrip('-').isdigit() else key)
    print(json.dumps(r, ensure_ascii=False, indent=1) if r else '找不到')

# ---------------- 地圖格子 / 路線 ----------------
_MAPS = None
def load_maps():
    global _MAPS
    if _MAPS is None:
        _MAPS = {}
        b = open(os.path.join(DATA, 'maps.bin'), 'rb').read()
        assert b[:7] == b'PSAMAP1'
        n, = struct.unpack_from('<i', b, 7); p = 11
        for _ in range(n):
            mid, w, h, ln = struct.unpack_from('<iHHi', b, p); p += 12
            _MAPS[mid] = (w, h, b[p:p + ln]); p += ln
    return _MAPS

_GRID = {}
def grid(mid):
    if mid not in _GRID:
        m = load_maps().get(mid)
        _GRID[mid] = (m[0], m[1], zlib.decompress(m[2], -15)) if m else None
    return _GRID[mid]

def map_id(key):
    if key.isdigit(): return int(key)
    rs = resolve('MapName', key)
    if not rs: raise SystemExit('找不到地圖：' + key)
    if len(rs) > 1: print('地圖「%s」符合 %d 筆，用 %s(%s)' % (key, len(rs), nm(rs[0]), rs[0]['ID']))
    return rs[0]['ID']

def bfs(mid, sx, sy, goals, near=1):
    """在地圖 mid 從 (sx,sy) 8 方向 BFS，走到任一 goal 的 near 格內；回傳 {goal: 步數}"""
    g = grid(mid)
    if not g: return {}
    w, h, c = g
    # 目標周圍 near 格內的格子 → 目標清單
    hit = collections.defaultdict(list)
    for gx, gy in goals:
        for yy in range(gy - near, gy + near + 1):
            for xx in range(gx - near, gx + near + 1):
                if 0 <= xx < w and 0 <= yy < h: hit[yy * w + xx].append((gx, gy))
    found = {}; need = len(set(goals))
    if not (0 <= sx < w and 0 <= sy < h): return found
    dist = [-1] * (w * h); s = sy * w + sx; dist[s] = 0
    q = collections.deque([s])
    nb = (-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1)
    while q and len(found) < need:
        p = q.popleft(); d = dist[p]
        if p in hit:
            for gg in hit[p]:
                if gg not in found: found[gg] = d
        x = p % w
        for o in nb:
            n = p + o
            if n < 0 or n >= w * h or dist[n] >= 0 or c[n] != 1: continue
            if abs(n % w - x) > 1: continue          # 換行邊界
            dist[n] = d + 1; q.append(n)
    return found

def cmd_route(args):
    if len(args) < 4: raise SystemExit('用法：route <起點地圖> <x> <y> <終點地圖> [x y]')
    sm, sx, sy, tm = map_id(args[0]), int(args[1]), int(args[2]), map_id(args[3])
    tx, ty = (int(args[4]), int(args[5])) if len(args) >= 6 else (None, None)
    exits = collections.defaultdict(list)
    for w in T('MapWarp'):
        if not w.get('isNotUse'): exits[w['fMap']].append((w['fX'], w['fY'], w['tMap'], w['tX'], w['tY']))
    # 先做地圖層級連通檢查（不看地圖內能不能走到出口），不相連就不必在格子上搜尋
    seen = {sm}; q = collections.deque([sm])
    while q:
        m = q.popleft()
        for e in exits.get(m, []):
            if e[2] not in seen: seen.add(e[2]); q.append(e[2])
    if tm not in seen:
        print('地圖出口無法從 %s 通到 %s（可能需要搭船 / 城鎮傳送 / 付費傳送 / 交通 NPC，見 knowledge/world/transport.md）' % (map_name(sm), map_name(tm)))
        return
    WARP = 8
    start = (sm, sx, sy)
    best = {start: 0}; prev = {}; pq = [(0, start)]; done = None
    while pq:
        d, node = heapq.heappop(pq)
        if d > best.get(node, 1e18): continue
        m, x, y = node
        if m == tm:
            if tx is None: done = node; break
            r = bfs(m, x, y, [(tx, ty)], near=1)
            if r:
                fin = ('END', tx, ty); nd = d + r[(tx, ty)]
                if nd < best.get(fin, 1e18): best[fin] = nd; prev[fin] = (node, None); heapq.heappush(pq, (nd, fin))
        if m == 'END': done = node; break
        ex = exits.get(m, [])
        if not ex: continue
        reach = bfs(m, x, y, [(e[0], e[1]) for e in ex], near=1)
        for e in ex:
            if (e[0], e[1]) not in reach: continue
            nxt = (e[2], e[3], e[4]); nd = d + reach[(e[0], e[1])] + WARP
            if nd < best.get(nxt, 1e18):
                best[nxt] = nd; prev[nxt] = (node, e); heapq.heappush(pq, (nd, nxt))
    if not done: print('找不到路線（可能需要搭船 / 傳送服務 / 交通 NPC，見 knowledge/world/transport.md）'); return
    steps = []; n = done
    while n in prev:
        p, e = prev[n]; steps.append((p, e, n)); n = p
    steps.reverse()
    print('路線：%s → %s（約 %d 步，含每次傳送成本 %d）' % (pos(sm, sx, sy), pos(tm, tx, ty) if tx is not None else map_name(tm), best[done], WARP))
    for i, (p, e, n) in enumerate(steps, 1):
        if e: print('%2d. 在 %s 走到出口 (%d,%d) → 到 %s' % (i, map_name(p[0]), e[0], e[1], pos(e[2], e[3], e[4])))
        else: print('%2d. 在 %s 走到 (%d,%d)' % (i, map_name(p[0]), n[1], n[2]))

def cmd_grid(args):
    mid, x, y = map_id(args[0]), int(args[1]), int(args[2])
    r = int(args[3]) if len(args) > 3 else 15
    g = grid(mid)
    if not g: print('沒有地圖資料：%s' % mid); return
    w, h, c = g
    marks = {}
    for n in T('Npc'):
        if n.get('map') == mid: marks[(n.get('x'), n.get('y'))] = 'N'
    for e in T('MapWarp'):
        if e.get('fMap') == mid and not e.get('isNotUse'): marks[(e['fX'], e['fY'])] = 'W'
    marks[(x, y)] = '@'
    print('%s (%d) 大小 %dx%d，中心 (%d,%d)；列 = y，欄 = x' % (map_name(mid), mid, w, h, x, y))
    head = [' '] * (2 * r + 8)
    for k, xx in enumerate(range(x - r, x + r + 1)):
        if xx % 10 == 0 and xx >= 0:
            for i, ch in enumerate(str(xx)):
                if k + i < len(head): head[k + i] = ch
    print('  x→  ' + ''.join(head).rstrip())
    for yy in range(y - r, y + r + 1):
        line = ''
        for xx in range(x - r, x + r + 1):
            if (xx, yy) in marks: line += marks[(xx, yy)]
            elif 0 <= xx < w and 0 <= yy < h: line += ' .~#'[c[yy * w + xx]]
            else: line += '?'
        print('%5d %s' % (yy, line))
    print('圖例：. 可走  ~ 水/懸崖  # 障礙  (空白) 無地面  ? 超出地圖  @ 中心  N NPC  W 出口')

def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    a = sys.argv[1:]
    if not a: print(__doc__); return
    c, rest = a[0], a[1:]
    key = ' '.join(rest)
    if c == 'find': cmd_find(key)
    elif c == 'item': cmd_item(key)
    elif c == 'pet': cmd_pet(key)
    elif c == 'npc': cmd_npc(key)
    elif c == 'map': cmd_map(key)
    elif c == 'skill': cmd_skill(key)
    elif c == 'task': cmd_task(key)
    elif c == 'steps': cmd_steps(key)
    elif c == 'route': cmd_route(rest)
    elif c == 'grid': cmd_grid(rest)
    elif c == 'petimg':
        sys.path.insert(0, os.path.join(ROOT, 'tools', 'extract'))
        import pet_images; pet_images.print_find(key)
    elif c == 'raw': cmd_raw(rest[0], rest[1])
    else: print(__doc__)

if __name__ == '__main__':
    main()
