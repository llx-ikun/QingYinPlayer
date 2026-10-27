# -*- coding: utf-8 -*-
"""应用数据路径解析。

数据存放：%APPDATA%\\轻音播放器\\（data.json + covers\\）
不使用 QStandardPaths，保证在无 QApplication 的单测环境同样可用。
"""
import os

APP_NAME = "轻音播放器"
DATA_FILE_NAME = "data.json"


def app_data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def data_file() -> str:
    return os.path.join(app_data_dir(), DATA_FILE_NAME)


def covers_dir() -> str:
    path = os.path.join(app_data_dir(), "covers")
    os.makedirs(path, exist_ok=True)
    return path


def library_dir() -> str:
    """曲库目录：导入的媒体文件会被复制到这里（v2.1.9 起的「受管理曲库」）。

    放在应用数据目录下，与 covers/ 同级：
        %APPDATA%\\轻音播放器\\library\\
    选择它的理由：① 与现有 data.json / covers 同一套隔离与备份逻辑；
    ② 相对路径稳定，Track id（按绝对路径哈希）不会因换盘/挪目录而漂移。
    代价：占用系统盘空间 —— 曲库很大的用户会希望改到其他盘，后续可在设置里加
    「曲库位置」并做迁移；本版先固定，避免 id 漂移。
    """
    path = os.path.join(app_data_dir(), "library")
    os.makedirs(path, exist_ok=True)
    return path


def lyrics_cache_dir() -> str:
    """联网歌词缓存目录：`<track_id>.lrc`，离线后仍可显示（v2.2）。"""
    path = os.path.join(app_data_dir(), "lyrics_cache")
    os.makedirs(path, exist_ok=True)
    return path


def bgs_dir() -> str:
    """自定义背景图片目录（v2.2）。

    选中的图片会被**复制**进来：用户把原图删了/挪走后背景不能变成一块黑，
    而且换盘路径漂移会导致设置里存着一个失效路径。
    """
    path = os.path.join(app_data_dir(), "bgs")
    os.makedirs(path, exist_ok=True)
    return path

