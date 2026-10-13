#!/usr/bin/env python3
"""漆黑洞窟步 5「守門人」單人版（1920×1017）：5 個角色各自單人去跟守門人講話領守護獸，不組隊。

使用者 2026-10-13：守門人任務要用角色各自單人去解（先前 11111 角色 1 因追蹤欄順序走錯順便講過了）。
流程：每個角色 → switch1920 切過去 → questflow1920 --dark-gate --solo（導航到守門人、講話；自動逃跑開）。
角色名單：tools/.cache/gate-roles-<client>.txt（內容例：2,3,4,5）優先，沒有就是 1,2,3,4,5；全部成功後刪掉這個檔。
全部做完切回角色 1（之後轉生要重新組隊）。

用法（專案根目錄）：
  uv run --no-project python tools/gui/gatesolo1920.py --client kkfaq11111 [--roles 2,3,4,5]
退出碼：0 全部完成；4 切角色失敗；5 有角色沒做成功（其他角色仍會繼續做完）。
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'


def log(m: str) -> None:
    print(time.strftime('%H:%M:%S'), m, flush=True)


def sub(script: str, *args) -> int:
    argv = [sys.executable, str(HERE / script), *[str(x) for x in args]]
    return subprocess.run(argv, cwd=str(ROOT), env=dict(os.environ)).returncode


def read_trans() -> int | None:
    """從人物資訊面板綠字「N轉M級」讀目前轉數（HUD 的 stat 會把 1 轉讀成 0，2026-10-13 角色 2 因此導到錯的漆黑洞窟任務）"""
    import re
    sys.path.insert(0, str(HERE))
    import fullrun1920 as fr
    import uikit
    uikit.gui('seq', f'click {fr.INFO_BTN[0]} {fr.INFO_BTN[1]}; wait 1500', note='gatesolo 開人物資訊')
    try:
        votes = {}
        for opts in (('-Zooms', '3,4'), ('-Zooms', '2,3', '-Dark', '200')):
            for t in uikit.ocr(fr.INFO_LV, *opts):
                m = re.search(r'(\d)\s*轉\s*\d{1,3}\s*級', t)
                if m:
                    votes[int(m.group(1))] = votes.get(int(m.group(1)), 0) + 1
        return max(votes.items(), key=lambda kv: kv[1])[0] if votes else None
    finally:
        uikit.gui('seq', f'click {fr.INFO_X[0]} {fr.INFO_X[1]}; wait 800', note='gatesolo 關人物資訊')


def roles_for(client: str, arg: str | None) -> list:
    if arg:
        txt = arg
    else:
        f = CACHE / f'gate-roles-{client}.txt'
        txt = f.read_text(encoding='utf-8').strip() if f.exists() else '1,2,3,4,5'
    return [int(x) for x in txt.split(',') if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--roles', default=None)
    ap.add_argument('--trans', type=int, default=None, help='目前轉數（預設從人物資訊面板讀）')
    a = ap.parse_args(argv)
    os.environ['PSA_EXE_MATCH'] = a.client
    os.environ.setdefault('PSA_GUI_SERVER', '1')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    roles = roles_for(a.client, a.roles)
    log(f'守門人單人版：角色 {roles}')
    trans = a.trans if a.trans is not None else read_trans()
    if trans is None:
        log('讀不到目前轉數（人物資訊面板）→ 停手；可用 --trans N 指定')
        return 4
    log(f'目前 {trans} 轉 → 漆黑洞窟任務依這個轉數決定')
    failed = []
    for r in roles:
        log(f'--- 角色 {r}：切換 ---')
        import uikit
        uikit.gui('key', '{ESC}', note='gatesolo 切換前先關掉可能開著的面板')   # 切換面板已開時再點「切換」會把它關掉 → switch1920 回「沒開」
        time.sleep(1.0)
        rc = sub('switch1920.py', '--client', a.client, '--role', r)
        if rc != 0:
            log(f'切到角色 {r} 失敗（退出碼 {rc}）→ 停手')
            return 4
        # 切完角色「切換角色」面板還開著，會蓋住外掛面板（questflow 開外掛 40 秒打不開，2026-10-13）：ESC 關掉再往下
        import uikit
        uikit.gui('key', '{ESC}', note='gatesolo 關切換角色面板')
        time.sleep(1.0)
        rc = sub('questflow1920.py', '--client', a.client, '--dark-gate', '--solo', '--no-potion', '--trans', trans)
        if rc != 0:
            log(f'角色 {r} 守門人沒成功（退出碼 {rc}）→ 記下，繼續下一個')
            failed.append((r, rc))
        else:
            log(f'角色 {r} 守門人完成')
    sub('switch1920.py', '--client', a.client, '--role', 1)
    if failed:
        log(f'有角色沒完成：{failed}')
        return 5
    f = CACHE / f'gate-roles-{a.client}.txt'
    try:
        f.unlink()
    except OSError:
        pass
    log('守門人 5 人都完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
