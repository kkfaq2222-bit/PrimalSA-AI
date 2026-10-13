#!/usr/bin/env python3
"""rebirthprep1920 的離線測試（只驗計畫內容，不碰遊戲）。uv run --no-project python tools/gui/test_rebirthprep.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebirthprep1920 as rp

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


def names(phase):
    return [Path(a[1]).name for _, a in rp.plan('kkfaq22222', phase)]


def joined(phase):
    return [' '.join(str(x) for x in a[2:]) for _, a in rp.plan('kkfaq22222', phase)]


check('階段順序', rp.PHASES, ['check', 'catch', 'rename', 'store', 'give', 'lock', 'gold', 'fight'])
check('check：先解散再確認全空', names('check'), ['q1920.py', 'petdepot1920.py'])
check('check 只查角色 5', '--roles 5' in joined('check')[1] and '--check-empty' in joined('check')[1], True)
check('catch：角色 5 抓格魯西斯 5 隻', all(k in joined('catch')[0] for k in ('--role 5', '格魯西斯', '--n 5', '老虎系')), True)
check('catch 不勾自動存倉庫（不帶 --store）', '--store' in joined('catch')[0], False)
check('rename：只改角色 5', joined('rename')[0].endswith('--roles 5'), True)
check('store：第 2~5 格存公共', all(k in joined('store')[0] for k in ('--slots 2,3,4,5', '--tab public', '--role 5', '--do')), True)
check('give：角色 1~4 各領第 1 格', all(k in joined('give')[0] for k in ('--first', '1:格魯西斯;2:格魯西斯;3:格魯西斯;4:格魯西斯')), True)
check('give 不含角色 5', '5:格魯西斯' in joined('give')[0], False)
check('lock：自己的 lockmount 子指令', joined('lock')[0].endswith('lockmount --roles 1,2,3,4,5'), True)
check('gold：只領朵拉、1 級', '--only 朵拉' in joined('gold')[0] and '--level 1' in joined('gold')[0], True)
check('fight：5 人設出戰', names('fight'), ['petsetup1920.py'])
check('OCR 容錯：缺字也認得', all(rp._hit(t) for t in ('格魯西斯', '格魯西', '魯西斯', '格魯 西斯'.replace(' ', ''))), True)
check('OCR 不誤認別隻', rp._hit('貝魯卡'), False)
print(f'失敗 {fails}')
sys.exit(1 if fails else 0)
