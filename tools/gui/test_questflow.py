#!/usr/bin/env python3
"""questflow / pausegate 離線測試（不碰遊戲）。
驗證：英文別名、起始步決定順序（指定 > 剛接 > 存檔 > OCR）、停手時 doing 標 paused、暫停檔、HUD 等級格式容錯。
用法：uv run --no-project python tools/gui/test_questflow.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pausegate  # noqa: E402
import q1920 as q  # noqa: E402
import questflow1920 as qf  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


# --only 時整理背包只跟著前面那組任務（2026-10-15 22222：--only 成人儀式 把兩次整理背包都跑掉並標 done）
check('only 成人儀式 不整理背包 1', qf.bag_in_only('__BAG__', ['成人儀式']), False)
check('only 成人儀式 不整理背包 2', qf.bag_in_only('__BAG2__', ['成人儀式']), False)
check('only 猜謎 不整理背包', qf.bag_in_only('__BAG2__', ['猜謎三兄弟']), False)
check('only 強盜 → 整理背包 1', qf.bag_in_only('__BAG__', ['強盜的洞穴']), True)
check('only 強盜 → 不做整理背包 2', qf.bag_in_only('__BAG2__', ['強盜的洞穴']), False)
check('only 彌生 → 整理背包 2', qf.bag_in_only('__BAG2__', ['彌生和日美子']), True)
check('only bag → 兩次都做', (qf.bag_in_only('__BAG__', ['bag']), qf.bag_in_only('__BAG2__', ['bag'])), (True, True))

# 別名
check('別名 mazu', qf.ALIAS['mazu'], '馬祖快遞')
check('別名 fourjade', qf.ALIAS['fourjade'], '四寶玉之謎')
check('英文別名都指到任務', all(v in qf.ADULT + qf.FOUR_CAVES + qf.HERO_ISLAND + qf.HERO_ISLAND_AFTER + qf.RIDDLE + qf.GROUP_A + qf.GROUP_B for k, v in qf.ALIAS.items() if k.isascii()), True)
check('別名涵蓋全部任務', all(n in qf.ALIAS.values() for n in qf.FOUR_CAVES + qf.GROUP_A + qf.GROUP_B), True)

# 起始步
steps = [(1, 'solo', '', 0), (2, 'boss', '', 0), (3, 'talk', '', 0)]
check('指定優先', qf.pick_start_step({'quest': 'X', 'step': 1}, 'X', steps, True, 2), (2, '--from-step 指定'))
check('剛接 = 1', qf.pick_start_step({'quest': 'X', 'step': 2}, 'X', steps, True, None), (1, '剛接的任務'))
check('存檔接續', qf.pick_start_step({'quest': 'X', 'step': 1}, 'X', steps, False, None)[0], 2)
check('存檔是別的任務 → OCR', qf.pick_start_step({'quest': 'Y', 'step': 1}, 'X', steps, False, None)[0], None)
check('存檔已完成 → OCR', qf.pick_start_step({'quest': 'X', 'step': None, 'done': True}, 'X', steps, False, None)[0], None)
check('存檔做完最後一步 → OCR', qf.pick_start_step({'quest': 'X', 'step': 3}, 'X', steps, False, None)[0], None)
check('步號不連續', qf.pick_start_step({'quest': 'X', 'step': 5}, 'X', [(5, 'solo', '', 0), (8, 'solo', '', 0)], False, None)[0], 8)

# 停手時 doing → paused（用暫存帳本）
tmp = Path(tempfile.mkdtemp())
q.LEDGER = tmp / 'ledger.json'
q.CLIENT = 'test-client'
q.ledger_mark('任務甲', 'doing', 'x')
q.ledger_mark('任務乙', 'done', 'y')
qf.mark_doing_paused('測試停手')
led = q.ledger_load()['test-client']
check('doing → paused', led['任務甲']['status'], 'paused')
check('done 不動', led['任務乙']['status'], 'done')

# 暫停檔
pausegate.CACHE = tmp
os.environ['PSA_EXE_MATCH'] = 'test-client'
check('沒檔不暫停', pausegate.paused(), False)
(tmp / 'PAUSE-test-client').write_text('x')
check('有檔暫停', pausegate.paused(), True)
check('別的客戶端的檔不影響', (lambda: (os.environ.__setitem__('PSA_EXE_MATCH', 'other'), pausegate.paused())[1])(), False)
os.environ['PSA_EXE_MATCH'] = 'test-client'
(tmp / 'PAUSE-test-client').unlink()
(tmp / 'PAUSE').write_text('x')
t0 = time.time()
import threading
threading.Timer(0.6, lambda: (tmp / 'PAUSE').unlink()).start()
waited = pausegate.wait(lambda m: None, poll_s=0.1)
check('刪檔後繼續（等了 0.5~3 秒）', 0.4 < waited < 3, True)

print(f'\n失敗 {fails}')
sys.exit(1 if fails else 0)
