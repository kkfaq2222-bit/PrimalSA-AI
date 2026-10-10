"""Clef / Clef-flash 判讀實驗（任務 1 分類 + 任務 3 黃色問號；任務 2 任務追蹤列辨識）。
用法：uv run --no-project --with pillow python eval.py   （pillow 只用來縮圖 / 裁切）
截圖來源：notes/shots/（已存的遊戲截圖）。結果 JSON 存 results.json，彙整表由 report() 印出。
總呼叫數：21 張 x 2 模型 + 4 裁切 x 2 模型 = 50。
"""
import io, json, os, sys
from PIL import Image
import clef

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
SHOTS = os.path.join(ROOT, 'notes', 'shots')

SCENES = {
    '對話框': 'NPC 對話框（右側棕色框，有 NPC 名稱、文字與按鈕）',
    '獲得物品或獎勵提示': '獲得物品 / 石幣 / 獎勵的提示或飄字',
    '主畫面閒置': '沒有任何視窗的地圖主畫面，只有 HUD 與聊天框',
    '背包或倉庫面板': '背包 / 倉庫 / 道具格子面板',
    '寵物面板': '寵物管理面板（寵物立繪與技能格）',
    '傳送地圖面板': '地圖傳送面板（彩色世界地圖）',
    '輔助設定面板': '灰白色 Automatic Synchronized System 輔助設定視窗',
    '任務詳情面板': '任務詳情視窗（任務列表與說明）',
    '載入畫面': '全螢幕載入畫面，有進度條 Loading',
    '戰鬥中': '回合制戰鬥畫面（雙方隊伍、指令列）',
    '答題或驗證視窗': '答題 / 防腳本驗證視窗，要選圖片選項',
    '其他': '以上皆非（設置面板、切換角色視窗等）',
}
# 人工標註：檔名 -> (場景, 黃色問號在 NPC 頭上? / None 不適用)
TRUTH = {
    '102-sea30': ('對話框', None), '209-chief2': ('對話框', None), '213-track': ('對話框', None), '97-try-abu20': ('對話框', None),
    '94-now': ('主畫面閒置', False), '200-start': ('主畫面閒置', True), '130-before': ('主畫面閒置', True),
    '168-closed': ('主畫面閒置', True), '132-manor': ('主畫面閒置', False),
    '210-chief3': ('獲得物品或獎勵提示', None), '03-after-use': ('獲得物品或獎勵提示', None),
    '22-dkb02-bag': ('背包或倉庫面板', None), '70-depot': ('背包或倉庫面板', None),
    '50-home': ('寵物面板', None), '90-tp-nis': ('傳送地圖面板', None), '93-tp-hero': ('傳送地圖面板', None),
    '150-ass': ('輔助設定面板', None), '205-quest-detail': ('任務詳情面板', None), '100-abu-04': ('載入畫面', None),
    '140-setting': ('其他', None), '20-switch': ('其他', None),
}
# 任務追蹤列裁切（1440x830 座標）與正解
TRACK_BOX = (60, 255, 420, 390)
TRACK_TRUTH = {'130-before': '初入石器', '211-after': '覲見村長', '215-done2': '成人儀式', '212-chief4': '覲見村長'}
TRACK_CANDS = ['初入石器', '覲見村長', '成人儀式', '伐木證書', '黃金羚羊之謎', '沒有任務']


def png(im):
    b = io.BytesIO(); im.save(b, 'PNG'); return b.getvalue()


def load(name):
    return Image.open(os.path.join(SHOTS, name + '.png')).convert('RGB')


def main():
    res = []
    for model in ('clef-flash', 'clef'):
        for name, (scene, mark) in TRUTH.items():
            im = load(name); im = im.resize((960, round(im.height * 960 / im.width)))
            data = png(im)
            qs = {
                'scene': {'type': 'choice', 'instructions': '這張是遊戲截圖，現在畫面屬於哪一種？', 'criteria': SCENES},
                'mark': {'type': 'noul', 'instructions': '有 NPC 頭上浮著黃色的問號（?）圖示嗎？'},
                'verify': {'type': 'noul', 'instructions': '畫面上有要求玩家選圖片選項的答題或驗證視窗嗎？'},
            }
            dt, out = clef.run(model, '精靈王石器（回合制網遊）的手機版遊戲截圖。', qs, [data])
            res.append({'task': 'scene', 'model': model, 'name': name, 'truth': scene, 'mark_truth': mark,
                        'sec': dt, 'bytes': len(data), 'out': out})
            print(model, name, round(dt, 2), json.dumps(out.get('result', out).get('answers', out), ensure_ascii=False)[:300], flush=True)
        for name, title in TRACK_TRUTH.items():
            im = load(name).crop(TRACK_BOX)
            data = png(im)
            qs = {
                'title': {'type': 'choice', 'instructions': '圖中任務追蹤欄的任務標題是哪一個？', 'criteria': {c: c for c in TRACK_CANDS}},
                'has_wood': {'type': 'noul', 'instructions': '任務追蹤欄的標題是「伐木證書」嗎？'},
            }
            dt, out = clef.run(model, '遊戲左側任務追蹤欄的裁切圖。', qs, [data])
            res.append({'task': 'track', 'model': model, 'name': name, 'truth': title, 'sec': dt, 'bytes': len(data), 'out': out})
            print(model, 'TRACK', name, round(dt, 2), json.dumps(out.get('result', out).get('answers', out), ensure_ascii=False)[:300], flush=True)
    json.dump(res, open(os.path.join(os.path.dirname(__file__), 'results.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
