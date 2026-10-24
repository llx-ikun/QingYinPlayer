# -*- coding: utf-8 -*-
"""app.queue 播放队列单元测试（纯逻辑）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import MODE_LOOP, MODE_SEQUENTIAL, MODE_SINGLE, MODE_SHUFFLE
from app.queue import PlayQueue

IDS = ["a", "b", "c", "d"]


class TestPlayQueue(unittest.TestCase):
    def test_loop_wraps(self):
        q = PlayQueue(IDS, 3, MODE_LOOP)
        self.assertEqual(q.next(), "a")  # 4 -> 1 循环
        self.assertEqual(q.next(), "b")
        self.assertEqual(q.previous(), "a")  # 回绕到末尾
        self.assertEqual(q.previous(), "d")

    def test_sequential_stops_at_end(self):
        q = PlayQueue(IDS, 2, MODE_SEQUENTIAL)
        self.assertEqual(q.next(), "d")
        self.assertIsNone(q.next())          # 播完停止
        self.assertEqual(q.current, "d")     # 停在最后播放的一首
        q2 = PlayQueue(IDS, 0, MODE_SEQUENTIAL)
        self.assertEqual(q2.previous(), "a")  # 首曲再上一首 = 停在首曲

    def test_single_replays_on_auto(self):
        q = PlayQueue(IDS, 1, MODE_SINGLE)
        self.assertEqual(q.next(auto=True), "b")   # 自动结束 -> 重播当前
        self.assertEqual(q.current, "b")
        self.assertEqual(q.next(auto=False), "c")  # 手动下一首 -> 正常前进

    def test_shuffle_permutation_and_cycle(self):
        q = PlayQueue(IDS, 0, MODE_SHUFFLE)
        self.assertEqual(sorted(q.ids), sorted(IDS))     # 是排列
        self.assertEqual(q.ids[0], "a")                   # 从当前曲开始
        seen = {q.current}
        for _ in range(len(IDS) - 1):
            nxt = q.next()
            self.assertIsNotNone(nxt)
            seen.add(nxt)
        self.assertEqual(seen, set(IDS))                  # 一轮内不重复
        nxt = q.next()                                    # 播完重新洗牌
        self.assertIn(nxt, IDS)

    def test_jump_to(self):
        q = PlayQueue(IDS, 0, MODE_SEQUENTIAL)
        self.assertTrue(q.jump_to("c"))
        self.assertEqual(q.current, "c")
        self.assertFalse(q.jump_to("不在队列里的id"))
        self.assertEqual(q.current, "c")

    def test_jump_to_in_shuffle_plays_picked_first(self):
        q = PlayQueue(IDS, 0, MODE_SHUFFLE)
        q.jump_to("d")
        self.assertEqual(q.current, "d")
        self.assertEqual(q.ids[0], "d")
        self.assertEqual(sorted(q.ids), sorted(IDS))

    def test_set_mode_to_shuffle_reorders(self):
        q = PlayQueue(IDS, 1, MODE_SEQUENTIAL)
        q.set_mode(MODE_SHUFFLE)
        self.assertEqual(q.current, "b")
        self.assertEqual(q.ids[0], "b")

    def test_set_ids_resets(self):
        q = PlayQueue(IDS, 2, MODE_LOOP)
        q.set_ids(["x", "y"], 1)
        self.assertEqual(q.current, "y")
        self.assertEqual(len(q), 2)

    def test_empty_queue(self):
        q = PlayQueue([], 0, MODE_LOOP)
        self.assertIsNone(q.current)
        self.assertIsNone(q.next())
        self.assertIsNone(q.previous())
        self.assertEqual(len(q), 0)

    def test_len_and_ids_snapshot(self):
        q = PlayQueue(IDS, 0, MODE_LOOP)
        self.assertEqual(len(q), 4)
        snapshot = q.ids
        q.next()
        self.assertEqual(snapshot, IDS)  # ids 返回副本，不受后续操作影响


if __name__ == "__main__":
    unittest.main()
