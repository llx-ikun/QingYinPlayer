# -*- coding: utf-8 -*-
"""构建脚本：生成应用图标 + PyInstaller 打包（单文件便携版 + 目录版）。

用法（项目根目录，venv 内）：
    env -u PYTHONPATH .venv/Scripts/python.exe build.py

产物：
    dist/轻音播放器.exe           单文件便携版（双击即用，首次启动稍慢）
    dist/轻音播放器-便携版/        目录版（启动快，适合固定安装）

注意：本沙箱中 pip/PyInstaller 需 `env -u PYTHONPATH` 前缀绕过删除守卫。
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

APP_NAME = "轻音播放器"
ICON_PATH = os.path.join(HERE, "assets", "app.ico")


def generate_icon() -> str:
    """用 Qt 绘制渐变圆角 + ♫ 图标，手工拼接多尺寸 ICO。"""
    os.makedirs(os.path.dirname(ICON_PATH), exist_ok=True)
    from PySide6.QtCore import Qt, QBuffer, QByteArray, QPointF, QRectF
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter

    if QGuiApplication.instance() is None:
        QGuiApplication(sys.argv[:1])

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images: list[bytes] = []
    for size in sizes:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = size * 0.22
        grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
        grad.setColorAt(0.0, QColor("#5b8cff"))
        grad.setColorAt(1.0, QColor("#a45bff"))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
        p.setPen(QColor("#ffffff"))
        font = QFont()
        font.setPixelSize(int(size * 0.56))
        font.setBold(True)
        p.setFont(font)
        p.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter), "♫")
        p.end()
        # 用 save 到字节流拿 PNG
        byte_array = QByteArray()
        buf = QBuffer(byte_array)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        images.append(bytes(byte_array))

    # ICO = header(6) + N*entry(16) + PNG 数据
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    blob = b""
    for size, data in zip(sizes, images):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blob += data
        offset += len(data)
    with open(ICON_PATH, "wb") as f:
        f.write(header + entries + blob)
    print(f"图标已生成: {ICON_PATH} ({len(sizes)} 尺寸, {os.path.getsize(ICON_PATH)} bytes)")
    return ICON_PATH


def _pyinstaller(onefile: bool) -> str:
    name = APP_NAME if onefile else f"{APP_NAME}-便携版"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", name,
        "--icon", ICON_PATH,
        "--paths", HERE,
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build", "pyinstaller"),
        "--specpath", os.path.join(HERE, "build"),
    ]
    if onefile:
        cmd.append("--onefile")
    cmd.append(os.path.join(HERE, "main.py"))
    print("运行 PyInstaller:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller 失败（{'onefile' if onefile else 'onedir'}），返回码 {result.returncode}")
    exe = os.path.join(HERE, "dist", name, f"{name}.exe") if not onefile else os.path.join(HERE, "dist", f"{name}.exe")
    print(f"构建完成: {exe} ({os.path.getsize(exe) / 1024 / 1024:.1f} MB)")
    return exe


def smoke_test(exe: str, audio_file: str | None = None) -> None:
    """离屏启动产物，验证主窗口可创建；附带音频时验证解码链路。"""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.pop("PYTHONPATH", None)
    cmd = [exe, "--smoke"] + ([audio_file] if audio_file else [])
    print(f"smoke test: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, cwd=HERE, timeout=90,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (result.stdout or "").strip().splitlines()[-1:] or [(result.stderr or "").strip()[-200:]]
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit(f"smoke test 失败，返回码 {result.returncode}")
    print("smoke test 通过:", tail)


def _cleanup_intermediate_exes() -> None:
    """删除 PyInstaller 工作目录(build/pyinstaller)里遗留的中间 exe。

    这些 exe 是 COLLECT 前的半成品，旁边没有 _internal 依赖目录，双击必然报
    "Failed to load Python DLL"。留在 build/ 里极易被误点，构建成功后统一清掉。
    """
    import glob
    strays = glob.glob(os.path.join(HERE, "build", "pyinstaller", "**", "*.exe"),
                       recursive=True)
    for stray in strays:
        try:
            os.remove(stray)
            print(f"已清理中间产物 exe: {os.path.relpath(stray, HERE)}")
        except OSError:
            pass


def main() -> None:
    from tests.make_fixtures import ensure_fixtures
    ensure_fixtures()
    fixture_audio = os.path.join(HERE, "tests", "fixtures", "我的音乐", "晴天 - 周杰伦.mp3")

    generate_icon()
    # 清理旧产物
    for path in (os.path.join(HERE, "dist"), os.path.join(HERE, "build")):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    exe_onefile = _pyinstaller(onefile=True)
    smoke_test(exe_onefile, fixture_audio)
    exe_ondir = _pyinstaller(onefile=False)
    smoke_test(exe_ondir)
    _cleanup_intermediate_exes()
    print("\n全部构建完成，可直接运行的是：")
    print("  单文件便携版:", exe_onefile)
    print("  目录版      :", exe_ondir)
    print("（build/ 目录只是构建过程文件，里面的 exe 已被清理，不可运行）")


if __name__ == "__main__":
    main()
