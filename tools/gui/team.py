#!/usr/bin/env python3
"""組隊狀態檢查 / 解散（P2；form 留到 P4）。計畫：notes/plan-scriptify.md §2。只用標準函式庫。

用法（專案根目錄；WSL / Windows 原生指令相同）：
  uv run --no-project python tools/gui/team.py status [--json] [--no-ocr]   # 唯讀：開切換面板 → 每人 當前 / 線上、隊長 / 隊員 / 其他
  uv run --no-project python tools/gui/team.py check [--size 5] [--leader DKBO] [--no-ocr]   # 0 = 1 隊長 + (size-1) 隊員
  uv run --no-project python tools/gui/team.py disband                      # 解散隊伍（當前角色必須是隊長）

退出碼（共用 0 / 1 / 2 / 8 / 9 / 10 見 uikit；team 自己 40～47）：
  40 切換面板打不開或讀圖中途消失（沒點任何面板內座標）
  41 隊伍不完整（有隊長 / 隊員但不是 1 隊長 + (size-1) 隊員）
  42 卡片數 < size（有角色不在線）
  43 OCR 名字與卡片順序 / --leader 矛盾（讀到別人的名字才算；讀不出不算矛盾）
  45 解散沒做成（quest.disband_team 失敗，或解散後仍有隊伍）
  46 當前角色不是隊長（解散要隊長；不點）
  47 全員單人（沒有任何隊伍）；disband 遇到這個回 0
（44 = form 專用，P4 才用到。）

判斷依據（P-I1 / P-I4 實測，2026-10-11；座標 = 截圖座標）：
- 卡片存在：卡片米色 (249,231,203) vs 空位棕 (169,127,84)，看卡片左緣 (416 / 726, y)。順序固定 DKBO, DKBO2, DKBO3, DKBO4, DKBO5（真名是字母 O；DKB0 同義）
  （左欄 y 300 / 385 / 470、右欄 +310；有人離線時卡片會往前補位 → 卡片數 < 5 就不能靠順序，只能靠 OCR 名字）。
- 當前 / 線上：卡片左側狀態框 (x+6, y)、(x+30, y)：藍（B>150、G<200、R<60）= 當前、綠（G>160、B<60）= 線上；用門檻不比精確值。
- 隊伍標籤：框左上角（左欄 452,y-25、右欄 762,y-25）內 x+4..+34、y+4..+34 全像素掃描計數：紅 (255,0,7)「隊長」/ 黃 (255,210,0)「隊員」；
  同框的綠「正常」(41,255,0) 不計。單點取色不可靠（字很細）。「單人」字色沒量過，所以「既不紅也不黃」一律當 other（單人 / 其他）。
  （quest.read_team_labels 是 15x8 間隔 2 的稀疏取樣，實測 P-I1 說單點不可靠，這裡改密掃，不改 quest.py。）
- 名字（2026-10-11 起）：先用 namematch.py 整名圖樣板比對（IoU，保守，None = 不確定）；命中就採用（卡片 < 5 也行）。
  None 的卡片才退回下面的舊邏輯：以卡片順序為主；OCR（-Zooms 2,3,4,5,6 合併）只當交叉確認：norm_char 命中，或尾碼 02～05 符合即可。
  OCR 讀不出不算矛盾、讀到別人的名字才算矛盾；單獨讀到 DKBO（可能是 DKBO5 被截斷）不當矛盾證據。
"""
import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import charstate  # noqa: E402
import namematch  # noqa: E402
import uikit  # noqa: E402

SRC = 'team'
EXIT_PANEL, EXIT_INCOMPLETE, EXIT_MISSING, EXIT_OCR_CONFLICT = 40, 41, 42, 43
EXIT_DISBAND_FAIL, EXIT_NOT_LEADER, EXIT_NO_TEAM = 45, 46, 47

