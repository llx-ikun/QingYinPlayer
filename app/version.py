# -*- coding: utf-8 -*-
"""应用标识与版本号（v2.7.6 起的单一真相源）。

为什么单独建这个模块：界面里的版本号原本是**硬编码字符串** ——
`ui/main_window.py` 写着 "v2.6.12 · 本地音乐与视频"，`ui/settings_dialog.py`
写着 "轻音播放器 v2.2"，从写下那天起就再没跟随过 `APP_VERSION`。

后果不只是「显示不好看」：界面在撒谎。任何基于「右下角版本号」的判断都会
跑偏 —— v2.7.5 交付时就因为这个把「用户明明在跑最新版」误判成了「在用旧版」，
白查一轮。

现在 main.py 的 APP_VERSION 也从这里来，改一处全局生效。

约束：本模块只依赖标准库（实际上什么都不依赖），main.py 与 ui 都能安全引用，
不会有循环依赖 —— main.py 顶部就要用它，而 ui 又被 main.py 间接导入。
"""

APP_NAME = "轻音播放器"
APP_VERSION = "3.1.0"

# 版本号后面的副标题，界面右下角与「关于」共用，避免两处各写一句
APP_TAGLINE = "本地音乐与视频"


def version_text(tagline: str | None = None) -> str:
    """统一的版本展示串，例如 `v2.7.6 · 本地音乐与视频`。

    `tagline=None` 用默认副标题；传空串表示「只要版本号，不要副标题」。
    """
    tail = APP_TAGLINE if tagline is None else tagline
    return f"v{APP_VERSION} · {tail}" if tail else f"v{APP_VERSION}"
