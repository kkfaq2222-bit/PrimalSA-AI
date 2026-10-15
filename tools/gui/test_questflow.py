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

# 任務詳情白名單（2026-10-15 22222 夢德洞窟：進行中的任務那顆鈕是「重置任務」花 50000 石幣；實測 OCR 字串）
check('進行中', qf.is_in_progress('|進行中進行中'), True)
check('待接取不是進行中', qf.is_in_progress('待接取待接取'), False)
check('待接取', qf.is_pending('|待接取'), True)
check('空白不是待接取', qf.is_pending('|'), False)
check('重置鈕不放行', qf.is_go_text('重倕務置倕務|~…重置蓩“'), False)
check('傳送鈕放行', qf.is_go_text('|傳送傳送'), True)
check('讀不到不放行', qf.is_go_text('|'), False)
check('重置提示窗', qf.is_reset_text('你是否願意花費50000重置此任務？'), True)

# 剛接的任務存「第 0 步」→ 下次從第 1 步開始（2026-10-15 22222 夢德洞窟：沒存檔 → 副標題 OCR 猜成第 3 步）
_st6 = [(i, 'talk', '', 0) for i in range(1, 7)]
check('剛接存第 0 步 → 第 1 步', qf.pick_start_step({'quest': '夢德洞窟', 'step': 0}, '夢德洞窟', _st6, False, None)[0], 1)
check('別的任務的存檔不用', qf.pick_start_step({'quest': '強恩一族', 'step': 0}, '夢德洞窟', _st6, False, None)[0], None)

# 練寵等級累計：None 不覆蓋、只升不降（2026-10-15 22222 金布伊）
_lv = {1: 80, 2: 77}
qf.merge_levels(_lv, {2: None, 3: 80, 4: None})
check('None 不蓋掉已達標', _lv, {1: 80, 2: 77, 3: 80})
qf.merge_levels(_lv, {3: 2})
check('等級只升不降', _lv[3], 80)

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
