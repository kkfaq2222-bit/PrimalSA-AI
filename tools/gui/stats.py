#!/usr/bin/env python3
"""統計（終端機看）：每日任務買了什麼 / 花多久、練功每個練功點花多久與 120→131 / 131→140、一條龍每個階段花多久。
只讀記錄檔，不碰遊戲：
  tools/.cache/stats-daily.jsonl     每日任務每個角色一行（dailyrun1920 跑完寫；2026-10-15 起）
  tools/.cache/daily-done-*.json     每日任務已買記錄（舊資料也有，沒有時間）
  notes/exp-log-<視窗>.csv           練功等級記錄（levelwatch 每 30 秒一行）
  tools/.cache/stats-fullrun.jsonl   一條龍每個階段一行（fullrun1920 寫；2026-10-15 起）
用法（專案根目錄）：
  uv run --no-project python tools/gui/stats.py            # 全部
  uv run --no-project python tools/gui/stats.py daily      # 只看每日任務（daily / grind / fullrun / errors 可多個）
  uv run --no-project python tools/gui/stats.py errors --since=2026-10-14   # 錯誤次數與原因（--since 只看某天起）
"""
import collections
import csv
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = ROOT / 'tools' / '.cache'
WINDOW_CLIENT = {'gameClient': 'kkfaq11111', 'PrimalSA222': 'kkfaq22222', 'PrimalSA478978': 'kkfaq33333'}
SPOT_NAME = {'500': '波拉島', '502': '波拉島2', '60049': '地雷區', '60050': '地雷區2', '11001': '柯奧龜洞', '31401': '五兄弟洞窟',
             '11004': '柯奧4F龜洞', '10001': '阿布龜洞', '11201': '11201(?)'}
GAP_S = 600          # 兩筆記錄間隔超過 10 分鐘 = 中斷（離線 / 停掉），不算進練功時間


def hm(mins: float) -> str:
    return f'{int(mins // 60)}時{int(mins % 60):02d}分' if mins >= 60 else f'{mins:.0f}分'


# ---------------- 每日任務 ----------------
def daily() -> None:
    sys.path.insert(0, str(HERE))
    import dailyquest1920 as dq
    stores = dq.load_stores()

    def kind(n):
        st = stores.get(n)
        return '裝備素材' if st and '素材屋' in st[0] else '食物素材'
    rows = []
    p = CACHE / 'stats-daily.jsonl'
    if p.exists():
        for ln in p.read_text(encoding='utf-8').splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
    seen = {(r['client'], r['role'], r['date']) for r in rows}
    for f in sorted(CACHE.glob('daily-done-*.json')):        # 舊資料：只有已買，沒有時間
        stem = f.stem[len('daily-done-'):]
        client, _, r = stem.partition('-r')
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except ValueError:
            continue
        key = (client, int(r) if r.isdigit() else 0, d.get('date'))
        if key not in seen and d.get('bought'):
            rows.append({'client': client, 'role': key[1], 'date': key[2], 'minutes': None, 'bought': d['bought'], 'items': None})
    print('== 每日任務 ==')
    print(f'{"日期":<9}{"帳號":<12}{"角色":>4}{"耗時":>8}{"裝備素材 種/個":>14}{"食物素材 種/個":>14}{"石幣":>9}')
    tot = collections.Counter()
    for r in sorted(rows, key=lambda r: (r['date'] or '', r['client'], r['role'])):
        c = collections.Counter(); q = collections.Counter()
        for n, k in r['bought'].items():
            c[kind(n)] += 1
            q[kind(n)] += k
        coin = sum(r['bought'].values()) * 500 + 10 * 1000
        mins = f'{r["minutes"]:.0f}分' if r.get('minutes') is not None else '—'
        print(f'{r["date"] or "?":<9}{r["client"]:<12}{r["role"]:>4}{mins:>8}'
              f'{c["裝備素材"]:>8}/{q["裝備素材"]:<5}{c["食物素材"]:>8}/{q["食物素材"]:<5}{coin:>9,}')
        tot['角色'] += 1; tot['裝備種'] += c['裝備素材']; tot['裝備個'] += q['裝備素材']
        tot['食物種'] += c['食物素材']; tot['食物個'] += q['食物素材']; tot['石幣'] += coin
    if tot['角色']:
        print(f'合計 {tot["角色"]} 個角色：裝備素材 {tot["裝備種"]} 種 / {tot["裝備個"]} 個、食物素材 {tot["食物種"]} 種 / {tot["食物個"]} 個、'
              f'石幣約 {tot["石幣"]:,}（材料 500 / 個 + 合成 1000 × 10）')
    print('（耗時「—」= 2026-10-15 前的舊記錄沒存時間；之後每個角色跑完會自動記）\n')


