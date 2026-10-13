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


check('setup：先解散、存倉庫、再確認全空', names('setup'), ['q1920.py', 'petdepot1920.py', 'petdepot1920.py'])
check('setup 最後一步是確認寵物欄全空', '--check-empty' in joined('setup')[2], True)
check('setup 存倉庫要 --do', '--do' in joined('setup')[1], True)
check('r1 鯊魚：解散 → 抓 → 第一隻改名 → 存公共 → 存個人 → 分給', names('r1'), ['q1920.py', 'catchrun1920.py', 'petname1_1920.py', 'petfetchimg1920.py', 'petfetchimg1920.py', 'petgive1920.py'])
check('r1 第一格改名 WW', '--slots 1' in joined('r1')[2] and '--name WW' in joined('r1')[2] and '--role 2' in joined('r1')[2], True)
check('r1 抓寵者是角色 2、不勾自動存', all(s in joined('r1')[1:][0] for s in ('--role 2', '克邦凱斯', '--n 5')) and '--store' not in joined('r1')[1:][0], True)
check('r1 誘餌來源公共', '--source public' in joined('r1')[1:][0], True)
check('r1 先存 2~5 格到公共', '--slots 2,3,4,5' in joined('r1')[1:][2] and '--tab public' in joined('r1')[1:][2], True)
check('r1 再存第 1 格到個人', '--slots 1' in joined('r1')[1:][3] and '--tab personal' in joined('r1')[1:][3], True)
check('r1 分給 1、3、4、5', '1:克邦凱斯;3:克邦凱斯;4:克邦凱斯;5:克邦凱斯' in joined('r1')[1:][4], True)
check('r3 是加格', '加格' in joined('r3')[0], True)
check('r4 鯊魚：不自動存', '--store' not in joined('r4')[0], True)
check('r4 存的是 2~5 格', '--slots 2,3,4,5' in joined('r4')[2], True)
check('r4 第一格也改名 WW', '--name WW' in joined('r4')[1], True)
check('r4 第 4 種是邦恩吉', '邦恩吉' in joined('r4')[0], True)
check('final：領 3 隻數字名稱', '--numeric 3' in joined('final')[0] and '--role 2' in joined('final')[0], True)
check('火雞系抓寵者是角色 3', '--role 3' in joined('r1', 'bird')[1:][0] and '火雞系' in joined('r1', 'bird')[1:][0], True)
check('火雞 r1 順序：解散 → 抓 → 改名 → 存公共 → 存個人 → 分給（固定第 1 格）',
      [Path(a[1]).name for _, a in k.plan('C', 'bird', 'r1')],
      ['q1920.py', 'catchrun1920.py', 'petname1_1920.py', 'petfetchimg1920.py', 'petfetchimg1920.py', 'petgive1920.py'])
check('火雞分給用 --first', '--first' in joined('r1', 'bird')[-1], True)
check('火雞不再學樣板 / 領樣板', all('learn' not in a and 'fetch' not in a and 'snap' not in a for p in ('r1', 'r2', 'r3', 'r4') for _, a in k.plan('C', 'bird', p)), True)
check('火雞 r4：抓 → 存公共 → 分給 → 誘餌放回', names('r4', 'bird'), ['catchrun1920.py', 'petname1_1920.py', 'petfetchimg1920.py', 'petgive1920.py', 'baitstore1920.py'])
check('任何階段都不再用 --store', all('--store' not in ' '.join(map(str, a)) for p in k.PHASES for f in k.FAMILY for _, a in k.plan('C', f, p)), True)
check('火雞分給 1、2、4、5', '1:火雞;2:火雞;4:火雞;5:火雞' in joined('r1', 'bird')[-1], True)
check('火雞 final 是角色 3', '--role 3' in joined('final', 'bird')[0], True)
print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
