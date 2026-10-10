#!/usr/bin/env python3
"""進度紀錄：把「哪一組、做了什麼、結果」追加到 notes/progress.md（只用標準函式庫；notes/ 不進 git）。

目的：刪掉對話後，隔天仍能從檔案看出做到哪（quest.py 結束、levelwatch 達標都會自動寫一行）。
用法（專案根目錄）：
  uv run --no-project python tools/gui/progress.py add "玄黃洞窟 第 4 步 威爾 對話完成"     # 手動補一行
  uv run --no-project python tools/gui/progress.py show [N]                                # 看最後 N 行（預設 20）
程式用：import progress; progress.add('文字'); progress.add_run('quest.py', sys.argv[1:], rc)
客戶端 = PSA_EXE_MATCH 經 winenv.resolve_client 換成資料夾名（沒設 = '-'）。不寫帳號 / 密碼。
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import winenv  # noqa: E402

FILE = HERE.parents[1] / 'notes' / 'progress.md'
HEADER = '# 進度紀錄（notes/ 不進 git；每行：時間 [客戶端] 內容）\n\n'


def add(msg: str, client: str | None = None, path: Path | None = None) -> bool:
    """追加一行；寫不進去回 False（不丟例外，不能讓紀錄拖垮主流程）"""
    f = path or FILE
    c = client if client is not None else (winenv.resolve_client() or '-')
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        new = not f.exists()
        with open(f, 'a', encoding='utf-8') as fh:
            if new:
                fh.write(HEADER)
            fh.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} [{c}] {msg}\n')
        return True
    except OSError:
        return False


def add_run(tool: str, argv: list[str], rc: int | None, path: Path | None = None) -> bool:
    """腳本結束時記一行：工具、參數、退出碼（None = 例外 / 被中斷）"""
    res = '異常中斷' if rc is None else f'退出碼 {rc}'
    return add(f'{tool} {" ".join(argv)} → {res}', path=path)


def tail(n: int = 20, path: Path | None = None) -> list[str]:
    f = path or FILE
    try:
        return f.read_text(encoding='utf-8').splitlines()[-n:]
    except OSError:
        return []


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if len(a) >= 2 and a[0] == 'add':
        return 0 if add(' '.join(a[1:])) else 1
    if a and a[0] == 'show':
        for ln in tail(int(a[1]) if len(a) > 1 and a[1].isdigit() else 20):
            print(ln)
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
