#!/usr/bin/env python3
"""多客戶端（多視窗）識別與每視窗狀態資料夾（只用標準函式庫）。

選視窗：環境變數 PSA_EXE_MATCH（沿用 gui.ps1 / psaclient.ps1 的同一個變數），值可以是
  - 帳號代號（tools/.cache/clients.json 對照，例 {"kkfaq11111": "gameClient", "kkfaq22222": "PrimalSA222"}）
  - 客戶端資料夾名（= 程序所在資料夾，例 PrimalSA222）
沒設定 = 主視窗（第一個 PrimalSA 程序）。

狀態資料夾：
  主視窗              → tools/.cache/（沿用原路徑）
  其他視窗 <資料夾名> → tools/.cache/clients/<資料夾名>/
只有跟帳號無關的樣板 / 圖庫（例 tools/.cache/ 底下的 OCR 樣板）放共用資料夾；
停手旗標、鎖檔、進度檔一律用 state_dir()。

用法：
  import clients
  clients.name()          # 'PrimalSA222' / None（主視窗）
  clients.state_dir()     # Path，會自動建立
  clients.state_file('netwatch.halt')
命令列：
  uv run --no-project python tools/gui/clients.py          印目前視窗名稱與狀態資料夾
退出碼：0 正常。
"""
import json
import os
import re
import sys
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / '.cache'
CLIENTS_JSON = CACHE / 'clients.json'
ENV = 'PSA_EXE_MATCH'


def _alias() -> dict:
    try:
        d = json.loads(CLIENTS_JSON.read_text(encoding='utf-8-sig'))
        return {str(k): str(v) for k, v in d.items() if v} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def raw() -> str:
    """環境變數原值（空字串 = 主視窗）"""
    return (os.environ.get(ENV) or '').strip()


def name(value: str | None = None) -> str | None:
    """解析成客戶端資料夾名（與 psaclient.ps1 Resolve-PsaClient 同規則）；沒設定回 None（主視窗）"""
    v = raw() if value is None else value.strip()
    if not v:
        return None
    return _alias().get(v, v)


def safe(n: str) -> str:
    """資料夾名只留安全字元（防 ..\\ 之類跳出 cache）"""
    s = re.sub(r'[^0-9A-Za-z_.-]', '_', n).strip('.')
    return s or '_'


def state_dir(value: str | None = None, create: bool = True) -> Path:
    n = name(value)
    d = CACHE if n is None else CACHE / 'clients' / safe(n)
    if create:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return d


def state_file(fname: str, value: str | None = None) -> Path:
    return state_dir(value) / fname


def label(value: str | None = None) -> str:
    """給 log 用的視窗名稱（主視窗 = 'main'）；是資料夾名，不是帳號"""
    return name(value) or 'main'


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')     # Windows 原生預設 cp950
    except (AttributeError, ValueError):
        pass
    print(f'{ENV}={raw() or "（未設定，主視窗）"} → {label()} → {state_dir(create=False)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
