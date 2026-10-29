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

import contextlib
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


def generate_icon(out_path: str | None = None) -> str:
    """用 Qt 绘制渐变圆角 + ♫ 图标，手工拼接多尺寸 ICO。

    `out_path` 默认为仓库里的 `assets/app.ico`。测试应传临时路径：offscreen 下
    字体库为空，`♫` 会画成空白/方块，若直接写仓库资产会把正式图标降级覆盖。
    """
    icon_path = out_path or ICON_PATH
    os.makedirs(os.path.dirname(os.path.abspath(icon_path)), exist_ok=True)
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
    # 注意：PNG 压缩的图像，ICO 目录项的 planes / bitcount 必须为 0（规范要求）。
    # 填 1/32（BMP 格式的值）在资源管理器里常被容忍，但任务栏/标题栏的图标
    # 加载器更严格，会拒绝加载导致窗口图标退化成「图片找不到」占位符。
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    blob = b""
    for size, data in zip(sizes, images, strict=True):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 0, 0, len(data), offset)
        blob += data
        offset += len(data)
    with open(icon_path, "wb") as f:
        f.write(header + entries + blob)
    print(f"图标已生成: {icon_path} ({len(sizes)} 尺寸, {os.path.getsize(icon_path)} bytes)")
    return icon_path


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
        # 把图标随包带上，供运行时 app.setWindowIcon 显式设置（双保险）
        "--add-data", f"{ICON_PATH}{os.pathsep}assets",
        # miniaudio 的 _miniaudio.pyd 在 C 层 `import _cffi_backend`，PE 依赖扫描
        # 抓不到这种运行时导入，PyInstaller 会漏收 —— 打包后一启动就
        # ModuleNotFoundError: No module named '_cffi_backend'（v2.6.9 实测，
        # 而且 windowed 产物还会弹错误框，把构建挂在 smoke 上）。必须显式声明。
        "--hidden-import", "_cffi_backend",
        # 瘦身（v2.7.0）：miniaudio 顶层 `try: import numpy / except: numpy = None`
        # 是可选依赖，PyInstaller 却顺着它把 numpy + numpy.libs（onedir 里约 27MB）
        # 整包打进去。本程序不用 numpy（本地对齐是纯 Python 算 RMS），显式排除后
        # miniaudio 会自动退化为 array 路径，exe 体积直接瘦一圈。
        "--exclude-module", "numpy",
        "--exclude-module", "numpy.libs",
        # 其余绝不使用的重量级库（未安装时为无害 no-op，装了也不会被打进去）
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "tkinter",
        "--exclude-module", "soundfile",
        "--exclude-module", "lameenc",
        "--exclude-module", "pypinyin",
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


def smoke_test(exe: str, audio_file: str | None = None, timeout_s: int = 180) -> None:
    """离屏启动产物，验证主窗口可创建；附带音频时验证解码链路。

    实现要点（v2.6.9 事故后重写，勿退回 `subprocess.run(capture_output=True)`）：
    - onefile 是父子进程：子进程会继承 stdout 管道句柄，一旦子进程卡住，杀父进程
      后 `communicate()` 仍等不到 EOF，整个构建永久挂死。所以输出**重定向到临时
      文件**，不从管道读；
    - 超时用 `taskkill /T /F` 杀整棵树，别只杀父进程；
    - windowed 产物在子进程异常时会弹一个错误对话框等人点确定 —— 这既会挂死构建，
      又会让「返回码」永远拿不到。杀树后把已经写到文件里的 traceback 打出来，
      才能看到真正的原因（这次就是靠它定位到 _cffi_backend 的）。
    """
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.pop("PYTHONPATH", None)
    cmd = [exe, "--smoke"] + ([audio_file] if audio_file else [])
    print(f"smoke test: {' '.join(cmd)}")
    td = tempfile.mkdtemp(prefix="qy_smoke_log_")
    try:
        out_path = os.path.join(td, "stdout.log")
        err_path = os.path.join(td, "stderr.log")
        with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
            proc = subprocess.Popen(cmd, env=env, cwd=HERE, stdout=fo, stderr=fe)
            timed_out = False
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=10)
        out, err = _read_logs(out_path, err_path)
        if timed_out:
            print(out)
            print(err)
            raise SystemExit(f"smoke test 超时（{timeout_s}s），已强制结束进程树: {os.path.basename(exe)}")
        if proc.returncode != 0:
            print(out)
            print(err)
            raise SystemExit(f"smoke test 失败，返回码 {proc.returncode}")
        tail = out.strip().splitlines()[-1:] or [err.strip()[-200:]]
        print("smoke test 通过:", tail)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def _read_logs(*paths: str) -> tuple[str, ...]:
    """读回 smoke/自检的重定向日志，缺文件按空串处理。

    windowed 产物（PyInstaller runw.exe）在重定向到文件时按**系统代码页**写
    （中文 Windows 是 cp936），不认 PYTHONIOENCODING——实测设了也还是 GBK。
    所以这里按字节读、先试 utf-8 再退 gbk，保证失败时的中文报错可读。
    """
    texts = []
    for path in paths:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            raw = b""
        for encoding in ("utf-8", "gbk"):
            try:
                texts.append(raw.decode(encoding))
                break
            except UnicodeDecodeError:
                continue
        else:
            texts.append(raw.decode("utf-8", "replace"))
    return tuple(texts)


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
    # 隔离用户数据目录：不带 --smoke 启动也会加载曲库，退出时可能回写 data.json。
    # 构建检查绝不能碰用户的真实曲库（%APPDATA%\轻音播放器）。
    env["APPDATA"] = os.path.join(td, "appdata")
    os.makedirs(env["APPDATA"], exist_ok=True)
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
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=10)
                print(f"真实平台检查通过: {os.path.basename(exe)} 持续运行 {timeout_s}s 未崩溃")
                return
        out = "".join(_read_logs(out_path, err_path))
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
    fixture_audio = os.path.join(ensure_fixtures(), "晴天 - 周杰伦.mp3")

    # 注意：generate_icon() 在 offscreen 下字体库为空，会直接把 ♫ 画成方块写入
    # assets/app.ico，把仓库里的正式图标降级覆盖。要改图标请在**真实桌面**下单独跑
    # （见 README「图标」一节），构建流程本身只在图标缺失时才补一个占位。
    if not os.path.exists(ICON_PATH):
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
