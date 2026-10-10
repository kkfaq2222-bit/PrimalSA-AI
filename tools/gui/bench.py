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
--server：全部經常駐 serve.ps1（winenv.enable_server）；--srv-ab：同時段交錯 A = 一次性、B = 常駐 server（第 2 階段驗收用）。
--soak：長跑（server）：預設 5000 次 pixel + 300 次 shot + 500 次 ocr + 200 次 stat，每階段後印 server 的 GDI / 記憶體（MB）/ 執行緒 / handle。
read_screen / titlematch 兩項走 Python 函式（quest.read_screen、titlematch.match_all 樣板比對，皆唯讀；沒有樣板時 titlematch 不會呼叫 PowerShell）。
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


def _quest():
    import quest   # 延遲載入：只有 read_screen / find_tpl 兩項才需要
    return quest


# python 層的項目（名稱 -> 呼叫函式，回傳輸出字串）；底下仍然經 winenv.run_ps，所以 oneshot / server 切換照樣有效
PY_TARGETS = {
    'read_screen': lambda: json.dumps(_quest().read_screen(), sort_keys=True),
    'titlematch': lambda: json.dumps([(h['name'], h['x'], h['y']) for h in __import__('titlematch').match_all().get('hits', [])]),
}


def run_once(script: str, args: list[str], script_dir: Path | None = None, server: bool = False) -> tuple[float, str]:
    """跑一次，回 (秒, 輸出文字)。script_dir 不是 None 且底下有該腳本就用它（舊版對照）；server=True 經常駐 server"""
    winenv._enabled = server
    winenv.DEFAULT_ON = True     # bench 自己決定走不走 server，不受預設關影響
    if script in PY_TARGETS:
        t0 = time.perf_counter()
        out = PY_TARGETS[script]()
        return time.perf_counter() - t0, out
    path = script
    if script_dir is not None and (script_dir / script).exists():
        path = str(script_dir / script)
    t0 = time.perf_counter()
    r = winenv.run_ps(path, *args, timeout=120)
    dt = time.perf_counter() - t0
    return dt, (r.stdout.strip() or r.stderr.strip())


def soak(counts: dict) -> int:
    """長跑：server 模式下依序跑 pixel / shot / ocr / stat，各階段後印 server 的資源（GDI / MB / 執行緒 / handle）"""
    winenv.enable_server()
    winenv.DEFAULT_ON = True
    shot = str(winenv.to_windows(winenv.ROOT / 'tools' / '.cache' / 'soak.png'))

    def stats() -> dict:
        m = winenv._server().admin('stats')
        return json.loads(m['out']) if m else {}
    phases = [('pixel', 'gui.ps1', ['pixel', '1300', '745'], counts['pixel']), ('shot', 'gui.ps1', ['shot', shot], counts['shot']),
              ('ocr', 'ocr.ps1', [*LIST_BOX], counts['ocr']), ('stat', 'stat.ps1', [], counts['stat'])]
    winenv.run_ps('gui.ps1', 'info')
    st0 = stats()
    print('起點', st0, flush=True)
    bad = 0
    for name, sc, args, n in phases:
        t0 = time.time()
        rcs = {}
        for i in range(n):
            r = winenv.run_ps(sc, *args, timeout=60)
            rcs[r.returncode] = rcs.get(r.returncode, 0) + 1
            if r.returncode != 0 or (name == 'pixel' and ',' not in r.stdout):
                bad += 1
            if (i + 1) % max(1, n // 4) == 0:
                print(f'  {name} {i + 1}/{n} {stats()}', flush=True)
        print(f'{name} x{n}：{time.time() - t0:.1f}s rc={rcs} 之後 {stats()}', flush=True)
    st1 = stats()
    print('終點', st1, '| 失敗請求數', bad)
    print(f'GDI {st0.get("gdi")} -> {st1.get("gdi")}；MB {st0.get("mb")} -> {st1.get("mb")}；threads {st0.get("threads")} -> {st1.get("threads")}；handles {st0.get("handles")} -> {st1.get("handles")}')
    return 1 if bad else 0


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
    ap.add_argument('--server', action='store_true', help='全部經常駐 server')
    ap.add_argument('--srv-ab', action='store_true', help='A = 一次性、B = 常駐 server，同時段交錯')
    ap.add_argument('--soak', action='store_true', help='server 長跑，看 GDI / 記憶體 / 執行緒')
    ap.add_argument('--soak-n', default='5000,300,500,200', help='soak 次數：pixel,shot,ocr,stat')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.soak:
        n = [int(x) for x in a.soak_n.split(',')]
        return soak(dict(zip(('pixel', 'shot', 'ocr', 'stat'), n)))
    ALL = {**TARGETS, **{k: None for k in PY_TARGETS}}
    names = [x for x in a.only.split(',') if x] or list(ALL)
    bad = [x for x in names if x not in ALL]
    if bad:
        print('不認得的項目：', bad, '可用：', list(ALL), file=sys.stderr)
        return 2
    old_dir = None
    if a.ab and a.srv_ab:
        print('--ab 與 --srv-ab 擇一', file=sys.stderr)
        return 2
    if a.ab:
        if not a.old_dir:
            print('--ab 需要 --old-dir', file=sys.stderr)
            return 2
        old_dir = Path(a.old_dir).resolve()
    _, info = run_once('gui.ps1', ['info'])
    bg = bg_procs()
    meta = {'platform': winenv.platform_kind(), 'info': info, 'background': bg, 'n': a.n, 'mode': 'srv-ab' if a.srv_ab else 'ab' if a.ab else 'server' if a.server else 'oneshot'}
    if not a.json:
        print(f'平台 {meta["platform"]} | {info} | 背景程序：{bg or "無"}')
    res: dict = {}
    for name in names:
        script, args = TARGETS[name] if name in TARGETS else (name, [])
        times = {'A': [], 'B': []}
        outs = {'A': '', 'B': ''}
        run_once(script, args, server=a.server)   # 暖機不計（第一次載入 / 磁碟快取 / 起 server）
        if a.srv_ab:
            run_once(script, args, server=True)
        for _ in range(a.n):
            for side in (('A', 'B') if (a.ab or a.srv_ab) else ('A',)):
                dt, out = run_once(script, args, old_dir if (side == 'B' and a.ab) else None, server=(a.server or (a.srv_ab and side == 'B')))
                times[side].append(dt)
                outs[side] = out
        row = {'A': summarize(times['A'])}
        if a.ab or a.srv_ab:
            row['B'] = summarize(times['B'])
            row['same_output'] = normalize(name, outs['A']) == normalize(name, outs['B'])
            if not row['same_output']:
                row['diff'] = {'A': normalize(name, outs['A'])[:300], 'B': normalize(name, outs['B'])[:300]}
        res[name] = row
    meta['results'] = res
    if a.json:
        print(json.dumps(meta, ensure_ascii=False, indent=1))
        return 0
    if a.ab or a.srv_ab:
        print(f'{"項目":<11} {("一次性 A" if a.srv_ab else "現行 A") + " 中位數":>12} {"min/max":>13} | {("server B" if a.srv_ab else "舊版 B") + " 中位數":>12} {"min/max":>13} | 輸出相同')
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
