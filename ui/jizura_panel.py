# -*- coding: utf-8 -*-
"""JIZURA 歌词面板：用 JIZURA 引擎渲染的「封面模糊 + 居中歌词 + 桃红逐字」视觉。

v3.4.0 引入。这是把第三方开源引擎 JIZURA（https://github.com/852wa/JIZURA ，MIT）
「改一下」当作播放器的歌词面板 —— 不是拿它的海报式视频特效，而是复用它的
Canvas 排版/逐字/几何线稿能力，做出一块安静、居中、可读的歌词面板。

与原生 `lyrics_panel.LyricsPanel` 的区别（也是各自的取舍）：
- 原生面板：功能全（右键菜单 / 逐句颜色 / 打轴 / 颜色覆盖 / 双语逐字真实时间轴），
  但视觉是 QSS 列表风格；
- 本面板：视觉更强（封面模糊铺底 + 衬线歌名 + 桃红逐字 + 几何涂鸦 + 颗粒），
  但 v1 只做「同步歌词展示 + 逐字高亮」，不做右键菜单 / 打轴 / 逐句颜色。

代价：需要 QtWebEngine，打包会带上 `Qt6WebEngineCore.dll`（约 194MB）。因此本面板
是**可选模式**，默认仍走原生 `LyricsPanel`；只有在用户显式开启时才实例化（见
`main_window` / `now_playing` 的接入点）。

接口刻意对齐 `LyricsPanel` 的核心子集，便于作为「替换歌词部件」接入：
    set_synced(lines) / set_plain(lines) / set_empty(hint)
    update_position(ms)
    set_cover(pixmap) / set_meta(title, artist, album)
    seek_requested(int)  （v1 未接，预留）
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time

from PySide6.QtCore import QBuffer, QUrl, Qt, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from app.lyrics import LyricLine, format_lrc
from app.models import JIZURA_BG_LABELS, JIZURA_BACKGROUNDS, JIZURA_PALETTE_LABELS, JIZURA_PALETTES
from app.paths import resource_path

# WebEngine 在部分环境（尤其无 GPU 的 CI/offscreen）需要放开沙箱与 GPU 黑名单，
# 否则白屏或软渲染卡死。必须在 import QtWebEngine 之后、创建实例之前设置。
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--no-sandbox --ignore-gpu-blocklist --ignore-certificate-errors",
)


def _ensure_webengine_runtime() -> None:
    """打包态（PyInstaller）下把 WebEngine 的运行时路径指对。

    开发态这些变量都不用管，Qt 自己在 PySide6 目录里能找到东西。但打包后
    `QtWebEngineProcess.exe` / `resources/` / `qtwebengine_locales/` 都被摊进
    `sys._MEIPASS`，Qt 仍按「可执行文件旁边」找 —— 找不到的表现是**白屏且无报错**
    （子进程起不来，Chromium 直接不给画面），非常难查。所以显式兜一层：
    路径存在才设，不覆盖用户已有的环境变量。
    """
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", "") or ""
    if not base:
        return
    for exe in (os.path.join(base, "PySide6", "QtWebEngineProcess.exe"),
                os.path.join(base, "QtWebEngineProcess.exe"),
                os.path.join(base, "PySide6", "Qt", "bin", "QtWebEngineProcess.exe")):
        if os.path.isfile(exe):
            os.environ.setdefault("QTWEBENGINEPROCESS_PATH", exe)
            break
    for var, rel in (("QTWEBENGINE_RESOURCES_PATH", ("PySide6", "resources")),
                     ("QTWEBENGINE_LOCALES_PATH",
                      ("PySide6", "translations", "qtwebengine_locales"))):
        path = os.path.join(base, *rel)
        if os.path.isdir(path):
            os.environ.setdefault(var, path)


_ensure_webengine_runtime()

# 渲染节流：两次 runJavaScript 渲染之间的最小间隔（ms）。30fps 足够逐字动效顺滑，
# 再高只会白烧 CPU（引擎单帧绘制成本 ~7ms，瓶颈反而在 JS 桥的往返）。
#
# v3.4.3：**逐帧渲染不再走这条路**。原来每一帧都是一次 Python → JS 的
# `runJavaScript`，Qt 定时器的抖动 + IPC 排队会直接变成画面抖动（全屏时尤其明显）。
# 现在渲染交给 JS 侧的 `requestAnimationFrame` 自驱（见 PANEL_JS 的 play/pause/sync），
# Python 只在必要时校正时间基准，节流间隔降到 100ms 一次即可。
_RENDER_INTERVAL_MS = 33
# 时间基准校正间隔（ms）：rAF 自己外推，Python 每 100ms 对一次表就够，
# 超过 150ms 的漂移才硬拉（见 JS 侧 sync 的阈值），避免频繁跳帧。
_SYNC_INTERVAL_MS = 100

# 引擎加载后，JIZURA 的 UI 与 `J.uiApi` 要一点时间才就绪（PoC 实测 2.5s 稳妥）。
_BOOT_DELAY_MS = 2600

# 面板可选项：**颜色本身的唯一真相源是下面注入 JS 里的 PALETTES / BGS**
# （绘制发生在 JS 侧，颜色只能写在那里）；这里只从 `app.models` 的 key 元组与
# 显示名派生「给设置页用的下拉数据」，避免 Python 侧再抄一份颜色表。
# 顺序与名字改了要同步 models；`tests/test_jizura_panel.py` 会断言 JS 里的表
# 与 models 的元组完全一致，漂移会直接红。
PALETTE_OPTIONS: list[dict] = [{"key": k, "name": JIZURA_PALETTE_LABELS[k]}
                               for k in JIZURA_PALETTES]
BACKGROUND_OPTIONS: list[dict] = [{"key": k, "name": JIZURA_BG_LABELS[k]}
                                  for k in JIZURA_BACKGROUNDS]

_PALETTE_KEYS = tuple(p["key"] for p in PALETTE_OPTIONS)
_BG_KEYS = tuple(b["key"] for b in BACKGROUND_OPTIONS)


def normalize_palette(key: str | int | None) -> str:
    """把任意输入收敛成合法的配色 key（不认识就回 "random"）。"""
    if isinstance(key, int) and 0 <= key < len(_PALETTE_KEYS):
        return _PALETTE_KEYS[key]
    return key if key in _PALETTE_KEYS else "random"


def normalize_background(key: str | int | None) -> str:
    """把任意输入收敛成合法的背景 key（不认识就回 "auto"）。"""
    if isinstance(key, int) and 0 <= key < len(_BG_KEYS):
        return _BG_KEYS[key]
    return key if key in _BG_KEYS else "auto"


def _engine_path() -> str:
    """引擎 HTML 的绝对路径：打包态走 `_MEIPASS`，开发态走仓库 `assets/jizura/`。

    用 file:// 直接加载（引擎是单文件、仅依赖 Google Fonts，已在下文离线降级）。
    """
    return resource_path("assets", "jizura", "engine.html")


# ---------------------------------------------------------------------------
# 注入到引擎页面的 JS：隐藏 UI、注册「丰富面板」布局与「封面涂鸦」背景，
# 并提供 `window.__panel` 桥。核心绘制逻辑与 PoC（jizura_poc/poc_panel_rich.py）
# 一致，这里是「改造后」的产物。
# ---------------------------------------------------------------------------
PANEL_JS = r"""
(() => {
  const J = window.J;
  if (!J) return 'NO_J';

  /* 1) 离线字体降级：引擎默认按需从 Google Fonts 拉字体，本地/断网会卡 5s 超时。
     面板只用到 gothic/mincho/mono，直接交给系统字体栈（微软雅黑 / 宋体 / 等宽），
     不再发起任何网络请求。 */
  J.ensureFonts = async () => {};
  J.GOOGLE_FONTS_URL = '';

  /* 2) 隐藏整套视频制作 UI，只留画布。用 visibility 而非 display，避免把画布压塌。 */
  (() => {
    const v = document.getElementById('view'); const keep = new Set();
    for (let n = v; n; n = n.parentElement) keep.add(n);
    document.querySelectorAll('body *').forEach(el => {
      if (!keep.has(el)) el.style.setProperty('visibility', 'hidden', 'important');
    });
    document.body.style.setProperty('margin', '0', 'important');
    document.body.style.setProperty('background', '#080F1B', 'important');
    v.style.setProperty('visibility', 'visible', 'important');
  })();

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v == null ? a : v));
  const easeOut = k => 1 - Math.pow(1 - k, 3);
  const fmt = s => {
    s = Math.max(0, Math.round(s));
    const m = Math.floor(s / 60);
    return m + ':' + String(s % 60).padStart(2, '0');
  };

  window.__COVER__ = new Image();
  window.__COVER_READY__ = false;
  window.__COVER__.onload = () => { window.__COVER_READY__ = true; window.__TINT__ = null; };
  window.__META__ = {};

  /* 噪点 tile：一次生成，pattern 平铺 */
  const grainTile = () => {
    if (window.__GRAIN__) return window.__GRAIN__;
    const S = 180, c = document.createElement('canvas'); c.width = c.height = S;
    const x = c.getContext('2d'), id = x.createImageData(S, S);
    for (let i = 0; i < id.data.length; i += 4) {
      const v = Math.random() * 255 | 0;
      id.data[i] = id.data[i + 1] = id.data[i + 2] = v; id.data[i + 3] = 20;
    }
    x.putImageData(id, 0, 0); window.__GRAIN__ = c; return c;
  };
  /* 封面取色：只让「有彩」像素参与（权重=饱和度²），避免大面积米白把画面冲灰 */
  const tintOf = () => {
    if (window.__TINT__) return window.__TINT__;
    const img = window.__COVER__;
    if (!img || !img.complete || !img.naturalWidth) return null;
    const s = 64, c = document.createElement('canvas'); c.width = c.height = s;
    const x = c.getContext('2d'); x.drawImage(img, 0, 0, s, s);
    let d; try { d = x.getImageData(0, 0, s, s).data; } catch (e) { return null; }
    let r = 0, g = 0, b = 0, wsum = 0, ar = 0, ag = 0, ab = 0;
    for (let i = 0; i < d.length; i += 4) {
      const R = d[i], G = d[i + 1], B = d[i + 2];
      ar += R; ag += G; ab += B;
      const mx = Math.max(R, G, B), mn = Math.min(R, G, B), sat = mx ? (mx - mn) / mx : 0;
      const w = sat * sat; r += R * w; g += G * w; b += B * w; wsum += w;
    }
    const n = d.length / 4;
    window.__TINT__ = wsum < 0.6 ? [ar / n | 0, ag / n | 0, ab / n | 0]
                                 : [r / wsum | 0, g / wsum | 0, b / wsum | 0];
    return window.__TINT__;
  };

  /* ---------- 配色 ---------- */
  J.STYLES.doodle = {
    name: '封面涂鸦', desc: '封面模糊铺底 · 几何线稿 · 桃红高亮',
    schemes: [{ bg: '#232830', fg: '#FFFFFF', sub: '#C9D2DE', accent: '#FF8FB6',
                accent2: '#F7CE5E', ink: '#FFFFFF', dim: '#1B2026',
                ghostA: '#FFFFFF', ghostB: '#FF8FB6' }],
    fonts: { display: ['mincho_bold'], serif: ['mincho_bold'], body: ['gothic_med'], mono: ['mono'] },
    texture: { grain: 0.06, paper: 0, scan: 0 }, ghost: 0.25, bias: {}, decor: {}, hud: false,
  };
  if (!J.STYLE_ORDER.includes('doodle')) J.STYLE_ORDER.push('doodle');

  /* ---------- 布局：信息栏 + 歌词面板 + HUD ---------- */
  J.register('layout', 'panelrich', {
    name: '丰富面板', fits: () => true,
    plan: () => ({ font: 'gothic_black', rows: 3, gap: 1.48, dimA: 0.92 }),
    render(env) {
      const W = env.W, H = env.H, sc = env.sc, ctx = env.ctx;
      const P = env.cut.params || {};
      const K = P.rows == null ? 3 : P.rows;
      const gap = P.gap || 1.48, dimA = P.dimA == null ? 0.92 : P.dimA;
      const lines = window.__PANEL_LINES__ || [];
      const cur = env.cut.line, t = env.t || 0;
      const dur = (env.plan && env.plan.duration) || 1;
      const M = window.__META__ || {};
      const size = Math.max(13, Math.min(H * 0.0525, W * 0.0356));
      const lh = size * gap, CX = W / 2, CY = H * 0.518, padX = W * 0.085;

      /* planner 会把一行切成多个 ~1s 的 cut 并写回行时间，逐字进度要按「整行」算 */
      let lineStart = env.cut.start, lineEnd = env.cut.end;
      {
        const cs = (env.plan && env.plan.cuts) || []; let k = -1;
        for (let i = 0; i < cs.length; i++) if (cs[i] === env.cut) { k = i; break; }
        if (k >= 0) {
          let a = k, b = k;
          while (a > 0 && cs[a - 1].line === cur && Math.abs(cs[a - 1].end - cs[a].start) < 0.03) a--;
          while (b < cs.length - 1 && cs[b + 1].line === cur && Math.abs(cs[b + 1].start - cs[b].end) < 0.03) b++;
          lineStart = cs[a].start; lineEnd = cs[b].end;
        }
      }
      const lineDur = Math.max(0.5, lineEnd - lineStart);
      const pIn = clamp((t - lineStart) / 0.45, 0, 1);
      const pSing = clamp((t - lineStart) / lineDur, 0, 1);
      const slide = (1 - easeOut(pIn)) * (size * 0.22);

      let bb = null;

      /* 当前行背后的横向柔光（跟随随机 accent 色） */
      {
        const bandW = W * 0.50, bandH = size * 1.85;
        const acc = J.hex(sc.accent);
        const g2 = ctx.createLinearGradient(CX - bandW / 2, 0, CX + bandW / 2, 0);
        g2.addColorStop(0, 'rgba(' + acc[0] + ',' + acc[1] + ',' + acc[2] + ',0)');
        g2.addColorStop(0.5, 'rgba(' + acc[0] + ',' + acc[1] + ',' + acc[2] + ',0.065)');
        g2.addColorStop(1, 'rgba(' + acc[0] + ',' + acc[1] + ',' + acc[2] + ',0)');
        ctx.save(); ctx.fillStyle = g2;
        ctx.fillRect(CX - bandW / 2, CY - slide - bandH / 2, bandW, bandH); ctx.restore();
      }

      const put = (text, d, isCur) => {
        if (!text) return;
        const fall = Math.max(0, 1 - Math.abs(d) / (K + 6.0));
        let a = isCur ? 1 : Math.max(0.20, dimA * fall);
        if (!isCur && Math.abs(d) >= K) a *= easeOut(pIn);
        if (!isCur) {
          env.draw({ text, font: P.font || 'gothic_black', size, x: CX, y: CY + d * lh,
                     track: 0.03, lead: 1.1, color: sc.fg, alpha: a });
          return;
        }
        const done = pSing * (text.length - 0.001);
        bb = env.draw({
          text, font: P.font || 'gothic_black', size, x: CX, y: CY - slide,
          track: 0.05, lead: 1.1, color: sc.fg, alpha: 1,
          charFn(i) {
            const k = i - done;
            if (k <= -0.5) return { color: sc.accent };
            if (k >= 0.5) return { color: J.mix(sc.accent, '#7A8088', 0.55), a: 0.96 };
            const b = 1 - Math.abs(k) * 2;
            return { color: sc.accent, s: 1 + 0.14 * b, dy: -size * 0.032 * b };
          },
        });
      };

      if (cur != null && cur >= 0 && lines[cur]) {
        for (let d = -K; d <= K; d++) {
          if (d === 0) continue;
          const ln = lines[cur + d]; if (!ln || !ln.text) continue;
          put(ln.text, d, false);
        }
        put(lines[cur].text, 0, true);
      } else {
        put(env.cut.text || env.cut.lineText || '', 0, true);
      }

      /* 当前行两侧展开的细线 + 端点 */
      if (bb) {
        const ex = easeOut(pIn);
        const halfW = Math.max(size * 0.8, (bb.x1 - bb.x0) / 2);
        const stick = size * 0.42 * ex, ly = CY - slide;
        const lwL = Math.max(1, H / 900), gapOut = halfW + size * 0.44;
        env.line([[CX - gapOut - stick, ly], [CX - gapOut, ly]], sc.accent, lwL, 0.50 * ex);
        env.line([[CX + gapOut, ly], [CX + gapOut + stick, ly]], sc.accent, lwL, 0.50 * ex);
        env.circle(CX - gapOut - stick, ly, Math.max(1.1, H / 680), sc.accent, null, 1, 0.70 * ex);
        env.circle(CX + gapOut + stick, ly, Math.max(1.1, H / 680), sc.accent, null, 1, 0.70 * ex);
      }

      /* 顶部信息栏 */
      const ty = H * 0.080, lwT = Math.max(1, H / 900);
      env.circle(padX, ty, Math.max(2.4, H / 260), sc.accent, null, 1, 0.95);
      env.draw({ text: 'NOW PLAYING', font: 'mono', size: Math.max(9, H * 0.0152),
                 x: padX + H * 0.027, y: ty, color: sc.sub, alpha: 0.70,
                 track: 0.34, lead: 1, align: 'left' });
      if (M.album) env.draw({ text: M.album, font: 'mono', size: Math.max(9, H * 0.0152),
                 x: W - padX, y: ty, color: sc.sub, alpha: 0.44, track: 0.22, lead: 1, align: 'right' });
      if (M.title) env.draw({ text: M.title, font: 'mincho_bold', size: Math.max(14, H * 0.042),
                 x: padX, y: H * 0.144, color: sc.fg, alpha: 0.96, track: 0.06, lead: 1, align: 'left' });
      if (M.artist) env.draw({ text: M.artist, font: 'gothic_light', size: Math.max(10, H * 0.0192),
                 x: padX, y: H * 0.190, color: sc.sub, alpha: 0.56, track: 0.08, lead: 1, align: 'left' });
      env.line([[padX, H * 0.224], [W * 0.268, H * 0.224]], sc.fg, lwT, 0.17);
      env.line([[padX, H * 0.232], [W * 0.176, H * 0.232]], sc.accent, lwT, 0.40);

      /* 底部 HUD */
      const by = H * 0.888, bR = H * 0.048;
      const bx0 = padX, bx1 = W - padX - bR * 2 - H * 0.030;
      const prog = clamp(t / dur, 0, 1);
      env.line([[bx0, by], [bx1, by]], sc.fg, lwT, 0.26);
      if (prog > 0.001) {
        const px2 = bx0 + (bx1 - bx0) * prog;
        env.line([[bx0, by], [px2, by]], sc.accent, lwT * 1.8, 0.95);
        env.circle(px2, by, Math.max(2.2, H / 280), sc.accent, null, 1, 1);
      }
      const tf = Math.max(9, H * 0.0175);
      env.draw({ text: fmt(t), font: 'mono', size: tf, x: bx0, y: by - H * 0.032,
                 color: sc.sub, alpha: 0.70, track: 0.12, lead: 1, align: 'left' });
      env.draw({ text: fmt(dur), font: 'mono', size: tf, x: bx1, y: by - H * 0.032,
                 color: sc.sub, alpha: 0.46, track: 0.12, lead: 1, align: 'right' });

      /* 右下圆形封面 + 环形进度 */
      const ccx = W - padX - bR, ccy = by - H * 0.010, img = window.__COVER__;
      if (img && img.complete && img.naturalWidth) {
        ctx.save(); ctx.beginPath(); ctx.arc(ccx, ccy, bR, 0, Math.PI * 2); ctx.clip();
        const s = Math.max(bR * 2 / img.naturalWidth, bR * 2 / img.naturalHeight) * 1.10;
        ctx.drawImage(img, ccx - img.naturalWidth * s / 2, ccy - img.naturalHeight * s / 2,
                      img.naturalWidth * s, img.naturalHeight * s);
        ctx.fillStyle = 'rgba(6,10,18,0.34)'; ctx.fillRect(ccx - bR, ccy - bR, bR * 2, bR * 2);
        ctx.restore();
      }
      env.circle(ccx, ccy, bR, null, sc.fg, lwT, 0.22);
      env.arc(ccx, ccy, bR + H * 0.0070, -90, -90 + 360 * prog, sc.accent, lwT * 1.7, 0.92);

      return bb;
    },
  });

  /* ---------- 背景：封面模糊 + 色染 + 漂浮线稿 + 颗粒 ---------- */
  J.register('bg', 'coverrich', {
    name: '封面涂鸦', subtle: true,
    draw(env) {
      const W = env.W, H = env.H, ctx = env.ctx, t = env.t || 0;
      const lw = Math.max(1.1, W / 1200), img = window.__COVER__;
      /* 主题底色：跟配色方案一起选（palette.bg）。压暗层、中央光晕、上下渐变都从它
         派生，避免「选了暖色主题、背景还是冷蓝」的割裂。 */
      const L = window.__LOOK__ || rollLook();
      const BG = L.bg || '#080F1B';
      const rgba = (hex, a) => {
        const c = J.hex(hex);
        return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
      };
      const glowHi = J.mix(BG, '#FFFFFF', 0.30), glowMid = J.mix(BG, '#FFFFFF', 0.15);
      const edgeDark = J.mix(BG, '#000000', 0.55);
      if (img && img.complete && img.naturalWidth) {
        const s = Math.max(W / img.naturalWidth, H / img.naturalHeight) * 1.16;
        ctx.save(); ctx.filter = 'blur(56px) saturate(1.45)';
        ctx.drawImage(img, (W - img.naturalWidth * s) / 2, (H - img.naturalHeight * s) / 2,
                      img.naturalWidth * s, img.naturalHeight * s);
        ctx.filter = 'none'; ctx.restore();
        /* 压暗 0.84（原 0.78）：背景色是用户自己选的，得让它真的看得见。
           0.78 时白底封面的模糊层会把自己的亮度压过底色 —— 选「纯黑」也像灰雾，
           那「独立背景色」就白做了。封面色只留 0.20 的软光提示（原 0.28）。 */
        env.rect(0, 0, W, H, BG, 0.84);
        const tint = tintOf();
        if (tint) {
          ctx.save(); ctx.globalCompositeOperation = 'soft-light'; ctx.globalAlpha = 0.20;
          ctx.fillStyle = 'rgb(' + tint[0] + ',' + tint[1] + ',' + tint[2] + ')';
          ctx.fillRect(0, 0, W, H); ctx.restore();
        }
        /* 中央一盏「主题光」：从底色提亮，而不是固定冷蓝 */
        const gl = ctx.createRadialGradient(W / 2, H * 0.50, 0, W / 2, H * 0.50, Math.min(W, H) * 0.62);
        gl.addColorStop(0, rgba(glowHi, 0.15)); gl.addColorStop(0.55, rgba(glowMid, 0.055));
        gl.addColorStop(1, rgba(BG, 0)); ctx.fillStyle = gl; ctx.fillRect(0, 0, W, H);
      } else {
        env.rect(0, 0, W, H, BG);
      }
      const gt = ctx.createLinearGradient(0, 0, 0, H * 0.30);
      gt.addColorStop(0, rgba(edgeDark, 0.60)); gt.addColorStop(1, rgba(edgeDark, 0));
      ctx.fillStyle = gt; ctx.fillRect(0, 0, W, H * 0.30);
      const gb = ctx.createLinearGradient(0, H, 0, H * 0.74);
      gb.addColorStop(0, rgba(edgeDark, 0.56)); gb.addColorStop(1, rgba(edgeDark, 0));
      ctx.fillStyle = gb; ctx.fillRect(0, H * 0.74, W, H * 0.26);
      const g = ctx.createRadialGradient(W / 2, H * 0.54, Math.min(W, H) * 0.10,
                                         W / 2, H * 0.54, Math.max(W, H) * 0.72);
      g.addColorStop(0, 'rgba(0,0,0,0)');
      g.addColorStop(0.55, 'rgba(0,0,0,0.22)');
      g.addColorStop(1, 'rgba(0,0,0,0.62)');
      ctx.save(); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); ctx.restore();

      const WHITE = '#FFFFFF', ph = t * 0.19;
      const WARM = L.warm, GHOST = L.ghost;
      const warmCol = L.warmOn ? WARM : WHITE;
      const ghostCol = L.ghostOn ? GHOST : WHITE;
      const dot = (x, y, r, a, col) => env.circle(W * x, H * y, H * r, col, null, 1, a);
      const ring = (x, y, r, a, col) => env.circle(W * x, H * y, H * r, null, col, lw, a);
      const tri = (x, y, r, a, col) => env.poly([
        [W * x, H * y - H * r], [W * x + W * r * 0.9, H * y + H * r * 0.55],
        [W * x - W * r * 0.9, H * y + H * r * 0.55]], col, a);
      const plus = (x, y, r, a, col) => {
        const th = H * r * 0.40;
        env.line([[W * x - H * r, H * y], [W * x + H * r, H * y]], col, th, a);
        env.line([[W * x, H * y - H * r], [W * x, H * y + H * r]], col, th, a);
      };
      const arcL = (x, y, r, a0, a1, a, col) => env.arc(W * x, H * y, H * r, a0, a1, col, lw * 1.05, a);
      const ln = (x0, y0, x1, y1, a, col, w) =>
        env.line([[W * x0, H * y0], [W * x1, H * y1]], col, w == null ? lw * 0.9 : w, a);

      /* 四套几何构图，随机选一套；元素位置/尺寸/透明度由种子抖动，配色跟随随机色。
         涂鸦全部压在四角与边缘，中央留给歌词，不随构图而乱入信息区。 */
      const j = L, C = j.comp;
      if (C === 0) {
        arcL(-0.055 + j.j1, 0.520, 0.300 * j.s1, -66, 70, j.a1, WHITE);
        arcL(-0.055 + j.j1, 0.520, 0.185 * j.s1, -54, 58, j.a1 * 0.5, WHITE);
        dot(0.905, 0.238 + j.j2, 0.026 * j.s2, j.a2, warmCol);
        ring(0.905, 0.238 + j.j2, 0.062 * j.s2, j.a1, WHITE);
        plus(0.128 + j.j3, 0.436, 0.032 * j.s3, j.a2, warmCol);
        tri(0.058, 0.762 + j.j4, 0.042 * j.s4, j.a3, WHITE);
        ln(0.104, 0.768 + j.j4, 0.168, 0.768 + j.j4, j.a3, WHITE);
        arcL(1.020, 0.470, 0.255 * j.s1, 96, 268, j.a1, WHITE);
        for (let i = 0; i < 3; i++)
          ln(0.900 + i * 0.030, 0.700, 0.900 + i * 0.030 - 0.052, 0.785, j.a3 - i * 0.028, WHITE);
      } else if (C === 1) {
        ring(0.900, 0.240 + j.j2, 0.070 * j.s1, j.a1, WHITE);
        tri(0.090, 0.250 + j.j1, 0.046 * j.s2, j.a2, warmCol);
        for (let i = 0; i < 3; i++) dot(0.080, 0.720 + i * 0.032, 0.010, j.a3, WHITE);
        plus(0.880, 0.740 + j.j4, 0.030 * j.s4, j.a2, ghostCol);
        ln(0.100, 0.300, 0.880, 0.680, j.a1 * 0.7, WHITE);
        for (let i = 0; i < 3; i++) ln(0.940, 0.360 + i * 0.055, 0.940, 0.398 + i * 0.055, j.a3, WHITE);
      } else if (C === 2) {
        for (let i = 0; i < 4; i++) ln(0.085, 0.300 + i * 0.085, 0.085, 0.345 + i * 0.085, j.a1 - i * 0.015, WHITE);
        arcL(1.005, 0.520, 0.270 * j.s1, 100, 265, j.a1, WHITE);
        dot(0.095, 0.245 + j.j1, 0.024 * j.s2, j.a2, warmCol);
        ring(0.095, 0.245 + j.j1, 0.050 * j.s2, j.a1, WHITE);
        tri(0.895, 0.730 + j.j4, 0.044 * j.s4, j.a3, ghostCol);
        for (let i = 0; i < 5; i++) dot(0.300 + i * 0.085, 0.815, 0.009, j.a3 * 0.8, WHITE);
      } else {
        arcL(-0.045 + j.j1, 0.500, 0.280 * j.s1, -62, 72, j.a1, WHITE);
        plus(0.120 + j.j3, 0.400, 0.030 * j.s3, j.a2, warmCol);
        ring(0.905, 0.780 + j.j4, 0.078 * j.s4, j.a1, WHITE);
        dot(0.905, 0.780 + j.j4, 0.024, j.a2, warmCol);
        tri(0.885, 0.240 + j.j2, 0.042 * j.s2, j.a2, ghostCol);
        for (let i = 0; i < 3; i++) dot(0.070, 0.700 + i * 0.034, 0.011, j.a3, WHITE);
        arcL(0.500, 0.430, 0.360 * j.s1, 210, 250, j.a1 * 0.7, WHITE);
        arcL(0.500, 0.430, 0.360 * j.s1, 290, 330, j.a1 * 0.7, WHITE);
      }
      const gtile = grainTile();
      if (gtile) {
        ctx.save(); ctx.globalCompositeOperation = 'overlay'; ctx.globalAlpha = 0.55;
        ctx.fillStyle = ctx.createPattern(gtile, 'repeat'); ctx.fillRect(0, 0, W, H); ctx.restore();
      }
    },
  });

  /* ---------- 前景配色（可选）----------
     只决定「高亮行 / 未唱字 / 进度条 / 装饰」的颜色。每套都按暗底挑过，
     看得清。`sel` 为下标或 key；0 / 'random' 表示交给 `J.randomPalette` 随机。
     构图抖动仍随机（同一首歌内稳定），只有「色」被锁定。

     `bg` 字段只是「背景 = 跟随配色」模式下的推荐底色，不再强制 ——
     背景由下面的 BGS 独立选（用户要求「独立背景色」）。 */
  const PALETTES = [
    { key: 'random',    name: '随机',   random: true },
    { key: 'rose',      name: '桃红',   accent: '#FF8FB6', warm: '#F7CE5E', bg: '#080F1B' },
    { key: 'cyan',      name: '青蓝',   accent: '#4FD8E8', warm: '#FFD166', bg: '#05141A' },
    { key: 'amber',     name: '琥珀',   accent: '#FFB547', warm: '#FF7A5C', bg: '#160F07' },
    { key: 'violet',    name: '紫罗兰', accent: '#A78BFA', warm: '#F472B6', bg: '#0E0A1A' },
    { key: 'mint',      name: '薄荷',   accent: '#6EE7B7', warm: '#FCD34D', bg: '#05140E' },
    { key: 'ice',       name: '冰蓝',   accent: '#7DD3FC', warm: '#C4B5FD', bg: '#07121C' },
    { key: 'vermilion', name: '朱红',   accent: '#FF7A5C', warm: '#FFD93D', bg: '#170C07' },
    { key: 'forest',    name: '森绿',   accent: '#86EFAC', warm: '#FDE68A', bg: '#09130B' },
  ];
  let lookSel = 0;   // 前景：0 = 随机

  /* ---------- 背景底色（独立可选）----------
     0 = 跟随配色（取 PALETTES 里搭配的推荐底），1 = 随机，其余为固定深色。
     全部是深色：面板文字是白的，浅底会糊。前景锁定的色在 rollLook 里还会过
     一遍 `J.fitContrast`，所以碰上「石墨」这种偏亮的底也不会看不清。 */
  const BGS = [
    { key: 'auto',    name: '跟随配色' },
    { key: 'random',  name: '随机' },
    { key: 'night',   name: '夜蓝',   hex: '#080F1B' },
    { key: 'teal',    name: '墨青',   hex: '#05141A' },
    { key: 'cocoa',   name: '深褐',   hex: '#160F07' },
    { key: 'plum',    name: '深紫',   hex: '#0E0A1A' },
    { key: 'pine',    name: '墨绿',   hex: '#05140E' },
    { key: 'glacier', name: '冰蓝',   hex: '#07121C' },
    { key: 'ember',   name: '炭红',   hex: '#170C07' },
    { key: 'moss',    name: '苔绿',   hex: '#09130B' },
    { key: 'ink',     name: '纯黑',   hex: '#050607' },
    { key: 'slate',   name: '石墨',   hex: '#14161A' },
  ];
  let lookBg = 0;    // 背景：0 = 跟随配色

  function rollLook(sel, bgSel) {
    if (sel != null) {
      const i = typeof sel === 'number' ? sel : PALETTES.findIndex(p => p.key === sel);
      if (i >= 0) lookSel = i;
    }
    if (bgSel != null) {
      const j = typeof bgSel === 'number' ? bgSel : BGS.findIndex(b => b.key === bgSel);
      if (j >= 0) lookBg = j;
    }
    const seed = (Math.random() * 1e9) | 0;
    const rnd = J.rng(seed);
    const base = PALETTES[lookSel] || PALETTES[0];
    const bsel = BGS[lookBg] || BGS[0];

    /* 顺序不能反：先定底、再按这块底算前景。
       底有三态 —— 固定色 / 随机（从固定色池挑）/ 跟随配色（用推荐底）。 */
    let bg;
    if (bsel.hex) bg = bsel.hex;
    else if (bsel.key === 'random') {
      const pool = BGS.filter(x => x.hex).map(x => x.hex);
      bg = pool[rnd.int(0, pool.length - 1)];
    } else bg = base.bg || '#080F1B';

    let accent, warm;
    if (base.random) {
      const pal = J.randomPalette(bg, rnd);
      accent = pal.accent; warm = pal.ghostA;
    } else {
      /* 锁定色也过一遍对比度校正：底比推荐底亮时（石墨）才不会糊成一团 */
      accent = J.fitContrast(base.accent, bg, 3);
      warm = J.fitContrast(base.warm, bg, 2.4);
    }
    const sch = J.STYLES.doodle.schemes[0];
    sch.accent = accent;
    sch.accent2 = warm;
    sch.ghostA = warm;
    sch.ghostB = accent;
    window.__LOOK__ = {
      seed, comp: rnd.int(0, 3), pal: lookSel, palKey: base.key, palName: base.name,
      bgSel: lookBg, bgKey: bsel.key, bgName: bsel.name,
      accent, warm, ghost: accent, bg,
      j1: rnd.range(-0.03, 0.03), j2: rnd.range(-0.03, 0.03),
      j3: rnd.range(-0.04, 0.04), j4: rnd.range(-0.03, 0.03),
      s1: rnd.range(0.82, 1.18), s2: rnd.range(0.82, 1.18),
      s3: rnd.range(0.80, 1.20), s4: rnd.range(0.80, 1.20),
      a1: rnd.range(0.10, 0.18), a2: rnd.range(0.20, 0.34),
      a3: rnd.range(0.08, 0.16), a4: rnd.range(0.12, 0.22),
      warmOn: rnd.chance(0.62), ghostOn: rnd.chance(0.5),
    };
    return window.__LOOK__;
  }

  /* ---------- 桥：外部（Python）通过它驱动面板 ---------- */
  const view = document.getElementById('view');
  const stripCut = c => { if (c) { c.trans = null; c.decor = []; c.kime = false; c.treat = 'none'; c.treatP = {}; } };
  const staticDraw = (title, rows) => {
    const W = J.ui.plan.W, H = J.ui.plan.H, x = view.getContext('2d');
    x.clearRect(0, 0, W, H);
    const B = (window.__LOOK__ && window.__LOOK__.bg) || '#080F1B';
    const bg = x.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, J.mix(B, '#FFFFFF', 0.05)); bg.addColorStop(1, B);
    x.fillStyle = bg; x.fillRect(0, 0, W, H);
    const cx = W / 2;
    x.textAlign = 'center'; x.textBaseline = 'middle';
    if (title) {
      x.fillStyle = 'rgba(255,255,255,0.92)';
      x.font = '700 ' + (H * 0.046) + 'px "Microsoft YaHei",sans-serif';
      x.fillText(title, cx, H * 0.34);
    }
    x.fillStyle = 'rgba(201,210,222,0.78)';
    const fs = H * 0.024, lh = fs * 1.7;
    x.font = '500 ' + fs + 'px "Microsoft YaHei",sans-serif';
    const list = (rows || []).slice(0, 7);
    const y0 = title ? H * 0.46 : H * 0.44;
    list.forEach((t, i) => x.fillText(String(t).slice(0, 40), cx, y0 + i * lh));
  };

  window.__PANEL_LINES__ = [];
  window.__panel = {
    ready: true,
    mode: 'empty',
    _t: 0,
    setMeta(m) { window.__META__ = m || {}; },
    setCover(dataUrl) {
      if (dataUrl) window.__COVER__.src = dataUrl; else window.__COVER_READY__ = false;
      window.__TINT__ = null;
    },
    clear(hint) {
      this.mode = 'empty';
      this._hint = hint || '暂无歌词';
      window.__PANEL_LINES__ = [];
      J.uiApi.pause(); J.ui.plan.events = [];
      staticDraw('', [this._hint]);
    },
    setPlain(lines) {
      this.mode = 'plain';
      this._rows = lines || [];     /* 存一份：切配色/背景时要重画 */
      window.__PANEL_LINES__ = [];
      J.uiApi.pause(); J.ui.plan.events = [];
      staticDraw(window.__META__.title || '', this._rows);
    },
    setLyrics(lrc) {
      this.mode = 'synced';
      this._lrc = lrc;
      const P = J.ui.project;
      P.lyrics = lrc; P.lang = 'zh-Hans'; P.style = 'doodle'; P.unify = false; P.typeset = false;
      P.title = ''; P.artist = '';
      P.fx = { motion: 0.10, glitch: 0, chroma: 0, decor: 0, density: 0.2, texture: 0,
               flash: false, onTwos: false, koma: 0, hud: 'off', bgSwitch: 0,
               hideNo: false, hideTime: false };
      window.__PANEL_LINES__ = J.parseLyrics(lrc).lines;
      const ov = {};
      window.__PANEL_LINES__.forEach((l, i) => {
        if (!l.text) return;
        ov[i] = { layout: 'panelrich', bg: 'coverrich', enter: 'cut', exit: 'cut',
                  hold: 'still', cam: 'push', decor: [], treat: 'none' };
      });
      rollLook();
      P.overrides = ov;
      J.uiApi.replan();
      (J.ui.plan.cuts || []).forEach(stripCut);
      J.uiApi.pause(); J.ui.plan.events = [];
      this.render(this._t);
    },
    /* 一次设好前景 + 背景：分开调会各自 replan 一遍，白烧一次解析 */
    setLook(sel, bgSel) {
      rollLook(sel, bgSel);
      this._repaint();
    },
    /* 切换前景配色 */
    setPalette(sel) {
      this.setLook(sel, null);
    },
    /* 切换背景底色：与前景色解耦，只换底（前景是「随机」时会按新底重算） */
    setBg(sel) {
      this.setLook(null, sel);
    },
    /* 换色后重画一遍当前内容。三种模式各有各的画法，别只处理 synced ——
       否则在「暂无歌词」/纯文本态切色会看到颜色没变（用户眼里就是「没反应」）。 */
    _repaint() {
      if (this.mode === 'synced' && this._lrc) this.setLyrics(this._lrc);
      else if (this.mode === 'plain') staticDraw(window.__META__.title || '', this._rows || []);
      else staticDraw('', [this._hint || '暂无歌词']);
    },
    /* ---------- 自驱渲染（v3.4.3） ----------
       Python 每帧发一次 runJavaScript 会让「Qt 定时器抖动 + IPC 排队」变成画面抖动。
       改成 JS 侧 requestAnimationFrame 自己跑：一帧一次绘制，天然对齐屏幕刷新率，
       掉帧也只是少画一帧，不会像 IPC 那样堆积。Python 只在切歌/拖动进度/暂停时
       用 sync() 校一次时间基准。 */
    _raf: 0,
    _baseT: 0,
    _baseWall: 0,
    _playing: false,
    _loop() {
      if (this._raf) return;
      const step = () => {
        if (!this._playing) { this._raf = 0; return; }
        this.render(this._baseT + (performance.now() - this._baseWall) / 1000);
        this._raf = requestAnimationFrame(step);
      };
      this._raf = requestAnimationFrame(step);
    },
    play(ms) {
      if (ms != null) this._baseT = ms / 1000;
      this._baseWall = performance.now();
      this._playing = true;
      this._loop();
    },
    pause(ms) {
      if (ms != null) this._baseT = ms / 1000;
      this._playing = false;
      if (this._raf) { cancelAnimationFrame(this._raf); this._raf = 0; }
      this.render(this._baseT);
    },
    sync(ms) {
      const target = (ms || 0) / 1000;
      if (!this._playing) { this._baseT = target; this.render(target); return; }
      const est = this._baseT + (performance.now() - this._baseWall) / 1000;
      /* 只有明显跑偏才重定基准：每次都拉会让画面在边界上来回跳（看起来像抖） */
      if (Math.abs(est - target) > 0.15) {
        this._baseT = target; this._baseWall = performance.now();
      }
    },

    /* ---------- 铺满模式（v3.4.3，全屏用） ----------
       contain：等比完整显示（默认，非 16:9 留边）；
       cover  ：等比放大到铺满视口、裁掉溢出部分 —— 不留黑边，也不拉伸变形。 */
    _fit: 'contain',
    setFit(mode) {
      this._fit = (mode === 'cover') ? 'cover' : 'contain';
      this._applyFit();
    },
    _applyFit() {
      const v = document.getElementById('view');
      if (!v) return;
      if (!this._css0) {
        this._css0 = v.style.cssText;
        this._origParent = v.parentElement;
        this._origNext = v.nextSibling;
      }
      if (this._fit !== 'cover') {
        v.style.cssText = this._css0;
        if (this._origParent && v.parentElement !== this._origParent) {
          this._origParent.insertBefore(v, this._origNext);
        }
        return;
      }
      /* 关键：把画布**搬出**原来的祖先链，直接挂到 body 上做 fixed 全屏。
         只改祖先的 width/height 是没用的 —— 实测（probe_fit_cover）引擎那几层
         容器还有别的尺寸来源，改完只是把画布放大了几个像素，仍然留边。
         搬出来之后 100vw×100vh + object-fit:cover 就是确定的：等比放大铺满、
         裁掉溢出部分，不拉伸变形。 */
      if (v.parentElement !== document.body) {
        this._origParent = this._origParent || v.parentElement;
        document.body.appendChild(v);
      }
      v.style.cssText = this._css0 +
        ';position:fixed !important;inset:0 !important;' +
        'width:100vw !important;height:100vh !important;' +
        'max-width:none !important;max-height:none !important;' +
        'aspect-ratio:auto !important;object-fit:cover !important;' +
        'z-index:2147483647 !important;';
    },
    render(t) {
      this._t = t;
      if (this.mode !== 'synced') return;
      J.ui.t = t;
      if (view.width !== J.ui.plan.W || view.height !== J.ui.plan.H) {
        view.width = J.ui.plan.W; view.height = J.ui.plan.H;
      }
      J.ui.renderer.frame(view.getContext('2d'), J.ui.plan, t, { scale: 1 });
    },
  };
  /* 视口变化（进出全屏 / 拖窗口改尺寸）时重算铺满缩放；contain 下不用管 */
  window.addEventListener('resize', () => {
    if (window.__panel && window.__panel._fit === 'cover') window.__panel._applyFit();
  });
  return 'panel ready';
})()
"""


class _PanelPage(QWebEnginePage):
    """捕获 JS 的 console.log（预留：点击歌词跳转的桥，v1 未用）。"""

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        # 预留通道，暂不处理；不打印以免刷屏。
        return


class JizuraLyricsPanel(QWidget):
    """用 JIZURA 引擎渲染的歌词面板（QtWebEngine 包裹）。

    接口对齐 `LyricsPanel` 的核心子集。面板固定逻辑分辨率 1280×720，由 CSS 等比
    缩放到部件尺寸（16:9 之外自动留黑边，背景本身就是深色，留边不可见）。
    """

    seek_requested = Signal(int)  # ms —— v1 预留，暂未从 JS 侧发信号
    # 右键菜单里「切回原生歌词面板」——原生面板的右键功能（重新匹配 / 打轴 /
    # 逐句颜色）视觉面板都不做，所以必须留一条回去的路，否则进来就出不去。
    native_panel_requested = Signal()

    def __init__(self, parent=None, engine_path: str | None = None):
        super().__init__(parent)
        self.setObjectName("Panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._view = QWebEngineView(self)
        self._page = _PanelPage(self._view)
        self._view.setPage(self._page)
        # Chromium 自带的右键菜单（后退/另存为…）对本地播放器毫无意义，
        # 换成我们自己的：只放「切回原生面板」这一条。
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._view)

        self._ready = False
        self._mode = "empty"
        self._position_ms = 0
        self._last_render = 0.0
        # v3.4.3：播放态与铺满模式。暂停时不跑 rAF（省电），全屏时 cover 铺满。
        self._playing = False
        self._fit = "contain"
        self._last_sync = 0.0
        self._engine_path = engine_path or _engine_path()
        # 这三项要先有初值：页面就绪前 set_cover / set_meta 可能已经调过，
        # `_push_meta_cover` 一读属性就炸（之前就是漏了初始化）。
        self._meta: dict = {}
        self._cover_dataurl = ""
        self._palette = "random"
        self._background = "auto"
        # 最近一次内容（"synced"/"plain"/"empty" + 载荷）：引擎就绪前设的歌词
        # 全被 ready 闸挡掉了，就绪后靠它补发。
        self._content: tuple[str, object] = ("empty", None)

        self._page.loadFinished.connect(self._on_load)
        self._load_engine()

    # ------------------------------------------------------------------ 内部

    def _load_engine(self) -> None:
        self._view.load(QUrl.fromLocalFile(self._engine_path))

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        act = menu.addAction("切回原生歌词面板")
        act.triggered.connect(self.native_panel_requested.emit)
        menu.addSeparator()
        hint = menu.addAction("（重新匹配 / 打轴 / 逐句颜色在原生面板里）")
        hint.setEnabled(False)
        menu.exec(self._view.mapToGlobal(pos))

    def _on_load(self, ok: bool) -> None:
        if not ok:
            # 页面本身没加载成功（最常见的原因：engine.html 没被打进包）。
            # 原来这里静默 return，问题就表现成「面板一片空白、但没有任何报错」——
            # 光靠看代码找不到，所以至少留一行痕迹给 smoke 日志。
            print(f"[jizura] 引擎页加载失败: {self._engine_path}", file=sys.stderr)
            return
        # 引擎 UI 与 J.uiApi 需要一点时间才就绪（PoC 实测 2.5s 稳妥）
        QTimer.singleShot(_BOOT_DELAY_MS, self._inject)

    def _inject(self) -> None:
        self._page.runJavaScript(PANEL_JS, lambda r: self._on_ready(r))

    def _on_ready(self, result) -> None:
        self._ready = bool(result)
        if not self._ready:
            return
        # 页面就是绪前（引擎注入要 2.6s）外部可能已经 set_synced / set_cover / 切色，
        # 这些调用当时都被 `_js` 的 ready 闸丢掉了。这里按「元信息 → 外观 → 内容」
        # 重放一遍，否则接进播放器后打开的第一首歌是一块「暂无歌词」的空面板。
        self._push_meta_cover()
        self._apply_look()          # 此时 JS 侧还是 empty，重画很便宜
        self._replay_content()      # 放上真正的歌词（synced 只在这里 replan 一次）
        self._render(force=True)
        # 就绪前可能已经进出过全屏 / 已经处于播放态，这两项状态要补推，
        # 否则「先开全屏再出画面」会退回归 16:9 留边、且动画不跑。
        self._js(f"__panel.setFit({json.dumps(self._fit)});")
        self._apply_play_state()

    def _replay_content(self) -> None:
        kind, payload = self._content
        if kind == "synced":
            self._send_lyrics(payload or [])
        elif kind == "plain":
            self._js(f"__panel.setPlain({json.dumps(list(payload or []), ensure_ascii=False)});")
        else:
            hint = payload if isinstance(payload, str) else "暂无歌词"
            self._js(f"__panel.clear({json.dumps(hint, ensure_ascii=False)});")

    def _send_lyrics(self, lines: list) -> None:
        lrc = format_lrc(lines)
        self._js(f"__panel.setLyrics({json.dumps(lrc, ensure_ascii=False)});")

    def _apply_look(self) -> None:
        """把「前景配色 + 背景底色」推给页面（两者独立，缺省值也要推一次）。"""
        if not self._ready:
            return
        self._js(
            f"__panel.setLook({json.dumps(self._palette)}, "
            f"{json.dumps(self._background)});"
        )

    def _push_meta_cover(self) -> None:
        if not self._ready:
            return
        self._js(f"__panel.setMeta({self._meta_json()});")
        if self._cover_dataurl:
            self._js(f"__panel.setCover({json.dumps(self._cover_dataurl)});")

    def _meta_json(self) -> str:
        return json.dumps(getattr(self, "_meta", {}) or {}, ensure_ascii=False)

    def _js(self, code: str) -> None:
        if self._ready:
            self._page.runJavaScript(code)

    def _render(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_render < _RENDER_INTERVAL_MS / 1000.0:
            return
        self._last_render = now
        if self._mode == "synced":
            self._js(f"__panel.render({self._position_ms / 1000.0:.3f});")

    # ------------------------------------------------------------------ 对外

    def set_meta(self, title: str = "", artist: str = "", album: str = "") -> None:
        self._meta = {"title": title or "", "artist": artist or "", "album": album or ""}
        self._push_meta_cover()

    def set_cover(self, pixmap: QPixmap | None) -> None:
        """设置封面。QPixmap → PNG base64 data URL 传给页面。"""
        self._cover_dataurl = ""
        if pixmap is not None and not pixmap.isNull():
            buf = QBuffer()
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            if pixmap.save(buf, "PNG"):
                raw = bytes(buf.data())
                self._cover_dataurl = "data:image/png;base64," + base64.b64encode(raw).decode()
            buf.close()
        self._push_meta_cover()
        if self._mode == "synced":
            self._render(force=True)

    def set_palette(self, key: str | int = "rose") -> None:
        """切换**前景配色**（高亮行 / 未唱字 / 进度条 / 装饰）。

        可选 key 见 `PALETTE_OPTIONS`：random / rose / cyan / amber / violet /
        mint / ice / vermilion / forest，也可传下标。不认识的值回落到 random。

        只换色，构图抖动仍随机（同一首歌内稳定）；当前歌词会重放一次以让新色生效。
        """
        self._palette = normalize_palette(key)
        if self._ready:
            self._js(f"__panel.setPalette({json.dumps(self._palette)});")

    def set_background(self, key: str | int = "auto") -> None:
        """切换**背景底色**（独立于前景配色，可自由组合）。

        可选 key 见 `BACKGROUND_OPTIONS`：auto（跟随配色）/ random / night / teal /
        cocoa / plum / pine / glacier / ember / moss / ink / slate，也可传下标。
        不认识的值回落到 auto。
        """
        self._background = normalize_background(key)
        if self._ready:
            self._js(f"__panel.setBg({json.dumps(self._background)});")

    def set_synced(self, lines: list[LyricLine]) -> None:
        """设置同步歌词并渲染。`lines` 转回 LRC 文本交给引擎（其自会按行排时间）。"""
        self._mode = "synced" if lines else "empty"
        self._content = ("synced", lines) if lines else ("empty", None)
        if lines:
            self._send_lyrics(lines)
        else:
            self._js('__panel.clear("暂无歌词");')
        if self._mode == "synced":
            self._render(force=True)

    def set_plain(self, lines: list[str]) -> None:
        self._mode = "plain" if lines else "empty"
        self._content = ("plain", list(lines)) if lines else ("empty", None)
        if lines:
            self._js(f"__panel.setPlain({json.dumps(list(lines), ensure_ascii=False)});")
        else:
            self._js('__panel.clear("暂无歌词");')

    def set_empty(self, hint: str | None = None) -> None:
        self._mode = "empty"
        self._content = ("empty", hint)
        self._js(f"__panel.clear({json.dumps(hint or '暂无歌词', ensure_ascii=False)});")

    def set_source(self, text: str | None) -> None:
        # v1 不展示来源小字（JIZURA 面板信息栏已满），保留接口兼容
        return

    def update_position(self, position_ms: int) -> None:
        """喂一个播放位置。

        v3.4.3 起**不再逐帧渲染**：画面由 JS 侧 `requestAnimationFrame` 自驱，
        这里只按 `_SYNC_INTERVAL_MS` 定期校正一次时间基准 —— 每帧都发一次
        runJavaScript 会让 Qt 定时器抖动 + IPC 排队变成肉眼可见的抖动。
        """
        self._position_ms = int(position_ms)
        if self._mode != "synced":
            return
        now = time.monotonic()
        if now - self._last_sync < _SYNC_INTERVAL_MS / 1000.0:
            return
        self._last_sync = now
        self._js(f"__panel.sync({self._position_ms});")

    def set_playing(self, playing: bool) -> None:
        """播放 / 暂停：控制 JS 侧 rAF 循环的启停。暂停时真的不画，不空转烧 CPU。"""
        playing = bool(playing)
        if playing == self._playing:
            return
        self._playing = playing
        self._apply_play_state()

    def _apply_play_state(self) -> None:
        if not self._ready:
            return
        if self._playing:
            self._js(f"__panel.play({self._position_ms});")
        else:
            self._js(f"__panel.pause({self._position_ms});")

    def set_fit(self, mode: str = "contain") -> None:
        """contain：等比完整显示（默认，非 16:9 会留边）；cover：铺满裁边（全屏用）。

        全屏态必须用 cover —— 否则宽屏上仍是中间一块 + 上下黑边，等于没全屏。
        """
        self._fit = "cover" if mode == "cover" else "contain"
        self._js(f"__panel.setFit({json.dumps(self._fit)});")

    # ---------- 可见性 / 尺寸：藏起来就别让 rAF 空转 ----------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._playing:
            self._apply_play_state()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        if self._ready:
            self._js("__panel.pause();")

    def resizeEvent(self, event) -> None:  # noqa: N802
        """控件尺寸变了（拖窗口 / 进出全屏）要重算 cover 的缩放倍数。

        光靠页面里的 `resize` 监听不够：搬进全屏窗口那一刻，Chromium 的合成器
        有时晚一拍才更新视口，实测会停在旧尺寸上（画面缩在左上角 + 一块黑）。
        所以这里从 Qt 侧再补一次。
        """
        super().resizeEvent(event)
        if self._fit == "cover":
            self.refresh_fit()

    def refresh_fit(self) -> None:
        """按当前 `_fit` 重新套一次几何（外部窗口在尺寸稳定后再喊一次）。"""
        self._js(f"__panel.setFit({json.dumps(self._fit)});")
