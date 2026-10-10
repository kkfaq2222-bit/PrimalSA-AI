#!/usr/bin/env python3
"""ocr.ps1 / stat.ps1 二值化（LockBits 版）與舊 GetPixel 版逐位元組比對（離線，不碰遊戲）。
實際工作在 test_binarize.ps1；樣本圖用 tools/.cache 裡的 gui shot 截圖（有就多比幾張）。
用法：uv run --no-project python tools/gui/test_binarize.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winenv  # noqa: E402

CACHE = Path(__file__).resolve().parents[1] / '.cache'
samples = [str(winenv.to_windows(p)) for p in sorted(CACHE.glob('*.png'))[:4]]
r = winenv.run_ps('test_binarize.ps1', *samples, timeout=600)
print(r.stdout, end='')
if r.stderr.strip():
    print(r.stderr, file=sys.stderr)
sys.exit(r.returncode)
