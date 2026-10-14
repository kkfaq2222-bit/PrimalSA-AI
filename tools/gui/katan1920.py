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
# 恐龍博士（任務 2016；使用者 2026-10-12）：5 人最後都是 寵物 1 = 魯尼帖斯、寵物 2 = 貝魯卡，不騎乘
DINO_PHASES = ['setup', 'r1', 'r2', 'r3', 'train', 'handin', 'cleanup']
NAME_FIRST = 'WW'                 # 鯊魚（角色 2）/ 火雞（角色 3）每輪抓完第一隻改的名字（遊戲不收單字元；使用者 2026-10-13）
BAIT_SOURCE = 'public'          # 誘餌全放共用倉庫（使用者 2026-10-12）；鯊魚（角色 2）背包已有誘餌 → 不再檢查；火雞（角色 3）只在 r1 檢查 / 取一次
PHASES = ['setup', 'r1', 'r2', 'r3', 'r4', 'final', 'train', 'handin', 'cleanup']


def py(script: str, *args) -> list:
    return [sys.executable, str(HERE / script), *[str(x) for x in args]]


def plan_dino(client: str, phase: str) -> list:
    """恐龍博士：角色 4 抓魯尼帖斯（呼拔拔系）、角色 5 抓貝魯卡（老虎系）。
    公共倉庫每一批只放同一種，所以分給大家一律固定領第 1 格（--first），不認圖。"""
    c = ['--client', client]
    out = []
    if phase == 'setup':
        out.append(('解散隊伍（抓寵要單人）', py('q1920.py', *c, 'disband')))
        out.append(('5 人身上的寵物全部存個人倉庫（卡坦剩的 / 朵拉比斯，寵物欄要空才抓得滿）', py('petdepot1920.py', *c, '--do')))
        out.append(('確認 5 人寵物欄全空（有寵物就停手，避免雜寵混入）', py('petdepot1920.py', *c, '--check-empty')))
        out.append(('角色 3 背包剩的寵物誘餌存回共用倉庫（火雞抓完還在它身上）', py('baitstore1920.py', *c, '--role', 3)))
        return out
    if phase == 'r1':
        out.append(('角色 4 抓魯尼帖斯 ×5（不勾自動存倉庫，誘餌從共用倉庫取）',
                    py('catchrun1920.py', *c, '--role', 4, '--system', '呼拔拔系', '--pet', '魯尼帖斯', '--n', 5, '--source', BAIT_SOURCE)))
        out.append(('角色 4 寵物欄第 2~5 格存公共（4 隻；第 1 格留自己用）',
                    py('petfetchimg1920.py', *c, 'storebar', '--role', 4, '--slots', '2,3,4,5', '--tab', 'public', '--do')))
        out.append(('魯尼帖斯分給角色 1、2、3、5（各領公共第 1 格）',
                    py('petgive1920.py', *c, '--first', '--plan', '1:魯尼帖斯;2:魯尼帖斯;3:魯尼帖斯;5:魯尼帖斯')))
        out.append(('角色 4 剩餘寵物誘餌存回共用倉庫（給角色 5 抓貝魯卡）', py('baitstore1920.py', *c, '--role', 4)))
        return out
    if phase == 'r2':
        # 角色 5 排法（使用者 2026-10-12）：抓 4 隻（第 2~5 格）→ 只存第 5 格 → 再補抓 1 隻進第 5 格 → 存第 5、4、3 格 → 第 2 格留下
        out.append(('角色 5 抓貝魯卡（寵物欄第 1 格已是魯尼帖斯，只剩 4 格，抓滿 4 隻自己停）',
                    py('catchrun1920.py', *c, '--role', 5, '--system', '老虎系', '--pet', '貝魯卡', '--n', 5, '--source', BAIT_SOURCE)))
        out.append(('角色 5 只存第 5 格到公共（公共 1 隻；寵物欄變成 魯、貝、貝、貝、空）',
                    py('petfetchimg1920.py', *c, 'storebar', '--role', 5, '--slots', '5', '--tab', 'public', '--do')))
        return out
    if phase == 'r3':
        out.append(('角色 5 再抓 1 隻貝魯卡（只剩第 5 格空，抓 1 隻欄滿遊戲自己停（不拆分：2026-10-13 拆分把整疊誘餌存回倉庫 → 可抓捕數 0 → 空抓））',
                    py('catchrun1920.py', *c, '--role', 5, '--system', '老虎系', '--pet', '貝魯卡', '--n', 1, '--source', BAIT_SOURCE)))
        out.append(('角色 5 存第 5、4、3 格到公共（公共現在 4 隻貝魯卡；第 2 格留下）',
                    py('petfetchimg1920.py', *c, 'storebar', '--role', 5, '--slots', '5,4,3', '--tab', 'public', '--do')))
        out.append(('貝魯卡分給角色 1、2、3、4（各領公共第 1 格）',
                    py('petgive1920.py', *c, '--first', '--plan', '1:貝魯卡;2:貝魯卡;3:貝魯卡;4:貝魯卡')))
        out.append(('角色 5 剩餘寵物誘餌存回共用倉庫（抓完放回去）', py('baitstore1920.py', *c, '--role', 5)))
        return out
    if phase == 'train':
        out.append(('練寵：魯尼 18 級後換貝魯卡，5 人第 2 隻 >= 30 級才收（五兄弟洞窟；30 分鐘沒進展就停手）',
                    py('katantrain1920.py', *c, 'train', '--slot', 2, '--target', 30)))
        return out
    if phase == 'handin':
        out.append(('全部改休息 → 5 人組隊到研究所接任務 → 解散 → 5 人逐一交步 1 + 步 2',
                    py('katantrain1920.py', *c, 'dino-handin')))
        return out
    if phase == 'cleanup':
        out.append(('丟棄獎勵「布克布克」（只准丟布克布克，提示窗名稱不對就取消）',
                    py('petdelbk1920.py', *c, '--roles', '1,2,3,4,5')))
        return out
    raise ValueError(phase)