# 6 個卡片位置（slot 順序 = 面板上的先後）：(卡片左緣 x, 卡片 y)。左欄 slot 0/2/4、右欄 slot 1/3/5
CARD_X = (416, 726)
CARD_Y = (300, 385, 470)
SLOTS = [(CARD_X[i % 2], CARD_Y[i // 2]) for i in range(6)]
EXIST_BEIGE = (249, 231, 203)
EXIST_TOL = 30                       # 與空位棕 (169,127,84) 差 80 以上，門檻放中間
LABEL_DX, LABEL_DY = 36, -25         # 標籤框左上 = (x0+36, y-25)：452,275 / 762,275 …
LABEL_SCAN = range(4, 35)            # 框內 x+4..+34、y+4..+34（31x31 全掃）
LABEL_MIN_PX = 3                     # 純色字像素 ≥ 3 才算（同框綠「正常」不計；雜訊像素不會是 (255,0,7) / (255,210,0)）
NAME_BOX_DX, NAME_BOX_DY, NAME_BOX_W, NAME_BOX_H = 149, -24, 90, 24    # 左欄 565,276,90,24；右欄 x +310（x0 差 310 已含在 x0）
OCR_ZOOMS = '2,3,4,5,6'


# ---- 純函式（離線測試用）----
def is_card(c) -> bool:
    return all(abs(a - b) <= EXIST_TOL for a, b in zip(c, EXIST_BEIGE))


def classify_status(c1, c2) -> str:
    """兩個狀態框邊線點 → 'current'（藍）/ 'online'（綠）/ 'unknown'。兩點都要符合"""
    if all(b > 150 and g < 200 and r < 60 for r, g, b in (c1, c2)):
        return 'current'
    if all(g > 160 and b < 60 for r, g, b in (c1, c2)):
        return 'online'
    return 'unknown'


def classify_label(cols) -> str:
    """標籤框掃描色 → 'leader'（紅 255,0,7）/ 'member'（黃 255,210,0）/ 'other'"""
    red = sum(1 for r, g, b in cols if r > 200 and g < 40 and b < 60)
    yel = sum(1 for r, g, b in cols if r > 230 and 190 < g < 235 and b < 40)
    if red >= LABEL_MIN_PX and red > yel:
        return 'leader'
    if yel >= LABEL_MIN_PX:
        return 'member'
    return 'other'


def name_hits(texts) -> tuple:
    """OCR 各行文字 → (強證據名字集合, 是否讀到單獨的 DKBO)。
    強證據 = norm_char 命中 DKBO2～5（含 OCR 常見錯字還原），或尾碼 0[2-5]（D02 / 03 / B04 / 05；O / 0 視為相同）。
    單獨的 DKBO（norm_char 命中 DKBO）可能是 DKBO5 被截斷，另外回傳，不當矛盾證據。"""
    strong, bare = set(), False
    known = charstate.chars()
    for t in texts:
        t = str(t or '')
        hit = charstate.norm_char(t)
        if hit:
            if hit == charstate.LEAD:
                bare = True
            else:
                strong.add(hit)
            continue
        m = re.search(r'0([2-5])\s*$', t.replace('O', '0').replace('o', '0').strip())
        if m:
            cand = charstate.LEAD + m.group(1)
            hit = next((k for k in known if charstate.same(k, cand)), None)
            if hit:
                strong.add(hit)
    return strong, bare


def cross_check(expect, texts) -> str:
    """順序推得的名字 expect vs OCR → 'ok'（讀到且一致）/ 'unknown'（讀不出或證據不足）/ 'conflict'（讀到別人的名字）"""
    strong, bare = name_hits(texts)
    if expect in strong:
        return 'ok' if len(strong) == 1 else 'unknown'      # 同卡讀出多個不同名字 = OCR 雜訊，不採信
    if strong:
        return 'conflict'
    if bare and charstate.same(expect, charstate.LEAD):
        return 'ok'
    return 'unknown'


def resolve_name(slot: int, texts):
    """卡片數 < 5 時順序不可靠：只靠 OCR。唯一強證據 → 該名字；slot 0 讀到單獨 DKBO → DKBO；其餘 None"""
    strong, bare = name_hits(texts)
    if len(strong) == 1:
        return next(iter(strong))
    if not strong and bare and slot == 0:
        return charstate.LEAD
    return None


@dataclass
class Card:
    slot: int
    status: str = 'unknown'          # current / online / unknown
    label: str = 'other'             # leader / member / other
    name: str | None = None          # 順序（5 張時）或 OCR 解出；None = 不知道
    ocr: list = field(default_factory=list)
    check: str = 'unread'            # ok / unknown / conflict / unread（沒做 OCR）
    via: str = ''                    # 名字來源：tpl（namematch）/ 空 = 順序或 OCR

    def d(self) -> dict:
        return {'slot': self.slot, 'name': self.name, 'status': self.status, 'label': self.label, 'ocr': self.ocr, 'ocr_check': self.check, 'via': self.via}


def build_cards(px_cols: list, ocr_texts: dict | None = None, matched: dict | None = None) -> list:
    """px_cols = read_pixels 回的整串顏色（順序：每 slot 先 card、s1、s2、再 LABEL 掃描）→ 存在的 Card 清單（照面板順序）。
    ocr_texts = {slot: [文字…]}；None = 沒做 OCR。matched = namematch 的 {slot: 名字或 None}（優先於順序 / OCR；None 才退回舊邏輯）。卡片位置不連續（空位在中間）視為異常 → 只回前面連續的那段"""
    per = 3 + len(LABEL_SCAN) ** 2
    cards = []
    order = charstate.chars()
    for i in range(len(SLOTS)):
        seg = px_cols[i * per:(i + 1) * per]
        if not is_card(seg[0]):
            break
        c = Card(i, status=classify_status(seg[1], seg[2]), label=classify_label(seg[3:]))
        cards.append(c)
    full = len(cards) == len(order)
    matched = matched or {}
    for c in cards:
        if ocr_texts is not None:
            c.ocr = list(ocr_texts.get(c.slot, []))
        hit = matched.get(c.slot)
        if hit:
            c.name, c.via = hit, 'tpl'
            # 5 張時順序可靠：樣板與順序不同 = 矛盾（judge 回 43）
            c.check = 'conflict' if full and hit != order[c.slot] else 'ok'
            continue
        if full:
            c.name = order[c.slot]
            if ocr_texts is not None:
                c.check = cross_check(c.name, c.ocr)
        elif ocr_texts is not None:
            c.name = resolve_name(c.slot, c.ocr)
            c.check = 'ok' if c.name else 'unknown'
    return cards


def summarize(cards: list) -> dict:
    lead = [c for c in cards if c.label == 'leader']
    mem = [c for c in cards if c.label == 'member']
    cur = [c for c in cards if c.status == 'current']
    return {'n': len(cards), 'leaders': len(lead), 'members': len(mem), 'others': len(cards) - len(lead) - len(mem),
            'leader': lead[0].name if len(lead) == 1 else None, 'current': cur[0].name if len(cur) == 1 else None,
            'current_slot': cur[0].slot if len(cur) == 1 else None, 'leader_slot': lead[0].slot if len(lead) == 1 else None}


def judge(cards: list, size: int, leader=None) -> tuple:
    """純函式：→ (退出碼, 說明)。優先序：42 卡片不足 > 47 全單人 / 41 不完整 > 43 OCR 矛盾 / --leader 對不上"""
    s = summarize(cards)
    desc = f'卡片 {s["n"]}、隊長 {s["leaders"]}、隊員 {s["members"]}、其他 {s["others"]}'
    if s['n'] < size:
        names = [c.name or '?' for c in cards]
        return EXIT_MISSING, f'{desc}：卡片數 {s["n"]} < {size}（有角色不在線；在線卡片 {names}）'
    if s['leaders'] + s['members'] == 0:
        return EXIT_NO_TEAM, f'{desc}：全員單人，沒有隊伍'
    if not (s['leaders'] == 1 and s['members'] == size - 1):
        return EXIT_INCOMPLETE, f'{desc}：不是 1 隊長 + {size - 1} 隊員（隊伍不完整）'
    bad = [c for c in cards if c.check == 'conflict']
    if bad:
        return EXIT_OCR_CONFLICT, f'{desc}：OCR 名字與卡片順序矛盾 ' + '、'.join(f'slot{c.slot}={c.name} 但 OCR {c.ocr}' for c in bad)
    if leader and not charstate.same(s['leader'], leader):
        return EXIT_OCR_CONFLICT, f'{desc}：隊長是 {s["leader"] or "?（名字無法確認）"}，不是 {leader}'
    return 0, f'{desc}：隊伍完整（隊長 {s["leader"] or "?"}、當前 {s["current"] or "?"}）'


# ---- 讀面板（要碰遊戲）----
def read_pixels() -> list | None:
    """切換面板開著時一次 pixel 讀 6 張卡片的存在 / 狀態 / 標籤掃描點；失敗 None"""
    pts = []
    for x0, y in SLOTS:
        pts += [(x0, y), (x0 + 6, y), (x0 + 30, y)]
        lx, ly = x0 + LABEL_DX, y + LABEL_DY
        pts += [(lx + dx, ly + dy) for dy in LABEL_SCAN for dx in LABEL_SCAN]
    cols = uikit.px(pts)
    return cols


def ocr_names(n_cards: int, only=None) -> dict:
    """逐張卡片名字 OCR（-Zooms 2,3,4,5,6 合併；預設 Dark 150，-Light 讀不到）→ {slot: [行…]}；only = 只讀這些 slot"""
    out = {}
    for i in range(n_cards):
        if only is not None and i not in only:
            continue
        x0, y = SLOTS[i]
        out[i] = uikit.ocr((x0 + NAME_BOX_DX, y + NAME_BOX_DY, NAME_BOX_W, NAME_BOX_H), '-Zooms', OCR_ZOOMS)
    return out


def read_state(ocr: bool = True, keep_open: bool = False) -> dict:
    """開切換面板 → 讀 → 關（只關自己開的；keep_open=True 讀完不關，char.py 要接著點卡片，呼叫端負責關）。回 {'ok': bool, 'cards': [...], 'summary': {...}, 'err': str, 'ms': {...}}。
    面板打不開 / 讀圖中途消失 → ok=False（呼叫端回 40）。不點任何面板內座標（開關只用 open_panel / close_panel 的開啟鈕與 ✕）"""
    res = {'ok': False, 'cards': [], 'summary': {}, 'err': '', 'ms': {}}
    t0 = time.time()
    was_open = uikit.is_open(uikit.SWITCH)
    if not uikit.open_panel(uikit.SWITCH):
        res['err'] = '切換面板打不開（HUD 不在或特徵沒出現）'
        return res
    res['ms']['open'] = int((time.time() - t0) * 1000)
    try:
        t1 = time.time()
        cols = read_pixels()
        res['ms']['pixel'] = int((time.time() - t1) * 1000)
        if cols is None:
            res['err'] = '讀不到面板像素'
            return res
        if not uikit.is_open(uikit.SWITCH):
            res['err'] = '讀圖中面板消失'
            return res
        n = len(build_cards(cols))
        matched = {}
        if ocr:                                   # --no-ocr = 完全不讀名字（維持舊行為：快、只靠順序）
            t3 = time.time()
            matched = namematch.read_names()
            res['ms']['tpl'] = int((time.time() - t3) * 1000)
        texts = None
        if ocr:
            need = [i for i in range(n) if not matched.get(i)]
            if need:                              # 樣板沒命中的卡才 OCR
                t2 = time.time()
                texts = ocr_names(n, only=need)
                res['ms']['ocr'] = int((time.time() - t2) * 1000)
            else:
                texts = {}
        if not uikit.is_open(uikit.SWITCH):
            res['err'] = '讀名字中面板消失'
            return res
        cards = build_cards(cols, texts, matched)
        res.update(ok=True, cards=cards, summary=summarize(cards))
        return res
    finally:
        if not was_open and not (keep_open and res['ok']):
            uikit.close_panel(uikit.SWITCH)


def _line(c: Card) -> str:
    st = {'current': '當前', 'online': '線上', 'unknown': '？'}[c.status]
    lb = {'leader': '隊長', 'member': '隊員', 'other': '單人/其他'}[c.label]
    ck = {'ok': 'OCR 一致', 'unknown': 'OCR 讀不出', 'conflict': 'OCR 矛盾', 'unread': ''}[c.check]
    if c.via == 'tpl':
        ck = {'ok': '樣板命中', 'conflict': '樣板與順序矛盾'}.get(c.check, '樣板')
    return f'slot{c.slot} {c.name or "?":6} {st} {lb:6} {ck} {c.ocr or ""}'.rstrip()


def status(as_json: bool = False, ocr: bool = True) -> int:
    rc = uikit.preflight(SRC)
    if rc:
        return rc
    t0 = time.time()
    r = read_state(ocr)
    if not r['ok']:
        uikit.snap('team-status-fail')
        return uikit.fail(SRC, EXIT_PANEL, r['err'])
    ms = int((time.time() - t0) * 1000)
    if as_json:
        print(json.dumps({'cards': [c.d() for c in r['cards']], 'summary': r['summary'], 'ms': ms, 'stage_ms': r['ms']}, ensure_ascii=False))
    else:
        for c in r['cards']:
            print(_line(c))
        s = r['summary']
        print(f'共 {s["n"]} 張：隊長 {s["leaders"]}、隊員 {s["members"]}、其他 {s["others"]}；隊長 {s["leader"] or "-"}、當前 {s["current"] or "-"}（{ms} ms {r["ms"]}）')
    return 0


def check(size: int = 5, leader=None, ocr: bool = True) -> int:
    rc = uikit.preflight(SRC)
    if rc:
        return rc
    if leader:
        leader = charstate.norm_char(leader)
        leader = charstate.display(leader) if leader else None
        if not leader:
            print('team：--leader 不在白名單', file=sys.stderr)
            return uikit.EXIT_USAGE
    r = read_state(ocr)
    if not r['ok']:
        uikit.snap('team-check-fail')
        return uikit.fail(SRC, EXIT_PANEL, r['err'])
    code, desc = judge(r['cards'], size, leader)
    for c in r['cards']:
        print(_line(c))
    print(f'check：{desc}（退出碼 {code}）')
    if code == EXIT_OCR_CONFLICT:
        uikit.snap('team-check-conflict')
        uikit.fail(SRC, code, desc)
    return code


def disband() -> int:
    """解散隊伍。先唯讀確認（沒有隊伍 → 0 不點；當前不是隊長 → 46 不點），再交給 quest.disband_team（左側分頁，逐步像素驗證），
    解散後重開切換面板確認沒有隊長 / 隊員，最後把左側分頁切回「任務」。"""
    rc = uikit.preflight(SRC)
    if rc:
        return rc
    r = read_state(ocr=False)
    if not r['ok']:
        uikit.snap('team-disband-fail')
        return uikit.fail(SRC, EXIT_PANEL, r['err'])
    s = r['summary']
    if s['leaders'] + s['members'] == 0:
        print('disband：本來就沒有隊伍，沒做任何點擊（退出碼 0）')
        return 0
    cur = [c for c in r['cards'] if c.status == 'current']
    if len(cur) != 1 or cur[0].label != 'leader':
        uikit.snap('team-disband-not-leader')
        return uikit.fail(SRC, EXIT_NOT_LEADER, f'當前角色不是隊長（當前 {s["current"] or "?"}、隊長 {s["leader"] or "?"}）：不點，先切到隊長再解散')
    import quest
    d = quest.disband_team()
    if d:
        uikit.snap('team-disband-quest-fail')
        return uikit.fail(SRC, EXIT_DISBAND_FAIL, f'quest.disband_team 回 {d}（解散沒做成）')
    r = read_state(ocr=False)
    if not r['ok']:
        uikit.snap('team-disband-verify-fail')
        return uikit.fail(SRC, EXIT_PANEL, '解散後驗證：' + r['err'])
    s = r['summary']
    if s['leaders'] + s['members']:
        uikit.snap('team-disband-still')
        return uikit.fail(SRC, EXIT_DISBAND_FAIL, f'解散後仍有隊伍（隊長 {s["leaders"]}、隊員 {s["members"]}）')
    quest.ensure_task_tab()
    print('disband：已解散（切換面板全員單人 / 其他），左側分頁已確認在任務')
    return 0


def main() -> int:
    import winenv
    winenv.enable_server()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('status', help='唯讀：顯示每人當前 / 隊長 / 隊員')
    p.add_argument('--json', action='store_true')
    p.add_argument('--no-ocr', action='store_true', help='不做名字 OCR 交叉確認（快）')
    p = sub.add_parser('check', help='0 = 1 隊長 + (size-1) 隊員')
    p.add_argument('--size', type=int, default=5)
    p.add_argument('--leader', help='隊長必須是這個角色（名字）')
    p.add_argument('--no-ocr', action='store_true')
    sub.add_parser('disband', help='解散隊伍（當前必須是隊長）')
    a = ap.parse_args()
    if a.cmd == 'status':
        return status(a.json, not a.no_ocr)
    if a.cmd == 'check':
        return check(a.size, a.leader, not a.no_ocr)
    return disband()


if __name__ == '__main__':
    sys.exit(main())
