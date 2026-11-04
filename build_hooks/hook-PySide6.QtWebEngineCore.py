# -*- coding: utf-8 -*-
"""覆盖 PyInstaller 自带的 `hook-PySide6.QtWebEngineCore.py`：收集完再**过滤**。

背景：v3.4.0 把 JIZURA 引擎做成视觉歌词面板，引入了 QtWebEngine。官方 hook 会把
Chromium 的全套资源原样收进包里 —— devtools 调试资源（debug 73MB + release 12MB）、
各 pak 的 `.debug` 副本（2.5MB）、以及 48 种语言的 locale（44MB）。

但这套 Chromium 在本项目里只干一件事：在 `<canvas>` 上画一块歌词面板。
不开 devtools（没接 `--remote-debugging-port`）、不显示 Chromium 自带 UI
（页面用 `visibility:hidden` 藏了）、不加载任何网页。上面那些资源一个都用不上。

实测（PySide6 6.12 / Qt 6.12）：把这些资源移走之后，面板渲染逐帧正常
（歌词 / 逐字高亮 / HUD / 圆形封面全在），onefile 从 288MB 降到约 160MB。

**为什么要手工展开目录**：`collect_qtwebengine_files()` 在 Windows 上返回的是
「整目录」条目 `(src_dir, dest_dir)`，PyInstaller 在 TOC 展开阶段才把目录里的文件
逐个收进来。直接对条目做过滤，要么整目录保留（devtools 全在），要么整目录删掉
（连 zh-CN 都没了）—— 第一版就是这么踩的，产物 277MB 且没有任何语言包。

维护提示：如果哪天真的要接 devtools 或 Chromium 自带 UI（比如做网页视图），
把下面 `_KEEP_LOCALES` 与 devtools 那两条判断去掉，别在别处打补丁。
"""
import os

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

if pyside6_library_info.version is not None:
    webengine_binaries, webengine_datas = pyside6_library_info.collect_qtwebengine_files()
    binaries += webengine_binaries
    datas += webengine_datas
    hiddenimports += ['PySide6.QtPrintSupport']

# 只留中英（含繁体）：面板没有 Chromium 自带文案，locale 只影响极少数错误页。
_KEEP_LOCALES = {'zh-CN.pak', 'zh-TW.pak', 'en-US.pak', 'en-GB.pak'}


def _unused_file(name: str, in_locales: bool) -> bool:
    if 'qtwebengine_devtools_resources' in name:      # devtools 整块不要
        return True
    if name.endswith('.debug.pak') or name.endswith('.debug.bin'):
        return True                                    # 调试符号资源
    return in_locales and name not in _KEEP_LOCALES


def _expand(items):
    """目录条目展开成逐文件条目，顺路过滤。"""
    out = []
    for src, dest in items:
        dest = (dest or '').replace('\\', '/')
        in_locales = 'qtwebengine_locales' in dest
        if os.path.isdir(src):
            for root, _dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                target = dest if rel == '.' else os.path.join(dest, rel)
                for fname in files:
                    if _unused_file(fname, in_locales):
                        continue
                    out.append((os.path.join(root, fname), target))
        elif not _unused_file(os.path.basename(src), in_locales):
            out.append((src, dest))
    return out


_before = len(datas)
datas = _expand(datas)
print("[hook] QtWebEngine 资源条目 %d -> %d（devtools / 调试 pak / 多余语言包已裁掉）"
      % (_before, len(datas)))
