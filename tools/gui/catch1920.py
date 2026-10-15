#!/usr/bin/env python3
"""外掛「捉寵設置」操作（1920×1017 專用）：讀狀態 / 選角色、系別、寵物 / 勾自動存倉庫、自動抓寵。只用標準庫 + ass + uikit。

只管外掛面板的「捉寵設置」分頁；取誘餌 / 拆分 / 存倉庫不在這支（背包 1920 座標另量）。
安全：不碰「可抓捕數 +」（紅區，疑似花石幣）、「丟棄不滿足條件的寵物」；戰鬥中 / 面板打不開就停手；一律點 X 關面板，不用 ESC。

用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1 較快）：
  uv run --no-project python tools/gui/catch1920.py --client kkfaq11111 status              # 唯讀：5 人的 系別 / 寵物 / 可抓捕數 / 兩個勾選
  uv run --no-project python tools/gui/catch1920.py --client kkfaq11111 set --role 2 --system 鯊魚系 --pet 克邦凱斯
  uv run --no-project python tools/gui/catch1920.py --client kkfaq11111 set --role 2 --store on --catch on   # 勾自動存倉庫 + 自動抓寵
  uv run --no-project python tools/gui/catch1920.py --client kkfaq11111 list --role 2 --which system          # 唯讀：列出下拉全部項目

座標（截圖 960×508，2026-10-11 實機量）：捉寵設置分頁 645,127；自動抓寵 勾 440,190；自動存倉庫 勾 542,190；
可抓捕數 OCR 框 770,180,40,20；「+」840,190（紅區，不點）；系別欄 500,230 / 箭頭 607,230；寵物欄 730,230 / 箭頭 833,230；
下拉清單可見 8 列：y = 258 + 26.4×i（系別 x 430~572；寵物 x 約 656~800）。
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TAB_CATCH = (645, 127)
CHK_CATCH = (440, 190)
CHK_STORE = (542, 190)
CNT_BOX = (765, 176, 50, 30)
SYS_FIELD, SYS_ARROW = (500, 230), (607, 230)
PET_FIELD, PET_ARROW = (730, 230), (833, 230)
SYS_BOX = (430, 218, 140, 24)
PET_BOX = (658, 218, 140, 24)
ROW0, ROW_STEP, ROWS = 258, 26.4, 8
UNCHECKED = (255, 255, 255)
TAB_ON = (0, 0, 255)       # 選中分頁藍底（只看藍色成分明顯高於紅綠）

sleep = time.sleep
SCROLL_PX = 50    # 實測約每 13px 一列（60px≈5 列、130px≈10 列）→ 50px ≈ 4 列；放開後要等約 1 秒才穩（使用者：適當就好）
BOTTOM = {"system": "洛克斯"}   # 系別清單最後一項（使用者 2026-10-11）：看到就不用再往下捲


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def gui(*a, note=''):
    import uikit
    return uikit.gui(*a, note=note)


def px(pts):
    import uikit
    return uikit.px(pts)


def ocr(box, *opts):
    import uikit
    lines = [t.strip() for t in uikit.ocr(box, *opts) if t.strip()]
    return lines[0] if lines else ''


def click(x, y, wait=700, note=''):
    gui('seq', f'click {x} {y}; wait {wait}', note=note)


def tab_on() -> bool:
    c = px([(645, 124)])
    return bool(c) and c[0][2] > 150 and c[0][0] < 80


def read_field(box) -> str:
    return ocr(box, '-Zooms', '2,3')


def row_y(i: int) -> int:
    return int(ROW0 + ROW_STEP * i)


def read_row(i: int, x0: int) -> str:
    return read_field((x0, row_y(i) - 11, 156, 22))


def ensure_tab() -> bool:
    for _ in range(3):
        if tab_on():
            return True
        click(*TAB_CATCH, wait=800, note='catch 捉寵設置分頁')
    return tab_on()


def read_state() -> dict:
    return {
        'system': read_field(SYS_BOX),
        'pet': read_field(PET_BOX),
        'count': read_field(CNT_BOX),
        'catch': is_checked(CHK_CATCH),
        'store': is_checked(CHK_STORE),
    }


def open_list(which: str) -> None:
    click(*(SYS_ARROW if which == 'system' else PET_ARROW), wait=900, note=f'catch 開{which}下拉')


def scroll_list(which: str, down: bool, px: int = None) -> None:
    px = px or SCROLL_PX
    x = 500 if which == 'system' else 730
    a, b = (430, 430 - px) if down else (250, 250 + px)
    gui('drag', str(x), str(a), str(x), str(b), note='catch 捲下拉清單')
    sleep(1.6)                                           # 放開後清單還在滑動，讀太快會讀到半途（使用者 2026-10-11：再慢 0.x 秒）


def visible_rows(which: str) -> list:
    x0 = 422 if which == 'system' else 658
    return [read_row(i, x0) for i in range(ROWS)]


# 寵物清單順序（Monster 表 ID 順序；清單只有 4 項、換系別後從第一項開始，OCR 常讀漏所以用位置直接點，欄位讀回驗證）
PET_ORDER = {'鯊魚': ['克邦凱斯', '加克拉', '加格', '邦恩吉'], '火雞': ['火雞', '克克洛斯', '霍爾克', '奇寶']}
RECIPES = Path(__file__).resolve().parents[1] / '.cache' / 'catch_recipes.json'


def _load_recipes() -> dict:
    try:
        import json
        return json.loads(RECIPES.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_recipe(key: str, n: int, row: int) -> None:
    import json
    r = _load_recipes()
    r[key] = {'n': n, 'row': row}
    try:
        RECIPES.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
    except OSError:
        pass


def _norm(x: str) -> str:
    """遊戲字型把「雞」畫成「難」（畫面「火難系」），OCR 也讀成難；比對前統一"""
    return x.replace('難', '').replace('鷄', '').replace('雞', '')   # 「火雞系」→「火系」：只靠前面的「火」字（使用者 2026-10-11）


def _match(target: str, t: str) -> bool:
    target, t = _norm(target), _norm(t)
    if target in t or (len(target) > 2 and target[1:] in t):
        return True
    # OCR 混字（克克洛斯 讀成 克克浴斯 等）：目標 ≥3 字時，有 ≥ len-1 個字出現在讀到的文字裡也算
    return len(target) >= 3 and sum(1 for ch in target if ch in t) >= len(target) - 1


def to_top(which: str) -> None:
    """往下拖（內容往上捲回頂）直到第 0 列文字不再變；最多 4 次"""
    x0 = 422 if which == 'system' else 658
    prev = None
    for _ in range(4):
        cur = read_row(0, x0)
        if cur and cur == prev:
            return
        prev = cur
        scroll_list(which, down=False, px=190)


def pick(which: str, target: str, ctx: str = '') -> bool:
    """開下拉 → 回到頂 → 有「學過的配方」就直接捲 n 次只讀 1 列，沒有 / 對不上就完整掃描並記下配方 → 點 → 讀回驗證。
    ctx：寵物下拉要帶系別名（寵物清單隨系別不同）。失敗會 ESC 關下拉回 False。"""
    box = SYS_BOX if which == 'system' else PET_BOX
    if _match(target, read_field(box)):
        return True
    x_click = 500 if which == 'system' else 730
    x0 = 422 if which == 'system' else 658
    key = f'{which}:{ctx}:{target}'
    open_list(which)
    sleep(0.6)
    cur = read_field(box)
    if which == 'system' and '呼' in target and '烏力' not in cur:
        # 呼拔拔系就在目前清單視窗上方約 9 列（使用者 2026-10-11：往下拉一點點）：只拉一小段（約 100px）再讀
        scroll_list(which, down=False, px=100)
        sleep(0.3)
        rows = visible_rows(which)
        idx = None
        for i, t in enumerate(rows):
            if '呼' in t or ('拔' in t and '系' in t):
                idx = i
                break
        if idx is None:                                  # 這一列 OCR 常讀成空白：用旁邊讀得到的名字推（穿山甲的上一列 / 特洛昆的下一列）
            for i, t in enumerate(rows):
                if '穿山' in t and i > 0:
                    idx = i - 1
                    break
                if ('特' in t and '昆' in t) and i + 1 < ROWS:
                    idx = i + 1
                    break
        if idx is not None:
            click(x_click, row_y(idx), wait=1000, note=f'catch 選 {target}（第 {idx + 1} 列，上方微拉）')
            f = read_field(box)
            if '呼' in f or '拔' in f:
                return True
        log(f'微拉後沒找到呼拔拔；rows={rows}')
        gui('key', '{ESC}', note='catch 關下拉'); sleep(0.6)
        return False
    if which == 'system' and '老虎' in target:
        # 老虎系在清單中間（使用者 2026-10-11：從最上面往下拉兩次）：回頂 → 拉兩次（各約 60px）→ 讀 → 點
        to_top(which)
        for _ in range(2):
            scroll_list(which, down=True, px=60)
        rows = visible_rows(which)
        hit = [i for i, t in enumerate(rows) if '老虎' in t or ('虎' in t and '系' in t)]
        if not hit:
            # 2026-10-15 22222：rows=['兔子系',…,'茄子系','','犀午糸','鯊魚系'] → 老虎那列讀不到。
            # 夾在茄子系與犀牛系中間的空白列就是老虎系（點完照樣讀回欄位驗證「虎」）
            hit = [i for i in range(1, len(rows) - 1)
                   if not rows[i].strip() and '茄' in rows[i - 1] and ('犀' in rows[i + 1] or '牛' in rows[i + 1])]
        for i in hit[:1]:
            click(x_click, row_y(i), wait=1000, note=f'catch 選 {target}（第 {i + 1} 列，拉兩次）')
            if '虎' in read_field(box):
                return True
        log(f'拉兩次後沒找到老虎；rows={rows}')
        gui('key', '{ESC}', note='catch 關下拉'); sleep(0.6)
        return False
    # 系別預設在最上（烏力系）、寵物清單換系別後也從第一項開始：已在頂就不拖（使用者 2026-10-11：一開始別往上拉）
    if which == 'system' and '烏力' not in cur and '力系' not in cur:
        to_top(which)
    if which == 'pet':
        for k, order in PET_ORDER.items():
            if k in ctx and target in order:
                idx = order.index(target)
                click(x_click, row_y(idx), wait=1000, note=f'catch 依序選 {target}（第 {idx + 1} 項）')
                if _match(target, read_field(box)):
                    return True
                log(f'依序點第 {idx + 1} 項後欄位不是「{target}」→ 改掃描')
                break
    rec = _load_recipes().get(key)
    if rec:                                              # 重播：捲 n 次，只讀該列
        for _ in range(rec['n']):
            scroll_list(which, down=True)
        if _match(target, read_row(rec['row'], x0)):
            sleep(0.4)
            if _match(target, read_row(rec['row'], x0)):
                click(x_click, row_y(rec['row']), wait=1000, note=f'catch 重播選 {target}')
                if _match(target, read_field(box)):
                    return True
        log(f'配方對不上「{target}」→ 從目前位置繼續掃描（不回頂）')
    last, n, same = None, 0, 0
    for _ in range(24):
        rows = visible_rows(which)
        if not any(rows):                                # 全空 = 清單沒開（被關掉了）：重新點箭頭開一次
            sleep(0.8)
            rows = visible_rows(which)
            if not any(rows):
                open_list(which)
                sleep(0.8)
                rows = visible_rows(which)
        for i, t in enumerate(rows):
            if _match(target, t):
                sleep(0.5)
                if not _match(target, read_row(i, x0)):
                    break
                click(x_click, row_y(i), wait=1000, note=f'catch 選 {target}')
                if _match(target, read_field(box)):
                    _save_recipe(key, n, i)
                    return True
                break
        same = same + 1 if rows == last else 0
        if same >= 2 or (BOTTOM.get(which) and any(BOTTOM[which] in t for t in rows)):
            log(f'到底仍沒有「{target}」；最後一屏：{rows}')
            break
        last = rows
        scroll_list(which, down=True)
        n += 1
    gui('key', '{ESC}', note='catch 關下拉'); sleep(0.6)
    return False


CHK_OFFS = [(dx, dy) for dy in (-6, -3, 0, 3, 6) for dx in (-6, -3, 0, 3, 6)]


def is_checked(pt) -> bool:
    """勾選框是否打勾：框內有一點是深色（勾的筆畫）就算。只讀中心一點會剛好落在白底上（2026-10-12 22222 實測：
    已勾選但中心點仍是純白 → 誤判沒勾、點了又取消）。"""
    cols = px([(pt[0] + dx, pt[1] + dy) for dx, dy in CHK_OFFS])
    return bool(cols) and any(sum(c) < 220 for c in cols)


def set_check(pt, want: bool, name: str) -> bool:
    if is_checked(pt) == want:
        return True
    click(*pt, wait=900, note=f'catch {name} → {want}')
    for _ in range(4):                                   # 勾選圖示更新有延遲：輪詢最多約 2 秒
        if is_checked(pt) == want:
            return True
        sleep(0.5)
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('cmd', choices=['status', 'set', 'list'])
    ap.add_argument('--role', type=int, help='1~5')
    ap.add_argument('--system')
    ap.add_argument('--pet')
    ap.add_argument('--store', choices=['on', 'off'])
    ap.add_argument('--catch', choices=['on', 'off'])
    ap.add_argument('--which', choices=['system', 'pet'], default='system')
    a = ap.parse_args(argv)
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import layout
    if layout.current() != '1920x1017':
        print(f'版面 {layout.current()}，這支只量過 1920x1017')
        return 2
    import ass
    names = ['DKBO', 'DKBO2', 'DKBO3', 'DKBO4', 'DKBO5']
    if a.cmd != 'status' and not a.role:
        print('set / list 需要 --role')
        return 1
    if not ass.open_panel():
        print('外掛面板打不開（戰鬥 / 對話中？）')
        return 3
    try:
        if not ensure_tab():
            print('切不到「捉寵設置」分頁')
            return 4
        roles = range(1, 6) if a.cmd == 'status' and not a.role else [a.role]
        for r in roles:
            if not ass.select_role(names[r - 1]):
                print(f'選不到角色 {r}')
                return 5
            if not ensure_tab():
                print('切角色後分頁沒在「捉寵設置」')
                return 4
            if a.cmd == 'status':
                log(f'角色{r} {read_state()}')
            elif a.cmd == 'list':
                open_list(a.which)
                seen = []
                scroll_list(a.which, down=False, px=190)
                for _ in range(20):
                    rows = visible_rows(a.which)
                    seen += [t for t in rows if t and t not in seen]
                    if BOTTOM.get(a.which) and any(BOTTOM[a.which] in t for t in rows):
                        break
                    scroll_list(a.which, down=True)
                gui('key', '{ESC}', note='catch 關下拉'); sleep(0.6)
                log(f'{a.which} 清單：{seen}')
            else:
                if a.system and not pick('system', a.system):
                    print(f'系別選不到「{a.system}」')
                    return 6
                if a.pet and not pick('pet', a.pet, ctx=read_field(SYS_BOX)):
                    print(f'寵物選不到「{a.pet}」')
                    return 7
                if a.store and not set_check(CHK_STORE, a.store == 'on', '自動存倉庫'):
                    return 8
                if a.catch and not set_check(CHK_CATCH, a.catch == 'on', '自動抓寵'):
                    return 9
                log(f'角色{r} {read_state()}')
    finally:
        ass.close_panel()
    return 0


if __name__ == '__main__':
    sys.exit(main())
