#!/usr/bin/env python3
"""hero1920 鏈資料離線測試：uv run --no-project python tools/gui/test_hero.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hero1920 as h  # noqa: E402


def main() -> int:
    rows = h.load_rows()
    chain = h.simulate(rows)
    assert len(chain) == 132, len(chain)
    assert chain[-1]['name'] == '路普勒斯' and chain[-1]['to'][0] == 1000
    bosses = [i for i, r in enumerate(chain, 1) if r['need']]
    assert bosses == [20, 40, 60, 80, 100, 120, 132], bosses
    assert len({r['id'] for r in chain}) == 132
    # 每一步落點都要在下一隻附近（鏈沒斷）
    for a, b in zip(chain, chain[1:]):
        if a['to'][0] == b['map']:
            assert h.dist(a['to'][1:], (b['x'], b['y'])) <= 30, (a['name'], b['name'])
    assert h.pick_next(rows, set(), (8210, 200, 30))['name'] == '守靈者121'
    assert h.pick_next(rows, {3261}, (8210, 203, 69))['name'] == '守靈者122'
    assert (h.stand_candidates((10, 10))[0][0] - 10) ** 2 + (h.stand_candidates((10, 10))[0][1] - 10) ** 2 <= 2
    print('test_hero OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
