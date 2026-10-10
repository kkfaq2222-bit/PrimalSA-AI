#!/usr/bin/env python3
"""人物名 / 寵物名辨識（純函式 + 小類別，只用標準函式庫；watch.py 呼叫）。計畫：notes/plan-watch-state.md「第 7 階段」。

人物名：HUD 沒有名字，只有角色頭頂名牌（畫面中央，約截圖座標 660,420,120x30；ocr.ps1 -Light 200 -Zooms 2,3,4）。
  OCR 會把 D 讀成 0、結尾的 0 讀成 O（2026-10-10 實測 DKB0 讀成「DKBO」），所以比對一律先「正規化」再「完全比對白名單」：
  大寫、去空白、全部 O → 0、首字 0 → D；白名單（tools/.cache/watch-config.json 的 chars，不進 git）也用同一個正規化；
  兩個白名單名字正規化後相同 → 無法分辨，該名字不採用。連續 2 次讀到同一個名字才採用；讀不到沿用舊值（標 stale）。
  旁路 tools/.cache/current-char.json（切換角色的工具點完卡片後寫）為主、OCR 只核對：兩者不同時「較新的」勝出並標 conflict。
寵物名：HUD 只有頭像（立繪，跟 pet-images 圖鑑不是同一套）。用 `watch.py --learn-pet 名` 當下頭像取樣存庫，之後比對；沒學過 = '?'。
"""
import json
import re
from pathlib import Path

# ---- 人物名 ----
NAME_BOX = (660, 420, 120, 30)               # 截圖座標；掛機時角色固定在畫面中央，名牌在腳下
NAME_OCR_OPTS = ('-Light', '200', '-Zooms', '2,3,4')
NAME_SETTLE_S = 5.0                          # 旁路寫入後這麼久內的 OCR 不採用（切換動畫 / 舊角色名牌還在）
NAME_STALE_S = 15.0                          # 最近一次核對 / 寫入超過這麼久 → stale


def canon(s: str) -> str:
    """OCR 容錯正規化：大寫、去空白、O → 0、首字 0 → D（DKB0 / DKBO / 0KB0 / 0KBO 都變成 DKB0）"""
    t = re.sub(r'\s+', '', str(s or '')).upper().replace('O', '0')
    return ('D' + t[1:]) if t.startswith('0') else t


def canon_map(chars) -> dict:
    """白名單 → {正規化名: 原名}；正規化後撞名的整組丟掉（分不出來就不認）"""
    out: dict = {}
    dup = set()
    for c in chars or []:
        k = canon(c)
        if not k:
            continue
        if k in out and out[k] != c:
            dup.add(k)
        out[k] = c
    return {k: v for k, v in out.items() if k not in dup}


def match_texts(texts, cmap: dict):
    """一次 OCR 的所有文字行 → 白名單名字（原名）；沒有 / 同時命中不同名字（不確定）→ None。完全比對，不做相似度"""
    hits = {cmap[canon(t)] for t in texts if canon(t) in cmap}
    return next(iter(hits)) if len(hits) == 1 else None


