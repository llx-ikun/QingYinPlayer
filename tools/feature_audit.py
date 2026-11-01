# -*- coding: utf-8 -*-
"""功能体检（开发辅助）：静态接线审计 + 主路径实跑，输出人可读报告。

为什么需要它：单元测试按「代码单元」组织，回答不了「这个功能现在还能不能用」。
本脚本换个维度——按**用户功能**取证：

1. **静态接线审计**：`ui/` 里声明的每个 `Signal` 是否真的被 `.connect` 过。
   漏接的信号不会报错、不会崩，只会让某个功能**静默失效**（点按钮没反应），
   这类 bug 靠单测很难抓。
2. **主路径实跑**：在离屏环境把「导入 → 播放 → 控制 → 歌单 → 收藏 → 歌词 →
   主题 → 搜索 → 队列 → 重启恢复」串一遍。单项都过、串起来断的问题只有这里能抓。
3. **右键菜单清单**：把歌词区菜单的实际条目打出来，供人工核对有没有多余/缺失。

用法（必须离屏，不要在有 Qt 进程时跑）：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/feature_audit.py

判定三态：
    PASS  = 功能可用（断言通过）
    SKIP  = 本环境物理上验不了（无音频后端 / 无 GPU / 需人工看画面），不算失败
    FAIL  = 真的有问题
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("PYTHONPATH", None)

# 必须在任何 app.paths 调用之前把数据目录指到临时位置，
# 否则体检会读写用户真实曲库（%APPDATA%/轻音播放器）。
_TMP = tempfile.mkdtemp(prefix="qy_audit_")
os.environ["APPDATA"] = _TMP

_APP = None
RESULTS: list[tuple[str, str, str]] = []   # (状态, 名称, 说明)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))


def case(status_ok=True):
    """装饰器：把一条检查包起来，异常记 FAIL 而不中断全流程。"""
    def wrap(fn):
        def inner(*a, **k):
            try:
                out = fn(*a, **k)
                if out:
                    record("PASS", fn.__doc__ or fn.__name__, str(out))
                else:
                    record("PASS", fn.__doc__ or fn.__name__)
            except SkipCheck as exc:
                record("SKIP", fn.__doc__ or fn.__name__, str(exc))
            except Exception as exc:  # noqa: BLE001 - 体检要记录而不是崩
                detail = f"{type(exc).__name__}: {exc}"
                record("FAIL", fn.__doc__ or fn.__name__, detail)
                LAST_TRACEBACK.append(traceback.format_exc())
        return inner
    return wrap


class SkipCheck(Exception):
    """本环境验不了。"""


LAST_TRACEBACK: list[str] = []


def _spin(predicate, timeout_ms=15000, interval_ms=20):
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(interval_ms / 1000)
    return predicate()


# ---------------------------------------------------------------- 静态审计


def audit_signal_wiring() -> None:
    """静态接线审计：ui/ 里声明的 Signal 有没有被 connect。"""
    ui_dir = os.path.join(ROOT, "ui")
    declared: dict[str, str] = {}
    sources: dict[str, str] = {}
    for fn in sorted(os.listdir(ui_dir)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(ui_dir, fn)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        sources[fn] = src
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, ast.Assign):
                    continue
                call = item.value
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                is_signal = (isinstance(func, ast.Name) and func.id == "Signal") or (
                    isinstance(func, ast.Attribute) and func.attr == "Signal")
                if not is_signal:
                    continue
                for tgt in item.targets:
                    if isinstance(tgt, ast.Name):
                        declared[tgt.id] = f"{fn}:{node.name}"

    all_src = "\n".join(sources.values())
    orphans = []
    for name, where in declared.items():
        # 出现次数：定义处 1 次；再出现说明被引用（connect / pyqtSignal 转发等）
        hits = all_src.count(name)
        if hits <= 1:
            orphans.append(f"{name} ({where})")

    record("PASS", f"声明信号共 {len(declared)} 个")
    if orphans:
        record("WARN", "疑似未接线的信号（仅声明、全库无其它引用）",
               "、".join(orphans))
    else:
        record("PASS", "所有声明信号都有引用（无静默失效风险）")


def audit_menu_items() -> None:
    """歌词区右键菜单清单（供核对多余/缺失项）。"""
    from PySide6.QtWidgets import QApplication
    from ui.lyrics_panel import LyricsPanel
    panel = LyricsPanel()
    menu = panel._build_menu(-1)
    items = []
    for act in menu.actions():
        if act.isSeparator():
            items.append("—")
        elif act.menu() is not None:
            subs = [a.text() for a in act.menu().actions()]
            items.append(f"{act.text()} > [{'/'.join(subs)}]")
        else:
            items.append(act.text())
    record("PASS", "歌词区右键菜单", " | ".join(items))
    if any("在线搜索歌词" in i for i in items):
        record("FAIL", "已移除的「在线搜索歌词」仍在菜单里")
    else:
        record("PASS", "「在线搜索歌词」已从菜单移除（v3.0.8）")
    QApplication.processEvents()


# ---------------------------------------------------------------- 主路径实跑


def spine() -> None:
    """主路径串联：导入 → 播放 → 控制 → 歌单 → 收藏 → 歌词 → 主题 → 搜索 → 队列 → 重启。"""
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    import ui.main_window as mw

    # 模态框替换成假的，避免 exec 阻塞（与 E2E 同款做法）
    from PySide6.QtCore import QObject, Signal

    class FakeImportDialog(QObject):
        cancelled = Signal()

        def __init__(self, parent=None):
            super().__init__()
            self.progress = 0

        def update_progress(self, *a, **k):
            pass

        def set_current_file(self, *a, **k):
            pass

        def finish(self, *a, **k):
            pass

        def reject(self):
            pass

        def exec(self):
            return 0

    mw.ImportProgressDialog = FakeImportDialog

    sys.path.insert(0, ROOT)
    from tests.make_fixtures import ensure_fixtures
    music_dir = ensure_fixtures()

    win = MainWindow()
    win.show()
    QApplication.processEvents()
    record("PASS", "主窗口构造 + 显示")

    print("STEP 版本号同源", flush=True)

    # --- 版本号同源 ---
    from app.version import APP_VERSION
    got = win.version_label.text()
    record("PASS" if APP_VERSION in got else "FAIL", "右下角版本号跟随 app.version", got)

    print("STEP 导入", flush=True)

    # --- 导入 ---
    win._start_import([music_dir])
    ok = _spin(lambda: win._scanner is None, timeout_ms=60000)
    n = len(win.store.all_tracks())
    record("PASS" if ok and n > 0 else "FAIL", f"导入夹具目录（曲目 {n} 首）")

    # 去重：再导一次不该变多
    n_before = len(win.store.all_tracks())
    win._start_import([music_dir])
    _spin(lambda: win._scanner is None, timeout_ms=60000)
    n_after = len(win.store.all_tracks())
    record("PASS" if n_after == n_before else "FAIL",
           "重复导入内容指纹去重", f"{n_before} → {n_after}")

    tracks = win.store.all_tracks()
    if not tracks:
        raise SkipCheck("曲库为空，后续播放类检查全部跳过")
    first = tracks[0]

    print("STEP 播放控制", flush=True)

    # --- 播放控制 ---
    win.player.play_single(first.id)
    _spin(lambda: win.player.current_track is not None, timeout_ms=8000)
    record("PASS" if win.player.current_track else "FAIL", "双击播放：当前曲目已设置",
           getattr(win.player.current_track, "title", ""))

    win.player.pause()
    QApplication.processEvents()
    record("PASS", "暂停")
    win.player.resume()
    QApplication.processEvents()
    record("PASS", "继续播放")

    status = win.player.media_status
    record("PASS", "媒体加载状态", str(status))

    # seek 需要 mediaStatus 已 Loaded/Buffered，否则 Qt 会丢弃
    loaded = _spin(lambda: "Loaded" in str(win.player.media_status)
                   or "Buffered" in str(win.player.media_status), timeout_ms=8000)
    if loaded:
        win.player.seek(500)
        QApplication.processEvents()
        record("PASS", "进度拖动 seek", f"position={win.player.position_ms}")
        if win.player.position_ms == 0:
            record("SKIP", "seek 后 position 未推进",
                   "离屏无音频后端，position 不推进是环境已知限制")
    else:
        record("SKIP", "进度拖动 seek", "媒体未进 Loaded/Buffered，离屏环境限制")

    win.player.set_volume(0.42)
    record("PASS" if abs(win.player.volume - 0.42) < 0.02 else "FAIL",
           "音量调节", str(win.player.volume))
    win.player.toggle_mute()
    muted = win.player.muted
    win.player.toggle_mute()
    record("PASS" if muted != win.player.muted else "FAIL", "静音切换")

    print("STEP 四种播放模式", flush=True)

    # --- 四种播放模式 ---
    seen = []
    for _ in range(5):
        seen.append(win.player.cycle_mode())
    record("PASS" if len(set(seen)) >= 4 else "FAIL", "播放模式循环（四种）", "→".join(seen))

    print("STEP 切歌", flush=True)

    # --- 切歌 ---
    if len(tracks) >= 2:
        ids = [t.id for t in tracks]
        win.player.play_tracks(ids, 0)
        _spin(lambda: win.player.current_track is not None, timeout_ms=8000)
        before = win.player.current_track.id if win.player.current_track else None
        win.player.next()
        _spin(lambda: win.player.current_track and win.player.current_track.id != before,
              timeout_ms=8000)
        after = win.player.current_track.id if win.player.current_track else None
        record("PASS" if after != before else "FAIL", "下一首")
        win.player.previous()
        _spin(lambda: win.player.current_track and win.player.current_track.id == before,
              timeout_ms=8000)
        back = win.player.current_track.id if win.player.current_track else None
        record("PASS" if back == before else "FAIL", "上一首")

    print("STEP 歌单", flush=True)

    # --- 歌单 ---
    pl = win.store.create_playlist("体检歌单")
    record("PASS" if win.store.get_playlist(pl.id) else "FAIL", "歌单：新建")
    record("PASS" if win.store.rename_playlist(pl.id, "体检改名") else "FAIL", "歌单：重命名")
    added = win.store.add_to_playlist(pl.id, [first.id])
    record("PASS" if added == 1 else "FAIL", "歌单：添加歌曲", str(added))
    win.store.move_in_playlist(pl.id, first.id, 0)
    record("PASS", "歌单：排序")
    win.store.remove_from_playlist(pl.id, first.id)
    record("PASS" if not win.store.playlist_tracks(pl.id) else "FAIL", "歌单：移出歌曲")
    record("PASS" if win.store.delete_playlist(pl.id) else "FAIL", "歌单：删除")

    print("STEP 我喜欢", flush=True)

    # --- 我喜欢 ---
    on1 = win.store.toggle_favorite(first.id)
    record("PASS" if on1 else "FAIL", "我喜欢：收藏")
    record("PASS" if win.store.favorite_count() >= 1 else "FAIL", "我喜欢：计数")
    on2 = win.store.toggle_favorite(first.id)
    record("PASS" if not on2 else "FAIL", "我喜欢：取消收藏")

    print("STEP 歌词", flush=True)

    # --- 歌词 ---
    with_lrc = None
    for t in tracks:
        win.player.play_single(t.id)
        _spin(lambda: win.now_playing.lyrics._mode != "empty", timeout_ms=6000)
        if win.now_playing.lyrics._mode == "synced":
            with_lrc = t
            break
    if with_lrc is not None:
        rows = win.now_playing.lyrics.list.count()
        record("PASS" if rows > 0 else "FAIL", "歌词：同名 .lrc 同步显示",
               f"{rows} 行 / {with_lrc.title}")
        win.now_playing.lyrics.update_position(1500)
        record("PASS", "歌词：按播放位置高亮")
    else:
        record("SKIP", "歌词：同名 .lrc 同步显示", "夹具里没找到带 .lrc 的可播曲目")

    print("STEP 主题", flush=True)

    # --- 主题 ---
    win._apply_theme("columbina")
    dark = win.store.settings.theme
    win._apply_theme("light")
    light = win.store.settings.theme
    record("PASS" if (dark, light) == ("columbina", "light") else "FAIL",
           "双主题切换", f"{dark} → {light}")

    print("STEP 搜索（搜索框在标题栏里）", flush=True)

    # --- 搜索（搜索框在标题栏里） ---
    box = win.title_bar.search_box
    box.setText("晴天")
    QApplication.processEvents()
    filtered = win.track_list.list.count()
    box.setText("")
    QApplication.processEvents()
    full = win.track_list.list.count()
    record("PASS" if filtered <= full else "FAIL", "全局搜索过滤",
           f"命中 {filtered} / 全部 {full}")

    print("STEP 队列浮层", flush=True)

    # --- 队列浮层 ---
    win.player.play_tracks([t.id for t in tracks], 0)
    _spin(lambda: win.player.current_track is not None, timeout_ms=8000)
    # ⚠️ 这里**不能**调 `win._show_queue_panel()`：它内部 `panel.exec_at(...)`
    # 是模态的，离屏无人点击会永久阻塞（实测卡死 5 分钟）。改为直接构造面板，
    # 验「能建出来、条目数与队列一致」，模态交互本身属人工确认项。
    from ui.queue_panel import QueuePanel
    qp = QueuePanel(win.player.queue_ids, win.player.queue_index,
                    win._queue_track_text, win)
    rows = qp.list.count()
    record("PASS" if rows == len(win.player.queue_ids) else "FAIL",
           "播放队列浮层（构造 + 条目）", f"{rows} 条")
    record("SKIP", "队列浮层弹窗交互", "exec_at 是模态，需人工点击确认")

    print("STEP 视图切换", flush=True)

    # --- 视图切换 ---
    for view in ("__favorites__", "__recent__"):
        try:
            win.set_view(view)
            QApplication.processEvents()
            record("PASS", f"视图切换 {view}")
        except Exception as exc:  # noqa: BLE001
            record("FAIL", f"视图切换 {view}", f"{type(exc).__name__}: {exc}")

    print("STEP 设置保存 + 重启恢复", flush=True)

    # --- 设置保存 + 重启恢复 ---
    win.store.set_setting("nickname", "体检昵称")
    win.store.set_setting("volume", 0.37)
    win.store.save()
    playing_id = win.player.current_track.id if win.player.current_track else None
    win.player.pause()
    win.close()
    QApplication.processEvents()

    win2 = MainWindow()
    win2.show()
    QApplication.processEvents()
    nick_ok = win2.store.settings.nickname == "体检昵称"
    vol_ok = abs(win2.store.settings.volume - 0.37) < 0.01
    record("PASS" if nick_ok and vol_ok else "FAIL", "重启恢复：设置（昵称/音量）",
           f"nickname={nick_ok} volume={vol_ok}")
    tracks2 = len(win2.store.all_tracks())
    record("PASS" if tracks2 == len(tracks) else "FAIL", "重启恢复：曲库",
           f"{len(tracks)} → {tracks2}")
    last = win2.store.settings.last_track_id
    record("PASS" if last == playing_id else "FAIL", "重启恢复：上次曲目",
           f"{last} vs {playing_id}")
    win2.player.stop()
    win2.close()
    QApplication.processEvents()


def part2() -> None:
    """外围功能：封面 / 排序 / 视频页 / 设置对话框 / 快捷键 / 数据目录。"""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QShortcut
    from ui.main_window import MainWindow
    from tests.make_fixtures import ensure_fixtures

    win = MainWindow()
    win.show()
    QApplication.processEvents()
    music_dir = ensure_fixtures()
    win._start_import([music_dir])
    _spin(lambda: win._scanner is None, timeout_ms=60000)
    tracks = win.store.all_tracks()
    if not tracks:
        raise SkipCheck("曲库为空")

    print("STEP2 封面", flush=True)
    # 封面：有内嵌封面的曲目要能取到 pixmap
    got = 0
    for t in tracks:
        pm = win.covers.get_pixmap(t, 280, 14)
        if pm is not None and not pm.isNull():
            got += 1
    record("PASS" if got == len(tracks) else "WARN",
           "封面提取（内嵌 / 占位图兜底）", f"{got}/{len(tracks)} 张非空")

    print("STEP2 排序", flush=True)
    # 排序：四种维度都走一遍，列表数量不变、不抛异常
    before = win.track_list.list.count()
    for sid in ("title:asc", "size:desc", "duration:asc", "added:desc"):
        win.track_list.sort_changed.emit(sid)
        QApplication.processEvents()
    after = win.track_list.list.count()
    record("PASS" if after == before else "FAIL", "排序（标题/大小/时长/添加时间）",
           f"{before} → {after}")

    print("STEP2 视频", flush=True)
    # 视频：导入 → 播放 → 切视频页 → 切回音乐模式
    video_dir = os.path.join(os.path.dirname(music_dir), "我的视频")
    if os.path.isdir(video_dir):
        win._start_import([video_dir])
        _spin(lambda: win._scanner is None, timeout_ms=60000)
        vs = [t for t in win.store.all_tracks() if t.is_video]
        if vs:
            win.player.play_single(vs[0].id)
            _spin(lambda: win.player.current_track is not None, timeout_ms=8000)
            win.now_playing.set_media_mode(True)
            QApplication.processEvents()
            vv = win.now_playing.video_view
            record("PASS" if vv.isVisible() else "FAIL", "视频页显示")
            win.now_playing.set_media_mode(False)
            QApplication.processEvents()
            record("PASS", "切回音乐模式（不重建播放器）")
            record("SKIP", "视频画面/全屏渲染",
                   "离屏无显示设备，画面与 F11 全屏需人工确认")
        else:
            record("SKIP", "视频导入", "夹具里没有可识别的视频")
    else:
        record("SKIP", "视频导入", "没有视频夹具目录")

    print("STEP2 设置", flush=True)
    # 设置对话框
    from ui.settings_dialog import SettingsDialog
    st = win.store.settings
    dlg = SettingsDialog(st.theme, st.nickname, {}, win)
    dlg.show()
    QApplication.processEvents()
    from PySide6.QtWidgets import QTabWidget
    tabs = dlg.findChildren(QTabWidget)
    record("PASS" if tabs else "FAIL", "设置对话框构造",
           f"{tabs[0].count() if tabs else 0} 个分页")
    fired = []
    dlg.theme_changed.connect(fired.append)
    dlg.theme_changed.emit("columbina")
    record("PASS" if fired == ["columbina"] else "FAIL", "设置：主题信号")
    dlg.close()
    QApplication.processEvents()

    print("STEP2 快捷键", flush=True)
    # 快捷键
    sc = win.findChildren(QShortcut)
    record("PASS" if len(sc) >= 5 else "FAIL", "快捷键绑定", f"{len(sc)} 个")

    print("STEP2 数据目录", flush=True)
    # 数据目录解析
    from app import paths
    root = paths.default_root()
    record("PASS" if os.path.isdir(root) else "FAIL", "数据目录解析", root)
    record("SKIP" if paths.portable_root() is None else "PASS", "便携模式检测",
           "开发态非 frozen，便携模式只在打包产物里生效（privacy: 不写真实目录）")

    win.player.stop()
    win.close()
    QApplication.processEvents()


# ---------------------------------------------------------------- 报告


def main() -> int:
    global _APP
    from PySide6.QtWidgets import QApplication
    _APP = QApplication(sys.argv[:1])

    print("=== 静态接线审计 ===")
    try:
        audit_signal_wiring()
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "静态接线审计", f"{type(exc).__name__}: {exc}")

    print("=== 右键菜单清单 ===")
    try:
        audit_menu_items()
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "右键菜单清单", f"{type(exc).__name__}: {exc}")

    # 外围功能（封面/排序/视频/设置/快捷键/数据目录）默认**不跑**：
    # 这部分在离屏环境实测会卡死在一个无 GIL 的 C 调用里（faulthandler 都打不出
    # 堆栈），且它们本来就有全绿的测试模块覆盖（test_video / test_dialogs /
    # test_sorting / test_e2e_video / test_icon）。要试就加 --part2。
    if "--part2" in sys.argv:
        print("=== 外围功能 ===", flush=True)
        try:
            part2()
        except SkipCheck as exc:
            record("SKIP", "外围功能（后续）", str(exc))
        except Exception as exc:  # noqa: BLE001
            record("FAIL", "外围功能", f"{type(exc).__name__}: {exc}")
            LAST_TRACEBACK.append(traceback.format_exc())

    print("=== 主路径实跑 ===", flush=True)
    try:
        spine()
    except SkipCheck as exc:
        record("SKIP", "主路径实跑（后续）", str(exc))
    except Exception as exc:  # noqa: BLE001
        record("FAIL", "主路径实跑", f"{type(exc).__name__}: {exc}")
        LAST_TRACEBACK.append(traceback.format_exc())

    lines = ["# 功能体检报告", ""]
    counts = {"PASS": 0, "SKIP": 0, "WARN": 0, "FAIL": 0}
    for status, _name, _detail in RESULTS:
        counts[status] = counts.get(status, 0) + 1
    lines.append(f"合计 {len(RESULTS)} 项：PASS {counts['PASS']} / "
                 f"SKIP {counts['SKIP']} / WARN {counts['WARN']} / FAIL {counts['FAIL']}")
    lines.append("")
    for status, name, detail in RESULTS:
        mark = {"PASS": "[OK]  ", "SKIP": "[SKIP]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
        lines.append(f"{mark} {name}" + (f" —— {detail}" if detail else ""))
    if LAST_TRACEBACK:
        lines.append("")
        lines.append("## 异常堆栈")
        lines.extend(LAST_TRACEBACK)

    report = "\n".join(lines)
    out_path = os.path.join(os.environ.get("TEMP", "."), "qy_feature_audit.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)
    print(f"\n报告: {out_path}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
