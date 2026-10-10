#!/usr/bin/env python3
"""HUD 數值「字元樣板比對」原型（只用標準函式庫；唯讀：只截圖 / 讀像素）。試做品，尚未取代 stat.ps1。

原理：digitmatch.ps1 背景截圖 → 各欄位原解析度二值化（0/1 字串列）→ 本檔依直欄投影切字 → 與 tools/.cache/digit-tpl/<版面>.json
的字元樣板做 IoU 比對（±1 px 平移）→ 組成與 stat.ps1 相同欄位的值。任何一個字認不出來 / 兩個候選太接近 → 該欄回 None（呼叫端退回 OCR）。

用法（專案根目錄）：
  uv run --no-project python tools/gui/digitmatch.py read            即時讀一次，印 JSON（含 ms、unsure 欄位）
  uv run --no-project python tools/gui/digitmatch.py learn [N]       用 stat.ps1 的 OCR 當標籤自動建樣板（取樣 N 次，預設 1；前後各截一次確認畫面沒變）
  uv run --no-project python tools/gui/digitmatch.py chars           目前各版面已學到的字元
  uv run --no-project python tools/gui/digitmatch.py bench [N]       digitmatch vs stat.ps1 各跑 N 次（預設 30），報告耗時與一致率；不一致樣本存 tools/.cache/digit-mismatch/
  uv run --no-project python tools/gui/digitmatch.py dump <欄位>      印即時二值化圖
程式用：import digitmatch → digitmatch.read_fields(capture) / digitmatch.capture()
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import winenv
from walk import ROOT

TPL_DIR = ROOT / 'tools' / '.cache' / 'digit-tpl'
MISMATCH_DIR = ROOT / 'tools' / '.cache' / 'digit-mismatch'
CW = 64                 # 字元畫布寬（bit）：字貼在 (PAD, PAD)，上下左右留 PAD 供 ±1 平移
PAD = 2
HIT_MIN = 0.80          # 字元 IoU 門檻
MARGIN = 0.06           # 最佳與「不同字元」次佳至少差這麼多
MAX_VARIANTS = 6        # 每個字元最多留幾個樣板變體
KNOWN_IOU = 0.93        # 補樣板時，字已被既有樣板以此分數以上正確認出就不再存
SAME_IOU = 0.97         # 與既有變體 IoU >= 此值視為重複，不再存
GAP = 30               # 切字後相鄰字元間距超過這麼多 px 視為不同簇（只留最大簇）
FIELDS = ('lv', 'hp', 'mp', 'plv', 'php', 'pos', 'pos2')


# ---------- 切字 ----------
def _rows_to_ints(rows: list[str]) -> list[int]:
    return [int(r[::-1], 2) for r in rows]          # bit i = 第 i 欄


def _components(rows: list[str]) -> list[dict]:
    """8 連通元件 → [{x0,x1,y0,y1,pts}]"""
    h, w = len(rows), len(rows[0])
    seen = [[False] * w for _ in range(h)]
    comps = []
    for y in range(h):
        for x in range(w):
            if rows[y][x] != '1' or seen[y][x]:
                continue
            stack, pts = [(x, y)], []
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and rows[ny][nx] == '1' and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            comps.append({'x0': min(xs), 'x1': max(xs), 'y0': min(ys), 'y1': max(ys), 'pts': pts})
    return comps


def segment(rows: list[str], pos_mode: bool = False) -> list[tuple[int, int, list[str]]]:
    """切字 → [(x0, y0, 字元點陣列字串)]（依 x 排序）。
    連通元件 → 丟掉高 <= 4 px 的細線（血條殘邊）→ x 重疊 >= 4 px 或 >= 60%（較窄者）的元件合併（轉 / 級 / 冒號）→ 丟掉高度 < 最高字 45% 的群
    （座標欄 pos_mode 保留落在數字帶內的小群 : , .）→ 只留最大的一簇（相鄰字距 < GAP；去掉兩端的場景雜訊）。"""
    if not rows:
        return []
    comps = [c for c in _components(rows) if c['y1'] - c['y0'] >= 4]
    comps.sort(key=lambda c: c['x0'])
    merged = []
    for c in comps:
        for m in merged:
            ov = min(m['x1'], c['x1']) - max(m['x0'], c['x0']) + 1
            if ov >= 4 or (ov > 0 and ov >= 0.6 * min(m['x1'] - m['x0'] + 1, c['x1'] - c['x0'] + 1)):
                m['x0'], m['x1'] = min(m['x0'], c['x0']), max(m['x1'], c['x1'])
                m['y0'], m['y1'] = min(m['y0'], c['y0']), max(m['y1'], c['y1'])
                m['pts'] += c['pts']
                break
        else:
            merged.append(dict(c))
    if not merged:
        return []
    merged.sort(key=lambda c: c['x0'])
    mh = max(c['y1'] - c['y0'] + 1 for c in merged)
    tall = [c for c in merged if c['y1'] - c['y0'] + 1 >= 0.8 * mh]
    top, bot = min(c['y0'] for c in tall), max(c['y1'] for c in tall)
    keep = []
    for c in merged:
        gh = c['y1'] - c['y0'] + 1
        if gh >= 0.45 * mh or (pos_mode and c['y0'] >= top - 2 and c['y1'] <= bot + 2 and len(c['pts']) >= 4):
            keep.append(c)
    clusters, cur = [], []
    for c in keep:
        if cur and c['x0'] - cur[-1]['x1'] > GAP:
            clusters.append(cur)
            cur = []
        cur.append(c)
    if cur:
        clusters.append(cur)
    best = max(clusters, key=len) if clusters else []
    out = []
    for c in best:
        grid = [['0'] * (c['x1'] - c['x0'] + 1) for _ in range(c['y1'] - c['y0'] + 1)]
        for px, py in c['pts']:
            grid[py - c['y0']][px - c['x0']] = '1'
        out.append((c['x0'], c['y0'], [''.join(r) for r in grid]))
    return out


def glyph_int(g: list[str]) -> tuple[int, int, int, int]:
    """字元點陣 → (畫布 int, 寬, 高, 墨點數)；畫布以 CW 為列寬，字貼在 (PAD, PAD)"""
    v = 0
    for y, r in enumerate(g):
        for x, c in enumerate(r):
            if c == '1':
                v |= 1 << ((y + PAD) * CW + x + PAD)
    return v, len(g[0]), len(g), v.bit_count()


def iou(a: int, na: int, b: int, nb: int) -> float:
    """a 平移 ±1 後與 b 的最大 IoU"""
    best = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            s = dy * CW + dx
            sa = a << s if s >= 0 else a >> -s
            inter = (sa & b).bit_count()
            if inter:
                best = max(best, inter / (na + nb - inter))
    return best


# ---------- 樣板 ----------
def tpl_path(layout: str) -> Path:
    return TPL_DIR / f'{layout}.json'


def load_tpl(layout: str) -> dict:
    """{字元: [點陣列字串, ...]}"""
    p = tpl_path(layout)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def save_tpl(layout: str, tpl: dict) -> None:
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    p = tpl_path(layout)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(tpl, ensure_ascii=False), encoding='utf-8')
    tmp.replace(p)


class Matcher:
    def __init__(self, tpl: dict):
        self.items = []     # (char, int, w, h, n)
        for ch, vs in tpl.items():
            for g in vs:
                v, w, h, n = glyph_int(g)
                self.items.append((ch, v, w, h, n))

    def classify(self, g: list[str]):
        """→ (字元 or None, 分數, 次佳不同字元分數)"""
        v, w, h, n = glyph_int(g)
        best = {}
        for ch, tv, tw, th, tn in self.items:
            if abs(tw - w) > 3 or abs(th - h) > 3:
                continue
            s = iou(v, n, tv, tn)
            if s > best.get(ch, 0):
                best[ch] = s
        if not best:
            return None, 0.0, 0.0
        rk = sorted(best.items(), key=lambda kv: -kv[1])
        sc = rk[0][1]
        second = rk[1][1] if len(rk) > 1 else 0.0
        if sc < HIT_MIN or sc - second < MARGIN:
            return None, sc, second
        return rk[0][0], sc, second


# ---------- 欄位解析 ----------
def read_text(matcher: Matcher, rows: list[str], pos_mode: bool = False) -> str | None:
    """整欄 → 字元串；有任何字認不出來回 None；整欄沒墨回 ''"""
    s = ''
    for _, _, g in segment(rows, pos_mode):
        ch, _, _ = matcher.classify(g)
        if ch is None:
            return None
        s += ch
    return s


def parse_level(t: str | None) -> str | None:
    if t is None:
        return None
    m = re.search(r'(\d*)轉(\d+)', t)
    return f"{m.group(1) or '0'}轉{m.group(2)}級" if m else None


def parse_num(t: str | None) -> int | None:
    m = re.search(r'\d+', t or '')
    return int(m.group()) if m else None


def parse_pos(t: str | None) -> str | None:
    m = re.search(r'(\d{3,6})[:.](\d+)[,.](\d+)', t or '')
    return f'{m.group(1)}:{m.group(2)},{m.group(3)}' if m else None


_MAPS: dict | None = None


def map_name(pos: str | None) -> str | None:
    """地圖 ID（pos 的冒號前）查 knowledge/data/tables/MapName.jsonl 的 nameTn（同 stat.ps1）；查不到回 ''；pos 為 None 回 None"""
    global _MAPS
    if not pos:
        return None
    if _MAPS is None:
        _MAPS = {}
        try:
            for ln in (ROOT / 'knowledge' / 'data' / 'tables' / 'MapName.jsonl').read_text(encoding='utf-8').splitlines():
                o = json.loads(ln)
                _MAPS[o['ID']] = o.get('nameTn', '')
        except (OSError, ValueError, KeyError):
            pass
    return _MAPS.get(int(pos.split(':')[0]), '')


def read_fields(cap: dict, tpl: dict | None = None) -> dict:
    """capture() 的結果 → 與 stat.ps1 同名欄位的值；認不出來的欄位為 None，並列在 unsure。
    hpPct / mpPct 是 digitmatch.ps1 的血條掃描（-1 → None）；map 由 pos 查表"""
    tpl = tpl if tpl is not None else load_tpl(cap['layout'])
    m = Matcher(tpl)
    f = cap['fields']
    txt = {k: read_text(m, f[k], k.startswith('pos')) for k in FIELDS if k in f}
    pos = parse_pos(txt.get('pos'))
    if pos is None:
        pos = parse_pos(txt.get('pos2'))
    out = {'level': parse_level(txt['lv']), 'hp': parse_num(txt['hp']), 'mp': parse_num(txt['mp']),
           'petLevel': parse_level(txt['plv']), 'petHp': parse_num(txt['php']), 'pos': pos,
           'hpPct': cap.get('hpPct') if cap.get('hpPct', -1) >= 0 else None,
           'mpPct': cap.get('mpPct') if cap.get('mpPct', -1) >= 0 else None}
    out['unsure'] = [k for k, v in out.items() if v is None]
    out['map'] = map_name(pos)
    out['raw'] = txt
    return out


# ---------- 截圖 ----------
def parse_capture(stdout: str) -> dict:
    """digitmatch.ps1 的輸出 → dict（fields 每欄拆成列清單）；失敗回 {'ok': False}。watch.py 用自己的白名單呼叫後交給這裡解析"""
    try:
        cap = json.loads((stdout or '').strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False, 'error': (stdout or '')[:200]}
    if not isinstance(cap, dict):
        return {'ok': False}
    if cap.get('ok'):
        cap['fields'] = {k: v.split(',') for k, v in cap['fields'].items()}     # ps1 為了快，每欄輸出一個逗號分隔字串
    return cap


def capture(image: str | None = None) -> dict:
    args = ['-Image', winenv.to_windows(Path(image).resolve())] if image else []
    r = winenv.run_ps('digitmatch.ps1', *args)
    cap = parse_capture(r.stdout)
    if not cap.get('ok') and not cap.get('error'):
        cap['error'] = (r.stderr or '')[:200]
    return cap


def stat() -> dict:
    r = winenv.run_ps('stat.ps1')
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False}


# ---------- 學習 ----------
def labels_from_stat(st: dict) -> dict:
    """stat.ps1 結果 → {欄位: 標籤字串}（只收看起來合理的）"""
    lab = {}
    for k, key in (('lv', 'level'), ('plv', 'petLevel')):
        v = st.get(key)
        if v and re.fullmatch(r'\d+轉\d+級', v):
            lab[k] = v
    for k, key in (('hp', 'hp'), ('mp', 'mp'), ('php', 'petHp')):
        if st.get(key) is not None:
            lab[k] = str(st[key])
    if st.get('pos') and re.fullmatch(r'\d+:\d+,\d+', st['pos']):
        lab['pos'] = st['pos']
    return lab


FIELD_KEY = {'lv': 'level', 'hp': 'hp', 'mp': 'mp', 'plv': 'petLevel', 'php': 'petHp', 'pos': 'pos'}


def learn_from(cap_a: dict, cap_b: dict, st: dict, tpl: dict, dm: dict | None = None, log=None) -> int:
    """用 stat 的 OCR 當標籤補樣板（就地改 tpl），回新增數。只在安全時採用，否則整欄略過：
      1. 兩次截圖（前後夾著 stat）該欄點陣相同 — 畫面沒在變，標籤才對得上；
      2. 切出的字數 == 標籤字數；
      3. dm（同一張截圖 digitmatch 的讀值）該欄有值就必須與 stat 一致 — 不一致代表其中一邊讀錯，誰都不信；
      4. 每個字若已被既有樣板認出，必須與標籤同字 — 衝突（標籤可能錯）不學；
      5. 已被既有樣板以 KNOWN_IOU 以上正確認出的字不存；每個字元最多 MAX_VARIANTS 個變體，與既有變體 IoU >= SAME_IOU 視為重複。
    情況「dm 與 stat 都有值且一致」與「dm 為 None 而 stat 有值」都走這裡。"""
    log = log or (lambda *_: None)
    added = 0
    m = Matcher(tpl)
    for k, label in labels_from_stat(st).items():
        if cap_a['fields'].get(k) != cap_b['fields'].get(k):
            log(f'  {k}: 前後畫面不同，略過')
            continue
        segs = segment(cap_a['fields'][k], k.startswith('pos'))
        if len(segs) != len(label):
            log(f'  {k}: 切出 {len(segs)} 字、標籤「{label}」{len(label)} 字，略過')
            continue
        if dm is not None and dm.get(FIELD_KEY[k]) is not None and dm[FIELD_KEY[k]] != st.get(FIELD_KEY[k]):
            log(f'  {k}: digitmatch 與 OCR 讀值不同（{dm[FIELD_KEY[k]]} / {st.get(FIELD_KEY[k])}），略過')
            continue
        bad = False
        known = []                 # 已被既有樣板以高分正確認出的字不必再存
        for (_, _, g), ch in zip(segs, label):
            c2, sc, _ = m.classify(g)
            known.append(c2 == ch and sc >= KNOWN_IOU)
            if c2 is not None and c2 != ch:
                log(f'  {k}: 字「{ch}」被既有樣板認成「{c2}」（{sc:.2f}），標籤可能有誤，略過')
                bad = True
                break
        if bad:
            continue
        for (_, _, g), ch, kn in zip(segs, label, known):
            if kn:
                continue
            v, w, h, n = glyph_int(g)
            vs = tpl.setdefault(ch, [])
            if len(vs) < MAX_VARIANTS and not any(iou(v, n, xv, xn) >= SAME_IOU for xv, _, _, xn in map(glyph_int, vs)):
                vs.append(g)
                added += 1
    return added


def learn_once(log=print) -> int:
    """前後各截一次（中間跑 stat），交給 learn_from；回新增的樣板數"""
    a = capture()
    st = stat()
    b = capture()
    if not (a.get('ok') and b.get('ok') and st.get('ok')):
        log('截圖 / stat 失敗')
        return 0
    layout = a['layout']
    tpl = load_tpl(layout)
    added = learn_from(a, b, st, tpl, read_fields(a, tpl), log)
    if added:
        save_tpl(layout, tpl)
    return added


def cmd_learn(n: int) -> None:
    for i in range(n):
        add = learn_once()
        tpl = load_tpl(capture().get('layout', ''))
        print(f'第 {i + 1}/{n} 次：新增 {add}；已有字元 {"".join(sorted(tpl))}')
        if i + 1 < n:
            time.sleep(2)


# ---------- 量測 ----------
def _save_pbm(cap: dict, tag: str) -> None:
    MISMATCH_DIR.mkdir(parents=True, exist_ok=True)
    (MISMATCH_DIR / f'{tag}.json').write_text(json.dumps(cap, ensure_ascii=False), encoding='utf-8')


def cmd_bench(n: int) -> None:
    MISMATCH_DIR.mkdir(parents=True, exist_ok=True)
    keys = [('level', 'level'), ('hp', 'hp'), ('mp', 'mp'), ('petLevel', 'petLevel'), ('petHp', 'petHp'), ('pos', 'pos')]
    stat_ms, dm_ms, agree = [], [], {k: 0 for k, _ in keys}
    unsure = {k: 0 for k, _ in keys}
    mism = []
    cmp_n = {k: 0 for k, _ in keys}
    for i in range(n):
        t = time.time(); cap = capture(); dm = read_fields(cap) if cap.get('ok') else None; t1 = time.time() - t
        t = time.time(); st = stat(); t2 = time.time() - t
        # 再截一次：若與第一次不同（數值在變）這輪不計一致率
        cap2 = capture()
        dm_ms.append(t1 * 1000); stat_ms.append(t2 * 1000)
        if not (dm and st.get('ok') and cap2.get('ok')):
            continue
        stable = {k: cap['fields'][fk] == cap2['fields'][fk] for k, fk in
                  (('level', 'lv'), ('hp', 'hp'), ('mp', 'mp'), ('petLevel', 'plv'), ('petHp', 'php'), ('pos', 'pos'))}
        for k, _ in keys:
            if not stable[k]:
                continue
            if dm[k] is None:
                unsure[k] += 1
                continue
            cmp_n[k] += 1
            if dm[k] == st.get(k):
                agree[k] += 1
            else:
                mism.append((i, k, dm[k], st.get(k)))
                _save_pbm({'cap': cap, 'dm': dm['raw'], 'stat': st}, f'bench{i}_{k}')
        print(f'#{i + 1} dm {t1 * 1000:.0f}ms stat {t2 * 1000:.0f}ms unsure={dm["unsure"]}', flush=True)
    avg = lambda xs: sum(xs) / len(xs) if xs else 0
    print(f'\n平均耗時：digitmatch {avg(dm_ms):.0f} ms（含 PowerShell 進程 / server 呼叫）  stat.ps1 {avg(stat_ms):.0f} ms')
    print(f'{"欄位":<10}{"可比對":>6}{"一致":>6}{"不一致":>6}{"不確定(None)":>14}')
    for k, _ in keys:
        print(f'{k:<10}{cmp_n[k]:>6}{agree[k]:>6}{cmp_n[k] - agree[k]:>6}{unsure[k]:>14}')
    for m in mism:
        print('不一致', m)


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    winenv.enable_server()      # 常駐 PowerShell server：省掉每次啟動 + Add-Type 編譯
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('read'); p.add_argument('--image')
    p = sub.add_parser('learn'); p.add_argument('n', nargs='?', type=int, default=1)
    sub.add_parser('chars')
    p = sub.add_parser('bench'); p.add_argument('n', nargs='?', type=int, default=30)
    p = sub.add_parser('dump'); p.add_argument('field')
    a = ap.parse_args()
    if a.cmd == 'read':
        t = time.time()
        cap = capture(a.image)
        if not cap.get('ok'):
            print(json.dumps(cap, ensure_ascii=False))
            return 1
        res = read_fields(cap)
        res.update(ok=True, ms=int((time.time() - t) * 1000), psMs=cap['ms'])
        print(json.dumps(res, ensure_ascii=False))
    elif a.cmd == 'learn':
        cmd_learn(a.n)
    elif a.cmd == 'chars':
        for p in sorted(TPL_DIR.glob('*.json')):
            tpl = json.loads(p.read_text(encoding='utf-8'))
            print(p.stem, ''.join(sorted(tpl)), {k: len(v) for k, v in sorted(tpl.items())})
    elif a.cmd == 'bench':
        cmd_bench(a.n)
    elif a.cmd == 'dump':
        cap = capture()
        for r in cap['fields'][a.field]:
            print(r.replace('0', '.').replace('1', '#'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
