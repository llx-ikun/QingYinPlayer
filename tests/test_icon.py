# -*- coding: utf-8 -*-
"""应用图标回归测试：确保 app.ico 是规范、可被 Windows 任务栏/标题栏加载的 PNG-ICO。

背景：v2.1 后用户反映「软件打开的图标」显示为「图片找不到」占位符。
根因是 generate_icon 把 PNG 写进 ICO 时目录项填了 planes=1/bitcount=32，
违反 ICO 规范（PNG 压缩图像这两项必须为 0）。资源管理器常容忍，但任务栏/
标题栏图标加载器更严格会拒绝加载，窗口图标因此退化成占位符。
本测试固化规范，防止复发。
"""
from __future__ import annotations

import os
import struct
import unittest

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QIcon

import build


def setUpModule() -> None:
    if QGuiApplication.instance() is None:
        QGuiApplication([])


class TestAppIcon(unittest.TestCase):
    def test_generate_produces_spec_compliant_ico(self) -> None:
        path = build.generate_icon()
        self.assertTrue(os.path.exists(path), "图标文件应已生成")
        with open(path, "rb") as f:
            data = f.read()
        reserved, typ, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, typ), (0, 1), "ICO 头应为 reserved=0, type=1")

        off = 6
        for i in range(count):
            w, h, _colors, _res, planes, bitcount, _size, dataoff = struct.unpack(
                "<BBBBHHII", data[off:off + 16])
            with self.subTest(entry=i, dims=f"{w}x{h}"):
                # PNG 压缩图像：planes/bitcount 必须为 0，否则任务栏/标题栏拒绝加载
                self.assertEqual(planes, 0, f"条目 {i} planes 必须为 0（PNG 规范）")
                self.assertEqual(bitcount, 0, f"条目 {i} bitcount 必须为 0（PNG 规范）")
                # 图像数据必须是 PNG 签名
                self.assertEqual(data[dataoff:dataoff + 4], b"\x89PNG", f"条目 {i} 数据应为 PNG")
            off += 16
        # 7 个尺寸（16/24/32/48/64/128/256），256 用 dim=0 表示
        self.assertEqual(count, 7)

    def test_qicon_loads_all_sizes(self) -> None:
        path = build.generate_icon()
        icon = QIcon(path)
        sizes = icon.availableSizes()
        self.assertEqual(len(sizes), 7, "QIcon 应能加载全部 7 个尺寸")
        pm = icon.pixmap(QSize(256, 256))
        self.assertFalse(pm.isNull(), "256 尺寸应可渲染为非空 pixmap")
        self.assertEqual(pm.width(), 256)

    def test_icon_resolves_at_runtime(self) -> None:
        # main._resolve_app_icon 在开发态应能用本地 assets/app.ico
        import main as app_main
        path = app_main._resolve_app_icon()
        self.assertIsNotNone(path, "开发态应能定位 assets/app.ico")
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
