# -*- coding: utf-8 -*-
"""应用数据路径解析（v2.6：数据目录可选择）。

解析优先级（高 → 低）：
1. 环境变量 `QY_DATA_DIR` —— 只给测试与 `--smoke` 自检用，保证隔离
2. 便携模式：**打包后**软件目录下存在 `data/` 文件夹 → 数据就放在那里
3. 指针文件 `%APPDATA%\\轻音播放器\\location.txt` 的内容（用户在设置里改过位置）
4. 默认位置 `%APPDATA%\\轻音播放器\\`

为什么便携模式只在打包后生效：开发态项目根就在仓库里，若有人手建一个 `data/`
目录，所有依赖「改 APPDATA 做隔离」的测试都会静默写到那个目录里去（进而污染
用户真实曲库）。源码运行时一律走 APPDATA，想验证便携模式请用 `QY_DATA_DIR`。

**不做缓存**：测试与工具会在运行中修改 `APPDATA` 来隔离数据（test_e2e /
test_e2e_video / shot.py 都是这个套路），一旦缓存根目录就会拿到旧值、静默写进
用户库里。这里每次调用都重新解析，代价是两次 `isdir` + 一次文件读。

不使用 QStandardPaths，保证在无 QApplication 的单测环境同样可用。
"""
import contextlib
import os
import sys

APP_NAME = "轻音播放器"
DATA_FILE_NAME = "data.json"

ENV_DATA_ROOT = "QY_DATA_DIR"       # 最高优先级：测试 / 自检隔离
PORTABLE_MARKER = "data"            # 软件目录下这个文件夹存在 = 便携模式
POINTER_NAME = "location.txt"       # 默认目录里的「数据实际位置」指针

# 由迁移逻辑负责搬运的子项（供 storage.migrate 使用）
DATA_SUBDIRS = ("covers", "library", "lyrics_cache", "bgs", "lyrics_colors")


def _frozen() -> bool:
    """是否是 PyInstaller 打包产物。"""
    return bool(getattr(sys, "frozen", False))


def default_root() -> str:
    """默认位置：%APPDATA%\\轻音播放器（非 Windows 退回用户目录）。"""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


def exe_dir() -> str:
    """软件所在目录：打包后是 exe 所在目录，开发态是仓库根目录。"""
    if _frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """只读**内置资源**（随程序分发的图片/图标）的绝对路径（v2.7.8）。

    区别于 `exe_dir()`：onefile 打包后 `sys.executable` 仍指向 dist/ 里的 exe，
    而资源被解压到临时目录 —— 只有 `sys._MEIPASS` 指向那里。所以这里必须
    优先用 `_MEIPASS`，开发态才回退到仓库根。

    只用于「跟着程序走、永不修改」的文件；用户数据一律走 `app_data_dir()`。
    """
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def portable_root() -> str | None:
    """便携模式的数据目录（软件目录下的 data/），未启用返回 None。

    只在打包后判断 —— 见模块说明：开发态误判会破坏测试隔离。
    """
    if not _frozen():
        return None
    path = os.path.join(exe_dir(), PORTABLE_MARKER)
    return path if os.path.isdir(path) else None


def pointer_file() -> str:
    return os.path.join(default_root(), POINTER_NAME)


def read_pointer() -> str | None:
    """读取指针文件；文件不存在 / 内容为空 / 目录已失效都返回 None。"""
    try:
        with open(pointer_file(), "r", encoding="utf-8") as f:
            target = f.read().strip()
    except OSError:
        return None
    if not target:
        return None
    target = os.path.abspath(target)
    # 目录失效（用户删了、U 盘拔了）→ 退回默认位置，而不是把程序指向一个空目录
    return target if os.path.isdir(target) else None


def write_pointer(root: str) -> None:
    """把「数据实际位置」写进默认目录的指针文件（会先建默认目录）。"""
    target = os.path.abspath(root)
    os.makedirs(default_root(), exist_ok=True)
    path = pointer_file()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(target)
    os.replace(tmp, path)


def clear_pointer() -> None:
    """删除指针文件（恢复默认位置）。不存在时静默返回。"""
    with contextlib.suppress(OSError):
        os.remove(pointer_file())


def resolve_root() -> str:
    """按优先级解析出当前数据根目录（不创建目录）。"""
    env = os.environ.get(ENV_DATA_ROOT)
    if env:
        return os.path.abspath(env)
    portable = portable_root()
    if portable is not None:
        return portable
    pointed = read_pointer()
    if pointed is not None:
        return pointed
    return default_root()


def current_root() -> str:
    return resolve_root()


def mode() -> str:
    """当前数据目录的模式，供设置页显示：env / portable / custom / default。"""
    if os.environ.get(ENV_DATA_ROOT):
        return "env"
    if portable_root() is not None:
        return "portable"
    return "custom" if read_pointer() is not None else "default"


def is_packaged() -> bool:
    """是否是安装/打包版。便携模式只对打包版有意义（见 `portable_root`）。"""
    return _frozen()


def is_portable() -> bool:
    return portable_root() is not None


def app_data_dir() -> str:
    """数据根目录（确保存在）。不可写时回退默认位置，避免启动即崩。"""
    path = resolve_root()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        fallback = default_root()
        os.makedirs(fallback, exist_ok=True)
        return fallback
    return path


def data_file() -> str:
    return os.path.join(app_data_dir(), DATA_FILE_NAME)


def _subdir(name: str) -> str:
    """数据根目录下的一个子目录（确保存在）。"""
    path = os.path.join(app_data_dir(), name)
    os.makedirs(path, exist_ok=True)
    return path


def covers_dir() -> str:
    return _subdir("covers")


def library_dir() -> str:
    """曲库目录：导入的媒体文件会被复制到这里（v2.1.9 起的「受管理曲库」）。

    默认在数据根目录下与 covers/ 同级：
        %APPDATA%\\轻音播放器\\library\\
    选它做默认的理由：① 与 data.json / covers 同一套隔离与备份逻辑；
    ② 路径稳定，Track id（按绝对路径哈希）不会因换盘/挪目录而漂移。
    v2.6 起整套数据可整体换位置（设置 → 存储，或软件目录下建 data/ 走便携）。
    """
    return _subdir("library")


def lyrics_cache_dir() -> str:
    """联网歌词缓存目录：`<track_id>.lrc`，离线后仍可显示（v2.2）。"""
    return _subdir("lyrics_cache")


def bgs_dir() -> str:
    """自定义背景图片目录（v2.2）。

    选中的图片会被**复制**进来：用户把原图删了/挪走后背景不能变成一块黑，
    而且换盘路径漂移会导致设置里存着一个失效路径。
    """
    return _subdir("bgs")


def lyrics_colors_dir() -> str:
    """逐曲「歌词自定义颜色」sidecar 目录（v2.9.0）。

    每首歌一个 `<track_id>.json`，存「行时间戳 -> 颜色」的映射。放数据目录而不是
    写进歌词文件：.lrc 是通用格式，不该被本应用的私有字段污染；换歌词文件时
    这些颜色仍留在原曲名下。
    """
    return _subdir("lyrics_colors")
