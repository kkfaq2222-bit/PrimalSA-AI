"""Clef / Clef-flash（Cloudflare Workers AI）呼叫小程式（只用標準函式庫）。

認證：wrangler 已登入的 OAuth token（~/.config/.wrangler/config/default.toml，scope 含 ai write）。
token 只在程序內讀取、放進 Authorization header，不印出、不寫檔。
（wrangler dev --remote 需要先註冊 workers.dev 子網域，所以改走 REST。）
過期時先跑一次 `npx --yes wrangler@4 whoami` 讓 wrangler 自動更新 token。
"""
import base64, io, json, os, re, subprocess, time, urllib.request, urllib.error

ACCOUNT = 'REDACTED-CF-ACCOUNT-ID'  # 來自 wrangler whoami（非機密）
MODELS = {'clef': '@cf/cloudflare/clef', 'clef-flash': '@cf/cloudflare/clef-flash'}


def _token():
    p = os.path.expanduser('~/.config/.wrangler/config/default.toml')
    m = re.search(r'oauth_token\s*=\s*"([^"]+)"', open(p, encoding='utf-8').read())
    return m.group(1)


def run(model, state, questions, images=None):
    """回傳 (端到端秒數, 解析後 JSON)。images = PNG/JPEG bytes 清單（最多 4 張）。"""
    body = {'model': model, 'state': state, 'questions': questions}
    if images:
        body['images'] = ['data:image/png;base64,' + base64.b64encode(b).decode() for b in images]
    req = urllib.request.Request(
        f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{MODELS[model]}',
        data=json.dumps(body).encode(), method='POST',
        headers={'Authorization': 'Bearer ' + _token(), 'Content-Type': 'application/json'})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        out = {'http_error': e.code, 'body': e.read().decode()[:600]}
    return time.time() - t, out
