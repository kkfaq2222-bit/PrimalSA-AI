#!/usr/bin/env python3
"""failshot 離線測試：保留規則、pre → shot 沿用改名、記錄與 stats 對圖、測試環境不拍"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import failshot  # noqa: E402


class FailshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.saved = (failshot.ROOT, failshot.FAIL_DIR, failshot.LOG, failshot.enabled, failshot._grab)
        failshot.ROOT = root
        failshot.FAIL_DIR = root / 'tools' / '.cache' / 'fail'
        failshot.LOG = root / 'tools' / '.cache' / 'stats-fail.jsonl'
        failshot.FAIL_DIR.mkdir(parents=True)
        failshot.enabled = lambda: True
        self.grabs = []

        def grab(p):
            self.grabs.append(p)
            p.write_bytes(b'png')
            return True
        failshot._grab = grab
        failshot._pending = None

    def tearDown(self):
        failshot.ROOT, failshot.FAIL_DIR, failshot.LOG, failshot.enabled, failshot._grab = self.saved
        failshot._pending = None
        self.tmp.cleanup()

    def test_disabled_under_unittest(self):
        self.assertFalse(self.saved[3]())

    def test_norm_groups_numbers(self):
        self.assertEqual(failshot.key('退出碼 7：第 3 頁'), failshot.key('退出碼 8：第 12 頁'))
        self.assertNotEqual(failshot.key('傳送後沒出現 NPC 對話窗'), failshot.key('任務詳情面板開不起來'))

    def test_prune_per_reason_and_total(self):
        for i in range(5):
            (failshot.FAIL_DIR / f'20261015-1000{i:02d}-q-aaaaaaaa.png').write_bytes(b'x')
        for i in range(2):
            (failshot.FAIL_DIR / f'20261015-1100{i:02d}-q-bbbbbbbb.png').write_bytes(b'x')
        self.assertEqual(failshot.prune(per_reason=3, total=4), 3)
        left = sorted(f.name for f in failshot.FAIL_DIR.glob('*.png'))
        # 新到舊：b 兩張先留，a 每原因上限 3 但總量上限 4 → a 只剩最新 2 張
        self.assertEqual(left, ['20261015-100003-q-aaaaaaaa.png', '20261015-100004-q-aaaaaaaa.png',
                                '20261015-110000-q-bbbbbbbb.png', '20261015-110001-q-bbbbbbbb.png'])

    def test_shot_records_line(self):
        p = failshot.shot('questflow', '退出碼 7：傳送後沒出現 NPC 對話窗')
        self.assertTrue(p.startswith('tools/.cache/fail/'))
        d = json.loads(failshot.LOG.read_text(encoding='utf-8').strip())
        self.assertEqual((d['src'], d['shot']), ('questflow', p))

    def test_pre_then_shot_reuses_and_renames(self):
        pre = failshot.pre('questflow')
        p = failshot.shot('questflow', '退出碼 7：傳送後沒出現 NPC 對話窗')
        self.assertEqual(len(self.grabs), 1)                         # 沒重拍
        self.assertNotEqual(pre, p)
        self.assertTrue(p.endswith(failshot.key('退出碼 7：傳送後沒出現 NPC 對話窗') + '.png'))
        self.assertTrue((failshot.ROOT / p).exists())

    def test_recent_dedup(self):
        a = failshot.shot('questflow', '退出碼 7：x')
        b = failshot.shot('fullrun', '[quests] 退出碼 7 → 停手')
        self.assertEqual(a, b)
        self.assertEqual(len(self.grabs), 1)
        self.assertEqual(len(failshot.LOG.read_text(encoding='utf-8').splitlines()), 2)

    def test_latest_by_reason(self):
        failshot.shot('questflow', '退出碼 7：傳送後沒出現 NPC 對話窗')
        m = failshot.latest_by_reason()
        self.assertIn('退出碼 #：傳送後沒出現 NPC 對話窗', m)


if __name__ == '__main__':
    unittest.main()
