#!/usr/bin/env python3
"""當前角色旁路檔 tools/.cache/current-char.json 的唯一讀寫 API（只用標準函式庫）。

格式 = watch 第 7 階段已定義的 watchstate.write_current_char：{"name": "DKB0", "ts": 1760090000.0, "src": "char.py"}。
本模組只是它的薄包裝（不另寫一套格式 / 原子寫入）；名字一律先過白名單正規化（charname.canon，與 watch 同一套）。
「未知」（例如剛重登，當前會變 DKB05）= 刪掉檔案：watch 沒有旁路時只靠頭頂名牌 OCR。
**只是提示**：使用者可能手動點卡片；點擊依據一律現場讀切換面板（SKILL.md「state 不能當點擊依據」）。

  import charstate
  charstate.write('DKB0', src='char.py')     # 切換 / 組隊（隊長變當前）後
  charstate.read(max_age=60)                 # → {'name','ts','src'} | None（沒有 / 太舊）
  charstate.clear()                          # 重登後當前未知
"""
import time

import charname
import watchstate

DEFAULT_CHARS = ['DKB0', 'DKB02', 'DKB03', 'DKB04', 'DKB05']


def chars() -> list:
    """白名單：watch-config.json 的 chars（不進 git），沒有就用預設五人"""
    c = watchstate.load_config().get('chars')
    return [str(x) for x in c] if isinstance(c, list) and c else list(DEFAULT_CHARS)


def norm_char(text, names=None):
    """OCR 文字 / 手打名字 → 白名單原名；對不上或有歧義 → None。規則就是 charname（O→0、首字 0→D、大寫去空白，完全比對）"""
    return charname.match_texts([text], charname.canon_map(names if names is not None else chars()))


def write(name: str, src: str = 'tool', path=None) -> bool:
    """寫當前角色；名字不在白名單（正規化後）→ 不寫、回 False；寫入失敗也回 False（不影響呼叫端）"""
    hit = norm_char(name)
    if hit is None:
        return False
    return watchstate.write_current_char(hit, src=src, path=path)


def read(max_age=None, path=None, now=time.time):
    """→ {'name','ts','src'} 或 None（沒有檔 / 壞檔 / 超過 max_age 秒）"""
    d = watchstate.read_current_char(path)
    if d is None:
        return None
    if max_age is not None and now() - d['ts'] > max_age:
        return None
    return d


def clear(path=None) -> bool:
    """當前角色未知（重登後）：刪旁路檔；本來就沒有也算成功"""
    try:
        (path or watchstate.CURCHAR_FILE).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True