# ---------------- 練功 ----------------
def load_exp(f: Path):
    out = []
    with open(f, encoding='utf-8', errors='replace') as fh:
        for r in csv.reader(fh):
            if len(r) < 3 or r[0] == 'time':
                continue
            try:
                t = dt.datetime.strptime(r[0].strip('\x00'), '%Y-%m-%d %H:%M:%S'); lv = int(r[1])
            except ValueError:
                continue
            out.append((t, lv, r[2].split(':')[0]))
    return out


def grind() -> None:
    print('== 練功（notes/exp-log；中斷超過 10 分鐘的時間不算）==')
    for f in sorted((ROOT / 'notes').glob('exp-log-*.csv')):
        win = f.stem[len('exp-log-'):]
        rows = load_exp(f)
        if not rows:
            continue
        client = WINDOW_CLIENT.get(win, win)
        # 練功點區段：同一張地圖連續的記錄
        segs, cur = [], None
        for i, (t, lv, mp) in enumerate(rows):
            gap = i and (t - rows[i - 1][0]).total_seconds() > GAP_S
            if cur is None or mp != cur['map'] or gap:
                if cur:
                    segs.append(cur)
                cur = {'map': mp, 't0': t, 't1': t, 'lv0': lv, 'lv1': lv, 'active': 0.0}
            else:
                cur['active'] += (t - cur['t1']).total_seconds()
                cur['t1'] = t; cur['lv1'] = max(cur['lv1'], lv)
        if cur:
            segs.append(cur)
        segs = [s for s in segs if s['active'] >= 300]          # 5 分鐘以下的是路過 / 補血
        print(f'-- {client}（{win}）最近 8 段練功點 --')
        for s in segs[-8:]:
            print(f'  {s["t0"]:%m-%d %H:%M} {SPOT_NAME.get(s["map"], s["map"]):<8} {s["lv0"]:>3}→{s["lv1"]:<3} 級  {hm(s["active"] / 60)}')
        # 1→120、120→131、131→140：每一輪都算，印最近一次完成的；最近 1 小時還有記錄、等級在區間內 → 進行中
        last_t, last_lv = rows[-1][0], rows[-1][1]
        recent = (dt.datetime.now() - last_t).total_seconds() < 3600
        for a, b in ((1, 120), (120, 131), (131, 140)):
            done, run = [], None                     # run = [開始時間, 上一筆時間, 練功秒數]
            for t, lv, mp in rows:
                if run and lv < a:                   # 轉生回低等級 → 這輪作廢
                    run = None
                if run is None and a <= lv < b:
                    run = [t, t, 0.0]
                    continue
                if run:
                    if (t - run[1]).total_seconds() <= GAP_S:
                        run[2] += (t - run[1]).total_seconds()
                    run[1] = t
                    if lv >= b:
                        done.append((run[0], t, run[2]))
                        run = None
            if done:
                t0, t1, act = done[-1]
                print(f'  {a:>3}→{b} 級：練功 {hm(act / 60)}（最近一次 {t0:%m-%d %H:%M} → {t1:%m-%d %H:%M}；共 {len(done)} 次）')
            if run and recent and a <= last_lv < b:
                print(f'  {a:>3}→{b} 級：進行中，目前 {last_lv} 級，已練 {hm(run[2] / 60)}')
    print()


# ---------------- 一條龍 ----------------
def fullrun() -> None:
    p = CACHE / 'stats-fullrun.jsonl'
    print('== 一條龍階段耗時（stats-fullrun.jsonl）==')
    if not p.exists():
        print('（還沒有記錄：2026-10-15 起每個階段跑完才會寫）\n')
        return
    rows = [json.loads(ln) for ln in p.read_text(encoding='utf-8').splitlines() if ln.strip()]
    by = collections.defaultdict(list)
    for r in rows:
        by[r['client']].append(r)
    for client, rs in by.items():
        print(f'-- {client} --')
        for r in rs[-20:]:
            ok = '完成' if not r['rc'] else f'失敗 {r["rc"]}'
            tgt = f'（目標 {r["target"]}）' if r.get('target') else ''
            print(f'  {r["start"][5:16]} {r["stage"]:<9}{hm(r["minutes"]):>9}  {ok}{tgt}')
    print()


