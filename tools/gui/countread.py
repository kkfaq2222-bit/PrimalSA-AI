#!/usr/bin/env python3
"""道具格右下角「數量」字形比對（1920×1017；只用標準函式庫；唯讀：只截圖）。

背景（使用者 2026-10-16：讀取能力要好，倉庫有 50~80 個卻讀不到 / 讀錯就會亂買）：
Windows OCR 讀格子數量很不穩（倉庫最下排「60」「8」「4」完全讀不到），
但 digitmatch.ps1 -Boxes 用原解析度二值化後字形非常清楚 → 改用字形樣板比對。
背包格的字比倉庫格大（字高約 21 vs 17 px），所以每個字先裁到外框、再縮放到固定大小比 IoU。

讀法：read_counts(slots, scale) → 每格 int / None（空格）/ '?'（有字但認不出來，呼叫端一律當「不確定」）。
樣板：tools/gui/count-tpl.json（learn 由已知數量的樣本建立）。
用法（專案根目錄）：
  uv run --no-project python tools/gui/countread.py learn      用 tools/.cache/depot-count-samples.json 的已知樣本建樣板
  uv run --no-project python tools/gui/countread.py selftest   每個樣本拿掉自己後用其他樣本讀讀看（留一法），印對錯
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'tools' / '.cache'
TPL = Path(__file__).resolve().parent / 'count-tpl.json'     # 樣板放進 repo（.cache 不進 git）
SAMPLES = CACHE / 'depot-count-samples.json'
GW, GH = 12, 16          # 字縮放後的大小
HIT_MIN = 0.72           # IoU 門檻
MARGIN = 0.06            # 第一名要贏第二名多少（不同數字），不然算認不出來
MIN_PX = 12              # 少於這麼多點的直欄塊當雜訊（圖示邊緣的亮點）


def glyphs(rows: list[str]) -> list[list[str]]:
    """二值化列 → 依直欄投影切成一個個字（由左到右），每個字裁到外框。
    只取最下面那一段連續有字的列（數量字在格子右下；上方圖示的亮點會被排除）。"""
    rows = [r for r in rows if r]
    if not rows:
        return []
    h, w = len(rows), len(rows[0])
    on = [k for k in range(h) if '1' in rows[k]]
    if not on:
        return []
    # 由下往上找最後一段連續有字的列（容許中間 1 列空白）
    bot = on[-1]
    top = bot
    while top - 1 >= 0 and ('1' in rows[top - 1] or (top - 2 >= 0 and '1' in rows[top - 2])):
        top -= 1
    band = rows[top:bot + 1]
    cols = [any(r[x] == '1' for r in band) for x in range(w)]
    out, x = [], 0
    while x < w:
        if not cols[x]:
            x += 1
            continue
        x0 = x
        while x < w and cols[x]:
            x += 1
        g = [r[x0:x] for r in band]
        ys = [k for k, r in enumerate(g) if '1' in r]
        g = g[ys[0]:ys[-1] + 1]
        if sum(r.count('1') for r in g) >= MIN_PX and len(g) >= 8:
            out.append(g)
    return out


def norm(g: list[str]) -> str:
    """字 → GW×GH 的 0/1 字串（最近鄰縮放）"""
    h, w = len(g), len(g[0])
    return ''.join(g[min(h - 1, y * h // GH)][min(w - 1, x * w // GW)] for y in range(GH) for x in range(GW))


def iou(a: str, b: str) -> float:
    i = sum(1 for p, q in zip(a, b) if p == '1' and q == '1')
    u = sum(1 for p, q in zip(a, b) if p == '1' or q == '1')
    return i / u if u else 0.0


def match(g: list[str], tpl: dict):
    """一個字 → (數字字元 or None, 最佳 IoU)"""
    v = norm(g)
    best = {}
    for d, vs in tpl.items():
        best[d] = max(iou(v, t) for t in vs)
    rank = sorted(best.items(), key=lambda kv: -kv[1])
    if not rank or rank[0][1] < HIT_MIN:
        return None, rank[0][1] if rank else 0.0
    if len(rank) > 1 and rank[0][1] - rank[1][1] < MARGIN:
        return None, rank[0][1]
    return rank[0][0], rank[0][1]


def read_rows(rows: list[str], tpl: dict):
    """一格的二值化列 → int / None（空格）/ '?'（認不出來）"""
    gs = glyphs(rows)
    if not gs:
        return None
    ds = [match(g, tpl)[0] for g in gs]
    if any(d is None for d in ds) or len(ds) > 3:
        return '?'
    return int(''.join(ds))


def load_tpl() -> dict:
    try:
        return json.loads(TPL.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def labeled_samples() -> list[tuple[str, int]]:
    """depot-count-samples.json → [(rows 字串, 已知數量)]"""
    out = []
    for o in json.loads(SAMPLES.read_text(encoding='utf-8')):
        if o.get('label') is not None and o.get('rows'):
            out.append((o['rows'], o['label']))
        elif o.get('expect_merged') is not None and o.get('rows_all'):
            out.append((o['rows_all'][0], o['expect_merged']))
    return out


def build(samples) -> dict:
    tpl = {}
    for rows, lab in samples:
        gs = glyphs(rows.split(','))
        if len(gs) != len(str(lab)):
            continue                       # 切字數對不上就不學（避免學到錯的字）
        for g, d in zip(gs, str(lab)):
            v = norm(g)
            if v not in tpl.setdefault(d, []):
                tpl[d].append(v)
    return tpl


def capture(slots, w=64, h=60):
    """slots = 截圖座標的格子中心；一次 digitmatch.ps1 -Boxes 截完全部格子的數量角 → [rows]"""
    import winenv
    bx = ';'.join(f'{2 * x - 4},{2 * y},{w},{h},1' for x, y in slots)
    d = json.loads(winenv.run_ps('digitmatch.ps1', '-Boxes', bx).stdout.strip().splitlines()[-1])
    return [d['fields'][f'b{i}'].split(',') for i in range(len(slots))]


def read_counts(slots, tpl: dict | None = None) -> list:
    tpl = tpl or load_tpl()
    return [read_rows(r, tpl) for r in capture(slots)]


def main(argv=None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not a or a[0] not in ('learn', 'selftest'):
        print(__doc__)
        return 2
    smp = labeled_samples()
    if a[0] == 'learn':
        tpl = build(smp)
        TPL.write_text(json.dumps(tpl), encoding='utf-8')
        print('學到的數字：' + '、'.join(f'{d}×{len(v)}' for d, v in sorted(tpl.items())))
        return 0
    bad = 0
    for k, (rows, lab) in enumerate(smp):
        tpl = build(smp[:k] + smp[k + 1:])
        got = read_rows(rows.split(','), tpl)
        ok = got == lab
        bad += not ok
        print(('OK  ' if ok else ('??  ' if got == '?' else 'BAD ')) + f'{lab} → {got}')
    print(f'{len(smp) - bad}/{len(smp)} 正確（? = 認不出來，算安全；BAD = 讀錯，不能有）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
