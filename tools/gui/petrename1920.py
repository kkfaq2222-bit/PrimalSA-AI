#!/usr/bin/env python3
"""把寵物欄寵物的暱稱恢復成原本種類名（1920×1017）：選格 → 名稱旁鉛筆 → 不輸入直接「確認」→ OCR 讀名字。
用法：uv run --no-project python tools/gui/petrename1920.py --client kkfaq11111 --roles 2,3,4,5
防呆：--expect 格魯西斯,格魯（OCR 片段，任一命中算改回）→ 每格最多重做 3 次，仍不符就停手（退出碼 6）；
      --count 5 → 該角色寵物欄必須剛好 5 隻（不符退出碼 7）。
結果寫 notes/pets-names.json（角色 → 5 格名稱）。只動寵物欄，不碰倉庫。
"""
import argparse, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
PENCIL = (468, 106)
OK_BTN = (410, 320)
OUT = Path(__file__).resolve().parents[2] / 'notes' / 'pets-names.json'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='2,3,4,5')
    ap.add_argument('--expect', default='', help='名稱 OCR 片段（逗號分隔，任一命中算改回原名）；不給就不驗證')
    ap.add_argument('--count', type=int, default=0, help='該角色寵物欄應有的隻數；0 = 不檢查')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    keys = [k.strip() for k in a.expect.split(',') if k.strip()]
    bad = 0
    res = {}
    for r in [int(x) - 1 for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r], wait=1200, note=f'petrename 選角色 {r + 1}')
        names = []
        for i in range(5):
            if pd.slot_empty(i):
                names.append(None); continue
            name = ''
            for t in range(1, 4 if keys else 2):
                pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=700, note=f'petrename 選第 {i + 1} 格')
                pd.click(*PENCIL, wait=900, note=f'petrename 鉛筆（第 {t} 次）')
                pd.click(*OK_BTN, wait=1000, note='petrename 確認（不輸入）')
                name = pd.pet_name()
                if not keys or any(k in name for k in keys):
                    break
                pd.log(f'角色{r + 1} 第 {i + 1} 格名稱「{name}」不是 {keys}，重做（{t}/3）')
            else:
                pd.log(f'角色{r + 1} 第 {i + 1} 格改名 3 次仍不符（讀到「{name}」）：停手')
                bad = 6
            names.append(name)
        have = sum(1 for n in names if n is not None)
        if a.count and have != a.count:
            pd.log(f'角色{r + 1} 寵物欄有 {have} 隻，應為 {a.count}：停手')
            bad = bad or 7
        res[f'角色{r + 1}'] = names
        pd.log(f'角色{r + 1}：{names}')
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    pd.click(*pd.CLOSE_X, wait=600, note='petrename 關面板')
    return bad


if __name__ == '__main__':
    sys.exit(main())
