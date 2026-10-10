#!/usr/bin/env python3
"""畫面辨識指令的唯讀量測（只用標準函式庫）。只截圖 / 讀像素 / OCR，不點擊、不按鍵、不走路。

  uv run --no-project python tools/gui/bench.py                      # 一次性（oneshot）各項 5 次，印中位數 / 最小 / 最大
  uv run --no-project python tools/gui/bench.py -n 5 --only ocr_zooms,stat
  uv run --no-project python tools/gui/bench.py --ab --old-dir tools/.cache/old   # A/B 交錯：A = tools/gui 現行版，B = 舊版目錄
  uv run --no-project python tools/gui/bench.py --json               # 機器可讀輸出
--ab：同一個時段內 A、B 輪流各跑 1 次（A B A B …），避免背景負載不同造成的誤差；--old-dir 下沒有的腳本（如 gui.ps1）兩邊都用現行版。
--ab 同時比對兩邊的輸出：ocr 比文字行、stat 比整個 JSON、其他比輸出字串（遊戲畫面有動就可能不同，只是提醒）。
開跑前會記錄背景程序（quest / petwatch / heal / netwatch / walk / stat.ps1（psa-hud））與客戶區大小；
**只在使用者確認沒有任務在跑時執行**；開跑前先 shot 確認是一般主畫面；出現答題 / 驗證視窗立刻停止並通知使用者。
（--server 模式：第 2 階段常駐 server 才有，目前不支援。）
"""
import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winenv  # noqa: E402

# 量測項目：名稱 -> (腳本, 參數)。座標 = 截圖座標；LIST_BOX 與 quest.py 讀任務追蹤列表的區域相同
LIST_BOX = ('75', '270', '260', '180')
TARGETS = {
    'info': ('gui.ps1', ['info']),
    'pixel1': ('gui.ps1', ['pixel', '1300', '745']),
    'waitpix0': ('gui.ps1', ['seq', 'waitpix 0 500,570,179,127,63/760,565,93,137,187/440,520,243,217,179 25']),
    'shot': ('gui.ps1', ['shot']),
    'stat': ('stat.ps1', []),
    'ocr': ('ocr.ps1', [*LIST_BOX]),
    'ocr_zooms': ('ocr.ps1', [*LIST_BOX, '-Zooms', '2,3,4,5,6,7', '-Dark', '150']),
    'findmark': ('findmark.ps1', []),
}


