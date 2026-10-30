# -*- coding: utf-8 -*-
"""纯 CPU 的几何/聚类单测，不需要 GPU、权重或 ffmpeg。

跑法（在已经 setup 过的环境里）：
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pplib.detect import _cluster, crop_geom, union_box  # noqa: E402


class CropGeomTest(unittest.TestCase):
    def test_size_is_multiple_of_8(self):
        x, y, w, h = crop_geom((100, 50, 200, 80), 1920, 1080, 0.45)
        self.assertEqual(w % 8, 0)
        self.assertEqual(h % 8, 0)

    def test_inside_frame(self):
        for box in ((100, 50, 200, 80), (0, 0, 300, 100), (1600, 900, 300, 150)):
            x, y, w, h = crop_geom(box, 1920, 1080, 0.45)
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertLessEqual(x + w, 1920)
            self.assertLessEqual(y + h, 1080)

    def test_min_size_is_128(self):
        x, y, w, h = crop_geom((10, 10, 20, 10), 1920, 1080, 0.45)
        self.assertGreaterEqual(w, 128)
        self.assertGreaterEqual(h, 128)

    def test_right_bottom_edge_is_clamped(self):
        x, y, w, h = crop_geom((1900, 1060, 20, 20), 1920, 1080, 0.45)
        self.assertLessEqual(x + w, 1920)
        self.assertLessEqual(y + h, 1080)

    def test_tiny_video(self):
        x, y, w, h = crop_geom((0, 0, 10, 10), 64, 64, 0.45)
        self.assertLessEqual(x + w, 64)
        self.assertLessEqual(y + h, 64)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_zero_padding(self):
        # 宽高都 >= 128 时不会被强制放大，原样返回
        x, y, w, h = crop_geom((128, 128, 200, 200), 640, 480, 0.0)
        self.assertEqual((x, y), (128, 128))
        self.assertEqual((w, h), (200, 200))

    def test_min_size_expands_around_box(self):
        # 小于 128 的框会被居中撑到 128，并保持在画面内
        x, y, w, h = crop_geom((128, 128, 64, 64), 640, 480, 0.0)
        self.assertEqual((x, y, w, h), (96, 96, 128, 128))


class UnionBoxTest(unittest.TestCase):
    def test_union(self):
        self.assertEqual(union_box([(10, 10, 20, 30), (50, 40, 10, 10)]), (10, 10, 50, 40))

    def test_single(self):
        self.assertEqual(union_box([(5, 6, 7, 8)]), (5, 6, 7, 8))


class ClusterTest(unittest.TestCase):
    def test_grouping(self):
        cands = [(0, (10, 10, 100, 20)),
                 (1, (11, 10, 100, 20)),
                 (2, (500, 300, 100, 20))]
        groups = _cluster(cands, tol=20)
        self.assertEqual(len(groups), 2)
        sizes = sorted(len(g["items"]) for g in groups)
        self.assertEqual(sizes, [1, 2])

    def test_empty(self):
        self.assertEqual(_cluster([], tol=10), [])


if __name__ == "__main__":
    unittest.main()
