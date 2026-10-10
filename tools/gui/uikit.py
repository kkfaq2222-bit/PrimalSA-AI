#!/usr/bin/env python3
"""腳本化流程（team / grind / char / pet）共用零件（只用標準函式庫）。計畫：notes/plan-scriptify.md §1.2。

安全原則（鐵則 2~5、SKILL.md）：
- 面板內點擊一律經 safe_click：面板特徵不在 → 不點（回 False，避免背景點擊穿透到地面走路）；點到 FORBIDDEN 矩形 → 丟 ForbiddenClick。
- preflight：版面、netwatch、戰鬥鎖、畫面連 3 次不認得（疑似驗證視窗）→ 退出 9 停手通知使用者。
- 名字比對「對不上就拒絕」：人物名走 charstate.norm_char（= charname 的正規化，與 watch 同一套）；寵物名 snap_pet 對 Monster 表。
所有會碰遊戲的函式都走模組層級的 gui / sleep / clock（測試可替換）；匯入本模組不會碰遊戲。
"""
import difflib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import charstate  # noqa: E402
import screen_sigs  # noqa: E402
import winenv  # noqa: E402

ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'
SHOT_DIR = CACHE / 'ui-log'
SHOT_KEEP_DAYS = 3
MONSTER_TABLE = ROOT / 'knowledge' / 'data' / 'tables' / 'Monster.jsonl'

# ---- 退出碼（共用；各工具自己的段：team 40～47、grind 50～59、char 60～65、pet 70～79）----
EXIT_OK, EXIT_USAGE, EXIT_LAYOUT = 0, 1, 2
EXIT_IN_BATTLE = 8               # 戰鬥中或 quest 鎖檔（同 ass.EXIT_IN_BATTLE 語意）
EXIT_UNKNOWN_SCREEN = 9          # 疑似驗證 / 不認得的畫面：停手通知使用者
EXIT_HALT = 10                   # netwatch halt（netwatch.guard 自己 sys.exit）
LAYOUT = '2880x1659'

UNKNOWN_N = 3                    # 連幾次 unknown 才算
UNKNOWN_GAP_S = 5.0              # 兩次讀之間至少間隔（避開轉場一瞬間）

sleep = time.sleep               # 測試時可替換
clock = time.time


class ForbiddenClick(AssertionError):
    """要點的座標落在該面板的紅區 / 禁區矩形內（程式 bug，不是執行期狀況）"""


# ---- 遊戲存取（薄包裝，測試替換 uikit.gui）----
def gui(*args: str, note: str = '') -> str:
    import walk
    return walk.gui(*args, note=note)


def px(points) -> list | None:
    """一次讀多點 → [(r,g,b), ...]；失敗 / 數量不符回 None（同 ass._px）"""
    pts = list(points)
    out = gui('pixel', ' '.join(f'{x},{y}' for x, y in pts)).split()
    try:
        cols = [tuple(int(v) for v in c.split(',')) for c in out]
    except ValueError:
        return None
    return cols if len(cols) == len(pts) and all(len(c) == 3 for c in cols) else None


def sig_match(sig) -> bool:
    """screen_sigs 格式的特徵（6 元素 tuple 清單）現場讀圖比對；讀不到 = False"""
    cols = px([(x, y) for x, y, *_ in sig])
    return bool(cols) and all(screen_sigs.close(c, (r, g, b), tol) for c, (_, _, r, g, b, tol) in zip(cols, sig))


def screen() -> dict:
    """一次讀 screen_sigs.points() → classify（同 quest.read_screen；不 import quest）。讀不到 → {'state': 'error'}"""
    pts = screen_sigs.points()
    cols = px(pts)
    if cols is None:
        return {'state': 'error'}
    return screen_sigs.classify(dict(zip(pts, cols)))


def hud_visible() -> bool:
    return sig_match(screen_sigs.SIG_HUD)


# ---- preflight ----
def preflight(src: str) -> int:
    """開跑前檢查，回退出碼（0 = 可以動）：版面不是 2880x1659 → 2；netwatch halt → 直接 sys.exit(10)；
    battle.lock（quest 跑著）→ 8；畫面連 3 次（間隔 ≥5 s）unknown / 讀不到 → 9（疑似驗證視窗，停手通知使用者）"""
    import layout
    if layout.current() != LAYOUT:
        print(f'{src}：只量過 {LAYOUT}，目前 {layout.current()}', file=sys.stderr)
        return EXIT_LAYOUT
    import netwatch
    netwatch.guard(src)
    import battleguard
    lk = battleguard.locked()
    if lk:
        print(f'{src}：battle.lock 有效（{lk.get("note", "")} pid {lk.get("pid")}），別的腳本在用畫面，不搶', file=sys.stderr)
        return EXIT_IN_BATTLE
    for i in range(UNKNOWN_N):
        if screen().get('state') not in ('unknown', 'error'):
            return EXIT_OK
        if i < UNKNOWN_N - 1:
            sleep(UNKNOWN_GAP_S)
    print(f'{src}：畫面連 {UNKNOWN_N} 次不認得（疑似驗證視窗），停手通知使用者（鐵則 5）', file=sys.stderr)
    return EXIT_UNKNOWN_SCREEN


