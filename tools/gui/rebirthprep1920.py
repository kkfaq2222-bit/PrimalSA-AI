#!/usr/bin/env python3
r"""轉生後 1 級、開始練等之前的準備（1920×1017；終端機直接跑；只用標準庫，實際操作都呼叫現有腳本）。

使用者規劃（2026-10-12）：
  1. 角色 5 單人抓 5 隻格魯西斯（老虎系；不勾自動存倉庫，5 隻留在寵物欄）
  2. 角色 5 的寵物暱稱改回原本種類名（petrename1920）
  3. 寵物欄第 2~5 格存公共倉庫（4 隻）；第 1 格留給角色 5 自己
  4. 角色 1、2、3、4 各從公共倉庫領第 1 格（--first：公共倉庫只放這一批同一種）
  5. 外掛區域：5 人「鎖定騎寵」選格魯西斯並打勾
  6. 從個人倉庫領出金飛（朵拉比斯）→ 設出戰（戰寵）
  （抓完、剩的寵物誘餌一律存回共用倉庫）

階段（--phase）：check（角色 5 寵物欄全空 + 解散隊伍）、catch、rename、store、give、lock、gold、fight；all = 依序全部。
用法（專案根目錄；Windows 原生 PSA_GUI_SERVER=1 較快）：
  uv run --no-project python tools/gui/rebirthprep1920.py --client kkfaq22222 --plan                 # 只印每個階段要跑的指令
  uv run --no-project python tools/gui/rebirthprep1920.py --client kkfaq22222 --do --resume         # 全部執行；中斷後同一行再跑會接續
  uv run --no-project python tools/gui/rebirthprep1920.py --client kkfaq22222 --phase lock --do     # 只做外掛鎖定騎寵
  uv run --no-project python tools/gui/rebirthprep1920.py --client kkfaq22222 lockmount             # 內部：外掛鎖定騎寵（--roles 1,2,3,4,5）
任何一個指令退出碼不是 0 就停手並通知；暫停檔（pausegate）在指令之間生效。
注意：抓寵要在「有格魯西斯野怪」的地圖上做；本腳本不傳送，請先自己站到抓寵點。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
STATE_DIR = ROOT / 'tools' / '.cache'

PET = '格魯西斯'
PET_KEYS = ('格魯西斯', '格魯', '魯西斯', '西斯')       # OCR 常缺字：任一片段命中就算
SYSTEM = '老虎系'
CATCHER = 5
OTHERS = [1, 2, 3, 4]
ROLES = [1, 2, 3, 4, 5]
ROLE_NAMES = {1: 'DKBO', 2: 'DKBO2', 3: 'DKBO3', 4: 'DKBO4', 5: 'DKBO5'}
PHASES = ['check', 'catch', 'rename', 'store', 'give', 'lock', 'gold', 'fight']

# 外掛「一般設置」分頁（1920×1017 截圖座標；2026-10-12 在 11111 實機量）
ASS_GENERAL_TAB = (540, 127)
LOCK_MOUNT_CHK = (439, 189)         # 鎖定騎寵 勾選框（純白 = 沒勾）
LOCK_MOUNT_FIELD = (575, 178, 225, 22)   # 欄位文字 OCR 框
LOCK_MOUNT_ARROW = (835, 189)       # 下拉鈕
LIST_X, LIST_Y0, LIST_DY = 688, 217, 26   # 下拉清單：第 k 列中心 y = 217 + 26k（依寵物欄順序，空格不列）
UNCHECKED = (255, 255, 255)
FALLBACK_ROW = 3                    # 名稱 OCR 驗證不到時，格魯西斯在下拉清單第 3 列（使用者說明）


def log(m: str) -> None:
    print(time.strftime('%H:%M:%S'), m, flush=True)


def py(script: str, *args) -> list:
    return [sys.executable, str(HERE / script), *[str(x) for x in args]]


def plan(client: str, phase: str) -> list:
    """純函式：該階段要跑的指令 [(說明, argv)]；離線可測"""
    c = ['--client', client]
    out = []
    if phase == 'check':
        out.append(('解散隊伍（抓寵要單人）', py('q1920.py', *c, 'disband')))
        out.append((f'確認角色 {CATCHER} 寵物欄全空（5 格都要能放格魯西斯；有寵物就停手）',
                    py('petdepot1920.py', *c, '--check-empty', '--roles', CATCHER)))
    elif phase == 'catch':
        out.append((f'角色 {CATCHER} 抓 {PET} ×5（{SYSTEM}；不勾自動存倉庫，5 隻留在寵物欄）',
                    py('catchrun1920.py', *c, '--role', CATCHER, '--system', SYSTEM, '--pet', PET, '--n', 5, '--source', 'public')))
        out.append((f'角色 {CATCHER} 剩餘寵物誘餌存回共用倉庫（抓完放回去）', py('baitstore1920.py', *c, '--role', CATCHER)))
    elif phase == 'rename':
        out.append((f'角色 {CATCHER} 寵物暱稱改回原本種類名', py('petrename1920.py', *c, '--expect', ','.join(PET_KEYS), '--count', 5, '--roles', CATCHER)))
    elif phase == 'store':
        out.append((f'角色 {CATCHER} 寵物欄第 2~5 格存公共倉庫（4 隻；第 1 格留自己）',
                    py('petfetchimg1920.py', *c, 'storebar', '--role', CATCHER, '--slots', '2,3,4,5', '--tab', 'public', '--do')))
    elif phase == 'give':
        out.append((f'{PET} 分給角色 ' + '、'.join(map(str, OTHERS)) + '（各領公共第 1 格）',
                    py('petgive1920.py', *c, '--first', '--plan', ';'.join(f'{r}:{PET}' for r in OTHERS))))
    elif phase == 'lock':
        out.append((f'外掛「鎖定騎寵」5 人選{PET}並打勾', py('rebirthprep1920.py', *c, 'lockmount', '--roles', '1,2,3,4,5')))
    elif phase == 'gold':
        out.append(('5 人從個人倉庫領出 1 級金飛（朵拉比斯；點選後讀卡片等級驗證）', py('petgetgold1920.py', *c, '--roles', '1,2,3,4,5', '--only', '朵拉', '--level', 1)))
    elif phase == 'fight':
        out.append(('5 人朵拉比斯設出戰（戰寵）', py('petsetup1920.py', *c, '--roles', '1,2,3,4,5')))
    else:
        raise ValueError(phase)
    return out


# ---- 外掛：鎖定騎寵（選格魯西斯 → 驗證欄位 → 打勾 → 驗證）----
def _hit(text: str) -> bool:
    return any(k in text for k in PET_KEYS)


def _ocr(uikit, box) -> str:
    out = ''
    for opts in (('-Zooms', '2,3'), ('-Zooms', '3,4')):
        try:
            out += ''.join(uikit.ocr(box, *opts))
        except Exception:
            pass
    return out


def lock_mount(client: str, roles: list) -> int:
    os.environ['PSA_EXE_MATCH'] = client
    import winenv
    winenv.enable_server()
    import ass
    import uikit
    # 外掛「鎖定騎寵」要先在寵物面板把那隻寵選一下（使用者 2026-10-13）：5 人各自開寵物面板 → 選角色 → 點寵物欄第 1 格（格魯西斯）→ 關面板
    import petdepot1920 as pd
    if pd.open_panel():
        try:
            for r in roles:
                pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=1000, note=f'lockmount 先選角色 {r}')
                pd.click(pd.SLOT_X, pd.SLOT_Y[0], wait=800, note=f'lockmount 角色 {r} 先在寵物欄選第 1 格（{PET}）')
        finally:
            pd.click(*pd.CLOSE_X, wait=700, note='lockmount 關寵物面板')
    else:
        log('寵物面板打不開 → 略過「先選寵」直接做外掛鎖定')
    if not ass.open_panel(timeout=40):
        log('外掛面板打不開（戰鬥 / 對話中？）')
        return 4
    rc = 0
    try:
        for r in roles:
            uikit.gui('seq', 'click 480 55; wait 300', note='lockmount 點標題列（收掉可能還開著的下拉清單）')   # 下拉清單開著會擋住角色清單：外掛選不到角色 3（22222 2026-10-13）
            if not ass.select_role(ROLE_NAMES[r]):
                log(f'角色 {r}：外掛選不到角色')
                return 4
            uikit.gui('seq', f'click {ASS_GENERAL_TAB[0]} {ASS_GENERAL_TAB[1]}; wait 700', note=f'lockmount 角色 {r} 一般設置')
            field = _ocr(uikit, LOCK_MOUNT_FIELD)
            if not _hit(field):
                uikit.gui('seq', f'click {LOCK_MOUNT_ARROW[0]} {LOCK_MOUNT_ARROW[1]}; wait 800', note=f'lockmount 角色 {r} 開下拉')
                picked = False
                for k in range(5):
                    y = LIST_Y0 + LIST_DY * k
                    row = _ocr(uikit, (575, y - 11, 225, 22))
                    if _hit(row):
                        uikit.gui('seq', f'click {LIST_X} {y}; wait 800', note=f'lockmount 角色 {r} 選{PET}（第 {k + 1} 列）')
                        picked = True
                        break
                if not picked:                       # 使用者 2026-10-12：驗證不到時，格魯西斯打開會在第 3 格
                    y = LIST_Y0 + LIST_DY * (FALLBACK_ROW - 1)
                    uikit.gui('seq', f'click {LIST_X} {y}; wait 800', note=f'lockmount 角色 {r} 名稱讀不到 → 選第 {FALLBACK_ROW} 列')
                    log(f'角色 {r}：下拉清單 OCR 認不出「{PET}」→ 依規則選第 {FALLBACK_ROW} 列（無法驗證名稱）')
                else:
                    field = _ocr(uikit, LOCK_MOUNT_FIELD)
                    if not _hit(field):
                        log(f'角色 {r}：選了之後欄位讀到「{field}」（OCR 沒認出{PET}，照規則繼續打勾）')
            def is_checked() -> bool:
                # 勾選框內暗色（✓ 筆劃）點數：有勾 63~71、沒勾 0（2026-10-13 實測；舊版只取 1 個像素會讀錯）
                pts = [(x, y) for y in range(178, 200, 2) for x in range(428, 452, 2)]
                c = uikit.px(pts) or []
                return sum(1 for (rr, gg, bb) in c if rr < 110 and gg < 110 and bb < 110) >= 8

            def refreshed_checked() -> bool:
                # 外掛的勾選圖示不會自己更新：切到別的角色再切回來才讀得到
                other = ROLE_NAMES[1] if r != 1 else ROLE_NAMES[2]
                ass.select_role(other)
                time.sleep(0.4)
                ass.select_role(ROLE_NAMES[r])
                time.sleep(0.4)
                uikit.gui('seq', f'click {ASS_GENERAL_TAB[0]} {ASS_GENERAL_TAB[1]}; wait 600', note=f'lockmount 角色 {r} 回一般設置')
                return is_checked()

            checked = is_checked()
            if not checked:
                uikit.gui('seq', f'click {LOCK_MOUNT_CHK[0]} {LOCK_MOUNT_CHK[1]}; wait 700', note=f'lockmount 角色 {r} 勾鎖定騎寵')
                checked = refreshed_checked()
            log(f'角色 {r}：鎖定騎寵 = {PET}，{"已打勾" if checked else "沒勾起來（讀不到變化）"}')
            if not checked:
                rc = 6
    finally:
        ass.close_panel()
    return rc


# ---- 階段執行 ----
def state_path(client: str) -> Path:
    return STATE_DIR / f'rebirthprep-{client}.json'


def load_done(client: str) -> list:
    try:
        return json.loads(state_path(client).read_text(encoding='utf-8')).get('done', [])
    except (OSError, ValueError):
        return []


def save_done(client: str, done: list) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(client).write_text(json.dumps({'done': done, 'at': time.strftime('%F %T')}, ensure_ascii=False), encoding='utf-8')


def run_phase(client: str, phase: str, do: bool) -> int:
    steps = plan(client, phase)
    log(f'===== 階段 {phase}（{len(steps)} 個指令）{"" if do else " [預覽，不執行]"} =====')
    for i, (title, argv) in enumerate(steps, 1):
        shown = ' '.join(str(x) for x in argv[1:]).replace(str(HERE) + os.sep, '')
        log(f'[{i}/{len(steps)}] {title}')
        log(f'    python {shown}')
        if not do:
            continue
        try:
            import pausegate
            pausegate.wait(log)
        except ImportError:
            pass
        env = dict(os.environ, PSA_EXE_MATCH=client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
        env.setdefault('PSA_CLICK_HOLD_MS', '120')
        r = subprocess.run(argv, cwd=str(ROOT), env=env)
        if r.returncode != 0:
            log(f'停手：「{title}」退出碼 {r.returncode}（階段 {phase}；修好後 --phase {phase} 重跑，--resume 會跳過已完成的階段）')
            try:
                import notifyhalt
                notifyhalt.alert(f'rebirthprep {phase} 退出碼 {r.returncode}')
            except Exception:
                pass
            return r.returncode
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='轉生後 1 級練等前準備')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('cmd', nargs='?', default='run', choices=['run', 'lockmount'])
    ap.add_argument('--phase', default='all', help='check / catch / rename / store / give / lock / gold / fight（逗號接多個）；all = 全部')
    ap.add_argument('--do', action='store_true', help='真的執行（預設只預覽）')
    ap.add_argument('--plan', action='store_true', help='只印計畫')
    ap.add_argument('--resume', action='store_true', help='跳過已完成的階段')
    ap.add_argument('--roles', default='1,2,3,4,5', help='lockmount 用')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if a.cmd == 'lockmount':
        return lock_mount(a.client, [int(x) for x in a.roles.split(',') if x.strip()])
    do = a.do and not a.plan
    phases = PHASES if a.phase == 'all' else [x.strip() for x in a.phase.split(',') if x.strip()]
    bad = [p for p in phases if p not in PHASES]
    if bad:
        print(f'階段只能是 {PHASES} 或 all（不認得：{bad}）')
        return 2
    done = load_done(a.client) if a.resume else []
    for p in phases:
        if a.resume and p in done:
            log(f'階段 {p} 已完成，跳過')
            continue
        rc = run_phase(a.client, p, do)
        if rc:
            return rc
        if do:
            done = sorted(set(load_done(a.client)) | {p})
            save_done(a.client, done)
    log('全部階段完成' if do else '預覽結束（加 --do 才真的執行）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
