#!/usr/bin/env python3
r"""暫停檔：tools/.cache/PAUSE（全部）或 PAUSE-<client>（只暫停那個客戶端）存在 → 腳本在「安全點」停住等待，刪掉就繼續。

安全點 = questflow 步與步之間 / 任務與任務之間、levelwatch 每輪監測開頭（不會停在戰鬥 / 對話 / 補血中途）。
用法：
  tools\gui\pause.cmd [client]      建立暫停檔（不給 client = 全部）
  tools\gui\resume.cmd [client]     刪除暫停檔
程式用：import pausegate; pausegate.wait(log)
"""
import os
import sys
import time
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / '.cache'


def files() -> list[Path]:
    c = os.environ.get('PSA_EXE_MATCH', '').strip()
    out = [CACHE / 'PAUSE']
    if c:
        out.append(CACHE / f'PAUSE-{c}')
    return out


def paused() -> bool:
    return any(p.exists() for p in files())


def wait(log=print, poll_s: float = 2.0) -> float:
    """有暫停檔就停在這裡等到被刪掉；回傳等了幾秒（沒暫停回 0）。"""
    if not paused():
        return 0.0
    t0 = time.time()
    log('已暫停（偵測到暫停檔）：刪除 PAUSE 檔 / 執行 resume.cmd 後繼續')
    while paused():
        time.sleep(poll_s)
    waited = time.time() - t0
    log(f'已繼續（暫停了 {waited:.0f} 秒）')
    return waited


def main(argv=None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if not a or a[0] not in ('on', 'off', 'status'):
        print(__doc__)
        return 2
    target = CACHE / (f'PAUSE-{a[1]}' if len(a) > 1 else 'PAUSE')
    CACHE.mkdir(parents=True, exist_ok=True)
    if a[0] == 'on':
        target.write_text(time.strftime('%F %T'), encoding='utf-8')
        print('已建立', target.name)
    elif a[0] == 'off':
        try:
            target.unlink()
            print('已刪除', target.name)
        except FileNotFoundError:
            print('本來就沒有', target.name)
    else:
        print('暫停中：' + ', '.join(p.name for p in CACHE.glob('PAUSE*')) if list(CACHE.glob('PAUSE*')) else '沒有暫停檔')
    return 0


if __name__ == '__main__':
    sys.exit(main())
