#!/usr/bin/env python3
"""katan1920 離線測試（不碰遊戲）：各階段指令的內容與順序。
用法：uv run --no-project python tools/gui/test_katan.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import katan1920 as k  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


def names(phase, family='shark'):
    return [Path(a[1]).name for _, a in k.plan('C', family, phase)]


def joined(phase, family='shark'):
    return [' '.join(str(x) for x in a[2:]) for _, a in k.plan('C', family, phase)]


check('setup：先解散再存倉庫', names('setup'), ['q1920.py', 'petdepot1920.py'])
check('setup 存倉庫要 --do', '--do' in joined('setup')[1], True)
check('r1 鯊魚：抓 → 分類 → 分給', names('r1'), ['catchrun1920.py', 'petshark1920.py', 'petgive1920.py'])
check('r1 抓寵者是角色 2 + 自動存', all(s in joined('r1')[0] for s in ('--role 2', '--store', '克邦凱斯', '--n 5')), True)
check('r1 誘餌來源公共', '--source public' in joined('r1')[0], True)
check('r1 分給 1、3、4、5', '1:克邦凱斯;3:克邦凱斯;4:克邦凱斯;5:克邦凱斯' in joined('r1')[2], True)
check('r3 是加格', '加格' in joined('r3')[0], True)
check('r4 鯊魚：不自動存', '--store' not in joined('r4')[0], True)
check('r4 存的是 2~5 格', '--slots 2,3,4,5' in joined('r4')[1], True)
check('r4 第 4 種是邦恩吉', '邦恩吉' in joined('r4')[0], True)
check('final：領 3 隻數字名稱', '--numeric 3' in joined('final')[0] and '--role 2' in joined('final')[0], True)
check('火雞系抓寵者是角色 3', '--role 3' in joined('r1', 'bird')[0] and '火雞系' in joined('r1', 'bird')[0], True)
check('火雞 r1 先學樣板再搬再分', [next((x for x in a if x in ('learn', 'move', 'fetch')), None) for _, a in k.plan('C', 'bird', 'r1')][1:3],
      ['learn', 'move'])
check('火雞 r1 分給 1、2、4、5', sum('fetch' in j and '--tab public' in j for j in joined('r1', 'bird')), 4)
check('火雞 r4 分給 4 個角色', sum('fetch' in j for j in joined('r4', 'bird')), 4)
check('火雞 final 是角色 3', '--role 3' in joined('final', 'bird')[0], True)
print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
