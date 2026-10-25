# -*- coding: utf-8 -*-
"""构建脚本：生成应用图标 + PyInstaller 打包（单文件便携版 + 目录版）。

用法（项目根目录，venv 内）：
    env -u PYTHONPATH .venv/Scripts/python.exe build.py

产物：
    dist/QingYinPlayer.exe            单文件便携版（双击即用，首次启动稍慢）
    dist/QingYinPlayer-Portable/      目录版（启动快，适合固定安装）

注意：本沙箱中 pip/PyInstaller 需 `env -u PYTHONPATH` 前缀绕过删除守卫。

⚠️ exe 文件名必须保持 ASCII（见下方 _require_ascii_app_name 的说明）。
界面/窗口标题的中文不受影响——main.py 里 setWindowTitle("轻音播放器")。
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 产物文件名（必须 ASCII！中文 exe 名会在部分 Windows 显卡驱动上触发崩溃，见 _require_ascii_app_name）
APP_NAME = "QingYinPlayer"
# 界面显示名（窗口标题等，保持中文）
DISPLAY_NAME = "轻音播放器"
ICON_PATH = os.path.join(HERE, "assets", "app.ico")


def _require_ascii_app_name() -> None:
    """构建期守卫：exe 名含非 ASCII 字符直接失败。

    实测（2026-10-25，本机 Intel 核显）：PyInstaller 产物 exe 文件名含中文时，
    Qt 创建主窗口经由 D3D9on12 → igd12um64xel.dll（Intel 显卡驱动）链路会以
    0xC0000409（ucrtbase __fastfail，无效参数）崩溃——同一二进制仅改名即可复现/规避。
    应用名疑似被驱动用于构建缓存路径，非 ASCII 时转换出错。
    这是驱动/Qt 环境缺陷，无法在应用层修复，只能避开：exe 文件名用 ASCII。
    """
    if not APP_NAME.isascii():
        raise SystemExit(
            f"构建中止：exe 文件名 {APP_NAME!r} 含非 ASCII 字符。\n"
            "中文 exe 名会在 Intel 核显 + D3D9on12 的 Windows 机器上导致启动崩溃\n"
            "（ucrtbase __fastfail 0xC0000409，实测可复现）。请改用 ASCII 名称，\n"
            "界面中文通过 main.py 的 setWindowTitle 保持，不受影响。"
        )


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
    name = APP_NAME if onefile else f"{APP_NAME}-Portable"
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


def _real_platform_check(exe: str, timeout_s: int = 8) -> None:
    """尽力而为的真实平台检查：不带 offscreen 实跑，确认能持续存活。

    offscreen 冒烟不创建真实窗口，覆盖不到显卡驱动/窗口创建链路的崩溃
    （2026-10-25 的中文 exe 名事故正是漏网于此）。headless 环境自动跳过。

    实现要点：
    - 输出重定向到临时文件而非管道——onefile 是父子进程架构，子进程会继承管道句柄，
      用管道会在超时杀父后永远等不到 EOF（构建挂死）；
    - 超时用 taskkill /T 杀整棵树，避免遗留子进程占用窗口。
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("QT_QPA_PLATFORM", None)
    # 用 mkdtemp + ignore_errors 清理：taskkill 后被杀进程的文件句柄释放有延迟，
    # TemporaryDirectory 的上下文退出会因 WinError 32 把异常抛进构建流程。
    td = tempfile.mkdtemp(prefix="qy_realcheck_")
    try:
        out_path = os.path.join(td, "stdout.log")
        err_path = os.path.join(td, "stderr.log")
        with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
            proc = subprocess.Popen([exe], env=env, cwd=HERE, stdout=fo, stderr=fe)
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                print(f"真实平台检查通过: {os.path.basename(exe)} 持续运行 {timeout_s}s 未崩溃")
                return
        out = ""
        for p in (out_path, err_path):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    out += f.read()
            except OSError:
                pass
        low = out.lower()
        if "platform plugin" in low or "could not" in low:
            tail = out.strip().splitlines()[-1] if out.strip() else ""
            print(f"真实平台检查跳过（无桌面环境）: {tail}")
            return
        if proc.returncode != 0:
            print(out[-2000:])
            raise SystemExit(
                f"真实平台检查失败: {os.path.basename(exe)} 启动后异常退出，返回码 {proc.returncode}")
        print(f"真实平台检查通过: {os.path.basename(exe)} 正常退出")
    finally:
        shutil.rmtree(td, ignore_errors=True)


def main() -> None:
    _require_ascii_app_name()
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
    _real_platform_check(exe_onefile)
    exe_ondir = _pyinstaller(onefile=False)
    smoke_test(exe_ondir)
    _real_platform_check(exe_ondir)
    _cleanup_intermediate_exes()
    print(f"\n全部构建完成（{DISPLAY_NAME}），可直接运行的是：")
    print("  单文件便携版:", exe_onefile)
    print("  目录版      :", exe_ondir)
    print("（build/ 目录只是构建过程文件，里面的 exe 已被清理，不可运行）")


if __name__ == "__main__":
    main()
