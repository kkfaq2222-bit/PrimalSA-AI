#!/usr/bin/env python3
r"""升級速度監測（唯讀；只用標準庫）：讀 levelwatch 寫的 notes/exp-log-<客戶端資料夾>.csv，
印每個帳號「目前等級、每級花多久、經驗速度、預計幾點到目標等級」。不碰遊戲、不寫任何檔案。

用法（專案根目錄；終端機直接跑）：
  uv run --no-project python tools/gui/levelspeed.py                      # 11111 + 22222 各印一次
  uv run --no-project python tools/gui/levelspeed.py --watch 60           # 每 60 秒更新一次（Ctrl+C 結束）
  uv run --no-project python tools/gui/levelspeed.py --clients kkfaq11111 --last 12 --target 131
預計到達時間：用「最近 3 級」與「最近 --last 級」兩個經驗速度各算一次，給一個區間
（經驗速度會隨等級 / 練功點變快，所以最近 3 級通常比較樂觀）。每級所需經驗取 knowledge/pets/levels.md。
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NOTES = ROOT / 'notes'
LEVELS_MD = ROOT / 'knowledge' / 'pets' / 'levels.md'
CLIENTS_JSON = ROOT / 'tools' / '.cache' / 'clients.json'
DEFAULT_CLIENTS = ['kkfaq11111', 'kkfaq22222']
FMT = '%Y-%m-%d %H:%M:%S'


def load_need() -> dict:
    """{等級: 升到下一級所需經驗}"""
    need = {}
    for ln in LEVELS_MD.read_text(encoding='utf-8').splitlines():
        m = re.match(r'\| (\d+) \| (\d+) \|', ln)
        if m:
            need[int(m.group(1))] = int(m.group(2))
    return need


def folder_of(client: str) -> str:
    """帳號代號 → 客戶端資料夾名（exp-log 檔名用）；對不到就原樣當資料夾名"""
    try:
        return json.loads(CLIENTS_JSON.read_text(encoding='utf-8')).get(client, client)
    except (OSError, ValueError):
        return client


def read_session(path: Path) -> list:
    """exp-log → 最近一次連續練功的 [(時間, 等級)]（等級往下掉 = 轉生 / 重練，從那之後算）"""
    rows = []
    try:
        with path.open(encoding='utf-8', newline='') as f:
            for ln in f:
                parts = ln.rstrip('\n').split(',', 2)      # pos 欄自己帶逗號，只切前兩個
                if len(parts) < 2 or not parts[1].strip().isdigit():
                    continue
                try:
                    rows.append((dt.datetime.strptime(parts[0], FMT), int(parts[1])))
                except ValueError:
                    continue
    except OSError:
        return []
    start = 0
    for i in range(len(rows) - 1, 0, -1):
        if rows[i][1] < rows[i - 1][1]:
            start = i
            break
    return rows[start:]


GAP_MIN = 6                      # 兩筆紀錄間隔超過這麼久 = levelwatch 中間停過，後面那一級的起點不可信


def level_times(rows: list) -> list:
    """[(等級, 第一次看到的時間, 起點可信嗎)]，依時間順序。
    紀錄斷檔後（或整份紀錄的第一筆）第一次看到的等級，真正的升級時間早於這筆 → 起點不可信，不拿來算速度"""
    seen, out = set(), []
    prev_t = None
    for t, lv in rows:
        fresh = prev_t is not None and (t - prev_t).total_seconds() / 60 <= GAP_MIN
        if lv not in seen:
            seen.add(lv)
            out.append((lv, t, fresh))
        prev_t = t
    return out


def rates(lt: list, need: dict) -> list:
    """每個「已升完」的等級 → (等級, 花的分鐘, 經驗 / 分)；相鄰兩級必須差 1 才算（讀漏的不算）"""
    out = []
    for (l0, t0, ok0), (l1, t1, ok1) in zip(lt, lt[1:]):
        mins = (t1 - t0).total_seconds() / 60
        if ok0 and ok1 and l1 == l0 + 1 and mins > 0 and l0 in need:
            out.append((l0, mins, need[l0] / mins))
    return out


def eta(cur: int, elapsed_min: float, target: int, rate: float, need: dict):
    """目前這級已花 elapsed_min 分 → 還要幾分鐘到 target 級（沒法算回 None）"""
    if rate <= 0 or cur >= target or any(l not in need for l in range(cur, target)):
        return None
    earned = min(rate * elapsed_min, need[cur] * 0.95)
    remain = sum(need[l] for l in range(cur, target)) - earned
    return remain / rate


def fmt_min(m: float) -> str:
    return f'{int(m // 60)} 小時 {int(m % 60):02d} 分' if m >= 60 else f'{m:.1f} 分'


def report(client: str, need: dict, last: int, target: int, now: dt.datetime) -> str:
    folder = folder_of(client)
    path = NOTES / f'exp-log-{folder}.csv'
    rows = read_session(path)
    head = f'【{client}（{folder}）】'
    if not rows:
        return head + f' 沒有紀錄（{path.name} 不存在或讀不到）；levelwatch 沒在跑？'
    cur, t_last = rows[-1][1], rows[-1][0]
    age = (now - t_last).total_seconds() / 60
    lt = level_times(rows)
    cur_since, cur_ok = next((t, ok) for lv, t, ok in lt if lv == cur)
    elapsed = (now - cur_since).total_seconds() / 60 if cur_ok else 0.0     # 起點不可信 → 當剛升級（偏保守）
    rs = rates(lt, need)
    lines = [head + f' 目前 {cur} 級；這一級已花 {("至少 " if not cur_ok else "") + fmt_min(elapsed)}'.replace('至少 0.0 分', '（起點不明）') + f'；最後一筆紀錄 {t_last:%H:%M:%S}（{fmt_min(age)}前）'
             + ('  ⚠ 超過 3 分鐘沒新紀錄，levelwatch 可能停了' if age > 3 else '')]
    show = rs[-last:]
    if show:
        lines.append('  等級 → 升級花的時間 / 經驗速度（最近 %d 級）：' % len(show))
        for lv, mins, r in show:
            lines.append(f'    {lv} → {lv + 1}：{fmt_min(mins):>10}   {r / 1e6:6.2f}M/分')
    else:
        lines.append('  還沒有完整升完的等級可以算速度')
    if rs:
        cand = []
        for label, sub in (('最近 3 級', rs[-3:]), (f'最近 {min(last, len(rs))} 級', rs[-last:])):
            tot_need = sum(need[l] for l, _, _ in sub)
            tot_min = sum(m for _, m, _ in sub)
            rate = tot_need / tot_min if tot_min else 0
            e = eta(cur, elapsed, target, rate, need)
            if e is not None:
                cand.append((e, label, rate))
        if cur - rs[-1][0] > 3:
            lines.append(f'  ※ 速度樣本最新只到 {rs[-1][0]} 級（中間紀錄斷過 / 換過練功點），下面時間僅供參考；levelwatch 跑一陣子就會變準')
        if cur >= target:
            lines.append(f'  已達 {target} 級')
        elif cand:
            cand.sort()
            for e, label, rate in cand:
                lines.append(f'  用{label}速度（{rate / 1e6:.2f}M/分）：還要約 {fmt_min(e)} → {now + dt.timedelta(minutes=e):%m-%d %H:%M} 到 {target} 級')
        else:
            lines.append(f'  算不出到 {target} 級的時間（等級表缺資料）')
    return '\n'.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='升級速度監測（唯讀）')
    ap.add_argument('--clients', default=','.join(DEFAULT_CLIENTS), help='帳號代號，逗號分隔（預設 kkfaq11111,kkfaq22222）')
    ap.add_argument('--last', type=int, default=8, help='列最近幾級的速度（預設 8）')
    ap.add_argument('--target', type=int, default=131, help='目標等級（預設 131）')
    ap.add_argument('--watch', type=int, default=0, help='每幾秒更新一次（0 = 只印一次）')
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    need = load_need()
    clients = [c.strip() for c in a.clients.split(',') if c.strip()]
    try:
        while True:
            now = dt.datetime.now()
            if a.watch:
                print('\033[2J\033[H', end='')
            print(f'升級速度監測 {now:%Y-%m-%d %H:%M:%S}（目標 {a.target} 級；唯讀）\n')
            for c in clients:
                print(report(c, need, a.last, a.target, now))
                print()
            if not a.watch:
                return 0
            sys.stdout.flush()
            time.sleep(a.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