class NameTracker:
    """OCR 結果累積器：連續 2 次一致才採用；讀不到沿用舊值。resolve() 合併旁路檔"""

    def __init__(self, chars=()):
        self.set_chars(chars)
        self.ocr_name = None
        self.ocr_ts = None
        self.cand = None
        self.cand_n = 0

    def set_chars(self, chars) -> None:
        self.cmap = canon_map(chars)

    def feed(self, texts, now: float, side_ts=None) -> bool:
        """傳入一次 OCR 的文字行；回 True = 這次有採用 / 更新（連續 2 次一致）。旁路剛寫入 NAME_SETTLE_S 內的讀數丟掉並重算"""
        if side_ts is not None and now < side_ts + NAME_SETTLE_S:
            self.cand, self.cand_n = None, 0
            return False
        name = match_texts(texts, self.cmap)
        if name is None:
            self.cand, self.cand_n = None, 0
            return False
        if name == self.cand:
            self.cand_n += 1
        else:
            self.cand, self.cand_n = name, 1
        if self.cand_n >= 2:
            self.ocr_name, self.ocr_ts = name, now
            return True
        return False

    def resolve(self, side, now: float) -> dict | None:
        """side = current-char.json 內容（{'name','ts'}）或 None → {'v','ts','src','stale'[, 'conflict']}；兩邊都沒有 → None"""
        s_ok = isinstance(side, dict) and isinstance(side.get('name'), str) and side['name'] and isinstance(side.get('ts'), (int, float))
        o_ok = self.ocr_name is not None
        if not s_ok and not o_ok:
            return None
        if s_ok:
            side = dict(side, name=self.cmap.get(canon(side['name']), side['name']))   # 旁路舊檔寫 DKB0 → 顯示白名單真名 DKBO
        if s_ok and o_ok:
            if canon(side['name']) == canon(self.ocr_name):
                v, ts, src, conflict = self.ocr_name, max(side['ts'], self.ocr_ts), 'both', False
            elif self.ocr_ts >= side['ts']:
                v, ts, src, conflict = self.ocr_name, self.ocr_ts, 'ocr', True
            else:
                v, ts, src, conflict = side['name'], side['ts'], 'sidecar', True
        elif s_ok:
            v, ts, src, conflict = side['name'], side['ts'], 'sidecar', False
        else:
            v, ts, src, conflict = self.ocr_name, self.ocr_ts, 'ocr', False
        out = {'v': v, 'ts': ts, 'src': src, 'stale': now - ts > NAME_STALE_S}
        if conflict:
            out['conflict'] = True
        return out


# ---- 寵物頭像 ----
AVATAR_PTS = [(x, y) for y in range(42, 84, 5) for x in range(294, 352, 6)]    # 頭像區（避開底下的等級字）10×9 = 90 點；2026-10-10 實測連讀 6 次 0 差異
AVATAR_MATCH = 10.0                          # 平均每通道絕對差 ≤ 這個才算同一隻（0～255）
AVATAR_MARGIN = 5.0                          # 第二名要比第一名至少大這麼多，否則不確定 → '?'
AVATAR_KEEP = 5                              # 每隻最多存幾個樣本


def avatar_arg() -> str:
    return ' '.join(f'{x},{y}' for x, y in AVATAR_PTS)


def parse_avatar(out: str):
    """gui pixel 輸出 → 指紋 [r,g,b,...]；點數不對 / 解析失敗 → None"""
    try:
        cols = [tuple(int(v) for v in c.split(',')) for c in (out or '').split()]
    except ValueError:
        return None
    if len(cols) != len(AVATAR_PTS) or any(len(c) != 3 for c in cols):
        return None
    return [v for c in cols for v in c]


def avatar_dist(a, b) -> float:
    return sum(abs(p - q) for p, q in zip(a, b)) / max(1, len(a))


def match_avatar(fp, lib: dict):
    """指紋 → 學過的寵物名；沒有夠近的 / 第二名太接近 → None（顯示 '?'，寧可不認）"""
    if not fp:
        return None
    best = []
    for name, samples in (lib or {}).items():
        ds = [avatar_dist(fp, s) for s in samples if isinstance(s, list) and len(s) == len(fp)]
        if ds:
            best.append((min(ds), name))
    best.sort()
    if not best or best[0][0] > AVATAR_MATCH:
        return None
    if len(best) > 1 and best[1][0] - best[0][0] < AVATAR_MARGIN:
        return None
    return best[0][1]


def load_avatars(path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, list)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def learn_avatar(lib: dict, name: str, fp) -> dict:
    """把樣本加進庫：和既有樣本幾乎一樣（< 2）就不重複存；每隻最多 AVATAR_KEEP 個（舊的先丟）"""
    lst = [s for s in lib.get(name, []) if isinstance(s, list)]
    if not any(len(s) == len(fp) and avatar_dist(fp, s) < 2.0 for s in lst):
        lst.append(list(fp))
    lib[name] = lst[-AVATAR_KEEP:]
    return lib
