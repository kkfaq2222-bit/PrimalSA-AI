#!/usr/bin/env python3
r"""卡坦的願望（任務 2019）抓寵 → 分寵流程總控（1920×1017；只用標準庫，實際操作都呼叫現有腳本）。

任務條件（knowledge）：步 1 收集 4 色鯊魚並練至 25 等以上、步 2 收集 4 色雞並練至 25 等以上；5 個角色各要一套，5 人組隊由隊長交一次。
使用者規劃（2026-10-12）：
  角色 2 抓鯊魚系（克邦凱斯 → 加克拉 → 加格 → 邦恩吉，各 5 隻）、角色 3 抓火雞系（火雞 → 克克洛斯 → 霍爾克 → 奇寶）。
  每一輪：抓 5 隻（不勾自動存倉庫）→ 寵物欄第 2~5 格手動存公共（4 隻）→ 第 1 格存個人倉庫（1 隻）→ 馬上分給其他 4 個角色（公共倉庫永遠只放這一批）。
  第 4 輪不勾自動存倉庫：5 隻留在寵物欄，第 1 格留著、第 2~5 格存公共分出去；最後從個人倉庫領回前 3 輪各 1 隻（名稱是數字）。
  一開始先解散隊伍、把 5 人身上的寵物全部存個人倉庫（含騎寵，不領回）。

階段（--phase）：setup（解散 + 全存個人倉庫）、r1 r2 r3 r4、final（抓寵者領回自己的 3 隻）、
  train（5 人轉換 25 級 → 組隊 → 五兄弟洞窟練，30 分鐘總等級沒增加就停手）、handin（全部休息 → 組隊 → 交卡坦步 1 / 步 2）、
  cleanup（鯊魚：刪修寶；火雞：朵拉比斯存個人倉庫）。--phase all = 依序全部。
一整套從頭到尾（鯊魚 → 火雞）：--family all --phase all --do --resume（一個指令；中斷後同一行再跑會接續）。
用法（專案根目錄）：
  uv run --no-project python tools/gui/katan1920.py --client kkfaq22222 --family shark --plan            # 只印每個階段要跑的指令
  uv run --no-project python tools/gui/katan1920.py --client kkfaq22222 --family shark --phase setup --do
  uv run --no-project python tools/gui/katan1920.py --client kkfaq22222 --family shark --phase r1 --do
  uv run --no-project python tools/gui/katan1920.py --client kkfaq22222 --family shark --phase all --do --resume   # 從上次中斷的階段接續
--family bird（火雞系）沒有校準過的顏色判斷，改用頭像樣板：每輪抓完先 learn --new 學這一種再搬 / 分。
每個階段都是「一串指令」，任何一個指令退出碼不是 0 就停手並通知（notifyhalt）；暫停檔（pausegate）在指令之間生效。
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

FAMILY = {
    'shark': {'role': 2, 'system': '鯊魚系', 'kinds': ['克邦凱斯', '加克拉', '加格', '邦恩吉']},
    'bird': {'role': 3, 'system': '火雞系', 'kinds': ['火雞', '克克洛斯', '霍爾克', '奇寶']},
}
ALL_ROLES = [1, 2, 3, 4, 5]
BAIT_SOURCE = 'public'            # 誘餌全放共用倉庫（使用者 2026-10-12）
PHASES = ['setup', 'r1', 'r2', 'r3', 'r4', 'final', 'train', 'handin', 'cleanup']


def py(script: str, *args) -> list:
    return [sys.executable, str(HERE / script), *[str(x) for x in args]]


def plan(client: str, family: str, phase: str) -> list:
    """純函式：回傳該階段要跑的指令清單 [(說明, argv)]。離線可測。"""
    f = FAMILY[family]
    catcher, system, kinds = f['role'], f['system'], f['kinds']
    others = [r for r in ALL_ROLES if r != catcher]
    c = ['--client', client]
    out = []
    if phase == 'setup':
        out.append(('解散隊伍', py('q1920.py', *c, 'disband')))
        out.append(('5 人寵物全部存個人倉庫（含騎寵）', py('petdepot1920.py', *c, '--do')))
        return out
    if phase in ('r1', 'r2', 'r3'):
        k = kinds[int(phase[1]) - 1]
        # 不勾自動存倉庫（使用者規定）：5 隻抓在寵物欄 → 手動 2~5 格存公共（4 隻）、第 1 格存個人（1 隻）
        out.append((f'抓 {k} ×5（不勾自動存倉庫，5 隻留在寵物欄）', py('catchrun1920.py', *c, '--role', catcher, '--system', system,
                                                              '--pet', k, '--n', 5, '--source', BAIT_SOURCE)))
        if family == 'bird':
            out.append(('公共倉庫存入前先拍一次（學樣板用）', py('petfetchimg1920.py', *c, 'snap', '--open-role', catcher, '--tab', 'public')))
        out.append(('寵物欄第 2~5 格存公共（4 隻）', py('petfetchimg1920.py', *c, 'storebar', '--role', catcher, '--slots', '2,3,4,5', '--tab', 'public', '--do')))
        if family == 'bird':
            out.append((f'學「{k}」樣板（前後比對找出新存進公共的）', py('petfetchimg1920.py', *c, 'learn', '--open-role', catcher, '--tab', 'public', '--new', '--name', k)))
        out.append(('寵物欄第 1 格存個人倉庫（1 隻）', py('petfetchimg1920.py', *c, 'storebar', '--role', catcher, '--slots', '1', '--tab', 'personal', '--do')))
        if family == 'shark':
            out.append((f'{k} 分給角色 ' + '、'.join(map(str, others)),
                        py('petgive1920.py', *c, '--first', '--plan', ';'.join(f'{r}:{k}' for r in others))))
        else:
            for r in others:
                out.append((f'角色 {r} 從公共領「{k}」', py('petfetchimg1920.py', *c, 'fetch', '--role', r, '--tab', 'public', '--names', k, '--do')))
        return out
    if phase == 'r4':
        k = kinds[3]
        out.append((f'抓 {k} ×5（不自動存，5 隻留在寵物欄）', py('catchrun1920.py', *c, '--role', catcher, '--system', system,
                                                        '--pet', k, '--n', 5, '--source', BAIT_SOURCE)))
        out.append(('寵物欄第 2~5 格存公共（第 1 格留著）', py('petfetchimg1920.py', *c, 'storebar', '--role', catcher, '--slots', '2,3,4,5', '--tab', 'public', '--do')))
        if family == 'shark':
            out.append((f'{k} 分給角色 ' + '、'.join(map(str, others)),
                        py('petgive1920.py', *c, '--first', '--plan', ';'.join(f'{r}:{k}' for r in others))))
        else:
            out.append((f'學「{k}」樣板（公共倉庫現在只有這 4 隻）', py('petfetchimg1920.py', *c, 'learn', '--open-role', catcher, '--tab', 'public', '--slot', 1, '--name', k)))
            for r in others:
                out.append((f'角色 {r} 從公共領「{k}」', py('petfetchimg1920.py', *c, 'fetch', '--role', r, '--tab', 'public', '--names', k, '--do')))
        return out
    if phase == 'train':
        out.append(('練寵到 25 級（五兄弟洞窟；30 分鐘沒進展就停手）', py('katantrain1920.py', *c, 'train')))
        return out
    if phase == 'handin':
        step = 1 if family == 'shark' else 2
        out.append((f'全部改休息 → 組隊 → 交卡坦的願望步 {step}', py('katantrain1920.py', *c, 'handin', '--step', step)))
        return out
    if phase == 'cleanup':
        if family == 'shark':
            out.append(('刪除步 1 獎勵「修寶」（只准丟修寶）', py('petdelxb1920.py', *c, '--roles', '1,2,3,4,5')))
        else:
            out.append(('步 2 獎勵（朵拉比斯）存個人倉庫', py('petdepot1920.py', *c, '--do')))
        return out
    if phase == 'final':
        out.append((f'角色 {catcher} 從個人倉庫領回前 3 輪各 1 隻（名稱是數字）',
                    py('petfetchimg1920.py', *c, 'fetch', '--role', catcher, '--numeric', 3, '--do')))
        return out
    raise ValueError(phase)


def state_path(client: str, family: str) -> Path:
    return STATE_DIR / f'katan-{client}-{family}.json'


def load_done(client: str, family: str) -> list:
    try:
        return json.loads(state_path(client, family).read_text(encoding='utf-8')).get('done', [])
    except (OSError, ValueError):
        return []


def save_done(client: str, family: str, done: list) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(client, family).write_text(json.dumps({'done': done, 'at': time.strftime('%F %T')}, ensure_ascii=False), encoding='utf-8')


def log(m: str) -> None:
    print(time.strftime('%H:%M:%S'), m, flush=True)


def run_phase(client: str, family: str, phase: str, do: bool) -> int:
    steps = plan(client, family, phase)
    log(f'===== 階段 {phase}（{family}，{len(steps)} 個指令）{"" if do else " [預覽，不執行]"} =====')
    for i, (title, argv) in enumerate(steps, 1):
        shown = ' '.join(str(x) for x in argv[1:]).replace(str(HERE) + os.sep, '')
        log(f'[{i}/{len(steps)}] {title}')
        log(f'    python {shown}')
        if not do:
            continue
        import pausegate
        pausegate.wait(log)
        env = dict(os.environ, PSA_EXE_MATCH=client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
        env.setdefault('PSA_CLICK_HOLD_MS', '120')
        r = subprocess.run(argv, cwd=str(ROOT), env=env)
        if r.returncode != 0:
            log(f'停手：「{title}」退出碼 {r.returncode}（階段 {phase}；修好後可用 --phase {phase} 重跑，已完成的階段不會重做）')
            try:
                import notifyhalt
                notifyhalt.alert(f'katan {phase} 退出碼 {r.returncode}')
            except Exception:
                pass
            return r.returncode
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='卡坦的願望 抓寵 → 分寵總控')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    ap.add_argument('--family', choices=list(FAMILY) + ['all'], required=True, help='shark / bird / all（鯊魚做完接火雞，一次從頭到尾）')
    ap.add_argument('--phase', default='all', help='setup / r1 / r2 / r3 / r4 / final / all')
    ap.add_argument('--do', action='store_true', help='真的執行（預設只預覽指令）')
    ap.add_argument('--plan', action='store_true', help='只印計畫（同不加 --do）')
    ap.add_argument('--resume', action='store_true', help='跳過已完成的階段（all 時用）')
    ap.add_argument('--no-setup', action='store_true', help='all 時不做 setup（已經解散 + 存好了，例如做第二個系別）')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    do = a.do and not a.plan
    phases = PHASES if a.phase == 'all' else [a.phase]
    if any(p not in PHASES for p in phases):
        print(f'階段只能是 {PHASES} 或 all')
        return 2
    families = list(FAMILY) if a.family == 'all' else [a.family]
    for fi, fam in enumerate(families):
        ph = list(phases)
        if a.no_setup or fi > 0:                 # 第二個系別不用再解散 / 全存倉庫（第一個系別的 setup 已做）
            ph = [p for p in ph if p != 'setup']
        done = load_done(a.client, fam) if a.resume else []
        for p in ph:
            if p in done and a.resume:
                log(f'[{fam}] 階段 {p} 已完成，跳過')
                continue
            rc = run_phase(a.client, fam, p, do)
            if rc:
                return rc
            if do:
                done = sorted(set(load_done(a.client, fam)) | {p})
                save_done(a.client, fam, done)
    log('全部階段完成' if do else '預覽結束（加 --do 才真的執行）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
