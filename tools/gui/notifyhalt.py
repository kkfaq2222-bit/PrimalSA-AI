#!/usr/bin/env python3
"""停手 / 完成時通知使用者（只用標準函式庫）：系統提示音 + 視窗標題改成原因（工作列會閃）。不改遊戲、不送任何網路請求。"""
import sys
import time


def set_title(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text[:200])
    except Exception:
        pass


def beep(n: int = 3) -> None:
    try:
        import winsound
        for _ in range(n):
            winsound.Beep(880, 250)
            time.sleep(0.1)
    except Exception:
        sys.stdout.write('\a' * n)
        sys.stdout.flush()


def alert(msg: str, ok: bool = False) -> None:
    """ok=True：正常結束（短提示音）；False：停手 / 例外（三聲）"""
    set_title(('完成：' if ok else '停手：') + msg)
    beep(1 if ok else 3)


def clear_title() -> None:
    set_title('')
