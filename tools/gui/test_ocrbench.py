#!/usr/bin/env python3
"""任務詳情像素判離線測試（不碰遊戲、不跑 OCR）：fixtures/qdetail_px.json（ocrbench --make-fixture 從 960×508 截圖抽的）
→ questflow1920.classify_status（進行中 / 待接取 / 已完成 / 壓暗不判）、q1920.classify_go_button（傳送 / 重置 / 不判）、
q1920.go_button_decide（顏色 + OCR 合判），以及 ocrbench 的判分規則與 ocr_samples.json 格式。
用法：uv run --no-project python tools/gui/test_ocrbench.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocrbench  # noqa: E402
import q1920 as q  # noqa: E402
import questflow1920 as qf  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  got={got!r} want={want!r}'))


fx = ocrbench.load_fixture()
check('fixture 7 張截圖', len(fx), 7)
check('fixture 點數一致', all(len(c) == len(ocrbench.qdetail_points()) for _, c in fx.values()), True)
for name, (want, cols) in fx.items():
    rows, btn = ocrbench.classify_all(cols)
    check(f'{name} 6 列狀態', rows, want['rows'])
    check(f'{name} 按鈕', btn, want['button'])

# 合成色：壓暗 / 判不出 / 混色
BG, YEL, WHT, GRN, DIM = (160, 128, 96), (240, 220, 0), (245, 245, 245), (20, 215, 10), (64, 64, 32)
n = len(qf.status_pts(0))
check('點數不符 → None', qf.classify_status([BG] * 10), None)
check('全棕底無字 → 判不出（交給 OCR）', qf.classify_status([BG] * n), None)
check('黃 30 點 → 進行中', qf.classify_status([YEL] * 30 + [BG] * (n - 30)), 'progress')
check('白 30 點 → 待接取', qf.classify_status([WHT] * 30 + [BG] * (n - 30)), 'pending')
check('綠 30 點 → 已完成', qf.classify_status([GRN] * 30 + [BG] * (n - 30)), 'done')
check('黃白混 → 判不出', qf.classify_status([YEL] * 30 + [WHT] * 30 + [BG] * (n - 60)), None)
check('上窗黃、下窗白（各窗矛盾）→ 判不出', qf.classify_status([YEL] * 30 + [BG] * (n - 60) + [WHT] * 30), None)
check('壓暗 → dim', qf.classify_status([DIM] * n), 'dim')
check('讀不到像素 → None', qf.classify_status(None), None)
check('dim 文字不是待接取', qf.is_pending(qf.STATUS_TEXT['dim']) or qf.is_in_progress(qf.STATUS_TEXT['dim']), False)
check('進行中文字', qf.is_in_progress(qf.STATUS_TEXT['progress']), True)
check('待接取文字', qf.is_pending(qf.STATUS_TEXT['pending']), True)
check('已完成文字不是待接取', qf.is_pending(qf.STATUS_TEXT['done']), False)

nb, npn = len(q.GO_BTN_PTS), len(q.GO_PANEL_PTS)
PANEL, BLUE, GOLD = (215, 165, 135), (64, 96, 160), (192, 128, 64)
check('藍鈕 → transfer', q.classify_go_button([BLUE] * nb + [PANEL] * npn), 'transfer')
check('金鈕 → reset', q.classify_go_button([GOLD] * nb + [PANEL] * npn), 'reset')
check('藍但面板不在（地圖）→ None', q.classify_go_button([BLUE] * nb + [(64, 128, 176)] * npn), None)
check('藍金各半 → None', q.classify_go_button([BLUE] * (nb // 2) + [GOLD] * (nb - nb // 2) + [PANEL] * npn), None)
check('點數不符 → None', q.classify_go_button([BLUE] * 3), None)

# 顏色 + OCR 合判：兩道都過才放行
check('藍 + 傳送 → transfer', q.go_button_decide('transfer', '|傳送'), 'transfer')
check('藍 + 讀不到 → 不按', q.go_button_decide('transfer', '|'), None)
check('藍 + 重置字 → 矛盾不按', q.go_button_decide('transfer', '重倕務|傳送'), None)
check('金 → reset', q.go_button_decide('reset', '|傳送'), 'reset')
check('顏色判不出 + 傳送字 → 不按', q.go_button_decide(None, '|傳送'), None)

# ocrbench 判分
check('判分 狀態命中', ocrbench.judge('status', '進行中', '|行中'), 'hit')
check('判分 狀態誤判', ocrbench.judge('status', '待接取', '進行中'), 'wrong')
check('判分 狀態讀不到', ocrbench.judge('status', '待接取', '|'), 'miss')
check('判分 按鈕把重置讀成傳送 = 誤判', ocrbench.judge('button', '重置任務', '|傳送'), 'wrong')
check('判分 按鈕重置命中', ocrbench.judge('button', '重置任務', '重倕務|'), 'hit')
check('判分 完整字串', ocrbench.judge('exact', '普通的米', '普通的米|'), 'hit')
spec = json.loads(ocrbench.SAMPLES.read_text(encoding='utf-8'))
check('樣本集：每個 group 的讀法 / baseline 都有定義',
      all(r in spec['readers'] for g in spec['groups'] for r in g['readers'] + [g['baseline']]), True)

print(f'failed={fails}')
sys.exit(1 if fails else 0)
