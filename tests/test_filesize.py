# -*- coding: utf-8 -*-
"""文件大小读取与格式化单测（「大小」列 + 按大小排序共用的基础能力）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.filesize import file_size, format_size  # noqa: E402


class TestFormatSize(unittest.TestCase):
    def test_unknown_is_placeholder(self):
        self.assertEqual(format_size(0), "--")
        self.assertEqual(format_size(-1), "--")

    def test_bytes(self):
        self.assertEqual(format_size(1), "1 B")
        self.assertEqual(format_size(512), "512 B")

    def test_kilobytes(self):
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(820 * 1024), "820 KB")   # 三位数取整

    def test_megabytes(self):
        self.assertEqual(format_size(int(8.4 * 1024 * 1024)), "8.4 MB")

    def test_gigabytes(self):
        self.assertEqual(format_size(int(1.2 * 1024 ** 3)), "1.2 GB")

    def test_max_width_fits_column(self):
        """「大小」列固定 56px，最长形态需控制在 7 个字符内。"""
        for size in (1023, 1023 * 1024, 1023 * 1024 ** 2, 999 * 1024 ** 3):
            self.assertLessEqual(len(format_size(size)), 7, format_size(size))


class TestFileSize(unittest.TestCase):
    def test_reads_real_file(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"x" * 4096)
            path = f.name
        try:
            self.assertEqual(file_size(path), 4096)
            self.assertEqual(file_size(path), os.path.getsize(path))
        finally:
            os.unlink(path)

    def test_missing_file_returns_zero(self):
        missing = os.path.join(tempfile.gettempdir(), "轻音-no-such-file.mp3")
        self.assertEqual(file_size(missing), 0)

    def test_empty_path_returns_zero(self):
        self.assertEqual(file_size(""), 0)


if __name__ == "__main__":
    unittest.main()
