#!/usr/bin/env python3
"""一條龍看門狗（supervisor）：代替 run_fullrun.cmd 啟動 fullrun1920.py，每分鐘檢查一次，出事自己處理（零 Claude 用量）。

規則（使用者 2026-10-13：有問題就修正再重啟，重大異常才等人處理）：
  退出碼 0                          全部完成 → 結束
  可自動重啟（暫時性）              3 組隊 / 4 外掛 / 5 找不到任務 / 7 逾時 / 8 做完仍殘留
                                    → 等 20 秒後重啟（fullrun 會從帳本 + 任務詳情接續）
                                    同一個退出碼 30 分鐘內第 4 次 → 判定修不好 → 停手通知
  一律停手通知（不自動重啟）        6 疑似驗證視窗 / 卡住（鐵則 5）、1 用法 / 缺少必要道具（龍王的守護沒了不算，會繼續跑）、2 版面不對、99 腳本例外、其他
  卡住偵測                          連續 STALL_S 秒沒有任何新輸出 → 殺掉重啟（同樣受次數限制）
停手時寫 tools/.cache/fullrun-flag-<client>.json（{at, code, reason, tail}）並呼叫 notifyhalt；
重啟 / 狀態寫 tools/.cache/watchdog-<client>.log。Claude 只要讀這個小檔案就知道要不要處理。

用法：uv run --no-project python tools/gui/fullrun_watchdog.py --client kkfaq11111 [--loop [--max-rounds N] [--max-trans 5]]
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'
sys.path.insert(0, str(HERE))

AUTO_RESTART = {3, 4, 5, 7, 8}
STALL_S = 420            # 7 分鐘沒有新輸出就當卡住（單步最長的等待是戰鬥 / 導覽，日誌會持續有輸出）
MAX_SAME_IN_WINDOW = 3   # 同一退出碼在 WINDOW_S 內最多自動重啟幾次
WINDOW_S = 1800


def now() -> str:
    return time.strftime('%F %T')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--stall', type=int, default=STALL_S)
    ap.add_argument('--loop', action='store_true', help='一輪（練等→任務→轉生→抓寵→練等）成功後自動開下一輪，直到轉數到 --max-trans 或 --max-rounds')
    ap.add_argument('--max-rounds', type=int, default=0, help='--loop 最多跑幾輪（0 = 不限，只看轉數）')
    ap.add_argument('--max-trans', type=int, default=5, help='--loop 轉數到這個數字就不再開下一輪（5 轉以上沒有漆黑洞窟可轉）')
    a = ap.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    CACHE.mkdir(parents=True, exist_ok=True)
    wlog = CACHE / f'watchdog-{a.client}.log'
    flag = CACHE / f'fullrun-flag-{a.client}.json'

    def log(m: str) -> None:
        line = f'{now()} [watchdog] {m}'
        print(line, flush=True)
        try:
            with open(wlog, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
        except OSError:
            pass

    def stop(code, reason, tail) -> None:
        try:
            flag.write_text(json.dumps({'at': now(), 'code': code, 'reason': reason, 'tail': list(tail)[-25:]}, ensure_ascii=False, indent=1), encoding='utf-8')
        except OSError:
            pass
        log(f'停手：{reason}（旗標 {flag.name}）')
        try:
            import notifyhalt
            notifyhalt.alert(f'一條龍看門狗：{reason}'[:80])
        except Exception:
            pass

    try:
        flag.unlink()
    except OSError:
        pass
    env = dict(os.environ, PSA_EXE_MATCH=a.client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
    env.setdefault('PSA_TILE_SCALE', '0.5')
    env.setdefault('PSA_CLICK_HOLD_MS', '120')
    history = {}                                   # 退出碼 → [重啟時間戳]
    rounds = 0
    while True:
        stamp = '；'.join(f'{n} {time.strftime("%H:%M:%S", time.localtime((HERE / n).stat().st_mtime))}'
                         for n in ('q1920.py', 'questflow1920.py', 'bag1920.py', 'fullrun1920.py', 'katan1920.py') if (HERE / n).exists())
        log(f'啟動 fullrun1920.py（載入的程式版本 = 檔案修改時間：{stamp}）')
        p = subprocess.Popen([sys.executable, str(HERE / 'fullrun1920.py'), '--client', a.client], cwd=str(ROOT), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
        tail = deque(maxlen=60)
        last_out = [time.time()]

        def pump():
            for line in p.stdout:
                last_out[0] = time.time()
                tail.append(line.rstrip())
                print(line, end='', flush=True)

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        stalled = False
        while p.poll() is None:
            time.sleep(5)
            if time.time() - last_out[0] > a.stall:
                stalled = True
                log(f'連續 {a.stall} 秒沒有新輸出 → 判定卡住，結束程序')
                p.kill()
                break
        t.join(timeout=5)
        code = p.wait()
        if stalled:
            code = 7
        if code == 0:
            rounds += 1
            if not a.loop:
                log('fullrun 全部階段完成，看門狗結束')
                return 0
            # --loop：看轉數與輪數決定要不要開下一輪（轉數讀不到就停，不盲目再轉）
            trans = None
            try:
                r = subprocess.run([sys.executable, str(HERE / 'transcheck.py'), '--client', a.client], cwd=str(ROOT), env=env,
                                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
                if r.returncode == 0 and r.stdout.strip().isdigit():
                    trans = int(r.stdout.strip())
            except Exception:
                pass
            log(f'第 {rounds} 輪完成；目前轉數 {trans}')
            if trans is None:
                stop(3, '第 %d 輪完成但讀不到轉數 → 不自動開下一輪，請人確認' % rounds, tail)
                return 3
            if trans >= a.max_trans or (a.max_rounds and rounds >= a.max_rounds):
                log(f'已到上限（轉數 {trans}/{a.max_trans}、輪數 {rounds}/{a.max_rounds or "不限"}）→ 看門狗結束')
                return 0
            history.clear()
            log(f'開第 {rounds + 1} 輪（狀態檔已歸零，從 train 開始）')
            time.sleep(10)
            continue
        if code not in AUTO_RESTART:
            reason = {6: '疑似驗證視窗 / 卡住（鐵則 5，請人看畫面）', 1: '用法錯誤或缺少必要道具（龍王的守護沒有不會走到這裡，會繼續跑）', 2: '視窗版面不對（要 1920x1017）'}.get(code, f'退出碼 {code}（不在自動重啟名單）')
            stop(code, reason, tail)
            return code
        ts = [x for x in history.get(code, []) if time.time() - x < WINDOW_S]
        if len(ts) >= MAX_SAME_IN_WINDOW:
            stop(code, f'退出碼 {code} 在 {WINDOW_S // 60} 分鐘內已自動重啟 {len(ts)} 次仍沒好，需要人看', tail)
            return code
        history[code] = ts + [time.time()]
        log(f'退出碼 {code}（暫時性）→ 20 秒後自動重啟（第 {len(ts) + 1}/{MAX_SAME_IN_WINDOW} 次）。最後輸出：{(list(tail)[-1] if tail else "")[:80]}')
        time.sleep(20)


if __name__ == '__main__':
    sys.exit(main())
