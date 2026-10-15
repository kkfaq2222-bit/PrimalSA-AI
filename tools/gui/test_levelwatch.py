#!/usr/bin/env python3
"""levelwatch / progress 離線測試（不碰遊戲）。
驗證：等級讀取（隊長與寵物取較大、漏讀位數）、第一次確認（兩個等級都讀到且差 ≤ 2）、練功點門檻（REAL_STAGES）、
進度紀錄追加。用法：uv run --no-project python tools/gui/test_levelwatch.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import levelwatch as lw  # noqa: E402
import progress  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


# parse_level：只看人物等級，不看寵物（使用者 2026-10-15；轉生後戰寵等級跟人物無關）
check('parse 不取寵物（寵物 0轉116、人物 3轉99）', lw.parse_level({'level': '3轉99級', 'petLevel': '0轉116級'}), (3, 99))
check('parse 兩者一致', lw.parse_level({'level': '0轉112級', 'petLevel': '0轉112級'}), (0, 112))
check('parse 只讀到隊長', lw.parse_level({'level': '0轉45級'}), (0, 45))
check('parse 都讀不到', lw.parse_level({'level': None, 'petLevel': ''}), None)
check('parse 轉生數', lw.parse_level({'level': '2轉30級', 'petLevel': '2轉30級'}), (2, 30))
check('parse 轉字讀壞', lw.parse_level({'level': '嘨117', 'petLevel': None}), (-1, 117))
check('parse 轉字讀壞取較高等級', lw.parse_level({'level': '嘨117', 'petLevel': '0轉112級'}), (-1, 117))
check('parse 單位數不算', lw.parse_level({'level': '7', 'petLevel': None}), None)

# 等級 / 轉數只升不降（2026-10-15 22222 4轉37級 → 讀成 4 級、轉數不同 → 傳回 1 級練功點）
check('同轉降級 = 誤讀', lw.is_misread_down(4, 37, 4, 4), True)
check('轉數讀不到降級 = 誤讀', lw.is_misread_down(4, 37, -1, 4), True)
check('轉數讀小、等級降 = 誤讀', lw.is_misread_down(4, 37, 1, 30), True)
check('轉數讀小、等級升 = 採信等級', lw.is_misread_down(4, 99, 0, 100), False)
check('記轉數不降', lw.keep_trans(4, 0), 4)
check('記轉數讀不到保留', lw.keep_trans(4, -1), 4)
check('記轉數轉生升上去', lw.keep_trans(4, 5), 5)
check('真的轉生（轉數變大）不擋', lw.is_misread_down(4, 131, 5, 1), False)
check('同轉升級不擋', lw.is_misread_down(4, 37, 4, 38), False)
check('已確認轉數不明只比等級', lw.is_misread_down(-1, 37, 4, 4), True)

# first_read_ok：只看隊長（人物）等級有沒有讀到，不跟寵物核對（使用者 2026-10-15）
check('first 兩者一致', lw.first_read_ok({'level': '0轉112級', 'petLevel': '0轉112級'}), True)
check('first 寵物等級不同也可（轉生後戰寵 7 級、隊長 1 級）', lw.first_read_ok({'level': '3轉1級', 'petLevel': '0轉7級'}), True)
check('first 只讀到隊長可', lw.first_read_ok({'level': '1轉1級'}), True)
check('first 只讀到寵物不可', lw.first_read_ok({'petLevel': '0轉112級'}), False)

# target_for：真門檻（REAL_STAGES）
R = lw.REAL_STAGES
for lv, want in [(1, '柯奧龜洞'), (9, '柯奧龜洞'), (10, '阿布龜洞'), (19, '阿布龜洞'), (20, '海主人隧道'),
                 (44, '海主人隧道'), (45, '五兄弟洞窟'), (60, '柯奧4F龜洞'), (79, '柯奧4F龜洞'),
                 (80, '波拉島'), (119, '波拉島'), (120, '地雷區'), (134, '地雷區')]:
    check(f'target {lv} 級', lw.target_for(lv, R), want)
check('target 0 級沒有', lw.target_for(0, R), None)
# 兩份門檻表都要由高到低（target_for 取第一個符合的）
for nm, tb in (('STAGES', lw.STAGES), ('REAL_STAGES', lw.REAL_STAGES)):
    needs = [n for n, _ in tb]
    check(f'{nm} 由高到低', needs, sorted(needs, reverse=True))

# progress：追加、header 只寫一次、client 欄位、run 紀錄
tmp = Path(tempfile.mkdtemp()) / 'sub' / 'progress.md'
check('progress.add', progress.add('玄黃洞窟 第 4 步', client='gameClient', path=tmp), True)
check('progress.add_run', progress.add_run('quest.py', ['--task', '玄黃洞窟'], 0, path=tmp), True)
check('progress.add_run 例外', progress.add_run('quest.py', ['--solo'], None, path=tmp), True)
lines = tmp.read_text(encoding='utf-8').splitlines()
check('header 只一次', sum(1 for ln in lines if ln.startswith('# 進度紀錄')), 1)
body = [ln for ln in lines if ln.startswith('20')]
check('3 筆', len(body), 3)
check('含 client', '[gameClient] 玄黃洞窟 第 4 步' in body[0], True)
check('含退出碼', body[1].endswith('→ 退出碼 0'), True)
check('例外中斷', body[2].endswith('→ 異常中斷'), True)
check('tail 取最後 2 行', len(progress.tail(2, path=tmp)), 2)
check('寫不進去回 False 不丟例外', progress.add('x', path=Path('Z:/不存在的磁碟/p.md')), False)

print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
