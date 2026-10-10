#!/usr/bin/env python3
"""PNG 解碼（純標準函式庫）：遊戲截圖是 8 bit RGB / RGBA、非交錯，支援 filter 0～4。
純標準函式庫 PNG 解碼（watch 與 fixture 取像素用）。"""
import struct
import zlib


def decode(data: bytes):
    """→ (w, h, bpp, rows)；rows 是每列 bytearray（w*bpp，bpp = 3 或 4）"""
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


def pixels(rows, bpp: int, pts) -> dict:
    """取 pts = [(x, y), ...] 的 (r, g, b)；座標越界會丟 IndexError"""
    return {(x, y): tuple(rows[y][x * bpp:x * bpp + 3]) for x, y in pts}