def bg_procs() -> list[str]:
    """背景程序（會讓量測失真）：WSL / Linux 端的 python 腳本 + Windows 端的 stat.ps1（psa-hud 每 15 秒跑一次）"""
    pat = re.compile(r'quest\.py|petwatch\.py|heal\.py|netwatch\.py|walk\.py|stat\.ps1')
    found: list[str] = []
    try:
        out = subprocess.run(['ps', '-eo', 'pid,args'], capture_output=True, text=True, timeout=10).stdout
        me = str(__import__('os').getpid())
        for ln in out.splitlines():
            m = pat.search(ln)
            if m and not ln.split()[0] == me and 'ps -eo' not in ln:
                found.append(f'linux:{m.group(0)}')
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        q = ("Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'quest\\.py|petwatch\\.py|heal\\.py|netwatch\\.py|walk\\.py|stat\\.ps1' "
             "-and $_.CommandLine -notmatch 'Get-CimInstance' } | % { $_.Name + ':' + $_.ProcessId }")
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command', q], capture_output=True, text=True, timeout=30)
        found += [f'windows:{x.strip()}' for x in r.stdout.splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return found


def run_once(script: str, args: list[str], script_dir: Path | None = None) -> tuple[float, str]:
    """跑一次，回 (秒, 輸出文字)。script_dir 不是 None 且底下有該腳本就用它（舊版對照）"""
    path = script
    if script_dir is not None and (script_dir / script).exists():
        path = str(script_dir / script)
    t0 = time.perf_counter()
    r = winenv.run_ps(path, *args, timeout=120)
    dt = time.perf_counter() - t0
    return dt, (r.stdout.strip() or r.stderr.strip())


def normalize(name: str, out: str) -> str:
    """輸出正規化後才比對：ocr 只比文字行；stat 比整個 JSON（鍵排序）；其他原字串；shot 只看有沒有存成功"""
    if name == 'waitpix0':                       # 後面的毫秒數每次不同
        return (out.split() or [''])[0]
    if name == 'findmark':                       # 畫面有動畫，blob 會變，不比
        return 'n/a'
    last = (out.splitlines() or [''])[-1]
    try:
        d = json.loads(last)
    except ValueError:
        return 'shot-ok' if name == 'shot' else out
    if name.startswith('ocr') and isinstance(d, dict):
        return json.dumps(sorted(l.get('text', '') for l in d.get('lines', [])) if d.get('ok') else d, ensure_ascii=False)
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def summarize(xs: list[float]) -> dict:
    return {'median': round(statistics.median(xs), 3), 'min': round(min(xs), 3), 'max': round(max(xs), 3), 'n': len(xs)}


def main() -> int:
    ap = argparse.ArgumentParser(description='畫面辨識指令唯讀量測')
    ap.add_argument('-n', type=int, default=5, help='每項次數（預設 5，取中位數）')
    ap.add_argument('--only', default='', help='只量這幾項（逗號分隔）：' + ','.join(TARGETS))
    ap.add_argument('--ab', action='store_true', help='A/B 交錯：現行版 vs --old-dir')
    ap.add_argument('--old-dir', default='', help='舊版腳本目錄（--ab 用；例：tools/.cache/old）')
    ap.add_argument('--oneshot', action='store_true', help='一次性（預設就是）')
    ap.add_argument('--server', action='store_true', help='常駐 server（第 2 階段才有）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.server:
        print('--server 還沒實作（第 2 階段）', file=sys.stderr)
        return 2
    names = [x for x in a.only.split(',') if x] or list(TARGETS)
    bad = [x for x in names if x not in TARGETS]
    if bad:
        print('不認得的項目：', bad, '可用：', list(TARGETS), file=sys.stderr)
        return 2
    old_dir = None
    if a.ab:
        if not a.old_dir:
            print('--ab 需要 --old-dir', file=sys.stderr)
            return 2
        old_dir = Path(a.old_dir).resolve()
    _, info = run_once('gui.ps1', ['info'])
    bg = bg_procs()
    meta = {'platform': winenv.platform_kind(), 'info': info, 'background': bg, 'n': a.n, 'mode': 'ab' if a.ab else 'oneshot'}
    if not a.json:
        print(f'平台 {meta["platform"]} | {info} | 背景程序：{bg or "無"}')
    res: dict = {}
    for name in names:
        script, args = TARGETS[name]
        times = {'A': [], 'B': []}
        outs = {'A': '', 'B': ''}
        run_once(script, args)                    # 暖機不計（第一次載入 / 磁碟快取）
        for _ in range(a.n):
            for side in (('A', 'B') if a.ab else ('A',)):
                dt, out = run_once(script, args, old_dir if side == 'B' else None)
                times[side].append(dt)
                outs[side] = out
        row = {'A': summarize(times['A'])}
        if a.ab:
            row['B'] = summarize(times['B'])
            row['same_output'] = normalize(name, outs['A']) == normalize(name, outs['B'])
            if not row['same_output']:
                row['diff'] = {'A': normalize(name, outs['A'])[:300], 'B': normalize(name, outs['B'])[:300]}
        res[name] = row
    meta['results'] = res
    if a.json:
        print(json.dumps(meta, ensure_ascii=False, indent=1))
        return 0
    if a.ab:
        print(f'{"項目":<11} {"現行 A 中位數":>12} {"min/max":>13} | {"舊版 B 中位數":>12} {"min/max":>13} | 輸出相同')
        for k, v in res.items():
            A, B = v['A'], v['B']
            print(f'{k:<11} {A["median"]:>11.3f}s {A["min"]:>6.2f}/{A["max"]:<6.2f} | {B["median"]:>11.3f}s {B["min"]:>6.2f}/{B["max"]:<6.2f} | {"是" if v["same_output"] else "否"}')
            if not v['same_output']:
                print('   A:', v['diff']['A'], '\n   B:', v['diff']['B'])
    else:
        print(f'{"項目":<11} {"中位數":>8} {"min":>7} {"max":>7}')
        for k, v in res.items():
            A = v['A']
            print(f'{k:<11} {A["median"]:>7.3f}s {A["min"]:>7.3f} {A["max"]:>7.3f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
