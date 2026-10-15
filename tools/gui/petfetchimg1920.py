#!/usr/bin/env python3
r"""用「頭像顏色樣板」從寵物倉庫領回指定的寵物（1920×1017 專用；只用標準庫 + petdepot1920 / uikit）。

為什麼不用「永遠點第一格」：個人倉庫裡混著別的寵物，而且取出一隻後後面的會往前補位。
所以每領一隻都要：現場讀整頁 20 格 → 用樣板找目標 → 點選 → 取出 → 重新讀整頁 → 再找下一隻（每一隻都重新定位）。

樣板 = 每格頭像區 4×4 取樣點的 RGB（16 點）；不依賴名稱（剛抓的寵物名稱是四圍數字，OCR 讀不出種類）。
樣板檔：tools/.cache/petdepot-tpl.json（不進 git）。每種寵物第一次放進倉庫時用 learn 學一次。

用法（專案根目錄；先在遊戲開好寵物面板 → 倉庫 → 個人 / 公共分頁）：
  scan  --client kkfaq22222 [--tab personal|public]                     讀 20 格，印每格最像哪個樣板與距離（唯讀）
  learn --client kkfaq22222 --slot 3 --name 克邦凱斯 [--tab ...]          把第 3 格（1~20，由左到右由上到下）的頭像存成樣板「克邦凱斯」
  names --client kkfaq22222 [--tab ...]                                 唯讀：印 20 格名稱 OCR 與是否為數字名稱
  fetch --client kkfaq22222 --role 2 --numeric 3 [--do]                 領 3 隻「名稱是數字」的寵物（別的寵物都是本名，不用樣板）
  move  --client kkfaq22222 --role 3 --name 火雞 --n 4 [--do]            個人倉庫 → 公共：依樣板搬 N 隻（寵物欄須為空）
  storebar --client kkfaq22222 --role 2 --slots 2,3,4,5 [--do]          把寵物欄第 2~5 格存公共倉庫（第 1 格不動）
  snap  --client kkfaq22222 [--tab ...]                                 存入寵物「之前」先拍一次整頁
  learn --client kkfaq22222 --new --name 克邦凱斯 [--tab ...]             存入後跑：變動的那一格就是剛存的，直接學成「克邦凱斯」（名稱是數字時用這個）
  fetch --client kkfaq22222 --role 2 --names 克邦凱斯,加克拉,加格 [--tab personal] [--do]
        預設只預覽（找得到幾隻、在哪格），加 --do 才真的取出；每隻取完重新定位，數量不對就停手。

使用者規劃（2026-10-12）：角色 2 第一格留邦恩吉（第四輪抓的），只從個人倉庫領克邦凱斯 / 加克拉 / 加格；
角色 3 第一格留奇寶，只領火雞 / 克克洛斯 / 霍爾克。寵物欄第 2~5 格先存進個人倉庫再領。

座標（截圖 960×508，2026-10-12 實機量）：格子 5 欄 × 4 列，中心 x = 541 + 66.75*欄、y = 166 + 67*列；
個人 / 公共分頁 592,100 / 757,100；取出寵物 362,430（選中倉庫寵物時，和「存入寵物」同一個位置）。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
TPL_PATH = ROOT / 'tools' / '.cache' / 'petdepot-tpl.json'

COLS, ROWS = 5, 4
XS = [542, 608, 675, 742, 808]          # 與 petshark / petgive 同一組（實機校準）
YS = [170, 237, 303, 370]
STORE_BTN = (360, 430)                  # 選中寵物欄的寵物時是「存入寵物」
SAMPLE_DX = (-21, -7, 7, 21)           # 頭像區取樣（避開上方名稱字、下方等級字）
SAMPLE_DY = (-14, -4, 6, 16)
TAB = {'personal': (592, 100), 'public': (757, 100)}
TAKE_BTN = (362, 430)
SAME_SPECIES_MAX = 35.0                # 同一批同種寵物兩兩距離的上限（learn --new）
MATCH_MAX = 28.0                       # 平均每通道差距門檻（RGB 0~255）；超過就當作不是這個
AMBIG_MARGIN = 8.0                     # 最佳與「不同名稱」次佳至少差這麼多，否則判為不明確


# ---------- 純函式（離線測試用）----------
def slot_center(i: int):
    """第 i 格（0~19，由左到右由上到下）的中心 (x, y)"""
    return XS[i % COLS], YS[i // COLS]


def slot_points(i: int) -> list:
    cx, cy = slot_center(i)
    return [(cx + dx, cy + dy) for dy in SAMPLE_DY for dx in SAMPLE_DX]


def dist(a: list, b: list) -> float:
    """兩個向量（[(r,g,b)×16]）的平均每通道絕對差"""
    if not a or len(a) != len(b):
        return 999.0
    return sum(abs(p - q) for ca, cb in zip(a, b) for p, q in zip(ca, cb)) / (3 * len(a))


def best_match(vec: list, tpls: dict):
    """→ (名稱 or None, 距離, 狀態)；狀態 ok / far（太遠）/ ambiguous（最佳與次佳名稱太接近）/ none（沒樣板）"""
    if not tpls:
        return None, 999.0, 'none'
    ds = sorted((min(dist(vec, v) for v in vs), n) for n, vs in tpls.items())
    d0, n0 = ds[0]
    if d0 > MATCH_MAX:
        return None, d0, 'far'
    if len(ds) > 1 and ds[1][0] - d0 < AMBIG_MARGIN:
        return None, d0, 'ambiguous'
    return n0, d0, 'ok'


def is_numeric_name(text: str) -> bool:
    """剛抓的寵物名稱是四圍數字（例 49/10/5/4）；本名都是中文。數字 >= 3 個且中文字 <= 1 個才算。"""
    t = str(text or '')
    if re.match(r'^\s*\d{1,3}\s*/', t):          # 「31/7/3/9」名稱較長時 OCR 只讀到「31/」（2026-10-13 11111 火雞）
        return True
    if t.strip().upper() in ('11', 'WW'):        # 抓完第一隻改名 WW（遊戲名字至少 2 字；使用者 2026-10-13）：之後只領名字是 WW 的（舊的 11 也認）
        return True
    digits = sum(ch.isdigit() for ch in t)
    cjk = sum('一' <= ch <= '鿿' for ch in t)
    return digits >= 3 and cjk <= 1


def load_tpls() -> dict:
    try:
        d = json.loads(TPL_PATH.read_text(encoding='utf-8'))
        return {n: [[tuple(c) for c in v] for v in vs] for n, vs in d.items()}
    except (OSError, ValueError):
        return {}


def save_tpls(t: dict) -> None:
    TPL_PATH.parent.mkdir(parents=True, exist_ok=True)
    TPL_PATH.write_text(json.dumps(t, ensure_ascii=False), encoding='utf-8')


# ---------- 遊戲操作 ----------
def take_label_ok() -> bool:
    """選中的是倉庫寵物時左下按鈕是「取出寵物」；若選取還停在寵物欄的寵物上，同位置是「存入寵物」，點下去會把自己的寵物存走
    （2026-10-12 角色 1 的克邦凱斯因此被存走）。按之前一定要確認。"""
    import uikit
    t = ''.join(uikit.ocr((300, 412, 125, 36), '-Zooms', '2,3'))
    return '取出' in t or ('取' in t and '存' not in t)


TAB_PROBE = {'personal': (560, 96), 'public': (790, 96)}   # 選中的分頁是亮黃 (251,219,135)，沒選中是棕 (171,127,84)


def tab_on(tab: str) -> bool:
    import uikit
    c = uikit.px([TAB_PROBE[tab]])
    return bool(c) and c[0][0] > 225 and c[0][1] > 190


def ensure_tab(tab: str, tries: int = 3) -> bool:
    """倉庫的「個人 / 公共」分頁一定要真的切到才存 / 取：遊戲偶爾吃掉點擊，存入就會進錯倉庫
    （2026-10-12 角色 5 的 3 隻貝魯卡被存進個人倉庫，公共只有 1 隻）"""
    import time as _t
    import petdepot1920 as pd
    for _ in range(tries):
        if tab_on(tab):
            return True
        pd.click(*TAB[tab], wait=900, note=f'petfetchimg 切到{tab}分頁')
        _t.sleep(0.3)
    return tab_on(tab)


def ensure_take_ready(x: int, y: int) -> bool:
    """點選倉庫格後按鈕要變成「取出寵物」。遊戲偶爾吃掉這一下點擊（或標籤還沒更新）：
    先等一下重讀，還不是就重點該格（最多 2 次），仍不是才放棄（不會去按「存入寵物」）。"""
    import time as _t
    import petdepot1920 as pd
    for k in range(3):
        _t.sleep(0.4)
        if take_label_ok():
            return True
        if k < 2:
            pd.click(x, y, wait=800, note=f'petfetchimg 重點倉庫格（第 {k + 1} 次重試）')
    return False


def read_grid():
    """一次讀 20 格 → [vec×20]；讀不到回 None"""
    import uikit
    pts = [p for i in range(COLS * ROWS) for p in slot_points(i)]
    cols = uikit.px(pts)
    if not cols:
        return None
    n = len(SAMPLE_DX) * len(SAMPLE_DY)
    return [cols[i * n:(i + 1) * n] for i in range(COLS * ROWS)]


def name_box(i: int):
    cx, cy = slot_center(i)
    return (cx - 32, cy - 31, 64, 20)       # 格子上方名稱字（寵物名疊在頭像上緣）


def read_names(only_filled=None):
    """20 格名稱 OCR → [str×20]（空格回 ''）；唯讀"""
    import uikit
    out = []
    for i in range(COLS * ROWS):
        if only_filled is not None and i not in only_filled:
            out.append('')
            continue
        try:
            out.append(''.join(uikit.ocr(name_box(i), '-Zooms', '2,3')).strip())
        except Exception:
            out.append('')
    return out


def bar_filled():
    import petdepot1920 as pd
    return [i for i in range(5) if not pd.slot_empty(i)]


PET_TAB_XY = (884, 150)          # 寵物面板左上「寵物」分頁（questflow.PET_TAB）
NAME_INK_PTS = [(x, y) for y in range(96, 124, 2) for x in range(230, 450, 2)]   # 名稱區（避開右邊鉛筆圖示）
WW_WIDTH_MAX = 26                # 名稱字的左右寬度（px，截圖座標）；WW 14~20
WW_INK_MAX = 60                  # 白點數 <= 此值 = 短名（WW / 11）；實測 WW 12~29、數字名 115+、中文名 123+（2026-10-14）


# ---- 外型簽名（忽略顏色；使用者 2026-10-14：名稱 / 白點數值偶爾量錯，加外型取最像的）----
# 頭像區灰階 -> 邊緣強度（|dx|+|dy|）-> 與樣板做正規化相關（NCC，-1~1）。邊緣不看底色，同系不同色的寵物也像。
SHAPE_XS = list(range(-22, 23, 2))
SHAPE_YS = list(range(-20, 15, 2))
SHAPE_OK_DEPOT = 0.40  # 倉庫格門檻（實測 2026-10-14：倉庫鯊魚 vs 倉庫樣板 0.49~0.82，其他寵物最高 0.29）
SHAPE_OK = 0.30        # 與任一樣板的相關 >= 此值才算「像」（實測：鯊魚彼此 0.39~0.78，鯊魚 vs 其他寵物 -0.13~0.14）


def shape_vec_from(cols) -> list:
    """cols = 該格 (len(SHAPE_YS) x len(SHAPE_XS)) 個 (r,g,b)，逐列 -> 邊緣強度向量"""
    w, h = len(SHAPE_XS), len(SHAPE_YS)
    lum = [[0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2] for c in cols[j * w:(j + 1) * w]] for j in range(h)]
    return [abs(lum[y][x + 1] - lum[y][x - 1]) + abs(lum[y + 1][x] - lum[y - 1][x])
            for y in range(1, h - 1) for x in range(1, w - 1)]


def shape_vecs(centers) -> list:
    """多個格子中心 -> [向量 or None, ...]（一次讀完，px 會自動分批）"""
    import uikit
    pts = [(cx + dx, cy + dy) for cx, cy in centers for dy in SHAPE_YS for dx in SHAPE_XS]
    cols = uikit.px(pts)
    n = len(SHAPE_XS) * len(SHAPE_YS)
    if not cols or len(cols) != len(pts):
        return [None] * len(centers)
    return [shape_vec_from(cols[i * n:(i + 1) * n]) for i in range(len(centers))]


def ncc(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da, db = [v - ma for v in a], [v - mb for v in b]
    na, nb = sum(v * v for v in da) ** 0.5, sum(v * v for v in db) ** 0.5
    return sum(x * y for x, y in zip(da, db)) / (na * nb) if na and nb else 0.0


def shape_path(family: str) -> Path:
    return ROOT / 'tools' / '.cache' / f'petshape-{family}.json'


def load_shape(family: str, where: str = 'bar') -> list:
    """where = bar（寵物欄）/ depot（倉庫格）：兩處畫面比例、背景不同，樣板分開存（使用者 2026-10-14）。舊檔的 vecs = bar"""
    try:
        d = json.loads(shape_path(family).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return d.get(where) or (d.get('vecs', []) if where == 'bar' else [])


def shape_score(vec, tpls: list) -> float:
    """與樣板的最大相關；沒樣板 / 讀不到 = -1"""
    if vec is None or not tpls:
        return -1.0
    return max(ncc(vec, t) for t in tpls)


WW_REF = (26, 15)                # WW 名稱區的 (白點數, 左右寬度) 參考值（實測 WW：23~29 / 14~16）
SCORE_OK = 1.0                   # 分數 <= 此值才算「像」；中文本名（含 1 級）實測 > 3


def similarity_score(ink: int, width: int, txt: str) -> float:
    """越小越像「WW / 數字名」：OCR 讀到數字名 = 0；否則看白點數 + 寬度離 WW 參考值多遠（不是各項都過門檻）"""
    if is_numeric_name(txt):
        return 0.0
    if not ink:
        return 9.0
    return abs(ink - WW_REF[0]) / WW_REF[0] + abs(width - WW_REF[1]) / WW_REF[1]


def _measure_selected() -> tuple:
    """量一次目前選中那隻的名稱區 → (是否, 白點數, 寬度, OCR 文字, 相似度)"""
    import uikit
    cols = uikit.px(NAME_INK_PTS) or []
    xs = [NAME_INK_PTS[j][0] for j, (r, g, b) in enumerate(cols) if r > 200 and g > 170]
    ink = len(xs)
    width = (max(xs) - min(xs)) if xs else 0
    if xs and similarity_score(ink, width, '') <= SCORE_OK:
        return True, ink, width, '', similarity_score(ink, width, '')
    import questflow1920 as qf
    txt = ''
    for opts in (('-Zooms', '3,4'), ('-Zooms', '2,3'), ('-Zooms', '3,4', '-Dark', '130'), ('-Zooms', '3,4', '-Dark', '0')):
        try:
            t = ''.join(uikit.ocr(qf.PET_NAME_BOX, *opts))
        except Exception:
            t = ''
        if is_numeric_name(t):
            return True, ink, width, t, 0.0
        txt = txt or t
    return False, ink, width, txt, similarity_score(ink, width, txt)


def selected_is_short_or_numeric(tries: int = 3) -> tuple:
    """目前選中的那隻寵物，名稱是不是 WW / 數字名 → (是否, 白點數, 寬度, OCR 文字)。
    WW：名稱區白字少且窄（量字的範圍，不靠 OCR）；數字名：多種倍率 OCR 讀名稱框，像「31/7/3/9」。
    中文本名（含 1 級寵物）= 否。點選後名稱欄偶爾還沒換完就量到舊畫面（2026-10-14 兩個客戶端同時跑，
    第 3 隻 WW 量成 31 / 64 被當本名）→ 量起來不像就等一下重量，最多 tries 次，取最像的那次。"""
    import time as _t
    best = None
    for k in range(tries):
        r = _measure_selected()
        if r[0]:
            return r[:4]
        if best is None or r[4] < best[4]:
            best = r
        if r[4] >= 5.0:          # 離 WW 很遠（中文本名實測 6.5 以上）→ 不用重量，省時間
            break
        if k < tries - 1:
            _t.sleep(0.6)
    return best[:4]


STRONG_SCORE = 1.0     # 相似度 <= 此值 = 非常像，倉庫掃描可以提早停（實測 2026-10-15 333：目標 0.18、其他寵物最低 4.39）


def depot_numeric_slots(shape_tpls: list = None, stop_at: float = None) -> list:
    """倉庫目前這一頁，名稱是 WW / 數字名的格（0 起算）：逐隻點選後量名稱區（舊的靠格子上緣小字 OCR，WW 讀不到）。
    stop_at：碰到相似度 <= stop_at 的格就不再往下點（外型像的排前面，通常第 1 格就中；
    2026-10-15 使用者：333 每領一隻都把 16 格全點一遍、約 40 秒，太浪費時間）"""
    import petdepot1920 as pd
    import uikit
    pts, spans = [], []
    for i in range(COLS * ROWS):          # 非空格：卡片底部有綠色「0轉N級」字（空格只有腳印圖；不靠「空」樣板，沒學過也能用）
        cx, cy = slot_center(i)
        p = [(cx - 30 + dx, cy + 4 + dy) for dy in range(0, 28, 2) for dx in range(0, 61, 3)]
        spans.append((len(pts), len(pts) + len(p)))
        pts += p
    cols = uikit.px(pts) or []
    if len(cols) != len(pts):
        return []
    filled = [i for i, (s0, e0) in enumerate(spans)
              if sum(1 for r, g, b in cols[s0:e0] if g > 150 and g - r > 50 and g - b > 90) >= 4]
    shapes = dict(zip(filled, shape_vecs([slot_center(i) for i in filled]))) if shape_tpls else {}
    # 外型像的先看；其他格仍然看（樣板是在欄位錄的，倉庫格的畫面比例可能略有不同，當保險）
    order = sorted(filled, key=lambda i: -shape_score(shapes.get(i), shape_tpls or []))
    out = []
    for i in order:
        x, y = slot_center(i)
        pd.click(x, y, wait=700, note=f'petfetchimg 看倉庫第 {i + 1} 格名稱')
        hit, ink, width, txt = selected_is_short_or_numeric()
        sc = similarity_score(ink, width, txt)
        sh = shape_score(shapes.get(i), shape_tpls or [])
        if sh >= SHAPE_OK_DEPOT:
            hit = True
            sc = min(sc, 3 * (1 - sh))           # 外型與名稱分數取較像的那個
        if hit:
            out.append((sc, i))
        pd.log(f'  倉庫第 {i + 1} 格：白點 {ink}、寬 {width}、OCR {txt!r}、外型 {sh:.2f} → 相似度 {sc:.2f}{"（像）" if hit else ""}')
        if hit and stop_at is not None and sc <= stop_at:
            pd.log(f'  第 {i + 1} 格非常像（{sc:.2f} <= {stop_at}）→ 不再往下看')
            break
    return [i for _, i in sorted(out)]       # 最像的排前面（同分取格序小的）


def bar_numeric_count(role: int, shape_tpls: list = None) -> int:
    """目前寵物欄裡「WW / 數字名」的隻數（逐隻點選後比相似度；不單靠 OCR 認 WW）。呼叫前面板要在「寵物」分頁。"""
    import petdepot1920 as pd
    n = 0
    filled = [i for i in range(5) if not pd.slot_empty(i)]
    vecs = dict(zip(filled, shape_vecs([(pd.SLOT_X, pd.SLOT_Y[i]) for i in filled]))) if shape_tpls else {}
    for i in filled:
        pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=800, note=f'petfetchimg 看寵物欄第 {i + 1} 格名稱')
        hit, ink, width, txt = selected_is_short_or_numeric()
        sh = shape_score(vecs.get(i), shape_tpls or [])
        if not hit and sh >= SHAPE_OK:           # 名稱量不像，但外型像（名稱欄沒換完 / OCR 失敗）-> 以外型為準
            hit = True
        pd.log(f'  寵物欄第 {i + 1} 格：白點 {ink}、寬 {width}、OCR {txt!r}、外型 {sh:.2f} -> 相似度 {similarity_score(ink, width, txt):.2f}'
               f'{"（WW/數字名）" if hit else "（本名）"}')
        n += hit
    return n


def goto(role: int, tab: str, count_bar: bool = False, shape_tpls: list = None):
    import petdepot1920 as pd
    try:                                    # 外掛面板還開著（catchrun 剛抓完）會蓋住寵物鈕 → 寵物面板打不開（2026-10-12 火雞 r1）
        import ass
        if ass.panel_open():
            ass.close_panel()
    except Exception:
        pass
    if not pd.open_panel():
        raise SystemExit('寵物面板打不開')
    other = 0 if role != 1 else 1          # 先切到別的角色再切回來才會刷新寵物欄（剛抓完的第 5 隻否則還顯示空格；2026-10-12 實測）
    pd.click(pd.ROLE_X, pd.ROLE_Y[other], wait=900, note='petfetchimg 先切別人（刷新）')
    pd.click(pd.ROLE_X, pd.ROLE_Y[role - 1], wait=1200, note=f'petfetchimg 選角色 {role}')
    have = None
    if count_bar:
        pd.click(*PET_TAB_XY, wait=900, note='petfetchimg 寵物分頁')
        have = bar_numeric_count(role, shape_tpls)
    pd.click(*pd.TAB_DEPOT, wait=1300, note='petfetchimg 倉庫分頁')
    pd.click(*TAB[tab], wait=900, note=f'petfetchimg {tab} 分頁')
    if not ensure_tab(tab):
        raise SystemExit(f'倉庫{tab}分頁切不過去 → 停手（不存、不取）')
    return have


def close_pet_panel_if_open() -> None:
    try:
        import petdepot1920 as pd
        for _ in range(3):
            if not pd.panel_open():
                return
            pd.click(*pd.CLOSE_X, wait=700, note='petfetchimg 關寵物面板')
    except Exception:
        pass


def maybe_open(a):
    """--open-role N：先開寵物面板、選角色 N、倉庫、--tab 分頁（沒給就用目前畫面）"""
    if getattr(a, 'open_role', 0):
        goto(a.open_role, a.tab)


def cmd_scan(a):
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    tpls = load_tpls()
    print(f'樣板：{", ".join(tpls) or "（無）"}')
    for i, vec in enumerate(grid):
        n, d, st = best_match(vec, tpls)
        print(f'  第 {i + 1:2d} 格  {n or "-":<8} 距離 {d:5.1f}  {st}')
    return 0


def cmd_names(a):
    """唯讀：印 20 格名稱 OCR 與是否判為數字名稱（先用它確認 OCR 讀得準，再用 fetch --numeric）"""
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    tpls = load_tpls()
    names = read_names()
    for i, (nm, vec) in enumerate(zip(names, grid)):
        empty = best_match(vec, {'空': tpls['空']})[0] == '空' if '空' in tpls else None
        print(f'  第 {i + 1:2d} 格  {nm!r:<24} 數字名稱={is_numeric_name(nm)}' + ('' if empty is None else f'  空格={empty}'))
    return 0


def snap_path(a) -> Path:
    return ROOT / 'tools' / '.cache' / f'petdepot-snap-{a.client}-{a.tab}.json'


def cmd_snap(a):
    """存入寵物「之前」先拍一次整頁（learn --new 用來找出剛存進去的那一格）"""
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    snap_path(a).parent.mkdir(parents=True, exist_ok=True)
    snap_path(a).write_text(json.dumps(grid), encoding='utf-8')
    print(f'已拍下 {a.tab} 倉庫整頁（存入寵物後再跑 learn --new --name 名稱）')
    return 0


def changed_slots(old: list, new: list, thr: float = 12.0) -> list:
    """兩次整頁快照之間「頭像變了」的格號（0 起算）"""
    return [i for i, (o, n) in enumerate(zip(old, new)) if dist([tuple(c) for c in o], n) > thr]


def cmd_learn(a):
    if not a.name:
        print('要用 --name 指定名稱')
        return 2
    maybe_open(a)
    grid = read_grid()
    if grid is None:
        print('讀不到畫面')
        return 3
    if a.new:
        try:
            old = json.loads(snap_path(a).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            print('沒有存入前的快照：先在存入寵物前跑 snap')
            return 2
        ch = changed_slots(old, grid)
        # 同一種寵物的頭像會有動作 / 位置差（實測 4 隻火雞兩兩差 3~22、不同種差 70 以上）→ 門檻 35
        if not ch or any(dist(grid[ch[0]], grid[j]) > SAME_SPECIES_MAX for j in ch[1:]):
            print(f'變動的格子 {[i + 1 for i in ch]} 不是同一種（或沒有變動）→ 不學，請改用 --slot 指定')
            return 5
        a.slot = ch[0] + 1
        print(f'剛存進去的是第 {a.slot} 格')
    vecs = [grid[i] for i in ch] if a.new else [grid[a.slot - 1]]   # --new：剛存進去的每一隻都當變體（涵蓋頭像動作差）
    tpls = load_tpls()
    tpls.setdefault(a.name, [])
    added = 0
    for vec in vecs:
        if any(dist(vec, v) < 3.0 for v in tpls[a.name]):
            continue
        if len(tpls[a.name]) >= 6:
            tpls[a.name].pop(0)
        tpls[a.name].append(vec)
        added += 1
    save_tpls(tpls)
    print(f'已存「{a.name}」樣板（新增 {added} 個，共 {len(tpls[a.name])} 個變體）')
    return 0


def cmd_storebar(a):
    """把角色 --role 寵物欄的 --slots（1~5，例 2,3,4,5）存進 --tab 倉庫（預設公共）；從大號往小號存（存了不影響前面格位）"""
    import time
    import petdepot1920 as pd
    slots = sorted({int(x) for x in a.slots.split(',') if x.strip()}, reverse=True)
    if not slots or not all(1 <= x <= 5 for x in slots):
        print('--slots 要寫 1~5，例如 2,3,4,5')
        return 2
    tab = 'public' if a.tab == 'personal' and not a.tab_given else a.tab
    goto(a.role, tab)
    for sl in slots:
        if pd.slot_empty(sl - 1):
            print(f'寵物欄第 {sl} 格是空的 → 停手')
            return 4
        pd.log(f'角色 {a.role} 欄 {sl} → {tab} 倉庫' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        pd.click(pd.SLOT_X, pd.SLOT_Y[sl - 1], wait=700, note=f'petfetchimg 選欄 {sl}')
        if not ensure_tab(tab):
            print(f'倉庫{tab}分頁不在選中狀態 → 不存、停手')
            return 6
        pd.click(*STORE_BTN, wait=1000, note='petfetchimg 存入寵物')
        for _ in range(10):
            if pd.warn_dialog():
                pd.click(*pd.WARN_OK, wait=1000, note='petfetchimg 提示窗確定')
            if pd.slot_empty(sl - 1):
                break
            time.sleep(0.5)
        if not pd.slot_empty(sl - 1):
            print(f'欄 {sl} 存不進去 → 停手')
            return 5
    pd.log('完成' if a.do else '預覽結束（加 --do 才真的存）')
    return 0


def cmd_move(a):
    """個人倉庫 → 公共倉庫：依樣板找出 --name 的寵物 --n 隻，逐隻「取出到寵物欄第 1 格 → 存入公共」（寵物欄必須是空的）"""
    import petdepot1920 as pd
    tpls = load_tpls()
    if a.name not in tpls:
        print(f'沒有「{a.name}」樣板（先用 learn 學）')
        return 2
    goto(a.role, 'personal')
    if bar_filled():
        print('寵物欄不是空的 → 停手')
        return 4
    for k in range(1, a.n + 1):
        pd.click(*TAB[a.tab], wait=800, note='petfetchimg 來源分頁')
        grid = read_grid()
        if grid is None:
            print('讀不到畫面 → 停手')
            return 3
        hits = [(d, i) for i, v in enumerate(grid) for n, d, st in [best_match(v, tpls)] if n == a.name]
        if not hits:
            print(f'找不到「{a.name}」→ 停手（已搬 {k - 1} 隻）')
            return 5
        d, i = min(hits)
        pd.log(f'第 {k}/{a.n} 隻「{a.name}」在第 {i + 1} 格（距離 {d:.1f}）' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        x, y = slot_center(i)
        pd.click(x, y, wait=800, note=f'petfetchimg 選第 {i + 1} 格')
        if not ensure_take_ready(x, y):
            print('按鈕不是「取出寵物」→ 不按、停手')
            return 8
        pd.click(*TAKE_BTN, wait=1100, note='petfetchimg 取出寵物')
        for _ in range(8):
            if not pd.slot_empty(0):
                break
            import time
            time.sleep(0.5)
        if pd.slot_empty(0):
            print('取出後欄 1 仍空 → 停手')
            return 6
        pd.click(*TAB['public'], wait=800, note='petfetchimg 公共分頁')
        pd.click(pd.SLOT_X, pd.SLOT_Y[0], wait=700, note='petfetchimg 選欄 1')
        pd.click(*STORE_BTN, wait=1000, note='petfetchimg 存入公共')
        for _ in range(8):
            if pd.slot_empty(0):
                break
            import time
            time.sleep(0.5)
        if not pd.slot_empty(0):
            print('存入公共後欄 1 仍有寵物 → 停手')
            return 7
    pd.log(f'完成：搬了 {a.n} 隻「{a.name}」到公共' if a.do else '預覽結束（加 --do 才真的搬）')
    return 0


SHORT_INK = (10, 30)     # 名稱列白字取樣點數：「11」約 17~19、中文本名 54~77、空格 <= 17（所以要再排除空格）


def name_ink_all() -> list:
    """20 格名稱列的白字取樣點數 [int×20]（OCR 讀不出「11」這種短名，改看字的多寡；唯讀）"""
    import uikit
    pts, spans = [], []
    for i in range(COLS * ROWS):
        x0, y0, w, h = name_box(i)
        p = [(x0 + dx, y0 + dy) for dy in range(0, h, 2) for dx in range(0, w, 2)]
        spans.append((len(pts), len(pts) + len(p)))
        pts += p
    cols = uikit.px(pts) or []
    if len(cols) != len(pts):
        return [0] * (COLS * ROWS)
    return [sum(1 for r, g, b in cols[s:e] if r > 215 and g > 215 and b > 215) for s, e in spans]


def short_named_slots(names: list) -> list:
    """名字是「11」的格（0 起算）：非空格 + 白字數在 SHORT_INK + OCR 沒讀出 2 個以上中文字"""
    import uikit
    ink = name_ink_all()
    pts, spans = [], []
    for i in range(COLS * ROWS):          # 非空格：卡片底部有綠色「0轉N級」字（空格只有腳印圖）
        cx, cy = slot_center(i)
        p = [(cx - 30 + dx, cy + 4 + dy) for dy in range(0, 28, 2) for dx in range(0, 61, 3)]
        spans.append((len(pts), len(pts) + len(p)))
        pts += p
    cols = uikit.px(pts) or []
    if len(cols) != len(pts):
        return []
    out = []
    for i, (s, e) in enumerate(spans):
        green = sum(1 for r, g, b in cols[s:e] if g > 150 and g - r > 50 and g - b > 90)
        if green < 4:
            continue
        cjk = sum('一' <= ch <= '鿿' for ch in str(names[i]))
        if SHORT_INK[0] <= ink[i] <= SHORT_INK[1] and cjk <= 1:
            out.append(i)
    return out


def cmd_fetch_numeric(a):
    """領「名稱是數字」的寵物 N 隻（別的寵物都是本名，不會錯亂）：每領一隻重新讀整頁名稱、重新定位
    數字名稱 = OCR 讀到的四圍數字（31/7/3/9），或名字被改成「11」的短名（OCR 讀不出來，改看字的多寡）"""
    import petdepot1920 as pd
    tpls = load_shape(a.shape, 'bar') if a.shape else []
    dtpls = load_shape(a.shape, 'depot') if a.shape else []
    if a.shape:
        pd.log(f'外型樣板「{a.shape}」：欄位 {len(tpls)} 張、倉庫 {len(dtpls)} 張' + ('' if (tpls or dtpls) else '（沒有 -> 只用名稱判斷）'))
    have = goto(a.role, a.tab, count_bar=bool(a.want_total), shape_tpls=tpls)
    need = a.numeric
    if a.want_total:           # 使用者 2026-10-14：重跑要先數寵物欄現有幾隻，只領還缺的（不是每次都領 --numeric 隻）
        need = max(0, min(a.numeric, a.want_total - have))
        pd.log(f'寵物欄已有 WW / 數字名 {have} 隻，目標總數 {a.want_total} → 還要領 {need} 隻')
        if need == 0:
            pd.log('已經夠了，不用再領')
            close_pet_panel_if_open()
            return 0
    before = bar_filled()
    free = 5 - len(before)
    pd.log(f'角色 {a.role} 寵物欄 {len(before)} 隻、空 {free} 格；要領 {need} 隻數字名稱寵物（{a.tab}）')
    if free < need:
        print('寵物欄空格不夠 → 停手')
        return 4
    taken = 0
    for k in range(1, need + 1):
        hits = depot_numeric_slots(dtpls, stop_at=STRONG_SCORE)
        names = [''] * (COLS * ROWS)
        if not hits:
            print(f'找不到數字名稱的寵物 → 停手（已領 {taken} 隻）')
            return 5
        i = hits[0]
        pd.log(f'第 {k}/{need} 隻：第 {i + 1} 格 {names[i]!r}（共 {len(hits)} 隻數字名稱）' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        x, y = slot_center(i)
        pd.click(x, y, wait=800, note=f'petfetchimg 選第 {i + 1} 格')
        if not ensure_take_ready(x, y):
            print('按鈕不是「取出寵物」→ 不按、停手')
            return 8
        pd.click(*TAKE_BTN, wait=1200, note='petfetchimg 取出寵物')
        now = bar_filled()
        if len(now) != len(before) + taken + 1:
            print(f'取出後寵物欄數量不對（{len(now)}）→ 停手')
            return 6
        taken += 1
    pd.log(f'完成：領回 {taken} 隻' if a.do else '預覽結束（加 --do 才真的取出）')
    return 0


def cmd_shape_learn(a):
    """錄製外型樣板：目前寵物欄（--role）裡每一隻（非空格）都存成 --shape 這個系別的樣板。
    先確認那幾隻就是該系的（鯊魚：角色 2 欄位 4 隻）。只讀畫面，存到 tools/.cache/petshape-<系別>.json（不進 git）。"""
    import petdepot1920 as pd
    if not a.shape:
        print('要給 --shape 系別（shark / bird）')
        return 2
    goto(a.role, a.tab)
    if a.where == 'depot':           # 倉庫格：--slots 指定倉庫第幾格（1~20）是這個系別的寵物
        idx = [int(x) - 1 for x in a.slots.split(',') if x.strip()]
        if not idx:
            print('--where depot 要給 --slots（倉庫格序，例 2,5）')
            return 2
        filled = idx
        vecs = shape_vecs([slot_center(i) for i in idx])
    else:
        filled = [i for i in range(5) if not pd.slot_empty(i)]
        vecs = shape_vecs([(pd.SLOT_X, pd.SLOT_Y[i]) for i in filled])
    if not filled or any(v is None for v in vecs):
        print('讀不到寵物欄 -> 停手')
        return 3
    for k in range(len(vecs)):
        sims = [round(ncc(vecs[k], vecs[j]), 2) for j in range(len(vecs))]
        pd.log(f'  寵物欄第 {filled[k] + 1} 格：{len(vecs[k])} 維；彼此相關 {sims}')
    try:
        d = json.loads(shape_path(a.shape).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        d = {}
    if 'vecs' in d and 'bar' not in d:
        d['bar'] = d.pop('vecs')
    d.update({'family': a.shape, a.where: vecs})
    shape_path(a.shape).write_text(json.dumps(d), encoding='utf-8')
    pd.log(f'已存 {len(vecs)} 張外型樣板 -> {shape_path(a.shape).name}')
    return 0


def cmd_fetch(a):
    if a.numeric:
        return cmd_fetch_numeric(a)
    import petdepot1920 as pd
    tpls = load_tpls()
    names = [n.strip() for n in a.names.split(',') if n.strip()]
    missing = [n for n in names if n not in tpls]
    if missing:
        print(f'沒有這些樣板：{missing}（先用 learn 學）')
        return 2
    goto(a.role, a.tab)
    before = bar_filled()
    free = 5 - len(before)
    pd.log(f'角色 {a.role} 寵物欄 {len(before)} 隻、空 {free} 格；要領 {len(names)} 隻（{a.tab}）')
    if free < len(names):
        print('寵物欄空格不夠 → 停手')
        return 4
    taken = 0
    for k, name in enumerate(names, 1):
        grid = read_grid()
        if grid is None:
            print('讀不到畫面 → 停手')
            return 3
        hits = []
        for i, vec in enumerate(grid):
            n, d, st = best_match(vec, tpls)       # 對全部樣板比，避免把別種誤認成目標
            if n == name:
                hits.append((d, i))
        if not hits:
            print(f'找不到「{name}」→ 停手（已領 {taken} 隻）')
            return 5
        d, i = min(hits)
        pd.log(f'第 {k}/{len(names)} 隻「{name}」在第 {i + 1} 格（距離 {d:.1f}）' + ('' if a.do else '  [預覽]'))
        if not a.do:
            continue
        x, y = slot_center(i)
        pd.click(x, y, wait=800, note=f'petfetchimg 選第 {i + 1} 格「{name}」')
        if not ensure_take_ready(x, y):
            print('按鈕不是「取出寵物」→ 不按、停手')
            return 8
        pd.click(*TAKE_BTN, wait=1200, note='petfetchimg 取出寵物')
        now = bar_filled()
        if len(now) != len(before) + taken + 1:
            print(f'取出後寵物欄數量不對（{len(now)}）→ 停手')
            return 6
        taken += 1
    pd.log(f'完成：領回 {taken} 隻' if a.do else '預覽結束（加 --do 才真的取出；預覽時清單沒變，同種多隻會都指到同一格）')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='用頭像樣板從倉庫領回指定寵物')
    ap.add_argument('cmd', choices=['scan', 'names', 'snap', 'learn', 'fetch', 'move', 'storebar', 'shape-learn'])
    ap.add_argument('--client', default='kkfaq22222')
    ap.add_argument('--tab', choices=list(TAB), default=None)
    ap.add_argument('--slots', default='')
    ap.add_argument('--open-role', type=int, default=0, help='scan / names / snap / learn：先開面板並切到這個角色的倉庫')
    ap.add_argument('--slot', type=int, default=1)
    ap.add_argument('--name', default='')
    ap.add_argument('--role', type=int, default=2)
    ap.add_argument('--names', default='')
    ap.add_argument('--new', action='store_true', help='learn：用 snap 的快照找出剛存進去的那一格')
    ap.add_argument('--numeric', type=int, default=0, help='fetch：領名稱是數字的寵物 N 隻（不用樣板）')
    ap.add_argument('--want-total', type=int, default=0, help='fetch --numeric：寵物欄目標總隻數（WW / 數字名）；先數現有的，只領缺的')
    ap.add_argument('--where', choices=['bar', 'depot'], default='bar', help='shape-learn：錄寵物欄（bar）還是倉庫格（depot，要 --slots）')
    ap.add_argument('--shape', default='', help='外型樣板系別（shark / bird）：fetch 時加外型判斷；shape-learn 時錄製')
    ap.add_argument('--n', type=int, default=4)
    ap.add_argument('--do', action='store_true')
    a = ap.parse_args(argv)
    a.tab_given = a.tab is not None
    a.tab = a.tab or 'personal'
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    winenv.enable_server()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    fn = {'scan': cmd_scan, 'names': cmd_names, 'snap': cmd_snap, 'learn': cmd_learn, 'fetch': cmd_fetch, 'move': cmd_move, 'storebar': cmd_storebar, 'shape-learn': cmd_shape_learn}[a.cmd]
    try:
        return fn(a)
    finally:
        close_pet_panel_if_open()      # 不留著面板（會蓋住外掛按鈕，後面的抓寵就打不開外掛面板；2026-10-12 火雞 r3）


if __name__ == '__main__':
    sys.exit(main())
