#!/usr/bin/env python3
"""唯讀：讀指定角色寵物欄 5 格的種類名（多種放大倍率補讀；鯊魚 / 火雞名單歸一）。
用法：uv run --no-project python tools/gui/petnames1920.py --client kkfaq11111 --roles 2,3,4,5
"""
import re
import argparse, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
KNOWN = ['火雞', '克克洛斯', '霍爾克', '奇寶', '克邦凱斯', '加克拉', '加格', '邦恩吉', '魯尼帖斯', '貝魯卡']
FUZZY = {'火難': '火雞', '霍爾': '霍爾克', '爾克': '霍爾克', '克克': '克克洛斯', '洛斯': '克克洛斯', '奇寶': '奇寶', '邦恩': '邦恩吉', '恩吉': '邦恩吉', '克拉': '加克拉', '加克': '加克拉', '凱斯': '克邦凱斯', '克邦': '克邦凱斯', '加格': '加格', '魯尼': '魯尼帖斯', '帖斯': '魯尼帖斯', '貝魯': '貝魯卡', '魯卡': '貝魯卡'}


ORDER = [  # 嚴格順序：先比較「專有字」再比較容易混的（克克 vs 克邦）
    ('克邦凱斯', ('凱斯', '克邦', '邦凱')),
    ('加克拉', ('加克', '克拉')),
    ('加格', ('加格', '格')),
    ('邦恩吉', ('邦恩', '恩吉', '恩')),
    ('魯尼帖斯', ('魯尼', '帖斯')),
    ('貝魯卡', ('貝魯', '貝', '魯卡')),
    ('霍爾克', ('霍', '爾克')),
    ('克克洛斯', ('克克', '洛斯')),
    ('奇寶', ('奇', '寶')),
    ('火雞', ('火雞', '火難', '雞')),
]


def canon(t: str):
    t = re.sub(r'[^一-鿿]', '', t)             # 去掉 OCR 混進來的標點 / 數字 / 引號（貝'魯 → 貝魯）
    for name, keys in ORDER:
        if name in t or any(k in t for k in keys):
            return name
    return None


def text_width(uikit) -> int:
    """名字橫幅（背景灰 ≈130、字 ≈200 / 描邊 ≈67；置中 x≈360）的字數估計：每字約 17px。OCR 讀不出霍爾克 / 克克洛斯時用（2026-10-12 實測：霍爾克 52px、火雞 32px）。"""
    xs = list(range(300, 424, 4))
    n = len(xs)
    cols = []
    for y in (100, 106, 112):
        cols += uikit.px([(x, y) for x in xs]) or []
    if len(cols) != 3 * n:
        return 0
    pos = [xs[i] for i in range(n) if any(abs(sum(cols[k * n + i]) / 3 - 132) > 40 for k in range(3))]
    if not pos:
        return 0
    return round((pos[-1] - pos[0] + 4) / 17)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default='kkfaq11111')
    ap.add_argument('--roles', default='2,3,4,5')
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    import winenv; winenv.enable_server()
    import petdepot1920 as pd, uikit
    if not pd.open_panel():
        print('寵物面板打不開'); return 3
    out = {}
    for r in [int(x) - 1 for x in a.roles.split(',')]:
        pd.click(pd.ROLE_X, pd.ROLE_Y[r], wait=900, note=f'petnames 選角色 {r + 1}')
        row = []
        for i in range(5):
            if pd.slot_empty(i):
                row.append(None); continue
            pd.click(pd.SLOT_X, pd.SLOT_Y[i], wait=1100, note=f'petnames 第 {i + 1} 格')
            got = None
            for z in ('2,3', '3,4', '4', '2'):
                t = ''.join(uikit.ocr((230, 92, 260, 32), '-Zooms', z)).strip()
                got = canon(t)
                if got:
                    break
            if not got:
                w = text_width(uikit)
                got = {3: '霍爾克', 4: '克克洛斯'}.get(w, f'?{w}字')
            row.append(got)
        out[f'角色{r + 1}'] = row
        pd.log(f'角色{r + 1}：{row}')
    (Path(__file__).resolve().parents[2] / 'notes' / 'pets-names.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    pd.click(*pd.CLOSE_X, wait=500, note='petnames 關面板')
    return 0


if __name__ == '__main__':
    sys.exit(main())
