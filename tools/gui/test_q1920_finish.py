#!/usr/bin/env python3
"""q1920 收尾檢驗的純函式測試（離線）：任務名比對、已完成卡片顏色、該解沒解的判斷。
uv run --no-project python tools/gui/test_q1920_finish.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import q1920 as q

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print('PASS' if ok else 'FAIL', name, '' if ok else f'got={got!r} want={want!r}')


check('漆黑二轉', q.match_known('漆黑洞窟(二轉)'), '漆黑洞窟(二轉)')
check('漆黑五轉（空白）', q.match_known('漆黑洞窟 (五轉)'), '漆黑洞窟(五轉)')
check('小豬愛情故事', q.match_known('小豬愛情故事(1.82)'), '小豬愛情故事')
check('英雄島前傳（必做）', q.match_known('英雄島前傳（必做）'), '英雄島前傳')
check('英雄島後傳', q.match_known('英雄島後傳'), '英雄島後傳')
check('天空之島(2.5)', q.match_known('天空之島(2.5)'), '天空之島')
check('不認得', q.match_known('隨便的字'), None)
check('已完成（綠字）', q.is_done_card([(11, 229, 7), (16, 218, 10), (169, 139, 110)]), True)
check('待接取（白字）', q.is_done_card([(252, 251, 251), (169, 139, 110), (255, 255, 255)]), False)
st = {'成人儀式': True, '漆黑洞窟(二轉)': False, '漆黑洞窟(三轉)': False, '英雄島後傳': False, '精靈少女': False,
      '天空之島': False, '龍的巢穴': False, '解救老爺爺': False, '恐龍博士': True}
check('該解沒解：依解題順序', q.judge_remaining(st), ['解救老爺爺', '龍的巢穴'])
check('只剩不解的 = 全做完', q.judge_remaining({'成人儀式': True, '英雄島後傳': False, '漆黑洞窟(二轉)': False}), [])
print(f'失敗 {fails}')
sys.exit(1 if fails else 0)
