# -*- coding: utf-8 -*-
"""
匯出寵物圖片（猜謎三兄弟「哪隻寵物叫 XX」比對用）。只讀 GameClient，輸出到 tools/.cache/pet-images/。

來源 bundle（Sprite 名 = Monster.imageId）：
  headicon1_yhkrn   寵物頭像（小圖，背包 / 寵物欄用）  → head/
  petstaticpic      寵物靜態圖（較大的立繪）            → static/
檔名：{繁中名}_{monsterId}_{imageId}.png；同 imageId 有多隻怪物時每隻各一個檔名（內容相同）。
index.tsv 欄位：monsterId、繁中名、簡中名、韓文名、imageId、head 檔、static 檔（缺圖留空）。

用法（專案根目錄）：
  uv run --no-project --with UnityPy python tools/extract/pet_images.py          # 匯出
  uv run --no-project python tools/extract/pet_images.py --find 諾克斯            # 只查索引（標準函式庫）
"""
import sys, os, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
OUT = os.path.join(ROOT, 'tools', '.cache', 'pet-images')
SRC = {'head': 'headicon1_yhkrn', 'static': 'petstaticpic'}

def safe(s):
    return ''.join('_' if c in '\\/:*?"<>|' else c for c in s).strip() or 'x'

def monsters():
    with open(os.path.join(ROOT, 'knowledge', 'data', 'tables', 'Monster.jsonl'), encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]

def find(key, out=OUT):
    """查索引：名稱（繁 / 簡 / 韓，子字串）或 monsterId / imageId；回傳 [(欄位list)]"""
    p = os.path.join(out, 'index.tsv')
    if not os.path.exists(p):
        return None
    rows = []
    with open(p, encoding='utf-8') as f:
        next(f)
        for l in f:
            c = l.rstrip('\n').split('\t')
            if key in c[1] or key in c[2] or key in c[3] or key == c[0] or key == c[4]:
                rows.append(c)
    return rows

def print_find(key):
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    rows = find(key)
    if rows is None:
        print('找不到索引，先執行：uv run --no-project --with UnityPy python tools/extract/pet_images.py'); return
    if not rows: print('查無寵物圖：' + key); return
    for c in rows:
        print('%s  %s / %s / %s  imageId=%s' % (c[0], c[1], c[2], c[3], c[4]))
        for label, sub, fn in (('頭像', 'head', c[5]), ('靜態圖', 'static', c[6])):
            print('  %s：%s' % (label, os.path.join(OUT, sub, fn) if fn else '（無）'))

def export():
    import UnityPy
    sys.path.insert(0, HERE)
    from extract import bundle_bytes
    ab = os.path.join(ROOT, 'GameClient', 'PrimalSA_Data', 'StreamingAssets', 'AssetBundles')
    sprites = {}
    for kind, bn in SRC.items():
        env = UnityPy.load(bundle_bytes(os.path.join(ab, bn + '.assetbundle')))
        d = sprites[kind] = {}
        for o in env.objects:
            if o.type.name == 'Sprite':
                s = o.read(); d[s.m_Name] = s
        os.makedirs(os.path.join(OUT, kind), exist_ok=True)
    rows, cnt = [], {'head': 0, 'static': 0}
    cache = {}   # (kind,imageId) -> PNG bytes
    for m in monsters():
        iid = str(m.get('imageId', ''))
        name = m.get('nameTn') or m.get('nameCn') or m.get('nameKr') or str(m['ID'])
        fns = {}
        for kind in SRC:
            s = sprites[kind].get(iid)
            if not s: fns[kind] = ''; continue
            fn = '%s_%s_%s.png' % (safe(name), m['ID'], iid)
            if (kind, iid) not in cache:
                import io
                b = io.BytesIO(); s.image.save(b, 'PNG'); cache[(kind, iid)] = b.getvalue()
            with open(os.path.join(OUT, kind, fn), 'wb') as f: f.write(cache[(kind, iid)])
            fns[kind] = fn; cnt[kind] += 1
        rows.append([str(m['ID']), m.get('nameTn', ''), m.get('nameCn', ''), m.get('nameKr', ''), iid, fns['head'], fns['static']])
    with open(os.path.join(OUT, 'index.tsv'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('monsterId\tnameTn\tnameCn\tnameKr\timageId\thead\tstatic\n')
        for r in rows: f.write('\t'.join(r) + '\n')
    print('怪物 %d 筆；頭像 %d、靜態圖 %d；輸出 %s' % (len(rows), cnt['head'], cnt['static'], OUT))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--find')
    a = ap.parse_args()
    print_find(a.find) if a.find else export()
