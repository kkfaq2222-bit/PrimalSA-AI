#!/usr/bin/env python3
"""顯示每日任務讀到的 5 頁與所需材料（給使用者看）。
用法：uv run --no-project python tools/gui/dailyshow.py [--client kkfaq11111] [--role 2]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--role', type=int, default=0)
    a = ap.parse_args()
    tag = f'-r{a.role}' if a.role else ''
    f = ROOT / 'tools' / '.cache' / f'daily-{a.client}{tag}.json'
    if not f.exists():
        print(f'找不到 {f}')
        return 2
    import dailyquest1920 as dq
    pages = json.loads(f.read_text(encoding='utf-8'))['pages']
    plan, stores = dq.build_plan(pages)
    print(f'角色 {a.role or "?"}　{f.name}\n')
    for pg, items in enumerate(pages, 1):
        print(f'── 第 {pg} 頁 ──')
        for it in items:
            mats = next((m for p, name, m in plan if p == pg and name == it), None)
            print(f'  {it or "（沒讀到）"}')
            if mats:
                print('      材料：' + '、'.join(f'{n}×{q}' + ('' if n in stores else '（?）') for n, q in mats) + '、石幣 1000')
    kinds = {n for _p, _i, m in plan for n, _q in m}
    print(f'\n共 {len(plan)} 項成品、材料 {len(kinds)} 種')
    return 0


if __name__ == '__main__':
    sys.exit(main())
