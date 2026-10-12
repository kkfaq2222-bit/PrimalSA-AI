#!/usr/bin/env python3
r"""卡坦的願望：練寵（五兄弟洞窟）+ 交任務（1920×1017）。katan1920.py 的 train / handin 階段呼叫這支。

  train    外掛「自動轉換戰寵」1~4 列轉 25 級 → 5 人組隊 → 傳去五兄弟洞窟（快速 + 自動戰鬥、原地遇敵）→
           每 2 分鐘讀 HUD 出戰寵物等級；換寵 3 次且第 4 隻 >= 25 級 = 4 隻都到，再多練 90 秒收；連續 30 分鐘沒進展就停手。
  handin   --step 1 / 2：全部任務寵改「休息」→ 確認 5 人組隊 → 到薩伊那斯對話交任務（questflow.run_quest 只做到該步）。

用法（專案根目錄）：
  uv run --no-project python tools/gui/katantrain1920.py --client kkfaq22222 train [--target 25] [--stall-min 30]
  uv run --no-project python tools/gui/katantrain1920.py --client kkfaq22222 handin --step 1
退出碼：0 成功；1 用法 / 找不到；4 外掛；6 疑似驗證視窗；7 逾時（沒進展）。停手 = 通知使用者，不自己亂猜。
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]

TRAIN_SPOT = '五兄弟洞窟'
QUEST = '卡坦的願望'
FIRST_POLL_S = 150            # 使用者：150 秒後第一次檢查
POLL_S = 30                   # 每隻約 1.5 分鐘升到 25，輪詢要比這短才不會漏掉換寵
SLOTS = 4                     # 任務寵在寵物欄 1~4 格（第 5 格不動）


def log(m: str) -> None:
    print(time.strftime('%H:%M:%S'), m, flush=True)


def all_done(levels: dict, target: int) -> bool:
    """levels = {角色: [第 1~4 格等級 or None]}；5 人 × 4 隻都讀到且 >= target"""
    return (len(levels) == 5 and all(len(v) == SLOTS and all(x is not None and x >= target for x in v)
                                     for v in levels.values()))


def total(levels: dict) -> int:
    return sum(x for v in levels.values() for x in v if x is not None)


def stalled(best_total: int, new_total: int, since_s: float, limit_s: float):
    """→ (新的最高總等級, 是否停滯)；總等級有增加就重置計時（呼叫端重置 since）"""
    if new_total > best_total:
        return new_total, False
    return best_total, since_s >= limit_s


SETTLE_S = 120                # 達標後多練一會兒，讓經驗略少的角色也過 25 級（5 人同隊戰鬥，等級差通常 1~2 級）


def done_by_swaps(swaps: int, lv: int, target: int) -> bool:
    """出戰寵物等級 > target = 一定是最後一隻（前面的在剛好 target 級就被換掉了）→ 完成；
    或換過 3 次（1→2→3→4）且現在出戰的第 4 隻 >= target。（2026-10-12：第一次讀到數字時已經 34 級、換寵次數是 0，
    只看換寵次數會永遠等不到完成）"""
    if lv is None:
        return False
    return lv > target or (swaps >= SLOTS - 1 and lv >= target)


def parse_pet_level(text) -> int | None:
    """'0轉44級' → 44；'0轉' / '' / '0轉級'（OCR 漏讀數字）→ None"""
    import re
    m = re.search(r'(\d+)\s*轉\s*(\d+)', str(text or ''))
    return int(m[2]) if m else None


def hud_pet_level(walk, tries: int = 5):
    """HUD 的出戰寵物等級（walk.stat 的 petLevel）。單次讀取不穩（實測 3 次只讀到 2 次），
    所以連讀最多 tries 次，取第一個讀得到的；全部讀不到 None。"""
    import time as _t
    for k in range(tries):
        try:
            lv = parse_pet_level(walk.stat().get('petLevel'))
        except Exception:
            lv = None
        if lv is not None:
            return lv
        if k < tries - 1:
            _t.sleep(0.8)
    return None


PET_TAB = (884, 150)             # 寵物面板右側「寵物」分頁（倉庫 884,285 / 圖鑑 884,420）；等級「0轉N」只有這個分頁才顯示


def slot4_level(q, qf, role: int = 1, slot: int = 4):
    """開寵物面板 → 切到「寵物」分頁 → 選第 slot 隻 → 讀中間下方黃字「0轉N」的 N（使用者 2026-10-12 的做法）。
    外掛是 1→2→3→4 順序換，第 4 隻 >= 25 就代表 4 隻都達標。讀不到 None。"""
    qf.open_pet_panel()
    try:
        q.click(PET_TAB, wait_ms=900, note='katan 寵物面板：寵物分頁')
        other = 1 if role == 1 else 0
        q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[other]), wait_ms=500, note='katan 刷新')
        q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[role - 1]), wait_ms=900, note=f'katan 角色 {role}')
        q.click((qf.PET_SLOT_X, qf.PET_SLOT_Y[slot - 1]), wait_ms=900, note=f'katan 選第 {slot} 隻')
        for _ in range(3):
            lv = qf.read_level_text()
            if lv is not None:
                return lv
            q.sleep(0.6)
        return None
    finally:
        qf.close_pet_panel()


def slot_levels(q, qf, roles, slot: int = 4) -> dict:
    """面板只開一次，逐個角色讀第 slot 隻的「0轉N」→ {角色: 等級 or None}"""
    qf.open_pet_panel()
    out = {}
    try:
        q.click(PET_TAB, wait_ms=900, note='katan 寵物面板：寵物分頁')
        for r in roles:
            other = 1 if r == 1 else 0
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[other]), wait_ms=450, note='katan 刷新')
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[r - 1]), wait_ms=800, note=f'katan 角色 {r}')
            q.click((qf.PET_SLOT_X, qf.PET_SLOT_Y[slot - 1]), wait_ms=800, note=f'katan 選第 {slot} 隻')
            lv = None
            for _ in range(3):
                lv = qf.read_level_text()
                if lv is not None:
                    break
                q.sleep(0.5)
            out[r] = lv
    finally:
        qf.close_pet_panel()
    return out


def bar_levels(q, qf) -> list:
    """開寵物面板，直接讀角色 1 寵物欄 1~4 格右下角的等級數字（不點進任何寵物）→ [等級 or None ×4]。
    2 位數以上 OCR 讀得到；1~9 級的單一數字讀不到 = None（視為還沒到 10 級）。"""
    qf.open_pet_panel()
    try:
        other = 1
        q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[other]), wait_ms=500, note='katan 刷新')
        q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[0]), wait_ms=900, note='katan 讀寵物欄等級')
        out = []
        for i in range(SLOTS):
            x, dy, w, h = LVL_BOX
            y = qf.PET_SLOT_Y[i] + dy
            texts = []
            for opts in (('-Zooms', '3,4'), ('-Zooms', '3,4', '-Dark', '170'), ('-Zooms', '2,3')):
                try:
                    texts += list(q.uk().ocr((x, y, w, h), *opts))
                except Exception:
                    pass
            out.append(parse_level(texts))
        return out
    finally:
        qf.close_pet_panel()


def battle_first(q, qf) -> None:
    """5 人各把寵物欄第 1 隻設「出戰」（取出 / 分來的寵物預設是「等待」，沒有出戰寵物就拿不到經驗，HUD 也沒有寵物等級）"""
    qf.open_pet_panel()
    try:
        for r in range(5):
            other = 0 if r else 1
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[other]), wait_ms=500, note='katan 刷新')
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[r]), wait_ms=900, note=f'katan 角色 {r + 1}')
            q.click((qf.PET_SLOT_X, qf.PET_SLOT_Y[0]), wait_ms=800, note='katan 選第 1 隻')
            q.click(qf.PET_BATTLE_BTN, wait_ms=900, note='katan 第 1 隻出戰')
    finally:
        qf.close_pet_panel()


def sub(script: str, *args) -> int:
    argv = [sys.executable, str(HERE / script), *[str(x) for x in args]]
    return subprocess.run(argv, cwd=str(ROOT), env=dict(os.environ)).returncode


def setup_env(client: str):
    os.environ['PSA_EXE_MATCH'] = client
    os.environ.setdefault('PSA_GUI_SERVER', '1')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import q1920 as q
    import questflow1920 as qf
    q.CLIENT = client
    qf.RUN_LOG = str(q.STATE_DIR / f'katan-train-{client}.log')
    return q, qf


def ensure_team(q) -> None:
    q.preflight()
    if not q.team_ok():
        q.form_team()
    q.require_team()
    q.set_ass(flee=False, auto=True)
    q.TRUST_TEAM = True


LVL_BOX = (180, 8, 44, 24)       # 寵物欄每格右下角的等級數字：(x, 相對格中心 y 的位移, 寬, 高)；不用點進每隻寵物


def parse_level(texts) -> int | None:
    """OCR 結果（多組字串）→ 等級：取出現最多的 1~200 之間整數；讀不到 None"""
    import collections
    import re
    vals = []
    for t in texts:
        for m in re.findall(r'\d+', str(t)):
            v = int(m)
            if 1 <= v <= 200:
                vals.append(v)
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def read_levels(q, qf) -> dict:
    """逐人讀寵物欄 1~4 格的等級：直接讀每格右下角的數字，不點進寵物（使用者 2026-10-12：一隻一隻點進去看太慢也讀不到）。
    每人只需要切換一次角色（先切別人再切回來刷新）。"""
    qf.open_pet_panel()
    out = {}
    try:
        for r in range(5):
            other = 0 if r else 1
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[other]), wait_ms=500, note='katan 刷新')
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[r]), wait_ms=900, note=f'katan 讀等級：角色 {r + 1}')
            lv = []
            for i in range(SLOTS):
                x, dy, w, h = LVL_BOX
                y = qf.PET_SLOT_Y[i] + dy
                texts = []
                for opts in (('-Zooms', '3,4'), ('-Zooms', '3,4', '-Dark', '170'), ('-Zooms', '2,3')):
                    try:
                        texts += list(q.uk().ocr((x, y, w, h), *opts))
                    except Exception:
                        pass
                lv.append(parse_level(texts))
            out[r + 1] = lv
    finally:
        qf.close_pet_panel()
    return out


def cmd_train(a) -> int:
    q, qf = setup_env(a.client)
    import pausegate
    try:
        lv0 = {}
        import walk as _walk
        lvn = None
        for _ in range(4):                       # 戰鬥動畫中 HUD 會被蓋住讀不到：隔幾秒重讀，不要一次讀不到就當作還沒練
            lvn = hud_pet_level(_walk)
            if lvn is not None:
                break
            q.sleep(4)
        if lvn is not None and lvn > a.target:
            log(f'出戰寵物已是 {lvn} 級（> {a.target}，一定是最後一隻）→ 不用再練，直接收')
            return 0
        battle_first(q, qf)
        log('5 人第 1 隻已設出戰')
        rc = sub('autoswap1920.py', '--client', a.client, '--roles', '1,2,3,4,5', '--level', a.target)
        if rc != 0:
            log(f'自動轉換戰寵設定失敗（退出碼 {rc}）→ 停手')
            return 4
        ensure_team(q)
        q.grind(TRAIN_SPOT)
        # 完成判斷改用 HUD 的「出戰寵物等級」（數字 OCR 穩）+ 換寵次數：外掛轉換級數 25 是照 1→2→3→4 順序換，
        # 出戰寵物升到 25 就換下一隻（等級從 25 掉回個位數）；換過 3 次且現在出戰的第 4 隻 >= 25 = 4 隻都到了。
        # 不再逐隻點進去讀（2026-10-12：一隻一隻點、20 隻全讀成 None、花 1 分鐘）。
        import walk
        t0 = time.time()
        swaps, prev, reset_pending = 0, None, False
        none_streak, bar_best, finished = 0, 0, False
        progress, t_prog = (0, 0), time.time()
        first = True
        while True:
            pausegate.wait(log)
            q.sleep(FIRST_POLL_S if first else POLL_S)
            first = False
            if q.state() == 'OTHER':
                q.sleep(5)
                if q.state() == 'OTHER':
                    raise q.Halt(q.EXIT_HALT, '練寵中連續看到不認得的畫面（疑似驗證視窗）：停手')
            lv = hud_pet_level(walk)
            if lv is None:
                # 1 級的單一數字 OCR 讀不到（'0轉級'）：高等級之後讀不到 = 剛換上新的 1 級寵物
                if prev is not None and prev >= 24:
                    reset_pending = True
                none_streak += 1
                log('出戰寵物等級讀不到（1 級單一數字 / 戰鬥中）')
                if none_streak >= 1:                   # HUD 讀不到：開寵物面板看第 4 隻的等級（>= 目標就全部達標）
                    try:
                        l4 = slot4_level(q, qf)
                    except q.Halt:
                        l4 = None                      # 戰鬥中開不了面板：下一輪再試
                    log(f'寵物面板第 4 隻等級：{l4}')
                    if l4 is not None and l4 >= a.target:
                        finished = True
                    elif l4 is not None and l4 > bar_best:
                        bar_best, t_prog = l4, time.time()
                if finished:
                    break
                if time.time() - t_prog >= a.stall_min * 60:
                    raise q.Halt(q.EXIT_TIMEOUT, f'連續 {a.stall_min} 分鐘等級沒有進展：停手，請看畫面')
                continue
            none_streak = 0
            if prev is not None and (lv < prev - 3 or (reset_pending and lv <= prev)):
                swaps += 1
                log(f'偵測到換寵（{prev} → {lv} 級），第 {swaps} 次')
            reset_pending = False
            prev = lv
            log(f'練寵進度（{int(time.time() - t0)} 秒）：出戰寵物 {lv} 級；已換寵 {swaps} 次')
            if done_by_swaps(swaps, lv, a.target):
                break
            now_prog = (swaps, lv)
            if now_prog > progress:
                progress, t_prog = now_prog, time.time()
            elif time.time() - t_prog >= a.stall_min * 60:
                raise q.Halt(q.EXIT_TIMEOUT, f'連續 {a.stall_min} 分鐘出戰寵物等級沒有進展（{lv} 級、換寵 {swaps} 次）：停手，請看畫面')
        log(f'4 隻都到 {a.target} 級（換寵 {swaps} 次、HUD 最後讀到 {prev} 級）；再多練 {SETTLE_S} 秒讓其他角色跟上')
        q.sleep(SETTLE_S)
        q.set_ass(encounter=False)
        q.wait_battle_end()
        log(f'5 人 × {SLOTS} 隻都 >= {a.target} 級，已關原地遇敵')
        return 0
    except Exception as e:
        code = getattr(e, 'code', 99)
        log(f'停手（退出碼 {code}）：{getattr(e, "msg", e)}')
        return code if isinstance(code, int) else 99


def cmd_handin(a) -> int:
    q, qf = setup_env(a.client)
    try:
        rc = sub('petrest1920.py', '--client', a.client, '--roles', '1,2,3,4,5')
        if rc != 0:
            log(f'改休息失敗（退出碼 {rc}）→ 停手')
            return 4
        ensure_team(q)
        log(f'=== 交「{QUEST}」步 {a.step}（5 人組隊，隊長交一次）===')
        qf.run_quest(QUEST, use_potion=False, from_step=a.step, to_step=a.step)
        log(f'「{QUEST}」步 {a.step} 已交')
        return 0
    except Exception as e:
        code = getattr(e, 'code', 99)
        log(f'停手（退出碼 {code}）：{getattr(e, "msg", e)}')
        return code if isinstance(code, int) else 99


def cmd_check(a) -> int:
    """只偵測、不做任何其他事：開寵物面板 → 寵物分頁 → 逐個角色選第 slot 隻 → 讀「0轉N」；
    --roles 的每一個角色都 >= 目標才停（退出碼 0），還沒達標的隔 --every 秒再看（只重看沒達標的）。
    不傳送、不組隊、不設出戰、不改任何設定。"""
    q, qf = setup_env(a.client)
    import pausegate
    roles = [int(x) for x in a.roles.split(',') if x.strip()]
    pending = list(roles)
    last = {}
    t0 = time.time()
    n = 0
    while pending:
        pausegate.wait(log)
        n += 1
        try:
            got = slot_levels(q, qf, pending, slot=a.slot)
        except Exception as e:                       # 戰鬥中開不了面板等：下一輪再看
            got = {}
            log(f'第 {n} 次：開面板失敗（{getattr(e, "msg", e)}）')
        last.update({r: v for r, v in got.items()})
        pending = [r for r in roles if last.get(r) is None or last[r] < a.target]
        shown = '  '.join(f'角色{r}={last.get(r) if last.get(r) is not None else "?"}' for r in roles)
        log(f'第 {n} 次（第 {a.slot} 隻，目標 {a.target}）：{shown}' + (f'；還沒達標：{pending}' if pending else ''))
        if not pending:
            break
        if a.max_min and time.time() - t0 >= a.max_min * 60:
            log(f'超過 {a.max_min} 分鐘仍未全部達標，停止偵測')
            return 7
        time.sleep(a.every)
    log(f'角色 {",".join(map(str, roles))} 的第 {a.slot} 隻都 >= {a.target} 級，停止偵測')
    try:
        import notifyhalt
        notifyhalt.alert('全部達標', ok=True)
    except Exception:
        pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='卡坦的願望：練寵 + 交任務')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    sp = ap.add_subparsers(dest='cmd', required=True)
    t = sp.add_parser('train')
    t.add_argument('--target', type=int, default=25)
    t.add_argument('--stall-min', type=int, default=30)
    c = sp.add_parser('check', help='只偵測第 N 隻的等級，達標就停、未達標隔幾秒再看')
    c.add_argument('--target', type=int, default=25)
    c.add_argument('--every', type=int, default=20)
    c.add_argument('--roles', default='1,2,3,4,5', help='要檢查的角色（預設 5 人都要達標）')
    c.add_argument('--slot', type=int, default=4)
    c.add_argument('--max-min', type=int, default=0, help='最多偵測幾分鐘（0 = 不限）')
    h = sp.add_parser('handin')
    h.add_argument('--step', type=int, choices=[1, 2], required=True)
    a = ap.parse_args(argv)
    return {'train': cmd_train, 'handin': cmd_handin, 'check': cmd_check}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
