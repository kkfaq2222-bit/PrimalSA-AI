#!/usr/bin/env python3
"""任務追蹤列表標題「圖片樣板比對」（只用標準函式庫；本機運算，不上傳）。取代 quest.py 的 OCR（一輪 20～30 秒）→ 一輪約 0.3 秒。

原理：titlematch.ps1 背景截圖 → 縮成 1/2 → 取列表區黑字（max(R,G,B)<140）→ 對 tools/.cache/task-titles/<任務名>@<n>.png
樣板各做「黑字 IoU」滑動比對（垂直 / 水平任意位置，所以格子在列表第幾格都行）。同一個標題字型固定，同一任務重抓分數 ≈ 1.0；
不同標題實測 <= 0.4。判定很保守：分數 >= HIT_MIN，且同一列沒有別的任務名的樣板分數差在 MARGIN 內才算（寧可回 None 退回 OCR）。

用法（專案根目錄）：
  uv run --no-project python tools/gui/titlematch.py match              # 即時截圖，列出看得到的樣板任務與位置、耗時
  uv run --no-project python tools/gui/titlematch.py find 伐木證書       # 這個任務在不在、y 多少（None = 沒有可靠命中）
  uv run --no-project python tools/gui/titlematch.py add 伐木證書 310    # 手動建樣板：任務名 + 標題中心 y（截圖座標）；加 --image 檔.png 可從截圖檔建
  uv run --no-project python tools/gui/titlematch.py list               # 現有樣板
程式用：import titlematch → titlematch.find(want) / titlematch.learn(name, y) / titlematch.has_templates(name)。
樣板自動累積：quest.py 的 OCR 認出目標任務那一格時呼叫 learn()，下次就不用 OCR。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import winenv
from walk import ROOT

TPL_DIR = ROOT / 'tools' / '.cache' / 'task-titles'
HIT_MIN = 0.85          # 命中門檻（IoU；同標題實測 >= 0.95，不同標題 <= 0.4）
MARGIN = 0.25           # 同一列有別的任務名樣板的分數也高時，最佳要領先至少這麼多，否則視為不確定
MAX_PER_NAME = 6        # 每個任務最多留幾個樣板（選中 / 未選中底色等變體）
ROW_DY = 10             # 同一列的判定：標題中心 y 差小於這個


def norm(t: str) -> str:
    """樣板用的任務名鍵：去空白、全形括號轉半形、去掉不能當檔名的字元；保留括號內容（「漆黑洞窟(一轉)」與「(二轉)」要分開）。
    樣板是圖片，不像 OCR 會把括號讀壞，所以不用 quest.py norm() 那種砍掉括號字尾的作法。"""
    t = t.replace('（', '(').replace('）', ')')
    return re.sub(r'[\s\\/:*?"<>|@]', '', t)


def base(name: str) -> str:
    return name.split('@')[0]


def templates() -> list[Path]:
    return sorted(p for p in TPL_DIR.glob('*.png') if not p.name.startswith('_')) if TPL_DIR.is_dir() else []


def has_templates(name: str) -> bool:
    n = norm(name)
    return any(base(p.stem) == n for p in templates())


def _run(*args) -> dict:
    r = winenv.run_ps('titlematch.ps1', *[str(a) for a in args])
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'ok': False, 'error': (r.stderr or r.stdout)[:200]}


def match_all(image: Path | str | None = None, thr: float = 0.5) -> dict:
    """所有樣板的最佳位置 → {'ok','ms','hits':[{name,x,y,score,second}]}；沒有樣板資料夾 / 沒有樣板回空 hits（不呼叫 PowerShell）"""
    if not templates():
        return {'ok': True, 'ms': 0, 'hits': []}
    args = ['-Mode', 'match', '-Dir', winenv.to_windows(TPL_DIR), '-Thr', thr]
    if image:
        args += ['-Image', winenv.to_windows(Path(image).resolve())]
    return _run(*args)


def cards(res: dict) -> list[dict]:
    """把 match_all 的結果整理成「畫面上看得到的任務」：每列（y 相近）取分數最高的樣板；
    回 [{task, y, score, ambiguous}]（依 y 排序）。ambiguous = 同一列有別的任務名分數差 < MARGIN，或分數 < HIT_MIN"""
    hits = sorted((h for h in res.get('hits', []) if h['score'] >= 0.5), key=lambda h: -h['score'])
    rows: list[dict] = []
    for h in hits:
        for row in rows:
            if abs(row['y'] - h['y']) < ROW_DY:
                if base(h['name']) != row['task'] and row['score'] - h['score'] < MARGIN:
                    row['ambiguous'] = True
                break
        else:
            rows.append({'task': base(h['name']), 'y': h['y'], 'score': h['score'], 'ambiguous': h['score'] < HIT_MIN})
    return sorted(rows, key=lambda r: r['y'])


def find(want: str, image: Path | str | None = None) -> int | None:
    """目前畫面追蹤列表上，任務 want 的標題中心 y（截圖座標）；沒有可靠命中回 None（呼叫端退回 OCR）"""
    n = norm(want)
    if not has_templates(n):
        return None
    for c in cards(match_all(image)):
        if c['task'] == n and not c['ambiguous']:
            return c['y']
    return None


def learn(name: str, y: int, image: Path | str | None = None) -> Path | None:
    """把目前畫面 y 那一格的標題存成樣板 <名>@<n>.png（OCR 認出該格時呼叫）；已有分數 >= 0.97 的同名樣板就不重複存。回新檔路徑或 None"""
    n = norm(name)
    if not n:
        return None
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    mine = [p for p in templates() if base(p.stem) == n]
    if len(mine) >= MAX_PER_NAME:
        return None
    tmp = TPL_DIR / '_new.png'
    args = ['-Mode', 'add', '-Y', int(y), '-Out', winenv.to_windows(tmp)]
    if image:
        args += ['-Image', winenv.to_windows(Path(image).resolve())]
    r = _run(*args)
    if not r.get('ok') or not tmp.exists():
        return None
    try:
        if not (14 <= r['h'] <= 28 and 24 <= r["w"] <= 170):       # 形狀不像單行標題（抓到框線 / 兩行）→ 丟掉
            return None
        # 重複判斷：同名樣板在同一張圖上是否已能以 >= 0.97 命中這一格
        res = match_all(image, 0.97)
        for h in res.get('hits', []):
            if base(h['name']) == n and abs(h['y'] - y) < ROW_DY:
                return None
        k = 1
        while (TPL_DIR / f'{n}@{k}.png').exists():
            k += 1
        dst = TPL_DIR / f'{n}@{k}.png'
        tmp.replace(dst)
        return dst
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('match'); p.add_argument('--image'); p.add_argument('--thr', type=float, default=0.5)
    p = sub.add_parser('find'); p.add_argument('name'); p.add_argument('--image')
    p = sub.add_parser('add'); p.add_argument('name'); p.add_argument('y', type=int); p.add_argument('--image')
    sub.add_parser('list')
    a = ap.parse_args()
    if a.cmd == 'list':
        for t in templates():
            print(t.stem)
        return 0
    if a.cmd == 'match':
        t0 = time.time()
        res = match_all(a.image, a.thr)
        print(f'耗時 {time.time() - t0:.2f}s（腳本內 {res.get("ms")}ms）ok={res.get("ok")} {res.get("error", "")}')
        for h in res.get('hits', []):
            print(f'  {h["name"]:<16} y={h["y"]:<4} x={h["x"]:<4} score={h["score"]:.3f} second={h["second"]:.3f}')
        for c in cards(res):
            print('  →', c)
        return 0
    if a.cmd == 'find':
        t0 = time.time()
        y = find(a.name, a.image)
        print(f'{a.name}: y={y}（{time.time() - t0:.2f}s）')
        return 0 if y is not None else 1
    if a.cmd == 'add':
        d = learn(a.name, a.y, a.image)
        print(f'新增樣板 {d}' if d else '沒有新增（已有相同樣板 / 已達上限 / 形狀不像標題 / 截圖失敗）')
        return 0 if d else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
