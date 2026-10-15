#!/usr/bin/env python3
"""OCR 離線回歸（不碰遊戲）：用 tools/.cache 的 960×508 截圖當樣本，對每種讀法跑 ocr.ps1 -Image，印命中率表格。
樣本集：tools/gui/fixtures/ocr_samples.json（截圖不進 git；缺圖的樣本跳過並列出）。
另外兩個子功能（純 Python、不跑 OCR）：
  --pixels         任務詳情狀態條 / 下方按鈕的像素判（questflow1920.classify_status、q1920.classify_go_button）對照表
  --make-fixture   把上面用到的像素抽成 fixtures/qdetail_px.json（給 test_ocrbench.py 離線測試；截圖不進 git）
用法（專案根目錄）：
  uv run --no-project python tools/gui/ocrbench.py                 # OCR 讀法命中率表（Windows 原生自動走常駐 server，較快）
  uv run --no-project python tools/gui/ocrbench.py --pixels
  uv run --no-project python tools/gui/ocrbench.py --cache D:/AI/tools/.cache   # 截圖在別的資料夾（例：worktree）
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import pngread  # noqa: E402

SAMPLES = HERE / 'fixtures' / 'ocr_samples.json'
QDETAIL = HERE / 'fixtures' / 'qdetail_px.json'
CACHE = HERE.parent / '.cache'

# 任務詳情像素樣本（全部 960×508；列名 y = 162 + 50k；None = 該列不測）。答案是人工看圖標的。
ROW_YS = [162 + 50 * k for k in range(6)]
QDETAIL_SAMPLES = {
    'detail_main.png': {'rows': ['progress', 'pending', 'pending', 'pending', 'done', 'done'], 'button': 'reset'},
    'detail_side.png': {'rows': ['progress', 'pending', 'pending', 'pending', 'pending', 'pending'], 'button': 'reset'},
    'qd1.png': {'rows': ['pending', 'pending', 'pending', 'done', 'done', 'done'], 'button': 'transfer'},
    'qd2.png': {'rows': ['pending'] * 6, 'button': 'transfer'},
    'fail/20261015-110133-questflow-45ddb17c.png': {'rows': ['pending'] * 6, 'button': 'transfer'},
    # 「你是否願意花費 50000 重置此任務？」提示窗壓暗整個任務詳情 → 全部不判
    'fail/20261015-103618-questflow-8a9b5279.png': {'rows': ['dim'] * 6, 'button': None},
    # 地圖畫面（河是藍色）→ 按鈕不判
    'fail/20261015-103949-fullrun-d38b5b8c.png': {'rows': ['dim'] * 6, 'button': None},
}


# ---- OCR 讀法比對 ----
STATUS_KEYS = {'進行中': ('進行', '行中'), '待接取': ('待接', '接取'), '已完成': ('已完', '完成')}


def judge(match: str, expect: str, text: str) -> str:
    """→ 'hit'（讀對）/ 'wrong'（讀成別的類別：最危險）/ 'miss'（讀不到 / 不完整）"""
    import q1920
    if match == 'status':
        got = [k for k, keys in STATUS_KEYS.items() if any(x in text for x in keys)]
        return 'hit' if got == [expect] else ('wrong' if any(k != expect for k in got) else 'miss')
    if match == 'button':
        go, reset = q1920.is_go_text(text), q1920.is_reset_text(text)
        if expect == '傳送':
            return 'hit' if go else ('wrong' if reset else 'miss')
        return 'wrong' if go else ('hit' if reset else 'miss')
    return 'hit' if expect in text.replace('|', '') else 'miss'


def ocr_image(img: Path, box, opts) -> str:
    import winenv
    r = winenv.run_ps('ocr.ps1', *map(str, box), *map(str, opts), '-Image', winenv.to_windows(img), timeout=60)
    try:
        d = json.loads((r.stdout.strip().splitlines() or [''])[-1])
    except json.JSONDecodeError:
        return ''
    return ''.join(ln['text'] for ln in d.get('lines', [])) if d.get('ok') else ''


def width(s: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def pad(s: str, n: int) -> str:
    return s + ' ' * max(0, n - width(s))


def bench(cache: Path, verbose: bool) -> int:
    import winenv
    os.environ.setdefault('PSA_GUI_SERVER', '1')   # 只跑 ocr.ps1 -Image（不碰遊戲）；常駐 server 省掉每次啟動 powershell
    winenv.enable_server()
    spec = json.loads(SAMPLES.read_text(encoding='utf-8'))
    rows, missing = [], set()
    for grp in spec['groups']:
        samples = [s for s in grp['samples'] if (cache / s['img']).exists()]
        missing |= {s['img'] for s in grp['samples'] if not (cache / s['img']).exists()}
        for name in grp['readers']:
            cnt = {'hit': 0, 'wrong': 0, 'miss': 0}
            for s in samples:
                text = '|'.join(ocr_image(cache / s['img'], s['box'], o) for o in spec['readers'][name])
                j = judge(grp['match'], s['expect'], text)
                cnt[j] += 1
                if verbose:
                    print(f'  {grp["kind"]} {name} {s["img"]} {s["box"]} 期望 {s["expect"]} → {text!r} {j}')
            rows.append((grp['kind'], name + ('（現行）' if name == grp['baseline'] else ''), len(samples), cnt))
    w1 = max(width(r[0]) for r in rows) + 2
    w2 = max(width(r[1]) for r in rows) + 2
    print(f'| {pad("項目", w1)}| {pad("讀法", w2)}| 樣本 | 命中 | 誤判 | 讀不到 | 命中率 |')
    print(f'|{"-" * (w1 + 1)}|{"-" * (w2 + 1)}|------|------|------|--------|--------|')
    for kind, name, n, c in rows:
        rate = f'{c["hit"] * 100 // n}%' if n else '-'
        print(f'| {pad(kind, w1)}| {pad(name, w2)}| {n:>4} | {c["hit"]:>4} | {c["wrong"]:>4} | {c["miss"]:>6} | {rate:>6} |')
    if missing:
        print('缺圖跳過：' + '、'.join(sorted(missing)))
    return 0


# ---- 像素判 ----
def qdetail_points() -> list:
    import q1920
    import questflow1920 as qf
    pts = [p for y in ROW_YS for p in qf.status_pts(y)]
    return pts + q1920.GO_BTN_PTS + q1920.GO_PANEL_PTS


def classify_all(cols: list) -> tuple:
    """qdetail_points() 的顏色 → ([6 列狀態], 按鈕)"""
    import q1920
    import questflow1920 as qf
    n = len(qf.status_pts(0))
    rows = [qf.classify_status(cols[k * n:(k + 1) * n]) for k in range(len(ROW_YS))]
    return rows, q1920.classify_go_button(cols[len(ROW_YS) * n:])


def grab(img: Path, pts) -> list:
    w, h, bpp, rows = pngread.decode(img.read_bytes())
    if (w, h) != (960, 508):
        raise ValueError(f'{img} 不是 960×508（{w}×{h}）')
    return [tuple(rows[y][x * bpp:x * bpp + 3]) for x, y in pts]


def pixels(cache: Path) -> int:
    pts, bad = qdetail_points(), 0
    print('| 截圖 | 6 列狀態（像素判） | 期望 | 按鈕 | 期望 | 結果 |')
    print('|---|---|---|---|---|---|')
    for name, want in QDETAIL_SAMPLES.items():
        if not (cache / name).exists():
            print(f'| {name} | 缺圖跳過 | | | | |')
            continue
        st, btn = classify_all(grab(cache / name, pts))
        ok = st == want['rows'] and btn == want['button']
        bad += not ok
        print(f'| {name} | {",".join(map(str, st))} | {",".join(want["rows"])} | {btn} | {want["button"]} | {"對" if ok else "錯"} |')
    return 1 if bad else 0


def make_fixture(cache: Path) -> int:
    pts = qdetail_points()
    out = {'note': 'ocrbench --make-fixture 產生：任務詳情 6 列狀態條 + 下方按鈕 + 兩側面板的像素（960×508 截圖座標，'
                   '順序 = ocrbench.qdetail_points()，每點 6 個十六進位字元 RRGGBB）。答案見 ocrbench.QDETAIL_SAMPLES。',
           'n_points': len(pts), 'samples': {}}
    for name, want in QDETAIL_SAMPLES.items():
        if not (cache / name).exists():
            print('缺圖跳過', name)
            continue
        cols = grab(cache / name, pts)
        out['samples'][name] = {'want': want, 'px': ''.join(f'{r:02x}{g:02x}{b:02x}' for r, g, b in cols)}
    QDETAIL.write_text(json.dumps(out, ensure_ascii=False) + '\n', encoding='utf-8')
    print('寫入', QDETAIL, len(out['samples']), '張')
    return 0


def load_fixture() -> dict:
    """fixtures/qdetail_px.json → {截圖名: (want, [(r,g,b), ...])}"""
    d = json.loads(QDETAIL.read_text(encoding='utf-8'))
    res = {}
    for name, s in d['samples'].items():
        h = s['px']
        res[name] = (s['want'], [tuple(int(h[i + k:i + k + 2], 16) for k in (0, 2, 4)) for i in range(0, len(h), 6)])
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cache', type=Path, default=CACHE, help='截圖資料夾（預設 tools/.cache）')
    ap.add_argument('--pixels', action='store_true', help='任務詳情像素判對照表（不跑 OCR）')
    ap.add_argument('--make-fixture', action='store_true', help='抽像素存 fixtures/qdetail_px.json')
    ap.add_argument('-v', '--verbose', action='store_true', help='逐筆印 OCR 結果')
    a = ap.parse_args()
    if a.make_fixture:
        return make_fixture(a.cache)
    if a.pixels:
        return pixels(a.cache)
    return bench(a.cache, a.verbose)


if __name__ == '__main__':
    sys.exit(main())
