#!/usr/bin/env python3
r"""寵物誘餌補貨（1920×1017 專用）：讀共用倉庫誘餌數量，不夠就到商城「石幣」分頁買，存回共用倉庫。

使用者 2026-10-16 的規則：
  - fullrun prebag 階段跑 --buy：共用倉庫少於 MIN_STOCK（40）個 → 買 BUY_N（55）個（50,000 石幣 / 個，共 275 萬）存共用倉庫。
  - 沒買到（讀不到數量 / 石幣不夠 / 24 小時內已試過 / 任何一步不對）一律**不停手**，只記警告，讓成人儀式、解任務、猜謎照跑。
  - katan 階段前跑 --check（只讀不買）：讀得到而且少於 MIN_STOCK 才停手（退出碼 4）；讀不到不停（抓寵時自己會示警）。
讀取（使用者：讀取能力要好，不要一格一格點）：
  - 倉庫 20 格的數量一次截圖、用 countread 字形比對（倉庫實測 14/14 全對，認不出來回 ?）；
  - 誘餌格：整塊名稱 OCR 有「誘 / 餌」的格優先，其次火焰色分數；只點候選格看浮窗標題確認是誘餌。
購買防呆：
  - 同一帳號 BUY_GAP_H（24）小時內只「試」一次（按下購買前就記錄，買失敗也不重買）；
  - 商城預設是鑽石分頁（紅區）→ 一定先切石幣分頁；按購買前核對：標題含「寵物誘」、數量 55、消費 2,750,000、擁有 >= 消費；
  - 按購買後「擁有」要正好少 2,750,000 才算買到；存倉後倉庫數量要正好多 55。

用法（專案根目錄）：
  uv run --no-project python tools/gui/baitsupply1920.py --client 333 --check      只讀，印數量
  uv run --no-project python tools/gui/baitsupply1920.py --client 333 --buy        不夠就買（prebag 用）
  加 --dry：--buy 走到按「購買」前就停（不花石幣），用來實機核對流程
退出碼：0 正常（含「沒買到但不停手」）；4 --check 讀到數量不夠；2 版面不符
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CACHE = HERE.parent / '.cache'

MIN_STOCK = 40
BUY_N = 55
PRICE = 50000
BUY_GAP_H = 24

# 商城（截圖座標，2026-10-16 11111 實測）
MALL_BTN = (407, 40)
MALL_STONE_TAB = (906, 435)
MALL_QTY_BOX = (748, 309)
MALL_BUY = (733, 447)
MALL_TITLE = (640, 90, 160, 30)
MALL_QTY = (710, 295, 80, 28)
MALL_OWN = (705, 335, 120, 30)
MALL_COST = (705, 375, 120, 30)


def log(m):
    print(time.strftime('%H:%M:%S ') + m, flush=True)


def state_path(client):
    return CACHE / f'baitbuy-{client}.json'


def last_try(client) -> float:
    try:
        return json.loads(state_path(client).read_text(encoding='utf-8')).get('last_try', 0)
    except (OSError, ValueError):
        return 0


def decide(total, now, last, min_stock=MIN_STOCK, gap_h=BUY_GAP_H) -> str:
    """純函式：'enough' / 'unknown'（數量讀不到）/ 'cooldown'（24 小時內試過）/ 'buy'"""
    if total is None:
        return 'unknown'
    if total >= min_stock:
        return 'enough'
    if now - last < gap_h * 3600:
        return 'cooldown'
    return 'buy'


def num(texts) -> int | None:
    """OCR 行 → 數字（多行讀法一致才算）"""
    vals = {int(re.sub(r'[^\d]', '', t)) for t in texts if re.sub(r'[^\d]', '', t)}
    return vals.pop() if len(vals) == 1 else None


# ---- 共用倉庫讀數量 ----

def open_public(cr):
    cr.open_bag()
    cr.click(cr.ROLE_X, cr.ROLE_Y[0], wait=1200, note='baitsupply 角色 1')
    cr.click(*cr.TAB_DEPOT, wait=1300, note='baitsupply 倉庫分頁')
    cr.click(*cr.DEPOT_PUBLIC, wait=1200, note='baitsupply 公共倉庫')


def name_hits(slots) -> set:
    """整塊倉庫一次 OCR 名稱，有「誘 / 餌」字的格（名稱在格子上半部）"""
    import winenv
    xs = sorted({x for x, _ in slots})
    ys = sorted({y for _, y in slots})
    hit = set()
    for opts in (('-Zooms', '2,3'), ('-Zooms', '2,3', '-Dark', '0')):
        try:
            r = winenv.run_ps('ocr.ps1', str(xs[0] - 34), str(ys[0] - 30), str(xs[-1] - xs[0] + 68), str(ys[-1] - ys[0] + 40), *opts)
            d = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            continue
        for ln in d.get('lines', []) if d.get('ok') else []:
            if any(k in ln['text'] for k in ('誘', '餌')):
                k = min(range(len(slots)), key=lambda i: abs(ln['x'] - slots[i][0]) + 2 * abs(ln['y'] - (slots[i][1] - 18)))
                hit.add(k)
    return hit


def read_stock(cr):
    """共用倉庫（已打開）誘餌總數：int / None（讀不到或不確定）。誘餌格要點開浮窗確認標題才算"""
    import countread
    slots = cr.depot_slots()
    counts = countread.read_counts(slots)
    filled = [k for k, v in enumerate(counts) if v is not None]
    if not filled:
        log('共用倉庫是空的 → 誘餌 0 個')
        return 0
    hits = name_hits(slots)
    order = sorted(filled, key=lambda k: (k not in hits, -cr.bait_score(slots[k])))
    total, found = 0, False
    for k in order[:4]:                     # 最多點 4 個候選（同物品會合併成一疊，通常第 1 個就是）
        if found and k not in hits:
            break
        cr.need_bag()
        cr.click(*slots[k], wait=900, note=f'baitsupply 候選格 {k + 1}')
        t = cr.title()
        if t:
            cr.gui('key', '{ESC}', note='baitsupply 關浮窗')
            time.sleep(0.5)
        if cr.BAIT not in t:
            continue
        if counts[k] == '?':
            log(f'共用倉庫第 {k + 1} 格是誘餌，但數量字形認不出來 → 當作讀不到')
            return None
        found = True
        total += counts[k]
    if not found:
        log(f'共用倉庫有 {len(filled)} 格東西，候選格點開都不是誘餌 → 誘餌 0 個')
    return total


def stock(cr):
    open_public(cr)
    n = read_stock(cr)
    cr.click(*cr.CLOSE_BAG, wait=800, note='baitsupply 關背包')
    return n


# ---- 商城購買 ----

def buy(cr, uikit, dry: bool, client: str) -> bool:
    """商城石幣分頁買 BUY_N 個；回傳是否確定買到（擁有正好少 BUY_N × PRICE）"""
    cr.click(*MALL_BTN, wait=2500, note='baitsupply 開商城')
    cr.click(*MALL_STONE_TAB, wait=1800, note='baitsupply 石幣分頁')
    title = ''.join(uikit.ocr(MALL_TITLE, '-Zooms', '2,3') + uikit.ocr(MALL_TITLE, '-Zooms', '3,4'))
    if '寵物誘' not in title:
        log(f'商城選中的商品不是寵物誘餌（讀到 {title!r}）→ 不買')
        return False
    cr.click(*MALL_QTY_BOX, wait=1100, note='baitsupply 數量框')
    for ch in str(BUY_N):
        cr.click(*cr.KEYS[ch], wait=450, note=f'baitsupply 鍵 {ch}')
    cr.click(*cr.KEY_ENTER, wait=1200, note='baitsupply Enter')
    qty = num(uikit.ocr(MALL_QTY, '-Zooms', '3,4'))
    cost = num(uikit.ocr(MALL_COST, '-Zooms', '2,3') + uikit.ocr(MALL_COST, '-Zooms', '3,4'))
    own = num(uikit.ocr(MALL_OWN, '-Zooms', '2,3') + uikit.ocr(MALL_OWN, '-Zooms', '3,4'))
    log(f'商城核對：數量 {qty}、消費 {cost}、擁有 {own}')
    if qty != BUY_N or cost != BUY_N * PRICE:
        log(f'數量 / 消費不是 {BUY_N} / {BUY_N * PRICE} → 不買')
        return False
    if own is None or own < cost:
        log(f'石幣不夠（擁有 {own}，要 {cost}）→ 不買')
        return False
    if dry:
        log('--dry：核對都對，停在按「購買」前')
        return False
    state_path(client).write_text(json.dumps({'last_try': time.time(), 'own_before': own}), encoding='utf-8')
    cr.click(*MALL_BUY, wait=2500, note=f'baitsupply 購買 {BUY_N} 個（石幣）')
    after = num(uikit.ocr(MALL_OWN, '-Zooms', '2,3') + uikit.ocr(MALL_OWN, '-Zooms', '3,4'))
    uikit.gui('shot', 'baitsupply-bought.png')
    if after != own - cost:
        log(f'按了購買，但擁有 {own} → {after}（不是少 {cost}）→ 不確定有沒有買到，不重買；看 tools/.cache/baitsupply-bought.png')
        return False
    log(f'已買 {BUY_N} 個寵物誘餌（石幣 {own} → {after}）')
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='寵物誘餌補貨')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true', help='只讀；數量讀得到且 < MIN_STOCK → 退出碼 4')
    g.add_argument('--buy', action='store_true', help='不夠就買（任何失敗都只警告、退出碼 0）')
    ap.add_argument('--dry', action='store_true', help='--buy 停在按購買前')
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
    import catchrun1920 as cr
    import uikit
    n = stock(cr)
    log(f'共用倉庫寵物誘餌：{n if n is not None else "讀不到"}（門檻 {MIN_STOCK}）')
    if a.check:
        if n is not None and n < MIN_STOCK:
            print(f'停手：共用倉庫寵物誘餌只有 {n} 個（< {MIN_STOCK}），卡坦 / 恐龍博士 / 坐騎會抓不完 → 請補誘餌')
            return 4
        return 0
    act = decide(n, time.time(), last_try(a.client))
    if act == 'enough':
        return 0
    if act == 'unknown':
        log('警告：讀不到誘餌數量 → 不買，不停手（卡坦前會再讀一次）')
        return 0
    if act == 'cooldown':
        log(f'警告：誘餌只有 {n} 個，但 {BUY_GAP_H} 小時內已試買過 → 不再買，不停手（卡坦前會再讀一次）')
        return 0
    ok = buy(cr, uikit, a.dry, a.client)
    cr.gui('key', '{ESC}', note='baitsupply 關商城')
    time.sleep(1.2)
    if not ok:
        log('警告：這次沒買到誘餌 → 不停手（卡坦前會再讀一次）')
        return 0
    r = subprocess.run([sys.executable, str(HERE / 'baitstore1920.py'), '--client', a.client, '--role', '1'])
    m = stock(cr)
    if r.returncode != 0 or m != n + BUY_N:
        log(f'警告：存倉後共用倉庫 {m} 個（應 {n + BUY_N}，baitstore 退出碼 {r.returncode}）→ 不停手，請檢查')
    else:
        log(f'補貨完成：共用倉庫寵物誘餌 {n} → {m}')
    return 0


if __name__ == '__main__':
    import failshot
    failshot.watch_stdout('baitsupply1920')
    sys.exit(main())