def plan(client: str, family: str, phase: str) -> list:
    """純函式：回傳該階段要跑的指令清單 [(說明, argv)]。離線可測。"""
    if family == 'dino':
        return plan_dino(client, phase)
    f = FAMILY[family]
    catcher, system, kinds = f['role'], f['system'], f['kinds']
    others = [r for r in ALL_ROLES if r != catcher]
    c = ['--client', client]
    out = []
    if phase == 'setup':
        out.append(('解散隊伍', py('q1920.py', *c, 'disband')))
        out.append(('5 人寵物全部存個人倉庫（含騎寵）', py('petdepot1920.py', *c, '--do')))
        out.append(('確認 5 人寵物欄全空（有寵物就停手，避免雜寵混入）', py('petdepot1920.py', *c, '--check-empty')))
        return out
    if phase in ('r1', 'r2', 'r3'):
        k = kinds[int(phase[1]) - 1]
        if phase == 'r1':
            # 抓寵一律單人：前一個系別交任務時是 5 人隊，火雞開抓前一定要先解散（使用者 2026-10-12；本來就單人時不點任何東西）
            out.append(('解散隊伍（抓寵要單人）', py('q1920.py', *c, 'disband')))
        # 不勾自動存倉庫（使用者規定）：5 隻抓在寵物欄 → 手動 2~5 格存公共（4 隻）、第 1 格存個人（1 隻）
        out.append((f'抓 {k} ×5（不勾自動存倉庫，5 隻留在寵物欄）', py('catchrun1920.py', *c, '--role', catcher, '--system', system,
                                                              '--pet', k, '--n', 5, '--source', BAIT_SOURCE,
                                                              *(['--no-bait-check'] if phase != 'r1' else []))))   # r1 一律檢查背包、沒誘餌就從公共倉庫領（鯊魚 2026-10-13 假設背包有而沒領 → 3.8 秒空抓）
        # 第一隻改名 WW（使用者 2026-10-13）：之後從個人倉庫只領名字是 WW 的，不會領錯；遊戲名字至少 2 字所以不用 1
        out.append((f'寵物欄第 1 格改名 {NAME_FIRST}（之後只領這個名字）', py('petname1_1920.py', *c, '--role', catcher, '--slots', '1', '--name', NAME_FIRST)))
        out.append(('寵物欄第 2~5 格存公共（4 隻）', py('petfetchimg1920.py', *c, 'storebar', '--role', catcher, '--slots', '2,3,4,5', '--tab', 'public', '--do')))
        out.append(('寵物欄第 1 格存個人倉庫（1 隻）', py('petfetchimg1920.py', *c, 'storebar', '--role', catcher, '--slots', '1', '--tab', 'personal', '--do')))
        # 公共倉庫永遠只放這一批同一種的 4 隻 → 一律固定領第 1 格（不認圖、不認顏色；火雞類彼此太像，樣板會混淆）
        out.append((f'{k} 分給角色 ' + '、'.join(map(str, others)),
                    py('petgive1920.py', *c, '--first', '--plan', ';'.join(f'{r}:{k}' for r in others))))
        return out
    if phase == 'r4':
        k = kinds[3]
        out.append((f'抓 {k} ×5（不自動存，5 隻留在寵物欄）', py('catchrun1920.py', *c, '--role', catcher, '--system', system,
                                                        '--pet', k, '--n', 5, '--source', BAIT_SOURCE, '--no-bait-check')))
        out.append((f'寵物欄第 1 格改名 {NAME_FIRST}（留在身上的第一隻也統一）', py('petname1_1920.py', *c, '--role', catcher, '--slots', '1', '--name', NAME_FIRST)))
        out.append(('寵物欄第 2~5 格存公共（第 1 格留著）', py('petfetchimg1920.py', *c, 'storebar', '--role', catcher, '--slots', '2,3,4,5', '--tab', 'public', '--do')))
        out.append((f'{k} 分給角色 ' + '、'.join(map(str, others)),
                    py('petgive1920.py', *c, '--first', '--plan', ';'.join(f'{r}:{k}' for r in others))))
        # 抓完一律把剩的寵物誘餌整疊存回共用倉庫道具（鯊魚 / 火雞 / 恐龍博士都一樣；使用者 2026-10-12：抓完也要放回去）
        out.append((f'角色 {catcher} 剩餘寵物誘餌存共用倉庫', py('baitstore1920.py', *c, '--role', catcher)))
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
        out.append((f'角色 {catcher} 從個人倉庫領回前 3 輪各 1 隻（名稱是數字；已在欄位裡的不重領：目標總數 4 = 第 4 輪留著的 1 + 前 3 輪 3）',
                    py('petfetchimg1920.py', *c, 'fetch', '--role', catcher, '--numeric', 3, '--want-total', 4, '--shape', family, '--do')))
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


