#!/usr/bin/env python3
"""遊戲畫面即時預覽（只讀）：每 N 秒截一張圖 → 本機網頁自動刷新顯示。只綁 127.0.0.1，不上傳。

用法：uv run --no-project python tools/gui/livemirror.py --client kkfaq11111 [--every 2] [--port 8765]
然後開 http://127.0.0.1:8765/ 。Ctrl+C 結束。
只做截圖（gui shot），不點擊、不按鍵；截圖存 tools/.cache/livemirror-<client>.png。
"""
import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CACHE = HERE.parents[1] / 'tools' / '.cache'

PAGE = """<!doctype html><meta charset="utf-8"><title>遊戲畫面</title>
<style>html,body{margin:0;background:#111;color:#ccc;font:14px sans-serif}
img{width:100%;height:auto;display:block}#t{padding:4px 8px}</style>
<div id="t">%CLIENT% · 每 %EVERY% 秒更新 · <span id="s">載入中</span></div><img id="i">
<script>
const img=document.getElementById('i'), s=document.getElementById('s');
function tick(){const u='/live.png?t='+Date.now();const n=new Image();
 n.onload=()=>{img.src=u;s.textContent=new Date().toLocaleTimeString()};
 n.onerror=()=>{s.textContent='讀不到截圖'};n.src=u}
tick();setInterval(tick,%MS%);
</script>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--client', default=os.environ.get('PSA_EXE_MATCH', 'kkfaq11111'))
    ap.add_argument('--every', type=float, default=2.0)
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    os.environ['PSA_EXE_MATCH'] = a.client
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import winenv
    winenv.enable_server()
    import uikit
    name = f'livemirror-{a.client}.png'
    path = CACHE / name

    def grab():
        while True:
            try:
                uikit.gui('shot', name)
            except Exception as e:           # 遊戲忙 / 最小化：略過這一張
                print('截圖失敗：', str(e)[:80], flush=True)
            time.sleep(a.every)

    threading.Thread(target=grab, daemon=True).start()
    html = PAGE.replace('%CLIENT%', a.client).replace('%EVERY%', str(a.every)).replace('%MS%', str(int(a.every * 1000))).encode('utf-8')

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith('/live.png'):
                try:
                    data = path.read_bytes()
                except OSError:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html)

    srv = ThreadingHTTPServer(('127.0.0.1', a.port), H)
    print(f'畫面預覽：http://127.0.0.1:{a.port}/ （Ctrl+C 結束）', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
