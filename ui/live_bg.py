# -*- coding: utf-8 -*-
"""动态背景（v3.3.0）：跟随歌曲能量的四种实时动画。

**为什么画在这里而不是做视频**：见 `docs/feature_lyric_video_feasibility.md` 的结论——
播放器里的「背景」必须是**实时**的，否则换首歌就没素材了。这里全部是程序化绘制，
不带任何素材文件，安装包零增长。

**性能**（`tools/probe_live_bg.py` 实测 1280×760）：一帧 5.18ms，占 30fps 预算的 15.6%。
半分辨率反而更慢（放大开销抵消收益），所以不做降采样。

**可读性**是这类功能的生死线，靠三件事一起保：
1. 所有图元 alpha 上限很低（最高不超过 90/255），只做氛围不抢字；
2. 面板本身是半透明的（`theme.build_stylesheet(scrim=...)`），会把背景再压一层；
3. 用户还能用「暗化」滑块继续压。

**风格与能量的关系必须是同一套**：四种风格都只吃 `(energy, phase)` 两个输入，
这样「换风格」不会改变跟随感 —— 只是同一段音乐换成四种画法。
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

from app.audio_energy import (DECODE_SR, ENERGY_HZ, build_envelope, energy_at,
                              envelope_path, load_envelope, save_envelope, source_key)

# 风格表是**唯一真相源**：设置页的按钮、配置里的 preset 值、这里的绘制分发都取它。
# 加一种风格只改这一处（对应 memory 里「动效命名必须单一真相源」那条教训）。
LIVE_STYLES = (
    ("glow", "呼吸光晕"),
    ("ring", "音频环"),
    ("dust", "粒子浮尘"),
    ("aurora", "极光流"),
)
LIVE_KEYS = tuple(key for key, _label in LIVE_STYLES)
LIVE_BY_KEY = dict(LIVE_STYLES)


def live_label(key: str) -> str:
    """取风格中文名；未知 key 返回空串（调用方自己决定怎么兜）。"""
    return LIVE_BY_KEY.get(key, "")


def is_live_style(key: str) -> bool:
    return key in LIVE_BY_KEY


# 浮尘的固定种子：位置必须只由种子决定，否则每次 resize 粒子全跳一遍
_DUST_SEED = 20261103
_DUST = [(random.Random(_DUST_SEED + i).random(),
          random.Random(_DUST_SEED + 100 + i).random(),
          random.Random(_DUST_SEED + 200 + i).random(),
          random.Random(_DUST_SEED + 300 + i).random()) for i in range(130)]


def _with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlpha(int(max(0, min(255, alpha))))
    return c


def paint_live(painter: QPainter, width: int, height: int, style: str,
               phase: float, energy: float, accent: QColor,
               intensity: float = 1.0) -> None:
    """画一帧动态背景。`phase` 是秒（持续增长），`energy` 是 0~1 的当前能量。

    四种风格共用这一个入口，未知 style 退回 `glow`（绝不什么都不画 ——
    用户选了一个风格却看到空白底，会以为功能坏了）。
    """
    if width <= 0 or height <= 0:
        return
    k = max(0.0, min(1.0, intensity))
    if k <= 0.0:
        return
    e = max(0.0, min(1.0, energy))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if style == "ring":
        _paint_ring(painter, width, height, phase, e, accent, k)
    elif style == "dust":
        _paint_dust(painter, width, height, phase, e, accent, k)
    elif style == "aurora":
        _paint_aurora(painter, width, height, phase, e, accent, k)
    else:
        _paint_glow(painter, width, height, phase, e, accent, k)
    painter.restore()


def _paint_glow(painter: QPainter, w: int, h: int, phase: float,
                energy: float, accent: QColor, k: float) -> None:
    """三团柔和光团：随能量膨胀变亮，位置极缓慢游移。

    最克制的一种 —— 光团轮廓本身看不见，只把面板后面的底色"烘"暖一点。
    """
    unit = min(w, h)
    for i, (fx, fy, base, speed, lag) in enumerate((
            (0.28, 0.34, 0.46, 0.21, 0.0),
            (0.74, 0.62, 0.34, 0.16, 1.7),
            (0.52, 0.88, 0.26, 0.13, 3.4))):
        dx = math.sin(phase * speed + lag) * w * 0.035
        dy = math.cos(phase * speed * 0.8 + lag) * h * 0.030
        pulse = 0.88 + 0.12 * math.sin(phase * (0.6 + i * 0.25) + lag)
        radius = unit * base * pulse * (0.90 + 0.22 * energy)
        peak = (26 + 34 * energy) * k
        grad = QRadialGradient(QPointF(w * fx + dx, h * fy + dy), radius)
        for pos, factor in ((0.0, 1.0), (0.46, 0.42), (1.0, 0.0)):
            grad.setColorAt(pos, _with_alpha(accent, peak * factor))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(QPointF(w * fx + dx, h * fy + dy), radius, radius)


def _paint_ring(painter: QPainter, w: int, h: int, phase: float,
                energy: float, accent: QColor, k: float) -> None:
    """一圈环形的「伪频谱」：56 根短线绕中心排布，长度随能量起伏。

    只有单一能量值，所以柱高不可能真的各有各的 —— 用位置相关的相位差造出
    高低错落的观感（`sin(phase*2 + i*0.55)`），视觉上等价于频谱，
    但诚实地说：它反映的是整体响度，不是频段。
    半径取 0.40·min(w,h)：正好落在内容区外侧，绕开中间的字。
    """
    cx, cy = w * 0.5, h * 0.5
    # 半径 × (1 + 最长柱) 必须小于半高，否则上下两端的柱子会被窗口边裁掉。
    # 0.33 × 1.31 ≈ 0.43 < 0.5，留出约 7% 余量；之前用 0.40 时顶部直接切平。
    base_r = min(w, h) * 0.33
    bars = 56
    pen = QPen()
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(bars):
        ang = math.tau * i / bars + phase * 0.05
        wave = abs(math.sin(phase * 1.9 + i * 0.55))
        length = base_r * (0.05 + 0.26 * wave * energy)
        alpha = (34 + 56 * energy) * k * (0.55 + 0.45 * wave)
        pen.setColor(_with_alpha(accent, alpha))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(cx + math.cos(ang) * base_r, cy + math.sin(ang) * base_r),
            QPointF(cx + math.cos(ang) * (base_r + length),
                    cy + math.sin(ang) * (base_r + length)))

    ring_pen = QPen(_with_alpha(accent, (14 + 18 * energy) * k))
    ring_pen.setWidthF(1.0)
    painter.setPen(ring_pen)
    painter.drawEllipse(QPointF(cx, cy), base_r, base_r)


def _paint_dust(painter: QPainter, w: int, h: int, phase: float,
                energy: float, accent: QColor, k: float) -> None:
    """浮尘：130 粒细点缓慢上浮，亮度随能量呼吸。最安静的一种。"""
    brush = QColor()
    painter.setPen(Qt.PenStyle.NoPen)
    for x0, y0, size, seed in _DUST:
        speed = 0.006 + 0.016 * seed
        y = (y0 - phase * speed) % 1.0
        x = (x0 + math.sin(phase * 0.25 + seed * math.tau) * 0.012) % 1.0
        twinkle = 0.5 + 0.5 * math.sin(phase * 1.4 + seed * 12.0)
        alpha = (18 + 96 * energy * twinkle) * k
        brush = _with_alpha(accent, alpha)
        painter.setBrush(brush)
        painter.drawEllipse(QPointF(x * w, y * h),
                            0.7 + size * 2.0, 0.7 + size * 2.0)


def _paint_aurora(painter: QPainter, w: int, h: int, phase: float,
                  energy: float, accent: QColor, k: float) -> None:
    """极光：3 条宽幅色带缓慢流动，能量大时更亮更厚。

    两个坑（第一版都踩了，出图后才发现）：
    1. **不能用纯色填充**。实心色块读起来是"硬边色板"，不是极光 —— 极光的关键
       是上下边缘都化开。所以每条带用一条纵向渐变（透明→有色→透明）填闭合路径。
    2. **厚度必须留够边距**。带子太靠上/太靠下时会被窗口裁掉，裁口是一条直线，
       看起来像渲染错误。中心位置取 0.24 / 0.50 / 0.76，厚度上限压到 0.31h。
    """
    painter.setPen(Qt.PenStyle.NoPen)
    for band in range(3):
        center = h * (0.24 + band * 0.26)
        thickness = h * (0.20 + 0.04 * band) * (0.70 + 0.60 * energy)
        top_y = center - thickness / 2.0
        speed = 0.10 + band * 0.06
        sway = h * 0.028

        # 默认参数把循环变量绑进函数（ruff B023）：否则闭包晚绑定，
        # 三条带会全用最后一轮的 speed/band，画出来三条完全同步 —— 极光的"各自流动"就没了
        def edge(u: float, _speed=speed, _band=band, _sway=sway) -> float:
            return math.sin(u * 3.4 + phase * _speed + _band * 1.7) * _sway

        path = QPainterPath()
        steps = 20
        for i in range(steps + 1):
            u = i / steps
            y = top_y + edge(u)
            if i == 0:
                path.moveTo(u * w, y)
            else:
                path.lineTo(u * w, y)
        for i in range(steps, -1, -1):
            u = i / steps
            path.lineTo(u * w, top_y + thickness + edge(u))
        path.closeSubpath()

        peak = (16 + 30 * energy) * k
        grad = QLinearGradient(QPointF(0.0, top_y), QPointF(0.0, top_y + thickness))
        grad.setColorAt(0.0, _with_alpha(accent, 0.0))
        grad.setColorAt(0.42, _with_alpha(accent, peak))
        grad.setColorAt(0.62, _with_alpha(accent, peak * 0.8))
        grad.setColorAt(1.0, _with_alpha(accent, 0.0))
        painter.setBrush(grad)
        painter.drawPath(path)


def paint_live_scrim(painter: QPainter, width: int, height: int) -> None:
    """动态背景专用的暗角：中间留空、四周压暗。

    单独一条函数是因为它只对 `live` 生效 —— 图片背景不该被它改观感。
    有它才敢把动画铺满整窗：文字总在中间区域，边缘的动感不会吵到阅读。
    """
    if width <= 0 or height <= 0:
        return
    rect = QRectF(0, 0, width, height)
    grad = QRadialGradient(QPointF(width * 0.5, height * 0.5),
                           math.hypot(width, height) * 0.60)
    grad.setColorAt(0.0, QColor(0, 0, 0, 0))
    grad.setColorAt(0.62, QColor(0, 0, 0, 22))
    grad.setColorAt(1.0, QColor(0, 0, 0, 78))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawRect(rect)


class EnergyWorker(QThread):
    """后台算包络：先查缓存，未命中再解码。

    为什么一定要线程：4 分钟 mp3 解码约 0.3s，放在 UI 线程会让切歌时窗口卡一下 ——
    而切歌本来就有加载动画，多这一下就变成"卡顿"。算完前背景用时间驱动兜底。
    """

    ready = Signal(str, list)      # (track_id, envelope)
    failed = Signal(str, str)      # (track_id, 原因)

    def __init__(self, track_id: str, path: str, cache_dir: str, parent=None):
        super().__init__(parent)
        self._track_id = track_id
        self._path = path
        self._cache_dir = cache_dir

    def run(self) -> None:      # noqa: D401 - QThread 入口
        tid = self._track_id
        src = source_key(self._path)
        if not src:
            self.failed.emit(tid, "文件不存在或不可读")
            return
        cache_path = envelope_path(self._cache_dir, tid)
        cached = load_envelope(cache_path, src)
        if cached:
            self.ready.emit(tid, cached)
            return
        if self.isInterruptionRequested():
            return
        try:
            from app.lyrics_local_align import decode_mono
            samples, sr = decode_mono(self._path, DECODE_SR)
        except Exception as exc:                  # 解码器缺失/格式不支持/读失败
            self.failed.emit(tid, f"{type(exc).__name__}")
            return
        if self.isInterruptionRequested():
            return
        envelope = build_envelope(samples, sr)
        if not envelope:
            self.failed.emit(tid, "包络为空")
            return
        duration_ms = int(len(samples) / max(1, sr) * 1000)
        save_envelope(cache_path, envelope, duration_ms, src)
        self.ready.emit(tid, envelope)


def energy_for(envelope: list[float] | None, position_ms: int) -> float:
    """给 UI 用的薄包装：把「查表」这件事集中在一处，方便测试替换。"""
    return energy_at(envelope, position_ms, ENERGY_HZ)
