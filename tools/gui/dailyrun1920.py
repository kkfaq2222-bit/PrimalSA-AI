#!/usr/bin/env python3
"""每日任務（委託接取）一條龍：讀 5 頁 → 查配方 → 傳送買材料（1009 / 2009）→ 存倉 → 回醫院 → 每頁領出 / 合成 / 提交。

前置（每次都要）：背包空 15 格、公共倉庫空 20 格；角色站在醫院（1005）委託接取 NPC 旁（約 37,49）。
用法（專案根目錄，終端機分頁跑，不佔 Claude 使用量）：
  uv run --no-project python tools/gui/dailyrun1920.py --client kkfaq11111 [--phase read|buy|craft|all] [--dry]
階段記在 tools/.cache/dailyrun-<client>.json（當天有效），中斷重跑會跳過已完成的階段；--fresh 全部重來。
底層工具是 dailyquest1920.py（read / plan / here / withdraw / craft），座標與規則見 notes/daily-quest-npc.md。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
DQ = str(HERE / 'dailyquest1920.py')
HOSPITAL_NPC_STAND = (36, 50)            # 37,49 / 37,50 的座標 OCR 常讀不到（「7,」），站 36,50 較穩，NPC 仍在可點範圍
TELEPORT = {'薩姆吉爾': (485, 311), '瑪麗娜絲': (375, 385)}      # 傳送面板「尼斯大陸」分頁座標（截圖座標）


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def run_dq(args, client, extra_env=None) -> int:
    env = dict(os.environ, PSA_EXE_MATCH=client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
    env.setdefault('PSA_CLICK_HOLD_MS', '120')
    r = subprocess.run([sys.executable, DQ] + args + ['--client', client], cwd=str(ROOT), env=env)
    return r.returncode


def run_walk(args, client) -> int:
    env = dict(os.environ, PSA_EXE_MATCH=client, PSA_GUI_SERVER='1', PSA_TILE_SCALE='0.5', PYTHONIOENCODING='utf-8')
    env.setdefault('PSA_CLICK_HOLD_MS', '120')
    r = subprocess.run([sys.executable, str(HERE / 'walk.py')] + args, cwd=str(ROOT), env=env)
    return r.returncode


def teleport(client, dest, want_map) -> bool:
    os.environ['PSA_EXE_MATCH'] = client
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import walk
    for _ in range(2):
        pd.gui('key', '{ESC}', note='dailyrun ESC')
        time.sleep(0.5)
    pd.click(897, 42, wait=1800, note='dailyrun 傳送按鈕')
    pd.click(190, 118, wait=1000, note='dailyrun 尼斯大陸分頁')
    pd.click(*TELEPORT[dest], wait=2500, note=f'dailyrun 傳送 {dest}')
    for _ in range(10):
        p = walk.wait_pos(tries=2)
        if p and p[0] == want_map:
            return True
        time.sleep(1.0)
    return False


# 醫院入口 → 委託接取 NPC 旁的路點（第一組 2026-10-14 實測可通；其餘是卡住時的備用繞法）
HOSPITAL_PATHS = ['32,60 36,50', '30,62 36,50', '33,60 36,50', '30,62 33,57 36,53 36,50', '30,62 35,58 36,50']   # 第 1 組 2026-10-14 實測：先到 32,60（櫃檯前）再一次點 36,50 最穩；走到櫃檯前再直接點終點，讓遊戲自己繞過櫃檯柱子（33,57 / 35,58 那條常卡在 32~33,60）


def go_hospital_npc(client, tries=4) -> bool:
    """醫院內走到 NPC 旁（防呆）：每次失敗都 ESC ×2、重讀位置，換一組路點從目前位置重走；
    路點都不行再用點地面小步 hop（dailyquest1920.hop_to，靠「委託接取」標籤定位）；離目標 <= 3 格就算到。"""
    os.environ['PSA_EXE_MATCH'] = client
    import winenv
    winenv.enable_server()
    import petdepot1920 as pd
    import walk
    tx, ty = HOSPITAL_NPC_STAND

    def near():
        p = walk.wait_pos(tries=3)
        # 座標 OCR 某些數字組合讀不出（實測 1005:37,50 的「7,」整串讀錯）→ 往旁邊挪 1~2 格換個座標再讀
        for ddx, ddy in ((-2, 0), (0, 1), (-1, -1)):
            if p:
                break
            log(f'讀不到座標 → 往旁邊挪一下（{ddx:+d},{ddy:+d} 格）再讀')
            pd.click(int(481 + 10.8 * (ddx + ddy)), int(243 + 7.5 * (ddy - ddx)), wait=1800, note='dailyrun 挪位重讀座標')
            p = walk.wait_pos(tries=3)
        return p, bool(p and p[0] == 1005 and abs(p[1] - tx) <= 3 and abs(p[2] - ty) <= 3)
    for k in range(tries):
        p, ok = near()
        if ok:
            return True
        pts = HOSPITAL_PATHS[k % len(HOSPITAL_PATHS)]
        if p and p[0] == 1005:      # 從目前位置接著走：跳過已經走過頭的路點（y 比目前大 = 在後面）
            rest = [s for s in pts.split() if int(s.split(',')[1]) < p[2]] or [f'{tx},{ty}']
            pts = ' '.join(rest)
        log(f'[craft] 醫院內走到 NPC 旁（第 {k + 1}/{tries} 次，目前 {p}）：{pts}')
        rc = run_walk(['--path', f'1005:{pts}'], client)
        if near()[1]:          # 走路程式說失敗（常是讀不到座標）也先看實際到了沒
            return True
        log(f'走路失敗（退出碼 {rc}）→ ESC 後重走')
        for _ in range(2):
            pd.gui('key', '{ESC}', note='dailyrun 走路失敗 ESC')
            time.sleep(0.5)
        time.sleep(1.0)
    try:
        import uikit
        import dailyquest1920 as dq
        log('[craft] 路點都走不到 → 改點地面小步走')
        if dq.hop_to(pd, uikit, walk, winenv, 1005, (tx, ty), [('委託接取', (41, 42))], max_hops=10) and near()[1]:
            return True
    except Exception as e:
        log(f'小步走出錯：{e}')
    return near()[1]


def go_hospital(client) -> int:
    """已在醫院（1005）就不動；否則傳送薩姆吉爾 → 走進醫院入口。回 0 = 在醫院。"""
    os.environ['PSA_EXE_MATCH'] = client
    import winenv
    winenv.enable_server()
    import walk
    p = walk.wait_pos(tries=3)
    if p and p[0] == 1005:
        return 0
    if not teleport(client, '薩姆吉爾', 1000):
        log('傳送失敗 → 停手')
        return 3
    rc = run_walk(['1000', '81', '66', '--exit', '1005'], client)
    if rc != 0:
        p = walk.wait_pos(tries=3)
        if not (p and p[0] == 1005):
            log(f'走進醫院失敗（退出碼 {rc}）→ 停手')
            return 4
    return 0


def wait_at(client, mp, xy, tol=3, timeout_min=15) -> bool:
    """等使用者把角色帶到 NPC 旁（醫院內沒有通行格資料，走路工具走不到）。"""
    os.environ['PSA_EXE_MATCH'] = client
    import winenv
    winenv.enable_server()
    import walk
    t0 = time.time()
    said = False
    while time.time() - t0 < timeout_min * 60:
        p = walk.wait_pos(tries=2)
        if p and p[0] == mp and abs(p[1] - xy[0]) <= tol and abs(p[2] - xy[1]) <= tol:
            return True
        if not said:
            log(f'請把角色帶到醫院委託接取 NPC 旁（約 {xy[0]},{xy[1]}），我等你（最多 {timeout_min} 分鐘）…')
            said = True
        time.sleep(3)
    return False



class _Tee:
    """stdout 同時寫到 tools/.cache/daily-live.log（dailywin.py 小視窗讀這個檔）"""
    def __init__(self, stream, path):
        self._s, self._p = stream, path

    def write(self, data):
        try:
            self._s.write(data)
        except Exception:
            pass
        try:
            if data.strip():
                with open(self._p, 'a', encoding='utf-8') as f:
                    f.write(time.strftime('%H:%M:%S ') + data.rstrip(chr(10)) + chr(10))
        except Exception:
            pass

    def flush(self):
        try:
            self._s.flush()
        except Exception:
            pass

    def __getattr__(self, k):
        return getattr(self._s, k)


def record_daily(client, role, t0, done_f, pages) -> None:
    """統計用：每個角色跑完一行寫進 tools/.cache/stats-daily.jsonl（時間、買了什麼、10 個成品；stats.py 讀）"""
    try:
        bought = json.loads(Path(done_f).read_text(encoding='utf-8')).get('bought', {}) if Path(done_f).exists() else {}
        row = {'client': client, 'role': role, 'date': time.strftime('%Y%m%d'),
               'start': time.strftime('%F %T', time.localtime(t0)), 'end': time.strftime('%F %T'),
               'minutes': round((time.time() - t0) / 60, 1), 'bought': bought, 'items': pages}
        with open(ROOT / 'tools' / '.cache' / 'stats-daily.jsonl', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception as e:
        log(f'統計記錄失敗（{e}）')


def run_roles(a) -> int:
    """使用者 2026-10-14：角色 1 解完自己切角色 2 再解，依序到 5。每個角色耗時記在 log。"""
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv
    winenv.enable_server()
    import uikit
    env = dict(os.environ, PSA_EXE_MATCH=a.client, PSA_GUI_SERVER='1', PYTHONIOENCODING='utf-8')
    for r in [int(x) for x in a.roles.split(',') if x.strip()]:
        log(f'===== 角色 {r}：切換 =====')
        uikit.gui('key', '{ESC}', note='dailyrun 切換前關面板')
        time.sleep(1.0)
        rc = subprocess.run([sys.executable, str(HERE / 'switch1920.py'), '--client', a.client, '--role', str(r)],
                            cwd=str(ROOT), env=env).returncode
        uikit.gui('key', '{ESC}', note='dailyrun 關切換角色面板')
        time.sleep(1.0)
        if rc != 0:
            log(f'切到角色 {r} 失敗（退出碼 {rc}）→ 停手')
            return 4
        t0 = time.time()
        args = [sys.executable, str(Path(__file__).resolve()), '--client', a.client, '--role', str(r)]
        if a.dry:
            args.append('--dry')
        rc = subprocess.run(args, cwd=str(ROOT), env=env).returncode
        log(f'角色 {r} 每日任務結束（退出碼 {rc}），耗時 {(time.time() - t0) / 60:.1f} 分')
        if rc != 0:
            log(f'角色 {r} 沒完成 → 停手（排除後用 --roles 從角色 {r} 接著跑，已買 / 已做的不會重來）')
            return rc
    log('全部角色每日任務完成')
    return 0


def main() -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, str(ROOT / 'tools' / '.cache' / 'daily-live.log'))
    ap = argparse.ArgumentParser(description='每日任務一條龍')
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--phase', default='all', choices=['read', 'buy', 'craft', 'all'])
    ap.add_argument('--role', type=int, default=0, help='角色編號（只用來把記錄檔分開；請先自己把視窗切到該角色）')
    ap.add_argument('--fresh', action='store_true', help='忽略當天階段記錄，全部重來（已買記錄 daily-done 另外處理）')
    ap.add_argument('--dry', action='store_true', help='只印計畫，不動遊戲（讀頁 / 買 / 合成都跳過）')
    ap.add_argument('--roles', default='', help='依序自動切換角色跑完（例：2,3,4,5）；每個角色先 switch1920 切過去，成功才換下一個')
    a = ap.parse_args()
    if a.roles:
        return run_roles(a)
    tag = f'-r{a.role}' if a.role else ''
    os.environ['PSA_DAILY_TAG'] = tag
    t_start = time.time()               # 子程序（dailyquest1920）的已買記錄也依角色分開
    cache = ROOT / 'tools' / '.cache'
    pages_json = cache / f'daily-{a.client}{tag}.json'
    st_path = cache / f'dailyrun-{a.client}{tag}.json'
    today = time.strftime('%Y%m%d')
    try:
        st = json.loads(st_path.read_text(encoding='utf-8'))
    except Exception:
        st = {}
    if a.fresh or st.get('date') != today:
        st = {'date': today, 'done': []}
        for f in (pages_json, cache / f'daily-done-{a.client}{tag}.json'):
            if f.exists() and not a.dry:
                f.rename(f.with_suffix('.json.' + time.strftime('%H%M') + '.bak'))

    def save():
        st_path.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')

    def phase(name):
        return a.phase in ('all', name) and name not in st['done']

    # 1) 讀 5 頁
    if phase('read'):
        log('[read] 讀每日任務 5 頁')
        if a.dry:
            log('（dry：略過）')
        else:
            rc = go_hospital(a.client)          # 讀頁也要站在委託接取 NPC 旁（換角色後常不在醫院）
            if rc == 0 and not go_hospital_npc(a.client):
                log('走不到委託接取 NPC 旁 → 請手動站過去，我等你')
                rc = 0 if wait_at(a.client, 1005, HOSPITAL_NPC_STAND) else 5
            if rc:
                return rc
            rc = run_dq(['read', '--out', str(pages_json)], a.client)
            if rc != 0:
                log(f'讀頁失敗（退出碼 {rc}）→ 停手；可手動編輯 {pages_json} 後用 --phase buy 繼續')
                return rc
            st['done'].append('read')
            save()
    if not pages_json.exists():
        log(f'找不到 {pages_json}')
        return 2
    # 規劃回合：背包 15 + 公共倉庫 20 = 33 種上限（使用者規則）。超過就拆：先第 1 頁、其餘 2~5 頁；不行再 1+2 頁、3~5 頁
    import dailyquest1920 as dq
    data = json.loads(pages_json.read_text(encoding='utf-8'))
    pages = data['pages']
    plan_all, _stores = dq.build_plan(pages)

    def kinds(pgs):
        return len({n for pg, _it, mats in plan_all if pg in pgs for n, _q in mats})
    LIMIT = 33
    allp = [1, 2, 3, 4, 5]
    if kinds(allp) <= LIMIT:
        rounds = [allp]
    elif kinds([2, 3, 4, 5]) <= LIMIT:
        rounds = [[1], [2, 3, 4, 5]]
    elif kinds([3, 4, 5]) <= LIMIT:
        rounds = [[1, 2], [3, 4, 5]]
    else:
        rounds = [[p] for p in allp]
    log(f'材料共 {kinds(allp)} 種（上限 {LIMIT}）→ 回合：{rounds}')
    if a.dry:
        for r in rounds:
            sub = [pg if i + 1 in r else [] for i, pg in enumerate(pages)]
            sj = cache / f'daily-{a.client}{tag}-dry.json'
            sj.write_text(json.dumps({'pages': sub, 'skip': []}, ensure_ascii=False), encoding='utf-8')
            log(f'--- 回合 {r} ---')
            run_dq(['plan', '--file', str(sj)], a.client)
        return 0

    for ri, rpages in enumerate(rounds, 1):
        sub = [pg if i + 1 in rpages else [] for i, pg in enumerate(pages)]
        sj = cache / f'daily-{a.client}{tag}-round{ri}.json'
        sj.write_text(json.dumps({'pages': sub, 'skip': []}, ensure_ascii=False), encoding='utf-8')
        pf = ['--file', str(sj)]
        log(f'===== 回合 {ri}/{len(rounds)}：第 {rpages} 頁 =====')
        # 2) 買材料：依計畫分到 1009 / 2009 兩張地圖
        if a.phase in ('all', 'buy') and f'r{ri}buy' not in st['done']:
            for mp, dest, door in ((1009, '薩姆吉爾', (106, 91, 1000)), (2009, '瑪麗娜絲', (73, 103, 2000))):
                key = f'r{ri}buy{mp}'
                if key in st['done']:
                    continue
                need_q = {}
                for pg, _it, mats in plan_all:
                    if pg in rpages:
                        for n, q in mats:
                            need_q[n] = need_q.get(n, 0) + q
                try:                                   # 扣掉已買的（重跑時不要白跑一趟已買完的地圖）
                    bought = json.loads((cache / f'daily-done-{a.client}{tag}.json').read_text(encoding='utf-8')).get('bought', {})
                except Exception:
                    bought = {}
                need_here = {n for n, q in need_q.items() if q > bought.get(n, 0)}
                if not any(v[2] == mp for n, v in dq.load_stores().items() if n in need_here):
                    st['done'].append(key)
                    continue
                log(f'[buy] 傳送 {dest} → 進 {mp} → 買本地圖材料')
                if not teleport(a.client, dest, door[2]):
                    log('傳送後沒到目標地圖 → 停手')
                    return 3
                if mp == 2009:     # 出口 (73,103) 前面 (73,100~102) 是障礙：要從左邊 x=71 繞下去（2026-10-14 實測）
                    rc = run_walk(['2000', '71', '95'], a.client)
                    if rc == 0:
                        rc = run_walk(['--path', '2000:71,99 71,102 72,103 73,103', '--exit', '2009'], a.client)
                else:
                    rc = run_walk([str(door[2]), str(door[0]), str(door[1]), '--exit', str(mp)], a.client)
                if rc != 0:
                    log(f'走進 {mp} 失敗（退出碼 {rc}）→ 停手')
                    return 4
                rc = run_dq(['here', '--do'] + pf, a.client)
                if rc != 0:
                    log(f'購買未完成（退出碼 {rc}；8 = 有店點不到）→ 停手；排除後重跑會從已買記錄接著買')
                    return rc
                st['done'].append(key)
                save()
            st['done'].append(f'r{ri}buy')
            save()
        # 3) 回醫院 → 每頁領出 / 合成 / 提交
        if a.phase in ('all', 'craft'):
            todo = [pg for pg in rpages if f'craft{pg}' not in st['done']]
            if todo:
                log('[craft] 回醫院')
                rc = go_hospital(a.client)
                if rc:
                    return rc
                # 醫院內：用手動路點走（2026-10-14 實測：入口 25,65 → 30,62 → 35,58 → 37,49 可通；沿途有傳送光圈，別亂點地面）
                if not go_hospital_npc(a.client):
                    log('醫院內自動走 4 次 + 小步走都失敗 → 請手動站到 NPC 旁，我等你')
                    if not wait_at(a.client, 1005, HOSPITAL_NPC_STAND):
                        log('等不到角色站到 NPC 旁 → 停手')
                        return 5
            for pg in todo:
                log(f'[craft] 第 {pg} 頁')
                rc = run_dq(['withdraw', '--page', str(pg)] + pf, a.client)
                if rc != 0:
                    return rc
                rc = run_dq(['craft', '--page', str(pg), '--submit'] + pf, a.client)
                if rc != 0:
                    log(f'第 {pg} 頁合成 / 提交失敗（退出碼 {rc}）→ 停手；看 tools/.cache/craft-p{pg}-*.png')
                    return rc
                st['done'].append(f'craft{pg}')
                save()
        done_f = cache / f'daily-done-{a.client}{tag}.json'
        if ri < len(rounds) and done_f.exists():          # 下一回合重新記格位（這回合的材料已用掉）
            done_f.rename(done_f.with_suffix('.json.r' + str(ri) + '.bak'))
    log('每日任務完成（請看 tools/.cache/craft-p5-submit.png 確認 5/5）')
    record_daily(a.client, a.role, t_start, cache / f'daily-done-{a.client}{tag}.json', pages)
    return 0


if __name__ == '__main__':
    sys.exit(main())