def run_phase(client: str, family: str, phase: str, do: bool, skip: int = 0) -> int:
    steps = plan(client, family, phase)[skip:]
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
    ap.add_argument('--family', choices=list(FAMILY) + ['dino', 'rest', 'all'], required=True,
                    help='shark / bird / dino（恐龍博士）/ rest（火雞接續 → 恐龍博士：從卡坦步 2 交付到恐龍博士做完）/ all（鯊魚 → 火雞 → 恐龍博士，從頭到尾）')
    ap.add_argument('--phase', default='all', help='setup / r1~r4 / final / train / handin / cleanup，可用逗號接多個；all = 該系別全部')
    ap.add_argument('--do', action='store_true', help='真的執行（預設只預覽指令）')
    ap.add_argument('--plan', action='store_true', help='只印計畫（同不加 --do）')
    ap.add_argument('--resume', action='store_true', help='跳過已完成的階段（all 時用）')
    ap.add_argument('--skip-cmds', type=int, default=0, help='第一個執行的階段略過前 N 個指令（該階段前幾個指令已經手動 / 上次做完時用，例：r4 抓完寵但存倉庫失敗 → --skip-cmds 1）')
    ap.add_argument('--no-setup', action='store_true', help='all 時不做 setup（已經解散 + 存好了，例如做第二個系別）')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    do = a.do and not a.plan
    want = None if a.phase == 'all' else [x.strip() for x in a.phase.split(',') if x.strip()]
    families = {'all': ['shark', 'bird', 'dino'], 'rest': ['bird', 'dino']}.get(a.family, [a.family])
    skip_left = a.skip_cmds
    for fi, fam in enumerate(families):
        allp = DINO_PHASES if fam == 'dino' else PHASES
        ph = list(allp) if want is None else [p for p in want if p in allp]
        if want is not None and not ph and fam == families[-1] and not any(p in allp for p in want):
            print(f'階段只能是 {allp} 或 all')
            return 2
        # setup（解散 + 全存倉庫）只在整套的第一個系別做；恐龍博士有自己的 setup（解散 + 存卡坦剩的 + 誘餌存回公共）一定要做
        if fam in ('shark', 'bird') and (a.no_setup or fi > 0 or a.family == 'rest'):
            ph = [p for p in ph if p != 'setup']     # rest = 鯊魚 / 火雞抓寵早就做完：絕不能再「全存倉庫」把要交的任務寵存走
        done = load_done(a.client, fam) if a.resume else []
        for p in ph:
            if p in done and a.resume:
                log(f'[{fam}] 階段 {p} 已完成，跳過')
                continue
            rc = run_phase(a.client, fam, p, do, skip=skip_left)
            skip_left = 0                        # --skip-cmds 只套用在第一個實際執行的階段
            if rc:
                return rc
            if do:
                done = sorted(set(load_done(a.client, fam)) | {p})
                save_done(a.client, fam, done)
    log('全部階段完成' if do else '預覽結束（加 --do 才真的執行）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
