#!/usr/bin/env python3
"""恐龍博士交遞（1920×1017）：對「當前角色」做 步 1（魯尼帖斯）+ 步 2（貝魯卡）。
流程（2026-10-12 實測）：點追蹤欄導航 → 對話選項「恐龍博士」→ 選項「完成」→ 跳「選擇」視窗 → 依名字點卡片（魯尼帖斯 / 貝魯卡）→ 確定。
用法：dino1920.py --client kkfaq11111 [--track 2]。換角色用 char.py / 切換面板（本檔不換人）。
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
CARD = {'貝魯卡': (450, 205), '魯尼帖斯': (450, 265)}     # 選擇視窗兩張卡的位置；順序每人不同，所以先讀名字再點
CARD_ROWS = [(415, 185, 200, 30), (415, 248, 200, 30)]
OK = (497, 373)
OPT1 = (650, 283)
DANGER = ('精靈王', '覲見', '覲兒', '轉生', '進入裏面', '趕緊通過')   # 守門人 / 精靈王的對話字樣（OCR 錯字也一起擋）


def card_for(uikit, want):
    for k, box in enumerate(CARD_ROWS):
        t = ''.join(uikit.ocr(box, '-Zooms', '2,3'))
        if want in t or (want == '魯尼帖斯' and '魯' in t and '尼' in t) or (want == '貝魯卡' and '貝' in t):
            return k
    return None


ALIASES = {'魯尼帖斯': ('魯尼帖斯', '魯尼帖', '尼帖斯', '魯尼'), '貝魯卡': ('貝魯卡', '貝魯', '魯卡')}
LIST_BOX = (360, 150, 300, 200)          # 「選擇」視窗寵物清單區（960×508）
OK_LIST = (497, 373)


def list_rows(uikit):
    """清單區 OCR 文字行 → [(文字, y)]（y = 截圖座標）。清單會捲動、卡片數不固定（領了守護獸後變多），不能用固定卡片位置。"""
    import json
    import winenv
    out = []
    for opts in (('-Zooms', '2,3'), ('-Zooms', '3,4')):
        try:
            r = winenv.run_ps('ocr.ps1', *map(str, LIST_BOX), *opts)
            d = json.loads((r.stdout.strip().splitlines() or [''])[-1])
        except Exception:
            continue
        if d.get('ok'):
            out += [(ln['text'], int(ln['y'])) for ln in d.get('lines', [])]
    return out


def pick_card(q, uikit, want) -> bool:
    """在選擇視窗找名字含 want 的卡片並點它（找不到就把清單往上 / 往下捲再找）。回 True = 已點到"""
    keys = ALIASES.get(want, (want,))
    for sweep in range(9):
        rows = list_rows(uikit)
        hits = sorted({y for t, y in rows if any(k in t for k in keys)})
        if hits:
            y = hits[-1]
            q.click((480, y + 6), wait_ms=700, note=f'dino 選 {want}（清單 y={y}）')
            return True
        # 沒看到：先往上看（內容往下拉）5 次，再往下看
        if sweep < 5:
            uikit.gui('seq', 'drag 520 200 520 290; wait 800', note='dino 選擇清單往上捲')
        else:
            uikit.gui('seq', 'drag 520 290 520 200; wait 800', note='dino 選擇清單往下捲')
    return False


def one_step(q, uikit, want):
    q.click(q.track_xy(), right=2, wait_ms=500, note='dino 點追蹤欄')
    s = q.wait_state(('DIALOG', 'REWARD'), timeout=40)
    if s != 'DIALOG':
        s2 = q.navigate()
        if s2 != 'DIALOG':
            return f'沒有對話（{s2}）'
    for _ in range(4):                                         # 選項：「恐龍博士」→「完成」
        txt = ''.join(uikit.ocr((555, 160, 350, 95), '-Zooms', '2,3'))
        opt = ''.join(uikit.ocr((565, 262, 175, 42), '-Zooms', '2,3'))
        q.log(f'dino 對話：{txt[:30]} / 選項 {opt[:10]}')
        # 安全：這支只會點「第 1 個選項」，走錯 NPC 時絕不能是轉生（2026-10-13 追蹤欄順序變了，走到漆黑洞窟守門人，第 1 選項是「覲見精靈王」）
        if any(k in txt + opt for k in DANGER):
            uikit.gui('key', '{ESC}', note='dino 對話出現精靈王 / 轉生 → ESC 離開')
            return f'走錯 NPC（對話含精靈王 / 轉生字樣）→ 停手：{txt[:20]}/{opt[:10]}'
        q.click(OPT1, wait_ms=1800, note='dino 選項')
        c = uikit.px([(665, 120), (497, 120)])
        # 「選擇」視窗特徵（2026-10-12 實測）：右上 ✕ ≈(195,70,46)、標題條 ≈(225,181,127)
        if c and abs(c[0][0] - 195) < 30 and abs(c[0][1] - 70) < 30 and abs(c[1][0] - 225) < 30 and abs(c[1][1] - 181) < 30:
            if not pick_card(q, uikit, want):
                return f'選擇視窗找不到 {want}'
            q.click(OK, wait_ms=1800, note='dino 確定')
            return 'ok'
    return '對話沒走到選擇視窗'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--track', type=int, default=2)
    ap.add_argument('--steps', default='1,2', help='要做哪幾步（1 = 魯尼帖斯、2 = 貝魯卡）；已經交過步 1 的角色用 --steps 2')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import q1920 as q, uikit
    q.CLIENT = a.client; q.TRACK_N = a.track; q.TRUST_TEAM = True
    # 追蹤欄順序會變（新接的任務排最上面、漆黑洞窟被擠到第 2 條）：不用固定第 N 條，依名稱找「恐龍博士」那一列
    import questflow1920 as qf
    q.scroll_tracker()                       # 切角色後追蹤欄可能停在「組隊」分頁 / 位置不對：先切回任務分頁（這步不能省，2026-10-13 角色 1 因此找不到）
    row = None
    for k in range(4):
        row = qf.find_track_row('恐龍博士', scroll=False, reveal=False)
        if row is not None:
            break
        q.log(f'追蹤欄找不到「恐龍博士」（第 {k + 1}/4 次）→ 重整追蹤欄再找')
        q.sleep(1.5)
        q.scroll_tracker()
    if row is None:
        q.log('追蹤欄找不到「恐龍博士」→ 停手（不用固定順序亂點，避免走到漆黑洞窟守門人）')
        return 5
    todo = {int(x) for x in a.steps.split(',') if x.strip()}
    for step, want in ((1, '魯尼帖斯'), (2, '貝魯卡')):
        if step not in todo:
            continue
        r = one_step(q, uikit, want)
        q.log(f'dino 步 {step}：{r}')
        if r != 'ok':
            return 5
    return 0


if __name__ == '__main__':
    sys.exit(main())