# ---- 面板 ----
def rect(cx: int, cy: int, r: int = 30) -> tuple:
    """以 (cx, cy) 為中心、半徑 r 的矩形 (x, y, w, h)"""
    return (cx - r, cy - r, 2 * r, 2 * r)


@dataclass
class Panel:
    name: str
    open_xy: tuple | None            # 主畫面開啟鈕（只在 SIG_HUD 在時點）
    sig: list | None                 # 面板開著的特徵（screen_sigs 格式）；None = 還沒量過 → 不能開 / 判定
    close_xy: tuple | None = None
    esc_close: bool = True           # 點 ✕ 後仍開 → 再按 ESC
    forbidden: dict = field(default_factory=dict)    # 名稱 → (x, y, w, h)；safe_click 不准點（allow= 明確放行的除外）
    settle_ms: int = 700             # 點開啟鈕後等多久再看
    is_open_fn: object = None        # 覆寫（例：ASS 沿用 ass.panel_open）
    open_fn: object = None
    close_fn: object = None


SWITCH = Panel('SWITCH', (763, 760), screen_sigs.SIG_PANEL, (1064, 208),
               forbidden={'login_all': rect(716, 578, 40)})                  # 全部登錄會讓角色上線（要問；--login-all 才 allow）
PET = Panel('PET', (318, 80), [(1310, 108, 197, 71, 49, screen_sigs.TOL)], (1310, 108),
            forbidden={'trash': rect(708, 565), 'recycle': rect(372, 610), 'loyal_minus': rect(1140, 234), 'loyal_plus': rect(1265, 234),
                       'lock': rect(708, 630), 'depot_expand': rect(1195, 705)})
TEAMPANEL = Panel('TEAMPANEL', (850, 760), None, None)                       # 特徵待量（P-I4）：sig=None → open_panel 拒絕
ASS = Panel('ASS', None, None, None)                                          # 見 _ass_panel()


def _ass_panel() -> Panel:
    import ass
    return Panel('ASS', None, None, None, is_open_fn=ass.panel_open, open_fn=ass.open_panel, close_fn=ass.close_panel)


def is_open(p: Panel) -> bool:
    """面板現在是不是真的開著（現場讀特徵；讀不到 / 沒特徵 = False）"""
    if p.is_open_fn:
        return bool(p.is_open_fn())
    return bool(p.sig) and sig_match(p.sig)


def open_panel(p: Panel, timeout: float = 4.0) -> bool:
    """開面板並驗證；已開著就成功。**只在主畫面（SIG_HUD）看得到時才點開啟鈕**；面板特徵沒出現就回 False，絕不點面板內座標"""
    if p.open_fn:
        return bool(p.open_fn())
    if p.sig is None or p.open_xy is None:
        return False
    end = clock() + timeout
    clicked = 0
    while True:
        if is_open(p):
            return True
        if hud_visible() and clicked < 3:
            gui('seq', f'click {p.open_xy[0]} {p.open_xy[1]}; wait {p.settle_ms}', note=f'uikit 開 {p.name} 面板')
            clicked += 1
            if is_open(p):
                return True
        if clock() >= end:
            return False
        sleep(0.5)


def close_panel(p: Panel) -> bool:
    """關面板並驗證消失：先點 ✕、仍開再 ESC（各最多 2 次）；只在面板確實開著時才送"""
    if p.close_fn:
        return bool(p.close_fn())
    for _ in range(2):
        if not is_open(p):
            return True
        if p.close_xy:
            gui('seq', f'click {p.close_xy[0]} {p.close_xy[1]}; wait 500', note=f'uikit 關 {p.name} 面板')
            if not is_open(p):
                return True
        if p.esc_close:
            gui('seq', 'key {ESC}; wait 500', note=f'uikit ESC 關 {p.name} 面板')
    return not is_open(p)


def in_rect(x: int, y: int, r: tuple) -> bool:
    return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]


def check_forbidden(p: Panel, x: int, y: int, allow=()) -> None:
    for nm, r in p.forbidden.items():
        if nm not in allow and in_rect(x, y, r):
            raise ForbiddenClick(f'{p.name} 面板 ({x},{y}) 落在禁區 {nm} {r}')


def safe_click(x: int, y: int, panel: Panel, note: str = '', allow=()) -> bool:
    """面板內點擊的唯一入口：禁區 → ForbiddenClick（先檢查，不讀圖）；面板特徵不在 → 不點、回 False；點了回 True"""
    check_forbidden(panel, x, y, allow)
    if not is_open(panel):
        return False
    gui('seq', f'click {x} {y}; wait 300', note=note or f'uikit {panel.name} 點 ({x},{y})')
    return True


