#!/usr/bin/env python3
r"""11111 一條龍總控（1920×1017；終端機直接跑；可中斷續跑）。

流程（使用者 2026-10-12 規劃）：
  train      練等到隊長 131 級（levelwatch --no-heal --stop-at-end）
  wait131    5 個角色都 >= 131 級才往下（組隊面板讀 5 人等級；沒到就每 60 秒再看，遇敵繼續開著）
  stopenc    停止遇敵：等戰鬥結束 → 關原地遇敵並驗證
  ledger     任務帳本歸零：轉生後任務全部重置，帳本裡這個帳號舊的 done 要清掉（先備份到 notes/；katan / rebirthprep 的續跑狀態一併備份清除）
  prebag     開跑任務前先整理一次背包（bag1920 --do：名單內刪除 / 存倉庫，名單外只列出來），保證獎勵進得了背包
  adult      成人儀式先做（questflow --only 成人儀式；轉生後會重置，一定排在四大洞窟之前；已做過就跳過）
  quests     questflow：全部任務（內含兩次整理背包：五兄弟之謎後 / 彌生和日美子後）
  riddle     猜謎三兄弟（questflow --only riddle；練金布伊 77 級）
  katan      卡坦的願望（鯊魚 → 火雞）          ← 寵物任務，排在最後
  dino       恐龍博士
  gate       漆黑洞窟步 5：跟守門人講話領守護獸（questflow --dark-gate，組隊去；questflow 只解到打完機暴，這一步留到轉生前）。個別角色漏掉才手動用 gatesolo1920 --roles N
  rebirth    轉生（使用者 2026-10-12 確定全自動）：go（組隊 + 導航到精靈王）→ auto（自動點對話選項）→ 偵測 5 人回到低等級
  gift       轉生後 1 級：開「N 轉新手禮盒」（最多試 3 次，失敗不停手）→ 吃 2 倍智慧果 + 離線水晶 → 安撫之素 / 寵物誘餌存共用倉庫（newbiebox1920）
  organize   整理寵物：丟棄 奇娜 / 多魯寶 / 烏力斯坦 / 修寶 / 布克布克；金飛 紅飛 紅暴 藍暴 金羊 存個人倉庫（petorganize1920）
  clear      寵物全身清空（petdepot --do 全存個人倉庫，再 --check-empty 驗證 5 人寵物欄全空）
  prep       rebirthprep：角色 5 抓格魯西斯 + 分給其他人 + 外掛鎖定騎寵 + 領個人倉庫第 1 隻設戰寵
  grind      練等 1~131（levelwatch --no-heal --stop-at-end；不補血）

用法（專案根目錄）：
  tools\gui\run_fullrun.cmd kkfaq11111 --plan              只印階段與每階段的指令
  tools\gui\run_fullrun.cmd kkfaq11111                      從頭 / 接續（狀態檔 tools/.cache/fullrun-<client>.json）
  tools\gui\run_fullrun.cmd kkfaq11111 --from quests        指定從哪個階段開始（前面視為已完成）
  tools\gui\run_fullrun.cmd kkfaq11111 --only wait131       只跑單一階段
任何階段退出碼不是 0 就停手；pausegate 暫停檔在階段之間生效。
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
ROOT = HERE.parents[1]
STATE_DIR = ROOT / 'tools' / '.cache'

STAGES = ['train', 'wait131', 'stopenc', 'ledger', 'prebag', 'adult', 'quests', 'riddle', 'katan', 'dino', 'gate', 'rebirth', 'gift', 'organize', 'clear', 'prep', 'grind']
TARGET = 131
GRIND_TARGET = TARGET          # 本輪練功目標（131 / 140）；進 train / wait131 / grind 前由 detect_grind_target 決定
TEAM_BTN, TEAM_X = (598, 465), (813, 42)
CARD_CX = (237, 355, 480, 604, 729)          # 組隊面板 5 張卡片的名牌中心 x（960×508 截圖座標；2026-10-12 11111 實機量）
LV_Y = 268


def log(m: str) -> None:
    print(time.strftime('%H:%M:%S'), m, flush=True)


def py(script: str, *args) -> list:
    return [sys.executable, str(HERE / script), *[str(x) for x in args]]


def plan(client: str, stage: str) -> list:
    """純函式：階段要跑的外部指令 [(說明, argv)]；內建階段（wait131 / stopenc / rebirth）回傳空清單"""
    c = ['--client', client]
    if stage == 'train':
        return [('確認 5 人自動轉換戰寵沒勾（卡坦 / 恐龍博士練寵後可能還開著）', py('autoswapoff1920.py', *c)),
                (f'練等到隊長 {GRIND_TARGET} 級（不補血）', py('levelwatch.py', '--every', 30, '--stop-at-end', '--no-heal', '--end-level', GRIND_TARGET))]
    if stage == 'prebag':
        return [('任務前整理背包', py('bag1920.py', *c, '--do'))]
    if stage == 'adult':
        # 使用者 2026-10-15：成人儀式一定先做（轉生後會重置；333 帳本誤標完成 → 先跑了四大洞窟）；questflow 開頭會用主線清單校正帳本
        return [('成人儀式（先做，四大洞窟之前）', py('questflow1920.py', *c, '--only', '成人儀式'))]
    if stage == 'quests':
        return [('任務總流程（含兩次整理背包）', py('questflow1920.py', *c))]
    if stage == 'riddle':
        return [('猜謎三兄弟（練金布伊到 77 級再交；卡坦的願望之前）', py('questflow1920.py', *c, '--only', 'riddle', '--no-potion'))]
    if stage == 'katan':
        return [('卡坦的願望：鯊魚 → 火雞', py('katan1920.py', *c, '--family', 'all', '--phase', 'all', '--do', '--resume'))]
    if stage == 'gate':
        return [('漆黑洞窟步 5 守門人（領守護獸；組隊去講；單人版 gatesolo1920 只在個別角色漏掉時手動用）', py('questflow1920.py', *c, '--dark-gate'))]
    if stage == 'dino':
        return [('恐龍博士', py('katan1920.py', *c, '--family', 'dino', '--phase', 'all', '--do', '--resume'))]
    if stage == 'gift':
        return [('開 N 轉新手禮盒 → 吃 2 倍智慧果 / 離線水晶 → 安撫之素 / 誘餌存共用倉庫（失敗只記警告）', py('newbiebox1920.py', *c, '--do'))]
    if stage == 'organize':
        return [('整理寵物（丟 5 種、存 5 種）', py('petorganize1920.py', *c, '--do'))]
    if stage == 'clear':
        return [('寵物全存個人倉庫', py('petdepot1920.py', *c, '--do')),
                ('驗證 5 人寵物欄全空', py('petdepot1920.py', *c, '--check-empty', '--roles', '1,2,3,4,5'))]
    if stage == 'prep':
        return [('抓格魯西斯 / 分寵 / 鎖定騎寵 / 領個人倉庫第 1 隻 / 設戰寵', py('rebirthprep1920.py', *c, '--do', '--resume'))]
    if stage == 'grind':
        return [('確認 5 人自動轉換戰寵沒勾（卡坦 / 恐龍博士練寵後可能還開著）', py('autoswapoff1920.py', *c)),
                (f'練等 1~{GRIND_TARGET}（不補血）', py('levelwatch.py', '--every', 30, '--stop-at-end', '--no-heal', '--end-level', GRIND_TARGET))]
    return []


# ---- 內建階段 ----
def parse_card_level(texts) -> int | None:
    """組隊面板綠字「1轉133級」的 OCR 很糊（3 讀成 g / B / ß，會掉位數、混進 • , 等符號）。
    到這個階段 5 人一定 >= 100 級，所以只看「級」前面最後兩個字元：十位數 / 個位數各自投票。
    十位數票至少 2 票一致才採信；個位數若讀不成數字就當未知（視為 1，即「剛好達標」）。
    回傳等級估計：十位 T、個位 O 有數字 → 100+10T+O；O 未知 → 100+10T+1。讀不到十位 → None。"""
    tens, ones = {}, {}
    for t in texts:
        t = str(t)
        t = t.split('轉', 1)[1] if '轉' in t else t
        t = t.split('級', 1)[0]
        t = re.sub(r'[^0-9A-Za-z一-鿿]', '', t)      # 去掉 • , . 空白 等雜訊符號
        if len(t) < 2:
            continue
        c2, c1 = t[-2], t[-1]
        if c2.isdigit():
            tens[c2] = tens.get(c2, 0) + 1
        if c1.isdigit():
            ones[c1] = ones.get(c1, 0) + 1
    if not tens:
        return None
    T, n = max(tens.items(), key=lambda kv: kv[1])
    if n < 2:
        return None
    if ones:
        O, m = max(ones.items(), key=lambda kv: kv[1])
        o = int(O) if m >= 2 else 1
    else:
        o = 1
    return 100 + 10 * int(T) + o


def parse_card_trans(texts) -> int | None:
    """綠字「1轉133級」：取「轉」前面那個數字投票（HUD 的 stat 常把轉生數讀錯，questflow 因此挑錯漆黑洞窟）"""
    votes = {}
    for t in texts:
        m = re.search(r'(\d)\s*轉', str(t))
        if m:
            votes[m[1]] = votes.get(m[1], 0) + 1
    if not votes:
        return None
    v, n = max(votes.items(), key=lambda kv: kv[1])
    return int(v) if n >= 2 else None


def read_trans() -> int | None:
    """開組隊面板讀隊長卡片的轉生數（5 張卡片合併投票）"""
    import uikit
    uikit.gui('seq', f'click {TEAM_BTN[0]} {TEAM_BTN[1]}; wait 1300', note='fullrun 開組隊面板（讀轉生數）')
    try:
        texts = []
        for cx in CARD_CX:
            for box, opts in (((cx - 30, LV_Y - 1, 60, 18), ('-Zooms', '4,5')),
                              ((cx - 45, LV_Y - 2, 90, 22), ('-Zooms', '4,5', '-Dark', '170')),
                              ((cx - 45, LV_Y - 2, 90, 22), ('-Zooms', '3,4', '-Dark', '200'))):
                try:
                    texts += list(uikit.ocr(box, *opts))
                except Exception:
                    pass
        return parse_card_trans(texts)
    finally:
        uikit.gui('seq', f'click {TEAM_X[0]} {TEAM_X[1]}; wait 800', note='fullrun 關組隊面板')


def _esc() -> None:
    import uikit
    uikit.gui('seq', 'key {ESC}; wait 700', note='fullrun 讀取失敗 → ESC')


INFO_BTN, INFO_X = (75, 45), (866, 65)                   # HUD 左上頭像 → 人物資訊面板 / 右上 ✕（960×508，2026-10-13 22222 實機量）
INFO_ROLE = ((52, 115), (52, 200), (52, 285), (52, 365), (52, 430))   # 面板左欄 5 個頭像（點了只換右邊顯示，不會切換操控）
INFO_LV = (140, 410, 275, 24)                            # 面板左下綠字「1轉131級(10000342)」


def parse_info_level(texts) -> int | None:
    """人物資訊面板「1轉131級(10000342)」→ 131；只取「轉」後面、「級」前面的 1~3 位數，括號內的 ID 不看。
    多組 OCR 結果各自解析，取最多票；讀不到回 None（面板字夠大，2026-10-13 實測 5 人全讀對）"""
    votes = {}
    for t in texts:
        m = re.search(r'轉\s*(\d{1,3})\s*級', str(t))
        if m:
            v = int(m.group(1))
            votes[v] = votes.get(v, 0) + 1
    if not votes:
        return None
    return max(votes.items(), key=lambda kv: kv[1])[0]


def read_team_levels() -> list:
    """開人物資訊面板、逐一點左欄 5 個頭像讀等級（讀完就關）→ [等級 or None ×5]
    （組隊卡片的綠字只有約 8 像素高，OCR 會掉位數，2026-10-13 22222 實測；人物資訊面板字大，5 人全讀對）"""
    import uikit

    def info_open() -> bool:
        c = uikit.px([INFO_X])                   # 右上 ✕（紅圓）出現 = 人物資訊面板真的開了
        return bool(c) and c[0][0] > 170 and c[0][1] < 120 and c[0][2] < 110

    # 沒開成功絕不能往下點左欄頭像（會點到左下角的聊天視窗，2026-10-13）：沒開 → ESC 後重來，最多 3 次，還是沒開就回全 None
    opened = False
    for k in range(3):
        uikit.gui('seq', f'click {INFO_BTN[0]} {INFO_BTN[1]}; wait 1500', note=f'fullrun 開人物資訊（第 {k + 1}/3 次）')
        if info_open():
            opened = True
            break
        uikit.gui('key', '{ESC}', note='fullrun 人物資訊沒開成功 → ESC 重來')
        uikit.gui('seq', 'wait 900', note='w')
    if not opened:
        log('人物資訊面板開不成功（3 次）→ 不點任何左欄座標，等級回 None')
        return [None] * 5
    try:
        out = []
        for x, y in INFO_ROLE:
            uikit.gui('seq', f'click {x} {y}; wait 1400', note='fullrun 人物資訊 選角色')
            texts = []
            for opts in (('-Zooms', '3,4'), ('-Zooms', '2,3', '-Dark', '200')):
                try:
                    texts += list(uikit.ocr(INFO_LV, *opts))
                except Exception:
                    pass
            out.append(parse_info_level(texts))
        return out
    finally:
        uikit.gui('seq', f'click {INFO_X[0]} {INFO_X[1]}; wait 800', note='fullrun 關人物資訊')


def read_team_levels_retry(tries: int = 3) -> list:
    """全部讀不到（面板沒開成 / 被別的視窗擋住）→ ESC ×1 再讀，最多 3 次（使用者 2026-10-13）"""
    lv = [None] * 5
    for k in range(tries):
        lv = read_team_levels()
        if any(v is not None for v in lv):
            return lv
        log(f'組隊面板讀不到等級（第 {k + 1}/{tries} 次）→ ESC 後重讀')
        _esc()
    return lv


def levels_ready(lv: list, target: int = None) -> bool:
    target = GRIND_TARGET if target is None else target
    return len(lv) == 5 and all(v is not None and v >= target for v in lv)


def detect_grind_target(client: str) -> int:
    """練功目標：任務詳情「主線」分頁最上面那格是「漆黑洞窟(五轉)」→ 140（要掛 16~18 小時），其餘一轉~四轉 → 131。
    使用者 2026-10-14：偵測異常時先 ESC 關視窗再重讀；還是讀不到就用人物資訊面板的轉數（4 轉 = 下一個漆黑是五轉）。"""
    import re
    try:
        import questflow1920 as qf
    except Exception as e:
        log(f'[target] 載入 questflow 失敗（{e}）→ 131')
        return 131
    for k in range(3):                             # 任務詳情「主線」分頁最上面那格的漆黑（使用者 2026-10-14：不要讀追蹤欄）
        top = ''
        try:
            if qf.open_detail(side=False):
                rows = sorted(qf.q._list_rows(), key=lambda r: r[1])
                lab = ('進行', '待接', '接取', '完成')
                names = [t for t, _ in rows if not any(x in t for x in lab)]
                top = names[0] if names else ''
        except Exception as e:
            log(f'[target] 任務詳情讀取失敗（{e}）')
        finally:
            try:
                qf.q.key('{ESC}')
                time.sleep(0.6)
            except Exception:
                pass
        if '漆黑' in top:
            five = bool(re.search(r'[五5][轉转]', top))
            if five or re.search(r'[一二三四1-4][轉转]', top):
                log(f'[target] 任務詳情主線最上面：{top!r} → {"五轉 → 140" if five else "131"}')
                return 140 if five else 131
            log(f'[target] 任務詳情主線最上面讀到漆黑但看不出幾轉：{top!r}（第 {k + 1}/3 次）')
        elif top:
            # 讀得到、只是最上面是別的任務（2026-10-14 11111 / 22222 都是「成人儀式」）：重讀也一樣，直接改看人物資訊轉數（省約 20 秒）
            log(f'[target] 任務詳情主線最上面是 {top!r}（不是漆黑）→ 改看人物資訊轉數')
            _esc()
            break
        else:
            log(f'[target] 任務詳情主線讀不到（第 {k + 1}/3 次）→ ESC 後重讀')
        _esc()
        time.sleep(1.0)
    try:                                           # 保底：人物資訊面板的轉數（4 轉 → 下一個漆黑是五轉）
        n = qf.current_trans()
        log(f'[target] 追蹤欄讀不到 → 人物資訊面板轉數 {n}')
        return 140 if n == 4 else 131
    except Exception as e:
        log(f'[target] 轉數也讀不到（{e}）→ 131')
        return 131


def stage_wait131(client: str, every: int, max_min: int) -> int:
    import q1920 as q
    t0 = time.time()
    while time.time() - t0 < max_min * 60:
        try:
            if q.state() != 'MAIN':
                time.sleep(10)                   # 戰鬥中不開面板
                continue
        except Exception:
            pass
        lv = read_team_levels_retry()
        log(f'5 人等級：{lv}（目標 >= {GRIND_TARGET}）')
        if levels_ready(lv):
            return 0
        time.sleep(every)
    log(f'等了 {max_min} 分鐘 5 人還沒全到 {GRIND_TARGET} 級 → 停手')
    return 7


def stage_stopenc(client: str) -> int:
    import heal
    import q1920 as q
    q.wait_battle_end(420)
    heal.set_encounter(False)
    time.sleep(1.0)
    if heal.encounter_on():
        log('原地遇敵關不掉 → 停手')
        return 4
    log('原地遇敵已關')
    return 0


def stage_ledger(client: str) -> int:
    """備份後清掉這個帳號在任務帳本 / katan / rebirthprep 的舊進度（轉生會重置全部任務；不清的話 questflow 會把舊 done 全跳過）"""
    import shutil
    stamp = time.strftime('%Y%m%d-%H%M%S')
    led = ROOT / 'notes' / 'quest-ledger.json'
    try:
        d = json.loads(led.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        d = {}
    if client in d:
        bak = led.with_name(f'quest-ledger.{client}.{stamp}.bak.json')
        bak.write_text(json.dumps({client: d[client]}, ensure_ascii=False, indent=1), encoding='utf-8')
        n = len(d.pop(client))
        tmp = led.with_suffix('.tmp')
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, led)
        log(f'任務帳本：已清掉 {client} 的 {n} 筆舊紀錄（備份 {bak.name}）')
    else:
        log(f'任務帳本：{client} 沒有舊紀錄')
    for p in list(STATE_DIR.glob(f'katan-{client}-*.json')) + [STATE_DIR / f'rebirthprep-{client}.json']:
        if p.exists():
            shutil.move(str(p), str(p.with_name(p.stem + f'.{stamp}.bak')))
            log(f'續跑狀態：{p.name} 已備份移開')
    return 0


REBIRTH_PREREQ = ['猜謎三兄弟', '卡坦的願望', '恐龍博士']     # 轉生前一定要先做完（轉生後任務全部重置，使用者 2026-10-14）


def rebirth_prereq_missing(client: str) -> list:
    """帳本裡這三個任務不是 done 的清單；轉生不可逆，漏做就不准轉。"""
    import json
    try:
        led = json.loads((ROOT / 'notes' / 'quest-ledger.json').read_text(encoding='utf-8')).get(client, {})
    except (OSError, ValueError):
        led = {}
    return [n for n in REBIRTH_PREREQ if led.get(n, {}).get('status') != 'done']


def stage_rebirth(client: str, wait_min: int) -> int:
    """go（組隊 + 導航到精靈王）→ 對話窗開著等使用者放行 → 偵測 5 人回到 1 級附近才算完成"""
    import q1920 as q
    miss = rebirth_prereq_missing(client)
    if miss:
        log(f'轉生前置未完成：{miss} 帳本不是 done → 不轉生、停手（轉生不可逆，任務會全部重置）')
        return 1
    rc = subprocess.call(py('rebirth1920.py', '--client', client, 'go'))
    if rc:
        return rc
    log('已到精靈王、對話窗開著 → 自動點對話選項轉生（全自動，使用者已確認）')
    rc = subprocess.call(py('rebirth1920.py', '--client', client, 'auto'))
    if rc:
        return rc
    t0 = time.time()
    while time.time() - t0 < wait_min * 60:
        time.sleep(30)
        try:
            if q.state() != 'MAIN':
                continue
        except Exception:
            pass
        lv = read_team_levels_retry()
        log(f'等待轉生完成；5 人等級：{lv}')
        hud = None
        if all(v is None for v in lv):        # 轉生後隊伍可能解散 → 組隊面板空的：改讀 HUD 隊長等級（< 20 = 已轉生）
            try:
                import walk
                import levelwatch
                p = levelwatch.parse_level(walk.stat())
                hud = p[1] if p else None
                log(f'組隊面板讀不到 → HUD 隊長等級：{hud}')
            except Exception as e:
                log(f'HUD 等級讀取失敗：{e}')
        if (hud is not None and hud < 20) or all(v is not None and v < 20 for v in lv):
            log('偵測到 5 人都回到低等級 → 轉生完成')
            return 0
    log('逾時仍沒偵測到轉生完成 → 停手')
    return 7


def run_cmds(client: str, stage: str) -> int:
    extra = []
    if stage in ('quests', 'riddle', 'gate'):          # questflow 的 HUD 轉生數 OCR 會讀錯 → 由組隊面板讀好傳進去
        tr = read_trans()
        if tr is None:      # 使用者 2026-10-14：讀不到就 ESC，改開左上角人物資訊面板讀大字，不重試組隊面板 3 次
            log('組隊面板讀不到轉生數 → ESC 後改用人物資訊面板')
            _esc()
            time.sleep(0.8)
            try:
                import questflow1920 as qf
                tr = qf.trans_from_info_panel()
            except Exception as e:
                log(f'人物資訊面板讀轉數失敗：{e}')
        log(f'讀到轉生數：{tr}')
        if tr is not None:
            extra = ['--trans', str(tr)]
    for desc, argv in plan(client, stage):
        if extra and argv and 'questflow1920.py' in argv[1]:
            argv = argv + extra
        rc = run_argv(client, stage, desc, argv)
        if rc:
            return rc
    return 0


def run_argv(client: str, stage: str, desc: str, argv: list) -> int:
    log(f'[{stage}] {desc}')
    env = dict(os.environ, PSA_EXE_MATCH=client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
    env.setdefault('PSA_TILE_SCALE', '0.5')
    env.setdefault('PSA_CLICK_HOLD_MS', '120')
    rc = subprocess.call(argv, cwd=str(ROOT), env=env)
    if rc:
        log(f'[{stage}] 退出碼 {rc} → 停手')
    return rc


def stage_grind(client: str, every: int, max_min: int) -> int:
    """練等 1~131：levelwatch 用 HUD OCR（會漏位數）說到 131 就結束，所以結束後一定開人物資訊面板讀 5 人等級確認
    （使用者 2026-10-13）；沒全到 131 就再跑 levelwatch 繼續練（HUD 若真的 >= 131 它會馬上結束，隔 every 秒再開面板看）"""
    import q1920 as q
    cmds = plan(client, 'grind')
    rc = run_argv(client, 'grind', *cmds[0])
    if rc:
        return rc
    t0 = None                                        # 第一次 levelwatch 結束後才開始算「確認等待」時間
    while True:
        rc = run_argv(client, 'grind', *cmds[1])
        if rc:
            return rc
        log('[grind] levelwatch 結束（HUD 讀到 >= 131）→ 開人物資訊面板確認 5 人等級')
        lv = [None] * 5
        for _ in range(30):                          # 戰鬥中不開面板，最多等 5 分鐘
            try:
                if q.state() == 'MAIN':
                    break
            except Exception:
                break
            time.sleep(10)
        lv = read_team_levels_retry()
        log(f'[grind] 5 人等級：{lv}（目標 >= {GRIND_TARGET}）')
        if levels_ready(lv):
            return 0
        t0 = t0 or time.time()
        if time.time() - t0 > max_min * 60:
            log(f'[grind] 超過 {max_min} 分鐘 5 人還沒全到 {GRIND_TARGET} 級 → 停手')
            return 7
        log(f'[grind] 面板顯示還沒全到 {GRIND_TARGET}（HUD 可能誤讀）→ 繼續練')
        time.sleep(every)


def state_file(client: str) -> Path:
    return STATE_DIR / f'fullrun-{client}.json'


def record_stage(client: str, stage: str, t0: float, rc) -> None:
    """統計用：每個階段一行寫進 tools/.cache/stats-fullrun.jsonl（stats.py 讀；寫失敗不影響流程）"""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        row = {'client': client, 'stage': stage, 'start': time.strftime('%F %T', time.localtime(t0)),
               'end': time.strftime('%F %T'), 'minutes': round((time.time() - t0) / 60, 1), 'rc': rc,
               'target': GRIND_TARGET if stage in ('train', 'wait131', 'grind') else None}
        with open(STATE_DIR / 'stats-fullrun.jsonl', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:
        pass


def load_done(client: str) -> list:
    try:
        done = json.loads(state_file(client).read_text(encoding='utf-8')).get('done', [])
    except (OSError, ValueError):
        return []
    if 'quests' in done and 'adult' not in done:     # 2026-10-15 新增 adult 階段前的狀態檔：已過 quests 就視為成人儀式也做過
        done.insert(done.index('quests'), 'adult')
    return done


def save_done(client: str, done: list) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file(client).write_text(json.dumps({'done': done, 'at': time.strftime('%F %T')}, ensure_ascii=False), encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--plan', action='store_true', help='只印階段與指令')
    ap.add_argument('--from', dest='from_stage', choices=STAGES, help='從這個階段開始（前面視為已完成）')
    ap.add_argument('--only', choices=STAGES, help='只跑這個階段')
    ap.add_argument('--fresh', action='store_true', help='忽略狀態檔，全部重來')
    ap.add_argument('--wait-every', type=int, default=60, help='wait131 每幾秒再看一次')
    ap.add_argument('--wait-max-min', type=int, default=180, help='wait131 最長等幾分鐘')
    ap.add_argument('--grind-wait-max-min', type=int, default=600, help='grind 結束後面板確認 5 人 >= 131 最長等幾分鐘（使用者 2026-10-13：600）')
    ap.add_argument('--rebirth-wait-min', type=int, default=60, help='rebirth 等使用者放行的最長分鐘數')
    a = ap.parse_args(argv)
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if a.plan:
        for s in STAGES:
            cmds = plan(a.client, s)
            if cmds:
                for desc, argv_ in cmds:
                    print(f'{s:9} {desc}\n          {" ".join(os.path.basename(x) if i == 1 else x for i, x in enumerate(argv_) if i)}')
            else:
                print(f'{s:9} （內建）')
        return 0
    import winenv
    winenv.enable_server()
    import pausegate
    done = [] if a.fresh else load_done(a.client)
    if a.from_stage:
        done = list(STAGES[:STAGES.index(a.from_stage)])
    for s in STAGES:
        if a.only and s != a.only:
            continue
        if s in done and not a.only:
            log(f'[{s}] 已完成，跳過')
            continue
        pausegate.wait(log)
        log(f'===== 階段 {s} =====')
        _t0 = time.time()
        if s in ('train', 'wait131', 'grind'):
            globals()['GRIND_TARGET'] = detect_grind_target(a.client)
            if GRIND_TARGET >= 140:
                log('練功目標 140（漆黑洞窟(五轉)）→ 要掛 16~18 小時，不設定多久沒動作')
            else:
                log(f'練功目標 {GRIND_TARGET}')
        if s == 'wait131':
            rc = stage_wait131(a.client, a.wait_every, a.wait_max_min)
        elif s == 'grind':
            rc = stage_grind(a.client, a.wait_every, a.grind_wait_max_min)
        elif s == 'stopenc':
            rc = stage_stopenc(a.client)
        elif s == 'ledger':
            rc = stage_ledger(a.client)
        elif s == 'rebirth':
            rc = stage_rebirth(a.client, a.rebirth_wait_min)
        else:
            rc = run_cmds(a.client, s)
        record_stage(a.client, s, _t0, rc)
        if rc:
            return rc
        if s not in done:
            done.append(s)
        save_done(a.client, done)
    save_done(a.client, [])               # 轉生後任務全部重置：下一輪從頭跑（ledger 階段也會再清一次帳本）
    log('全部階段完成（狀態檔已歸零，下一輪轉生後直接再跑同一行）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
