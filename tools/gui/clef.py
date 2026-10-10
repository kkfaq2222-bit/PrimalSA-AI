#!/usr/bin/env python3
"""Clef-flash / Clef（Cloudflare Workers AI）畫面判讀「加速層」（只用標準函式庫）。

只當加速層：任何失敗（額度用完 / 限流 / token 失效 / 逾時 / 網路錯誤 / 回應格式不對）都回 None，
呼叫端退回原本的 OCR / 規則流程，絕不丟例外、不卡住。實驗與數據見 notes/clef-eval.md。

認證（token 絕不印出、不寫檔、不寫 log）：
  1. 環境變數 CF_AI_TOKEN（只有 Workers AI 權限的專用 API token）；CF_ACCOUNT_ID（或 ~/.config/psa-ai/cf_account_id，一行帳號 ID）必填，沒設就停用 Clef
  2. 使用者設定檔 ~/.config/psa-ai/cf_ai_token（只讀不建立；WSL / Windows 都用使用者家目錄）
  不再退回 wrangler OAuth（會過期、權限過大）。找不到 / 失效時會在 stderr 印醒目提示並寫事件 log。
關閉：環境變數 PSA_NO_CLEF=1，或呼叫端 set_enabled(False)（quest.py --no-clef）。

limit 退回（使用者明確要求）：
  - 額度類錯誤（HTTP 429 / 402、Workers AI code 4006、錯誤文字含 neuron / quota / rate limit / daily / allocation）
    → 立刻停用，並把 UTC 日期寫進 tools/.cache/clef-state.json；同一個 UTC 日之後的執行直接不呼叫。
  - token 失效（401 / 403）→ 本次執行停用（不寫狀態檔，換 token 後下次就能用）。
  - 暫時性錯誤（逾時 / 網路 / 5xx / 回應壞掉）→ 連續 MAX_FAILS 次才本次停用，成功一次就歸零。
  事件經 set_logger() 註冊的函式輸出（quest.py 接到 notes/quest-events.log）。
"""
import base64
import io
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / 'tools' / '.cache' / 'clef-state.json'
MODELS = {'clef': '@cf/cloudflare/clef', 'clef-flash': '@cf/cloudflare/clef-flash'}
TIMEOUT = 5.0                 # 秒；逾時就退回原流程
MAX_FAILS = 3                 # 暫時性錯誤連續幾次後本次停用
QUOTA_WORDS = ('neuron', 'quota', 'rate limit', 'rate-limit', 'too many', 'daily', 'allocation')

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
SCENE_STATE = '精靈王石器（回合制網遊）的遊戲截圖。'
VERIFY_Q = {'type': 'noul', 'instructions': '畫面上有要求玩家選圖片選項的答題或驗證視窗嗎？'}
TRACK_BOX = (60, 255, 420, 390)       # 左側任務追蹤區（1440x830 截圖座標），與實驗相同
NO_TASK = '沒有任務'

_enabled = os.environ.get('PSA_NO_CLEF', '') not in ('1', 'true', 'yes')
_fails = 0
_reason = ''                  # 本次執行被停用的原因（空 = 沒停用）
_logger = lambda msg: None
_state_checked = False


