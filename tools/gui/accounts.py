#!/usr/bin/env python3
"""每視窗帳號對照（只用標準函式庫）。給斷線重登在「多視窗」時把帳號欄改回本視窗的帳號用。

設定檔：tools/gui/accounts.local.json（本機檔，.gitignore 已排除，絕不 commit；PSA_ACCOUNTS_FILE 可改路徑，測試用）
  {"gameClient": "帳號A", "PrimalSA222": "帳號B"}
  鍵 = 客戶端資料夾名（= PSA_EXE_MATCH 解析後的名字）或代號（clients.json 的鍵）；值 = 帳號字串。
  **只放帳號，不放密碼**：密碼一律由遊戲自己記住，工具絕不讀、不打、不清密碼欄。

規則：
  - 帳號名不准出現在 log / errlog / actions.log / 截圖檔名 / 例外訊息 / 本工具輸出；只能印「有沒有設定」與長度。
  - 真正打字由 gui.ps1 typeacct 自己讀這個檔案（帳號不經 Python、不進命令列參數）；本模組只做檢查。

用法：
  uv run --no-project python tools/gui/accounts.py check    列出哪些視窗有設定、帳號長度（不印帳號）
命令列退出碼：0 設定檔格式正確（或不存在：視為沒有設定）、1 格式錯誤、2 用法錯誤。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clients  # noqa: E402

DEFAULT_FILE = Path(__file__).resolve().parent / 'accounts.local.json'


class AccountsError(Exception):
    """設定檔讀不到 / 格式錯；訊息只描述問題，不含檔案內容"""


def path() -> Path:
    return Path(os.environ['PSA_ACCOUNTS_FILE']) if os.environ.get('PSA_ACCOUNTS_FILE') else DEFAULT_FILE


def load() -> dict:
    """回 {鍵: 帳號}；檔案不存在回 {}；格式錯丟 AccountsError（訊息不含內容）"""
    f = path()
    if not f.exists():
        return {}
    try:
        d = json.loads(f.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise AccountsError('accounts.local.json 不是合法 JSON') from None   # from None：不帶原例外（可能含檔案片段）
    if not isinstance(d, dict):
        raise AccountsError('accounts.local.json 最外層要是 {"視窗": "帳號"} 物件')
    bad = [k for k, v in d.items() if not isinstance(v, str) or not v.strip()]
    if bad:
        raise AccountsError(f'{len(bad)} 個鍵的值不是非空字串（值只能是帳號字串，不能放密碼物件）')
    return {str(k): v.strip() for k, v in d.items()}


def has_account(value: str | None = None) -> bool:
    """這個視窗（預設 = 目前 PSA_EXE_MATCH）有沒有設定帳號。只回 bool，不回帳號"""
    try:
        d = load()
    except AccountsError:
        return False
    keys = [clients.raw() if value is None else value, clients.name(value)]
    return any(k and k in d for k in keys)


def check_lines() -> list[str]:
    """check 的輸出：每個鍵一行「鍵 → 資料夾名：有設定（N 字）」；不含帳號本身"""
    d = load()
    if not d:
        return [f'{path().name}：沒有設定（檔案不存在或是空的）→ 多視窗時斷線不自動登入，只通知人']
    out = [f'{path().name}：{len(d)} 個視窗有設定']
    for k, v in d.items():
        n = clients.name(k)
        out.append(f'  {k}' + (f'（→ {n}）' if n != k else '') + f'：有設定（{len(v)} 字）')
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding='utf-8')     # Windows 原生預設 cp950
        except (AttributeError, ValueError):
            pass
    if argv != ['check']:
        print('用法：accounts.py check', file=sys.stderr)
        return 2
    try:
        for line in check_lines():
            print(line)
    except AccountsError as e:
        print(f'設定檔錯誤：{e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
