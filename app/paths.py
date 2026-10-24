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
