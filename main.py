# -*- coding: utf-8 -*-
"""轻音播放器 —— 本地音乐播放器入口。

用法：
    python main.py                         启动应用
    python main.py --check                 环境自检（不加载 GUI）
    python main.py --check-ai <模型目录> [音频]
                                           AI 对齐链路自检（不加载 GUI，报告写文件）
    python main.py --download-model [档位]  下载 AI 模型并验证能加载（报告写文件）
"""
import os
import sys

from PySide6.QtGui import QIcon

# v2.7.6：版本号收敛到 app/version.py，界面与「关于」都从那里取。
# 原来 APP_VERSION 只在本文件定义，而 ui/main_window.py 里另写死了一个
# "v2.6.12" —— 两个数字各说各话，界面显示永远是旧的。
from app.version import APP_NAME, APP_VERSION

# `--check-ai` 报告落点。为什么写文件而不是 print：windowed 打包产物里
# sys.stdout 是 None，print 出去的诊断信息直接消失，最适合「打包后到底能不能
# 加载模型」这种只能在产物里验证的问题。
AI_CHECK_REPORT = os.path.join(
    os.environ.get("TEMP") or os.environ.get("TMP") or ".", "qy_ai_check.txt")


def _check_ai(argv: list[str]) -> int:
    """验证 AI 对齐链路（v3.0.0）：能 import 组件、能加载模型、能推理出词级时间戳。

    为什么需要这个入口：`ctranslate2` 在 PyInstaller 产物里加载模型会 segfault
    （Phase 0 实测，4.8.4 必崩、4.6.0 正常），这种失败**不抛异常、不打印任何东西**，
    只能靠一个能跑通的诊断命令来证明。开发态和打包态都能用同一个命令对比。
    """
    args = [a for a in argv[argv.index("--check-ai") + 1:] if not a.startswith("--")]
    model_dir = args[0] if args else ""
    audio = args[1] if len(args) > 1 else ""
    lines = [f"{APP_NAME} v{APP_VERSION} AI 自检"]
    code = 0
    try:
        from app import lyrics_asr as la
        lines.append(f"import app.lyrics_asr OK（默认档位 {la.DEFAULT_AI_MODEL}）")
        lines.append(f"模型目录存在: {os.path.isdir(model_dir)}  就绪: {la.model_ready(model_dir)}")
        if audio:
            if not os.path.isfile(audio):
                lines.append(f"音频不存在: {audio}")
                code = 2
            else:
                pcm, sr = la.decode_for_asr(audio)
                lines.append(f"解码 OK: {len(pcm) / sr:.2f}s @ {sr}Hz")
                outcome = None
                if la.model_ready(model_dir):
                    outcome = la.transcribe(audio, model_dir, "zh",
                                            predecoded=(pcm, sr))
                    if outcome.ok:
                        lines.append(f"推理 OK: 语言 {outcome.language} "
                                     f"时长 {outcome.duration_ms}ms 词数 {len(outcome.words)}")
                        for word in outcome.words[:5]:
                            lines.append(f"  {word.start_ms}~{word.end_ms} "
                                         f"p={word.probability:.2f} {word.text!r}")
                    else:
                        # 没有语音内容 / 置信度低不算「环境坏了」，只是这份音频对不上
                        lines.append(f"推理返回: {outcome.error} {outcome.detail}")
                else:
                    lines.append("模型未就绪，跳过推理")
    except Exception as exc:  # noqa: BLE001 - 自检要把崩溃原因也写下来
        lines.append(f"失败: {type(exc).__name__}: {exc}")
        code = 1
    text = "\n".join(lines)
    try:
        with open(AI_CHECK_REPORT, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    print(text)
    print(f"报告: {AI_CHECK_REPORT}")
    return code


def _download_model(argv: list[str]) -> int:
    """下载指定档位的 AI 模型并验证能加载（v3.0.1）。

    为什么单独开一个入口：v3.0.0 出货后用户在真实环境里必现「模型下载失败」，
    开发态却一切正常 —— 只能靠「在产物里跑一遍真实下载」拿到真实报错。窗口化
    打包没有 stdout，所以结论写文件。

    用法：`QingYinPlayer.exe --download-model base`（不加载 GUI，跑完即退）
    """
    args = [a for a in argv[argv.index("--download-model") + 1:] if not a.startswith("--")]
    lines = [f"{APP_NAME} v{APP_VERSION} 模型下载诊断"]
    code = 0
    try:
        from app import lyrics_asr as la
        from app.models import DEFAULT_AI_MODEL, LYRICS_AI_MODELS

        name = args[0] if args and args[0] in LYRICS_AI_MODELS else DEFAULT_AI_MODEL
        target = la.model_dir_for(name)
        lines.append(f"档位 {name} → 目录 {target}")
        lines.append(f"下载站 {la.download_endpoint()}（{la.MODEL_REPOS.get(name, '?')}）")
        lines.append(f"下载前就绪: {la.model_ready(target)}")

        # 进度回调每 1MB 一次，461MB 的 small 档会刷上千行 —— 报告按 10% 归并
        last_bucket = [-1]

        def _report(stage: str, fraction: float) -> None:
            bucket = int(fraction * 10)
            if bucket > last_bucket[0]:
                last_bucket[0] = bucket
                lines.append(f"  {stage} {bucket * 10}%")

        # 已经就绪时 ensure_model 不会联网，重复跑这个命令是安全的
        model_dir, err, detail = la.ensure_model(name, _report)
        lines.append(f"ensure_model → 错误码 {err or '(无)'} 详情 {detail or '(无)'}")
        lines.append(f"下载后就绪: {la.model_ready(model_dir)}")
        if err:
            code = 1
        else:
            # 下载成功不等于能用：ctranslate2 在 PyInstaller 里有过 segfault 前科，
            # 所以再真正加载一次模型，把「文件齐了但加载崩」也一起验掉
            from faster_whisper import WhisperModel

            WhisperModel(model_dir, device="cpu", compute_type="int8")
            lines.append("WhisperModel 加载 OK")
    except Exception as exc:  # noqa: BLE001 - 诊断入口要把崩溃原因也写下来
        lines.append(f"失败: {type(exc).__name__}: {exc}")
        code = 1
    text = "\n".join(lines)
    try:
        with open(AI_CHECK_REPORT, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    print(text)
    print(f"报告: {AI_CHECK_REPORT}")
    return code


def _resolve_app_icon() -> str | None:
    """定位应用图标：打包后随 --add-data 进入 sys._MEIPASS，开发态用本地 assets。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "assets", "app.ico")
    return path if os.path.exists(path) else None


def _apply_app_icon(app) -> None:
    icon = _resolve_app_icon()
    if icon:
        app.setWindowIcon(QIcon(icon))


def main() -> int:
    if "--check-ai" in sys.argv:
        return _check_ai(sys.argv)

    if "--download-model" in sys.argv:
        return _download_model(sys.argv)

    if "--check" in sys.argv:
        print(f"{APP_NAME} v{APP_VERSION} (Python {sys.version.split()[0]})")
        try:
            import PySide6  # noqa: F401
            import mutagen  # noqa: F401
            print("依赖检查: PySide6 OK / mutagen OK")
        except ImportError as e:
            print(f"依赖检查失败: {e}")
            return 1
        return 0

    if "--smoke" in sys.argv:
        # 打包产物自检：创建主窗口；若附带音频文件则验证可解码播放
        #
        # 关键：smoke 会走 MainWindow → LibraryStore(add_or_update)，而 store 默认
        # 落在 %APPDATA%\轻音播放器\data.json —— 也就是**用户真实曲库**。若不隔离，
        # 每次 build.py 自检都会把合成夹具「晴天」写进用户库，退出时还会覆盖
        # last_view / last_track_id。这里在创建窗口之前把 APPDATA 指向临时目录。
        #
        # v2.6 起还有两条会绕过 APPDATA 的路径：便携模式（软件目录的 data/）和
        # 指针文件（用户改过数据位置）。两者优先级都高于 APPDATA，所以这里必须再设
        # QY_DATA_DIR —— 它是最高优先级，能把自检牢牢钉在临时目录里。
        import atexit
        import shutil
        import tempfile
        import time

        _smoke_appdata = tempfile.mkdtemp(prefix="qy_smoke_")
        os.environ["APPDATA"] = _smoke_appdata
        os.environ["QY_DATA_DIR"] = os.path.join(_smoke_appdata, "data")
        atexit.register(shutil.rmtree, _smoke_appdata, True)

        from PySide6.QtCore import QCoreApplication, QTimer
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtWidgets import QApplication

        from app.metadata import read_track
        from ui.main_window import MainWindow

        # 本地歌词对齐依赖 miniaudio（_miniaudio.pyd 在 C 层 import _cffi_backend）。
        # 打包最常见的事故就是漏收 _cffi_backend：界面一切正常，用户点「本地对齐」
        # 才报缺组件（v2.6.9 实测）。自检里显式探一次，让问题在构建阶段就暴露，
        # 而不是带着坏功能出厂。
        try:
            import miniaudio  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - 任何加载失败都算打包残缺
            print(f"smoke fail: 本地对齐解码器不可用（{type(exc).__name__}: {exc}）")
            return 1
        print("smoke decoder: miniaudio OK")

        app = QApplication(sys.argv[:1])
        app.setApplicationName(APP_NAME)
        _apply_app_icon(app)
        window = MainWindow()
        window.show()

        audio_file = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        if audio_file:
            meta = read_track(audio_file)
            if meta is None:
                print(f"smoke fail: 无法读取音频 {audio_file}")
                return 1
            track = window.store.add_or_update(meta, audio_file)
            window.player.play_single(track.id, autoplay=True)
            deadline = time.time() + 10
            status = None
            while time.time() < deadline:
                QCoreApplication.processEvents()
                status = window.player.media_status
                if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                              QMediaPlayer.MediaStatus.BufferedMedia,
                              QMediaPlayer.MediaStatus.EndOfMedia,
                              QMediaPlayer.MediaStatus.InvalidMedia):
                    break
                time.sleep(0.05)
            loaded = status in (QMediaPlayer.MediaStatus.LoadedMedia,
                                QMediaPlayer.MediaStatus.BufferedMedia,
                                QMediaPlayer.MediaStatus.EndOfMedia)
            duration = window.player.duration_ms
            print(f"smoke media: status={status.name if status else None} duration={duration}ms")
            if not loaded or duration <= 0:
                print("smoke fail: 音频解码异常")
                return 1
            QTimer.singleShot(300, app.quit)
            app.exec()
            print("smoke ok (含音频解码)")
            return 0

        QTimer.singleShot(600, app.quit)
        code = app.exec()
        print("smoke ok")
        return code

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    from PySide6.QtWidgets import QApplication

    from app.paths import app_data_dir, current_root, mode
    from ui.main_window import MainWindow

    # 先确定数据目录并建好，再开窗口：路径解析要读指针/探测便携模式，
    # 出问题（比如指向了已拔掉的 U 盘）应该在窗口出现前就降级处理。
    app_data_dir()

    # v2.7.5：异常钩子必须在**路径确定之后**装。日志写进数据目录（含便携
    # 模式/自定义位置），所以要等 app_data_dir() 把一切探明。
    # 打包是 windowed 模式，sys.stderr 为 None，未捕获异常原本完全不可见 ——
    # 现在至少能在 logs/app.log 里留下现场。
    from app import crashlog

    crashlog.install()
    crashlog.log_message(f"{APP_NAME} v{APP_VERSION} 启动，数据目录 {current_root()} ({mode()})")

    # 打包成 windowed 后双击启动时 sys.stdout 是 None，直接 print 会抛异常
    if sys.stdout is not None:
        print(f"数据目录: {current_root()} ({mode()})")

    app = QApplication(sys.argv)
    # Qt 自己的警告（例如关窗时 "QThread: Destroyed while thread is still
    # running"）只在控制台可见，必须等 QApplication 建好才能接管
    crashlog.install_qt()
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    _apply_app_icon(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
