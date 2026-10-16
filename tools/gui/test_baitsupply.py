#!/usr/bin/env python3
"""誘餌補貨離線測試：買不買的決策、OCR 數字一致性"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import baitsupply1920 as b  # noqa: E402
import fullrun1920 as f  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


H = 3600
check('夠了不買', b.decide(140, 100 * H, 0), 'enough')
check('剛好 40 不買', b.decide(40, 100 * H, 0), 'enough')
check('39 要買', b.decide(39, 100 * H, 0), 'buy')
check('0 要買', b.decide(0, 100 * H, 0), 'buy')
check('讀不到不買', b.decide(None, 100 * H, 0), 'unknown')
check('24 小時內試過不再買', b.decide(10, 100 * H, 90 * H), 'cooldown')
check('超過 24 小時可以再買', b.decide(10, 100 * H, 75 * H), 'buy')
check('兩種讀法一致', b.num(['2750000', '2750000']), 2750000)
check('兩種讀法不一致 → None', b.num(['2750000', '275000']), None)
check('讀不到 → None', b.num([]), None)
check('prebag 有補貨', any('baitsupply1920.py' in ' '.join(map(str, cmd)) and '--buy' in cmd for _d, cmd in f.plan('x', 'prebag')), True)
check('katan 先檢查', '--check' in f.plan('x', 'katan')[0][1], True)
print('全部通過' if not fails else f'{fails} 項失敗')
sys.exit(1 if fails else 0)
