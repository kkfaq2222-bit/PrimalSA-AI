#!/usr/bin/env python3
"""依名字從公共倉庫領指定寵物給指定角色（1920×1017）。每領一隻都重新判讀倉庫（取出後會重排）；領後確認欄內數量 +1。
用法：petgrab1920.py --client kkfaq11111 --plan "2:貝魯卡;3:貝魯卡;4:貝魯卡;5:貝魯卡"   （同角色多隻用逗號）
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--plan', required=True)
    ap.add_argument('--src', choices=['public', 'personal'], default='public')
    a = ap.parse_args()
    plan = [(int(p.split(':')[0]), p.split(':')[1].split(',')) for p in a.plan.split(';')]
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit, petreconcile1920 as rc
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    for r, wanted in plan:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r - 1], wait=800, note=f'petgrab 角色 {r}')
        for nm in wanted:
            rc.goto(pd, a.src); time.sleep(1.3)         # 切角色後倉庫刷新要時間（否則讀到上一個角色的）
            have = sum(1 for i in range(5) if not pd.slot_empty(i))
            if have >= 5:
                print(f'角色{r} 寵物欄已滿 → 停手'); return 4
            for _try in range(4):                               # 切角色 / 切分頁後倉庫會晚一點才刷新：沒讀到就等一下重讀
                names = rc.depot_names(pd, uikit)
                if nm in names:
                    break
                time.sleep(1.0)
            if nm not in names and nm == '加格' and names.count('T') == 1:
                names[names.index('T')] = '加格'                  # 標籤 OCR 讀不出的深藍鯊魚（只剩一隻 T）= 加格
            if nm not in names:
                print(f'角色{r} 要 {nm}，倉庫讀到 {names} → 停手'); return 5
            k = names.index(nm)
            pd.click(rc.XS[k % 5], rc.YS[k // 5], wait=700, note=f'petgrab 角色{r} 取 {nm}（第 {k + 1} 格）')
            pd.click(*rc.TAKE, wait=900, note='petgrab 取出')
            for _ in range(8):
                if sum(1 for i in range(5) if not pd.slot_empty(i)) == have + 1:
                    break
                time.sleep(0.4)
            else:
                print(f'角色{r} 取 {nm} 後欄內數量沒變 → 停手'); return 6
            pd.log(f'角色{r} 已領 {nm}（欄 {have}→{have + 1}）')
    pd.click(*pd.CLOSE_X, wait=500)
    return 0


if __name__ == '__main__':
    sys.exit(main())