# ---- OCR ----
def ocr(box, *opts) -> list:
    """ocr.ps1 → 文字行清單；逾時 / 失敗回 []（同 petwatch.ocr）"""
    import subprocess
    try:
        r = winenv.run_ps('ocr.ps1', *map(str, box), *map(str, opts))
    except subprocess.TimeoutExpired:
        return []
    try:
        d = json.loads((r.stdout.strip().splitlines() or [''])[-1])
    except json.JSONDecodeError:
        return []
    return [ln['text'] for ln in d.get('lines', [])] if d.get('ok') else []


# ---- 人物名（與 watch 同一套：charstate.norm_char → charname）----
CHARS = charstate.DEFAULT_CHARS
chars = charstate.chars
norm_char = charstate.norm_char


# ---- 寵物名 ----
MOUNTS = ['瑪斯貝卡']              # 騎寵名單（計畫決定 4：只有瑪斯貝卡）
SNAP_CUTOFF = 0.8
_names_cache: dict = {}


def _pet_key(t: str) -> str:
    """比對用正規化：去空白 / 標點 / 括號內容"""
    t = re.sub(r'[\(（\[【].*$', '', str(t or ''))
    return re.sub(r'[\s·．.。,，:：\-_/\\|]+', '', t)


def pet_names(path=None) -> dict:
    """Monster 表所有名稱（繁中 nameTn、簡中 nameCn、韓文 nameKr）→ 正式名（nameTn，缺就 nameCn）。同名不同寵不分（只要名字）"""
    p = Path(path) if path else MONSTER_TABLE
    if p in _names_cache:
        return _names_cache[p]
    out: dict = {}
    try:
        for ln in p.read_text(encoding='utf-8').splitlines():
            if not ln.strip():
                continue
            d = json.loads(ln)
            canon = d.get('nameTn') or d.get('nameCn')
            if not canon:
                continue
            for k in ('nameTn', 'nameCn', 'nameKr'):
                v = _pet_key(d.get(k))
                if v:
                    out.setdefault(v, canon)
    except (OSError, ValueError):
        out = {}
    _names_cache[p] = out
    return out


def snap_pet(text, names=None, cutoff: float = SNAP_CUTOFF):
    """OCR 文字 → Monster 表正式名。完全相同優先；否則 difflib 相似度 ≥ cutoff 且「最佳唯一」（第二名正式名分數必須更低）才採用；
    其他（太像多個 / 差太多 / 空字串）→ None（對不上就拒絕，不猜）"""
    key = _pet_key(text)
    if not key:
        return None
    table = names if names is not None else pet_names()
    if key in table:
        return table[key]
    if len(key) < 3:                  # 太短的片段（例「金布」）相似度不可靠，除非完全相同
        return None
    best: dict = {}
    for k, canon in table.items():
        sm = difflib.SequenceMatcher(None, key, k)
        if sm.real_quick_ratio() < cutoff or sm.quick_ratio() < cutoff:
            continue
        r = sm.ratio()
        if r >= cutoff and r > best.get(canon, 0):
            best[canon] = r
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[1][1] >= ranked[0][1]:
        return None
    return ranked[0][0]


def is_mount_like(text, mounts=None, cutoff: float = 0.6) -> bool:
    """fail-safe 版：OCR 文字只要「像」任何騎寵名（精確或相似度 ≥ cutoff，鬆很多）就視為騎寵 → 呼叫端一律拒絕存倉等動作。
    例：「瑪斯貝卞」（OCR 錯字，snap_pet 會拒絕）也算"""
    key = _pet_key(text)
    if not key:
        return False
    return any(difflib.SequenceMatcher(None, key, _pet_key(m)).ratio() >= cutoff for m in (mounts or MOUNTS))


# ---- 截圖 / 錯誤 ----
def cleanup_old_shots(days: int = SHOT_KEEP_DAYS, folder: Path = None, now: float | None = None) -> int:
    """刪 folder（預設 ui-log）第一層超過 days 天的 png；錯誤都吞掉"""
    folder = SHOT_DIR if folder is None else folder
    now = time.time() if now is None else now
    n = 0
    try:
        for f in folder.iterdir():
            try:
                if f.is_file() and f.suffix.lower() == '.png' and now - f.stat().st_mtime > days * 86400:
                    f.unlink()
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    return n


def snap(tag: str) -> str | None:
    """失敗現場存圖到 tools/.cache/ui-log/HHMMSS-tag.png（先清 3 天前的）；回相對專案根的路徑，失敗回 None"""
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        cleanup_old_shots()
        p = SHOT_DIR / f'{time.strftime("%H%M%S")}-{re.sub(r"[^0-9A-Za-z_-]", "_", tag)}.png'
        gui('shot', winenv.to_windows(p))
        return str(p.relative_to(ROOT))
    except Exception:
        return None


def fail(src: str, rc: int, msg: str) -> int:
    """印訊息 + errlog + 回 rc（errlog 寫失敗不影響）"""
    print(f'{src}：{msg}', file=sys.stderr)
    try:
        import errlog
        errlog.add(msg, source=src)
    except Exception:
        pass
    return rc