def set_logger(fn) -> None:
    """註冊事件輸出函式（quest.py 傳 event）；訊息保證不含 token"""
    global _logger
    _logger = fn


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = on


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_state(d: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def _notify(msg: str) -> None:
    """醒目告知使用者（stderr + 事件 log）；訊息不含 token"""
    print(f'[Clef] {msg}', file=sys.stderr, flush=True)
    _logger(f'[Clef] {msg}')


def _disable(reason: str, quota: bool = False, notice: str = '') -> None:
    """停用 Clef（本次執行）；quota=True 另記 UTC 日期到狀態檔，同日不再呼叫"""
    global _reason
    if _reason:
        return
    _reason = reason
    if quota:
        _save_state({'quota_exhausted_utc': _utc_today(), 'reason': reason[:200]})
    if notice:
        _notify(notice)
    else:
        _logger(f'Clef 已停用，退回 OCR / 規則流程：{reason}' + ('（今日 UTC 內不再呼叫）' if quota else ''))


def available() -> bool:
    """能不能呼叫：沒被關掉、本次沒停用、今天（UTC）沒用完額度、有 token"""
    global _state_checked
    if not _enabled or _reason:
        return False
    st = _load_state()
    if st.get('quota_exhausted_utc') == _utc_today():
        _disable('今日額度已用完（狀態檔記錄）')
        return False
    if st.get('quota_exhausted_utc') and not _state_checked:
        _state_checked = True
        _logger('Clef 額度日期已過（UTC 換日），重新啟用')
    if not _token():
        _disable('找不到 token（CF_AI_TOKEN / ~/.config/psa-ai/cf_ai_token）',
                 notice='未設定 CF_AI_TOKEN，Clef 加速已停用，改用原本模式；設定方法見 .claude/skills/psa-game-ui/ui/quest.md「Clef 加速層」')
        return False
    if not _account():
        _disable('找不到帳號 ID（CF_ACCOUNT_ID / ~/.config/psa-ai/cf_account_id）',
                 notice='未設定 CF_ACCOUNT_ID，Clef 加速已停用，改用原本模式；設定方法見 .claude/skills/psa-game-ui/ui/quest.md「Clef 加速層」')
        return False
    return True


def _account() -> str:
    """環境變數 CF_ACCOUNT_ID → ~/.config/psa-ai/cf_account_id（只讀）；都沒有回空字串"""
    a = os.environ.get('CF_ACCOUNT_ID', '').strip()
    if a:
        return a
    try:
        return (Path.home() / '.config' / 'psa-ai' / 'cf_account_id').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _token() -> str:
    """環境變數 CF_AI_TOKEN → ~/.config/psa-ai/cf_ai_token（只讀）；都沒有回空字串"""
    t = os.environ.get('CF_AI_TOKEN', '').strip()
    if t:
        return t
    try:
        return (Path.home() / '.config' / 'psa-ai' / 'cf_ai_token').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _is_quota_error(status: int, body: str) -> bool:
    low = body.lower()
    if status in (429, 402):
        return True
    if '4006' in low or '"code":4006' in low.replace(' ', ''):    # Workers AI：daily free allocation of 10,000 neurons used up
        return True
    return 400 <= status < 500 and any(w in low for w in QUOTA_WORDS)


def _urlopen(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)      # 獨立出來方便測試 mock


def run(model: str, state: str, questions: dict, images: list) -> dict | None:
    """呼叫 Workers AI；成功回傳 answers dict，任何失敗回 None（並依類型停用）"""
    global _fails
    if not available():
        return None
    acct = _account()
    body = {'model': model, 'state': state, 'questions': questions,
            'images': ['data:image/png;base64,' + base64.b64encode(b).decode() for b in images]}
    req = urllib.request.Request(
        f'https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{MODELS[model]}',
        data=json.dumps(body).encode(), method='POST',
        headers={'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json'})
    try:
        with _urlopen(req, TIMEOUT) as r:
            out = json.load(r)
        answers = out['result']['answers']
        if not isinstance(answers, dict):
            raise ValueError('answers 格式不對')
        _fails = 0
        return answers
    except urllib.error.HTTPError as e:
        try:
            txt = e.read().decode('utf-8', 'replace')[:400]
        except Exception:
            txt = ''
        if _is_quota_error(e.code, txt):
            _disable(f'額度 / 限流錯誤 HTTP {e.code}', quota=True)
        elif e.code in (401, 403):
            _disable(f'token 失效或權限不足 HTTP {e.code}',
                     notice=f'CF_AI_TOKEN token 無效或權限不足（HTTP {e.code}），Clef 加速已停用，改用原本模式；請檢查 token 是否有 Workers AI 權限')
        elif 400 <= e.code < 500:
            _disable(f'請求被拒 HTTP {e.code}')
        else:
            _transient(f'HTTP {e.code}')
    except Exception as e:                      # 逾時 / 網路 / JSON 壞掉 / 欄位缺
        _transient(type(e).__name__)
    return None


def _transient(what: str) -> None:
    global _fails
    _fails += 1
    _logger(f'Clef 暫時性錯誤（{what}），連續 {_fails}/{MAX_FAILS}，這次退回原流程')
    if _fails >= MAX_FAILS:
        _disable(f'連續 {MAX_FAILS} 次暫時性錯誤')


def _top(ans: dict | None, qid: str) -> tuple[str, float] | None:
    """choice 題 → (最高機率選項, 機率)"""
    try:
        pr = ans[qid]['probabilities']
        k = max(pr, key=pr.get)
        return k, float(pr[k])
    except (TypeError, KeyError, ValueError):
        return None


def _noul(ans: dict | None, qid: str) -> float | None:
    try:
        return float(ans[qid]['noul'])
    except (TypeError, KeyError, ValueError):
        return None


# ---------------- PNG 縮放 / 裁切（純標準函式庫；遊戲截圖是 8 bit RGB / RGBA、非交錯）----------------
def _png_decode(data: bytes):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('不是 PNG')
    pos, idat, w = 8, [], None
    while pos < len(data):
        n, typ = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if typ == b'IHDR':
            w, h, depth, ctype, _, _, inter = struct.unpack('>IIBBBBB', chunk)
        elif typ == b'IDAT':
            idat.append(chunk)
        elif typ == b'IEND':
            break
    if depth != 8 or ctype not in (2, 6) or inter:
        raise ValueError('只支援 8 bit RGB/RGBA 非交錯 PNG')
    bpp = 3 if ctype == 2 else 4
    raw = zlib.decompress(b''.join(idat))
    stride = w * bpp
    rows, prev = [], bytearray(stride)
    p = 0
    for _ in range(h):
        f = raw[p]
        cur = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif f == 2:
            cur = bytearray((a + b) & 255 for a, b in zip(cur, prev))
        elif f == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[i] = (cur[i] + pr) & 255
        rows.append(cur)
        prev = cur
    return w, h, bpp, rows


def _png_encode(w: int, h: int, rows) -> bytes:
    """rows = 每列 RGB bytes（w*3）"""
    raw = b''.join(b'\x00' + bytes(r) for r in rows)
    def ck(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + ck(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + ck(b'IDAT', zlib.compress(raw, 6)) + ck(b'IEND', b'')


def prepare(png: bytes, box: tuple | None = None, width: int | None = None) -> bytes:
    """box = (x, y, w, h) 裁切（原圖座標）；width = 縮到這個寬（等比，最近鄰取樣）。有 PIL 就用 PIL。
    失敗丟例外，由呼叫端決定（_shot_bytes 會轉成 None）"""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert('RGB')
        if box:
            im = im.crop((box[0], box[1], box[0] + box[2], box[1] + box[3]))
        if width and im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        b = io.BytesIO()
        im.save(b, 'PNG')
        return b.getvalue()
    except ImportError:
        pass
    w, h, bpp, rows = _png_decode(png)
    x0, y0, bw, bh = box if box else (0, 0, w, h)
    x0, y0 = max(0, x0), max(0, y0)
    bw, bh = min(bw, w - x0), min(bh, h - y0)
    sub = [bytes(r[x0 * bpp:(x0 + bw) * bpp]) for r in rows[y0:y0 + bh]]
    if bpp == 4:      # RGBA → RGB
        sub = [b''.join(r[i:i + 3] for i in range(0, len(r), 4)) for r in sub]
    if width and bw > width:
        nh = round(bh * width / bw)
        xs = [int((i + 0.5) * bw / width) * 3 for i in range(width)]
        out = []
        for j in range(nh):
            src = sub[min(bh - 1, int((j + 0.5) * bh / nh))]
            out.append(b''.join(src[x:x + 3] for x in xs))
        return _png_encode(width, nh, out)
    return _png_encode(bw, bh, sub)


# ---------------- 高階介面 ----------------
SCENE_ADOPT = 0.85
TRACK_ADOPT = 0.9
# 驗證視窗警報門檻（高信心才停手）：原本 0.05 太敏感——2026-10-10 14:03 真實的「單人一般戰鬥下指令畫面」就給 0.105 而誤停；
# 實驗（notes/clef-eval.md）21 張非驗證畫面最大 0.02，加上這張戰鬥圖 0.105，所以取 0.6。
# 低於門檻不是放行：quest.py 當成「不認得」繼續累計（連續 3 次且滿 UNKNOWN_CONFIRM_SECS 秒照舊停手，鐵則 5 不削弱）。
VERIFY_ALARM = 0.6


def classify_scene(png: bytes) -> dict | None:
    """png = 遊戲視窗截圖（原樣 1440x830；內部縮 960 寬後上傳）。
    回傳 {'scene': 場景或 None, 'p': 機率, 'model': 模型, 'verify_p': 驗證視窗機率最大值, 'alarm': bool}；
    scene 為 None = 信心不足（呼叫端維持 unknown 流程）；整個失敗回 None。
    先 Clef-flash，top < 0.85 升級 Clef 複核；verify >= VERIFY_ALARM（0.6）在任一次呼叫出現就 alarm（只增不減）。"""
    if not available():
        return None
    try:
        img = prepare(png, width=960)
    except Exception as e:
        _logger(f'Clef：截圖前處理失敗（{type(e).__name__}），退回原流程')
        return None
    qs = {'scene': {'type': 'choice', 'instructions': '這張是遊戲截圖，現在畫面屬於哪一種？', 'criteria': SCENES}, 'verify': VERIFY_Q}
    res = {'scene': None, 'p': 0.0, 'model': '', 'verify_p': 0.0, 'alarm': False}
    for model in ('clef-flash', 'clef'):
        ans = run(model, SCENE_STATE, qs, [img])
        top = _top(ans, 'scene')
        if top is None:
            if res['model']:
                break                 # 已有 flash 結果，升級失敗就維持 flash 的結論
            return None
        v = _noul(ans, 'verify') or 0.0
        res['verify_p'] = max(res['verify_p'], v)
        res['model'], res['p'], scene = model, top[1], top[0]
        if top[1] >= SCENE_ADOPT:
            res['scene'] = scene
            break
    res['alarm'] = res['verify_p'] >= VERIFY_ALARM or res['scene'] == '答題或驗證視窗'
    return res


def check_track_top(png: bytes, want: str, known: list | None = None) -> bool | None:
    """png = 原圖截圖（1440x830）；裁左側追蹤區問「最上面一格標題是不是 want」。
    回傳 True = 標題是 want 且 choice 與 noul 機率都 >= 0.9（呼叫端可直接點第一格）；
    False = 不確定或不是（呼叫端退回 OCR / 樣板掃描）；None = Clef 不可用 / 失敗。"""
    if not available():
        return None
    try:
        img = prepare(png, box=(TRACK_BOX[0], TRACK_BOX[1], TRACK_BOX[2] - TRACK_BOX[0], TRACK_BOX[3] - TRACK_BOX[1]))
    except Exception as e:
        _logger(f'Clef：追蹤區裁切失敗（{type(e).__name__}），退回原流程')
        return None
    cands = list(dict.fromkeys([want] + [k for k in (known or []) if k] + [NO_TASK]))
    qs = {'title': {'type': 'choice', 'instructions': '圖中任務追蹤欄最上面一格的任務標題是哪一個？', 'criteria': {c: c for c in cands}},
          'is_want': {'type': 'noul', 'instructions': f'任務追蹤欄最上面一格的標題是「{want}」嗎？'}}
    ans = run('clef-flash', '遊戲左側任務追蹤欄的裁切圖。', qs, [img])
    top, nu = _top(ans, 'title'), _noul(ans, 'is_want')
    if top is None or nu is None:
        return None if ans is None else False
    return top[0] == want and top[1] >= TRACK_ADOPT and nu >= TRACK_ADOPT
