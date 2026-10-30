# -*- coding: utf-8 -*-
"""界面队列逻辑单测（不依赖 Qt）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.queue import (STATUS_DONE, STATUS_PENDING, JobQueue,  # noqa: E402
                            QueueItem)
from pplib.const import MAX_QUEUE  # noqa: E402


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ppq_")

    def _mk(self, name):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as fh:
            fh.write(b"0")
        return p

    def test_cap_is_20(self):
        self.assertEqual(MAX_QUEUE, 20)
        q = JobQueue()
        paths = [self._mk("v%02d.mp4" % i) for i in range(25)]
        added, rejected = q.add_paths(paths)
        self.assertEqual(len(added), 20)
        self.assertEqual(len(q), 20)
        self.assertEqual(len(rejected), 5)
        self.assertTrue(q.full)

    def test_dedupe(self):
        p = self._mk("a.mp4")
        q = JobQueue()
        q.add_paths([p])
        added, _ = q.add_paths([p])
        self.assertEqual(added, [])
        self.assertEqual(len(q), 1)

    def test_reject_non_video(self):
        bad = self._mk("note.txt")
        q = JobQueue()
        added, rejected = q.add_paths([bad])
        self.assertEqual(added, [])
        self.assertTrue(any("不支持" in why for _, why in rejected))

    def test_next_pending_and_reset(self):
        a, b = self._mk("a.mp4"), self._mk("b.mp4")
        q = JobQueue()
        q.add_paths([a, b])
        self.assertEqual(q.next_pending_index(), 0)
        q[0].status = STATUS_DONE
        self.assertEqual(q.next_pending_index(), 1)
        q[1].status = STATUS_DONE
        self.assertIsNone(q.next_pending_index())
        q.reset()
        self.assertEqual(q.next_pending_index(), 0)
        self.assertEqual(q[0].pct, 0.0)

    def test_remove(self):
        a = self._mk("a.mp4")
        q = JobQueue()
        q.add_paths([a])
        self.assertIsNotNone(q.remove(0))
        self.assertEqual(len(q), 0)
        self.assertIsNone(q.remove(5))


class QueueItemTest(unittest.TestCase):
    def test_name(self):
        it = QueueItem(path=os.path.join("D:\\", "videos", "测试.mp4"))
        self.assertEqual(it.name, "测试.mp4")
        self.assertEqual(it.status, STATUS_PENDING)


if __name__ == "__main__":
    unittest.main()
