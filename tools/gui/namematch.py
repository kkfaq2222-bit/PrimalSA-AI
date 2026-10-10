#!/usr/bin/env python3
"""切換面板卡片「名字圖」整名樣板比對（只用標準函式庫；本機運算）。取代 team.py 的名字 OCR（常只讀到尾碼 '03'、'05'、'DKBO'）。

原理：digitmatch.ps1 -Boxes 背景截圖 → 每張卡片的名字框（截圖座標 565,276,90,24；右欄 x+310；y 276/361/446 → 客戶區 ×2）
以咖啡色字（≈125,64,28，米底 ≈249,231,200）二值化 → 與 tools/.cache/name-tpl/<版面>.json 的整名樣板做 IoU（允許 ±2 px 平移）。
同一個名字的渲染固定，所以同名分數 ≈ 1.0；不同名（DKB02 vs DKB03）差在一個字形，分數明顯較低。
保守：最佳 IoU < HIT_MIN 或與次佳名字差距 < MARGIN → None（呼叫端退回 OCR / 卡片順序）。
卡片名字不隨「當前 / 線上」變色（實測），但仍允許每名多個變體（MAX_VARIANTS）。

用法（專案根目錄；切換面板必須先開著 = `read` / `learn` 不自己開關面板；team.py 會幫你開）：
  uv run --no-project python tools/gui/namematch.py read [--json]    # 面板開著時讀 6 個卡位 → {卡位: 名字或 None}、分數、耗時
  uv run --no-project python tools/gui/namematch.py learn            # 5 人都在線（卡片數 = 5）才學：順序 + OCR 不矛盾 → 存樣板
  uv run --no-project python tools/gui/namematch.py list             # 現有樣板（名字 → 變體數）
程式用：namematch.read_names() → {slot: name|None}（沒樣板 / 版面不對 / 截圖失敗 → {}，不呼叫 PowerShell 的情況：沒有樣板檔）。
名字白名單 = charstate.chars()（watch-config.json）；樣板檔裡不在白名單的名字一律忽略。
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import charname  # noqa: E402
import charstate  # noqa: E402
import winenv  # noqa: E402

ROOT = HERE.parents[1]
TPL_DIR = ROOT / 'tools' / '.cache' / 'name-tpl'
LAYOUT = '2880x1659'
# 6 個卡位（slot 順序 = team.SLOTS：左欄 0/2/4、右欄 1/3/5）；框為截圖座標 (x, y, w, h)，客戶區 ×2
CARD_X = (416, 726)
CARD_Y = (300, 385, 470)
NAME_DX, NAME_DY, NAME_W, NAME_H = 149, -24, 90, 24
SCALE = 2
CW_ = NAME_W * SCALE            # 二值圖寬 180
CH_ = NAME_H * SCALE            # 二值圖高 48
PAD = 3                         # 平移 ±2 用
STRIDE = CW_ + 2 * PAD
SHIFT = 2
MODE_BROWN = 2                  # digitmatch.ps1 -Boxes 的咖啡色字模式
HIT_MIN = 0.95                  # 命中門檻（IoU；實測同名 ≈ 1.0）
MARGIN = 0.05                   # 與次佳名字至少差這麼多
MIN_INK = 150                   # 墨點太少 = 空卡位 / 沒字，不比對
MAX_VARIANTS = 4
DUP_IOU = 0.995                 # 與既有變體幾乎一樣就不重複存


def boxes() -> list:
    """6 個卡位的客戶區框 (x, y, w, h)"""
    return [((CARD_X[i % 2] + NAME_DX) * SCALE, (CARD_Y[i // 2] + NAME_DY) * SCALE, CW_, CH_) for i in range(6)]


# ---- 二值圖 <-> 大整數 ----
def rows_to_int(rows: list) -> int:
    """'0'/'1' 字串列 → 單一大整數（bit = (y+PAD)*STRIDE + x+PAD）；列數 / 寬度不符的部分直接截掉 / 補 0"""
    v = 0
    for y, r in enumerate(rows[:CH_]):
        for x, c in enumerate(r[:CW_]):
            if c == '1':
                v |= 1 << ((y + PAD) * STRIDE + x + PAD)
    return v


def int_to_rows(v: int) -> list:
    return [''.join('1' if v >> ((y + PAD) * STRIDE + x + PAD) & 1 else '0' for x in range(CW_)) for y in range(CH_)]


def iou(a: int, b: int) -> float:
    """a 平移 ±SHIFT（x、y 各）後與 b 的最大 IoU"""
    na, nb = a.bit_count(), b.bit_count()
    if not na or not nb:
        return 0.0
    best = 0.0
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            s = dy * STRIDE + dx
            sa = a << s if s >= 0 else a >> -s
            inter = (sa & b).bit_count()
            if inter:
                best = max(best, inter / (na + nb - inter))
    return best


# ---- 樣板檔 ----
def tpl_path(layout: str = LAYOUT) -> Path:
    return TPL_DIR / f'{layout}.json'


def load_tpl(layout: str = LAYOUT) -> dict:
    """{名字: [變體 hex 字串…]}（只留白名單內的名字）"""
    p = tpl_path(layout)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}
    # 鍵用 canon 對應到白名單真名（舊樣板鍵 DKB0 → DKBO；O / 0 視為相同）
    cmap = charname.canon_map(charstate.chars())
    out: dict = {}
    for n, vs in raw.items():
        real = cmap.get(charname.canon(n))
        if real and isinstance(vs, list):
            out.setdefault(real, []).extend(v for v in vs if isinstance(v, str))
    return out


def save_tpl(tpl: dict, layout: str = LAYOUT) -> None:
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    p = tpl_path(layout)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(tpl, ensure_ascii=False), encoding='utf-8')
    tmp.replace(p)


def _ints(tpl: dict) -> dict:
    return {n: [int(h, 16) for h in vs] for n, vs in tpl.items()}


# ---- 比對（純函式）----
def score_all(img: int, tpl_ints: dict) -> dict:
    """一張名字圖 → {名字: 最佳變體 IoU}"""
    return {n: max((iou(img, v) for v in vs), default=0.0) for n, vs in tpl_ints.items()}


def decide(scores: dict, hit_min: float = HIT_MIN, margin: float = MARGIN):
    """→ (名字或 None, 最佳分, 次佳分)。保守：低於門檻或差距太小 = None"""
    if not scores:
        return None, 0.0, 0.0
    rk = sorted(scores.items(), key=lambda kv: -kv[1])
    best_n, best = rk[0]
    second = rk[1][1] if len(rk) > 1 else 0.0
    if best < hit_min or best - second < margin:
        return None, best, second
    return best_n, best, second


def match_rows(rows_by_slot: dict, tpl: dict) -> dict:
    """{slot: 二值列} + 樣板 → {slot: {'name','score','second','ink'}}；墨點太少（空卡位）name = None"""
    ti = _ints(tpl)
    out = {}
    for slot, rows in rows_by_slot.items():
        img = rows_to_int(rows)
        ink = img.bit_count()
        if ink < MIN_INK:
            out[slot] = {'name': None, 'score': 0.0, 'second': 0.0, 'ink': ink}
            continue
        name, best, second = decide(score_all(img, ti))
        out[slot] = {'name': name, 'score': round(best, 3), 'second': round(second, 3), 'ink': ink}
    return out


# ---- 截圖（要碰遊戲；測試替換 namematch.capture）----
def capture() -> dict | None:
    """切換面板開著時裁 6 張名字框 → {slot: 二值列}；失敗 / 版面不是 2880x1659 → None"""
    import digitmatch
    spec = ';'.join(f'{x},{y},{w},{h},{MODE_BROWN}' for x, y, w, h in boxes())
    try:
        r = winenv.run_ps('digitmatch.ps1', '-Boxes', spec, timeout=15)
    except Exception:
        return None
    cap = digitmatch.parse_capture(r.stdout)
    if not cap.get('ok') or cap.get('layout') != LAYOUT:
        return None
    f = cap.get('fields', {})
    return {i: f[f'b{i}'] for i in range(6) if f'b{i}' in f}


def read_detail(rows_by_slot: dict | None = None) -> dict:
    """→ {slot: {'name','score','second','ink'}}；沒有樣板 → {}（不截圖）；截圖失敗 → {}"""
    tpl = load_tpl()
    if not tpl:
        return {}
    if rows_by_slot is None:
        rows_by_slot = capture()
        if not rows_by_slot:
            return {}
    return match_rows(rows_by_slot, tpl)


def read_names(rows_by_slot: dict | None = None) -> dict:
    """→ {slot: 名字或 None}（沒有樣板 / 截圖失敗 = {}）。team.py 用"""
    return {s: d['name'] for s, d in read_detail(rows_by_slot).items()}


# ---- 學習 ----
def add_variant(tpl: dict, name: str, img: int) -> bool:
    """把名字圖加進樣板（與既有變體幾乎相同 / 已達上限就不加）；回是否有新增"""
    vs = tpl.setdefault(name, [])
    if any(iou(img, int(h, 16)) >= DUP_IOU for h in vs) or len(vs) >= MAX_VARIANTS:
        return False
    vs.append(format(img, 'x'))
    return True


def learn_from(rows_by_slot: dict, labels: dict, tpl: dict, log=print) -> int:
    """labels = {slot: 名字}（呼叫端已確認）→ 新增樣板數。已有別的名字樣板 IoU 也高（>= HIT_MIN）→ 視為標籤可疑，整次不學"""
    ti = _ints(tpl)
    imgs = {s: rows_to_int(rows_by_slot[s]) for s in labels if s in rows_by_slot}
    for s, name in labels.items():
        if s not in imgs or imgs[s].bit_count() < MIN_INK:
            log(f'namematch：slot{s} 沒有名字墨點，不學')
            return 0
        for n, sc in score_all(imgs[s], ti).items():
            if n != name and sc >= HIT_MIN:
                log(f'namematch：slot{s} 標籤 {name} 但與既有 {n} 樣板 IoU {sc:.3f}，標籤可疑，整次不學')
                return 0
    n_new = 0
    for s, name in labels.items():
        if add_variant(tpl, name, imgs[s]):
            n_new += 1
    return n_new


def learn(log=print) -> int:
    """面板開著、5 人都在線 → 以「卡片順序 + OCR 交叉確認不矛盾」當標籤學樣板。回 0 = 成功（含「沒有新變體」）、其他 = 沒學"""
    import team
    import uikit
    if not uikit.is_open(uikit.SWITCH):
        log('namematch learn：切換面板沒開（本指令不自己開面板；team.py status 會開）')
        return 1
    cols = team.read_pixels()
    if cols is None:
        log('namematch learn：讀不到面板像素')
        return 1
    cards = team.build_cards(cols)
    order = charstate.chars()
    if len(cards) != len(order):
        log(f'namematch learn：卡片數 {len(cards)} != {len(order)}（有人離線，順序不可靠），不學')
        return 2
    texts = team.ocr_names(len(cards))
    labels = {}
    for c in cards:
        name = order[c.slot]
        ck = team.cross_check(name, texts.get(c.slot, []))
        if ck == 'conflict':
            log(f'namematch learn：slot{c.slot} 順序 {name} 但 OCR {texts.get(c.slot)} 矛盾，整次不學')
            return 3
        labels[c.slot] = name
    rows = capture()
    if not rows or not all(s in rows for s in labels):
        log('namematch learn：名字截圖失敗')
        return 1
    tpl = load_tpl()
    n = learn_from(rows, labels, tpl, log)
    if n:
        save_tpl(tpl)
    log(f'namematch learn：新增 {n} 個變體；樣板現況 ' + '、'.join(f'{k}×{len(v)}' for k, v in sorted(tpl.items())))
    return 0


def main() -> int:
    winenv.enable_server()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('read', help='面板開著時讀 6 個卡位的名字')
    p.add_argument('--json', action='store_true')
    sub.add_parser('learn', help='5 人都在線時學樣板（面板要先開著）')
    sub.add_parser('list', help='列出樣板')
    a = ap.parse_args()
    if a.cmd == 'list':
        for n, vs in sorted(load_tpl().items()):
            print(f'{n}: {len(vs)} 個變體')
        return 0
    if a.cmd == 'learn':
        return learn()
    t0 = time.time()
    d = read_detail()
    ms = int((time.time() - t0) * 1000)
    if a.json:
        print(json.dumps({'ms': ms, 'cards': d}, ensure_ascii=False))
    else:
        if not d:
            print('沒有樣板或截圖失敗（先 learn）')
        for s, r in sorted(d.items()):
            print(f'slot{s} {r["name"] or "None":6} score {r["score"]} second {r["second"]} ink {r["ink"]}')
        print(f'{ms} ms')
    return 0


if __name__ == '__main__':
    sys.exit(main())