# ---------------- 錯誤 / 停手 ----------------
def _norm(reason: str) -> str:
    import re
    r = re.sub(r'\d+', '#', reason)
    r = re.sub(r'\s+', ' ', r).strip(' ：:，,')
    return r[:60]


def errors(since: str = '') -> None:
    """各腳本記錄檔的錯誤次數與原因：看門狗重啟 / 停手、解任務停手 / 暫時性失敗、每日任務停手"""
    import re
    print('== 錯誤 / 停手統計 ==' + (f'（{since} 起）' if since else ''))
    groups = collections.defaultdict(lambda: collections.defaultdict(list))   # 來源 → 原因 → [時間]

    def add(src, reason, when):
        if since and when and when[:10] < since:
            return
        groups[src][_norm(reason)].append(when)
    for f in sorted(CACHE.glob('watchdog-*.log')):
        client = f.stem[len('watchdog-'):]
        for ln in f.read_text(encoding='utf-8', errors='replace').splitlines():
            when = ln[:19]
            m = re.search(r'退出碼 (\d+)（暫時性）.*最後輸出：(.*)', ln)
            if m:
                add(f'看門狗 {client}（自動重啟）', f'退出碼 {m.group(1)}：{m.group(2)}', when)
                continue
            m = re.search(r'\[watchdog\] 停手：(.*?)（旗標', ln)
            if m:
                add(f'看門狗 {client}（停手）', m.group(1), when)
    for f in sorted(CACHE.glob('questflow-*.log')):
        client = f.stem[len('questflow-'):]
        for ln in f.read_text(encoding='utf-8', errors='replace').splitlines():
            when = ln[:19]
            m = re.search(r'停手（退出碼 (\d+)）：(.*)', ln)
            if m and '帳本' not in ln:
                add(f'解任務 {client}（停手）', f'退出碼 {m.group(1)}：{m.group(2)}', when)
                continue
            m = re.search(r'暫時性失敗（退出碼 (\d+)：(.*?)）→', ln)
            if m:
                add(f'解任務 {client}（暫時性失敗，自動重試）', f'退出碼 {m.group(1)}：{m.group(2)}', when)
    dl = CACHE / 'daily-live.log'
    if dl.exists():
        for ln in dl.read_text(encoding='utf-8', errors='replace').splitlines():
            if ('停手' in ln or '不提交' in ln) and not ln.startswith(' '):
                body = re.sub(r'^\d\d:\d\d:\d\d\s*', '', ln)
                if body.startswith(('購買未完成', '角色 ')) or '停手；排除後' in body:
                    continue                         # 摘要行（原因在前一行）
                add('每日任務（停手）', body, '')
    if not groups:
        print('（沒有記錄）\n')
        return
    for src in sorted(groups):
        items = sorted(groups[src].items(), key=lambda kv: -len(kv[1]))
        total = sum(len(v) for _, v in items)
        print(f'-- {src}：共 {total} 次 --')
        print(f'  {"次數":>4}  {"第一次":<16} {"最後一次":<16} 原因')
        for reason, ts in items[:12]:
            ts2 = sorted(t for t in ts if t)
            a = ts2[0][5:16] if ts2 else '—'
            b = ts2[-1][5:16] if ts2 else '—'
            print(f'  {len(ts):>4}  {a:<16} {b:<16} {reason}')
        if len(items) > 12:
            print(f'  …另外 {len(items) - 12} 種原因')
    print('（「#」= 數字；每日任務記錄沒有日期，所以沒有時間欄）\n')


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    args = sys.argv[1:]
    since = next((x.split('=', 1)[1] for x in args if x.startswith('--since=')), '')
    want = [x for x in args if not x.startswith('--')] or ['daily', 'grind', 'fullrun', 'errors']
    for w in want:
        if w == 'errors':
            errors(since)
            continue
        {'daily': daily, 'grind': grind, 'fullrun': fullrun}.get(w, lambda: print(f'不認得：{w}（daily / grind / fullrun / errors）'))()
    return 0


if __name__ == '__main__':
    sys.exit(main())
