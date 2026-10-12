#!/usr/bin/env python3
r"""卡坦的願望：練寵（五兄弟洞窟）+ 交任務（1920×1017）。katan1920.py 的 train / handin 階段呼叫這支。

  train    外掛「自動轉換戰寵」1~4 列轉 25 級 → 5 人組隊 → 傳去五兄弟洞窟（快速 + 自動戰鬥、原地遇敵）→
           每輪逐人讀寵物欄 1~4 格的等級，5 人 × 4 隻全部 >= 25 級才結束；連續 30 分鐘總等級沒增加就停手。
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
POLL_S = 120
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


def read_levels(q, qf) -> dict:
    """逐人讀寵物欄 1~4 格的等級（不靠空格像素；讀不到 = None）"""
    qf.open_pet_panel()
    out = {}
    try:
        for r in range(5):
            q.click((qf.PET_ROLE_X, qf.PET_ROLE_Y[r]), wait_ms=900, note=f'katan 讀等級：角色 {r + 1}')
            out[r + 1] = [qf.read_pet(i)[1] for i in range(SLOTS)]
    finally:
        qf.close_pet_panel()
    return out


def cmd_train(a) -> int:
    q, qf = setup_env(a.client)
    import pausegate
    try:
        lv0 = read_levels(q, qf)
        log(f'目前等級：{lv0}')
        if all_done(lv0, a.target):
            log('5 人 × 4 隻都已達標，不用再練')
            return 0
        rc = sub('autoswap1920.py', '--client', a.client, '--roles', '1,2,3,4,5', '--level', a.target)
        if rc != 0:
            log(f'自動轉換戰寵設定失敗（退出碼 {rc}）→ 停手')
            return 4
        ensure_team(q)
        q.grind(TRAIN_SPOT)
        t0 = time.time()
        best, t_best = total(lv0), time.time()
        first = True
        while True:
            pausegate.wait(log)
            q.sleep(FIRST_POLL_S if first else POLL_S)
            first = False
            if q.state() == 'OTHER':
                q.sleep(5)
                if q.state() == 'OTHER':
                    raise q.Halt(q.EXIT_HALT, '練寵中連續看到不認得的畫面（疑似驗證視窗）：停手')
            try:
                lv = read_levels(q, qf)
            except q.Halt:
                continue                           # 戰鬥中開不了面板：下一輪再讀
            log(f'練寵進度（{int(time.time() - t0)} 秒）：{lv}')
            if all_done(lv, a.target):
                break
            best2, is_stall = stalled(best, total(lv), time.time() - t_best, a.stall_min * 60)
            if best2 > best:
                best, t_best = best2, time.time()
            elif is_stall:
                raise q.Halt(q.EXIT_TIMEOUT, f'連續 {a.stall_min} 分鐘總等級沒有增加（{total(lv)}）：停手，請看畫面')
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='卡坦的願望：練寵 + 交任務')
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq22222'))
    sp = ap.add_subparsers(dest='cmd', required=True)
    t = sp.add_parser('train')
    t.add_argument('--target', type=int, default=25)
    t.add_argument('--stall-min', type=int, default=30)
    h = sp.add_parser('handin')
    h.add_argument('--step', type=int, choices=[1, 2], required=True)
    a = ap.parse_args(argv)
    return {'train': cmd_train, 'handin': cmd_handin}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
