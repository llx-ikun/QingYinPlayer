# 功能评估：歌词视频（文字 PV）导出

> 参照物：[852wa/JIZURA](https://github.com/852wa/JIZURA)（歌词 → 文字 PV 的浏览器 / AE 工具）
> 结论：**技术可行，且不需要新增任何第三方依赖**；但有一个必须先做技术验证（spike）的未知点。
> 本文只做评估，不改代码。

---

## 1. 结论先行

| 项 | 判断 |
|---|---|
| 可行性 | **可行**（Qt 原生能力已具备，`PySide6 6.12` 实测） |
| 新增依赖 | **零**（复用 Qt Multimedia 已打包的 FFmpeg 后端） |
| 最大未知 | `QMediaRecorder` 接收外部帧时**能否超实时喂帧**、能否无窗口运行 |
| 建议范围 | 先做「单曲 → 1080p30 MP4」最小闭环，样式预设与批量放二期 |
| 与现有代码冲突 | 低。主要是把 `LyricsPanel` 的绘制逻辑抽成纯函数，不动数据层 |
| 体积影响 | **0**（不新增 DLL；反而与「优化方案」里保留 QtMultimedia 的结论一致） |

**为什么不走别的路**（已排除）：

| 方案 | 否决理由 |
|---|---|
| 引入 `imageio-ffmpeg` / 自带 `ffmpeg.exe` | +30~70MB，且要处理分发许可与 PATH |
| 用 PyAV 编码 | 与优化方案「裁掉 av 的 68MB」直接冲突，等于为了导出把 68MB 加回来 |
| 纯 Python 写 MP4 封装 | 工作量大、易错，且要自己实现 H.264（不现实） |
| 只导出 PNG 序列让用户自己合 | 体验差，不符合「一键出片」 |

---

## 2. 技术路径

Qt 6.8+ 提供了「外部帧输入」能力，正好是浏览器 `WebCodecs` 的桌面等价物：

```
QImage（QPainter 画的每一帧）
   ↓ 包成 QVideoFrame（带时间戳）
QVideoFrameInput ──┐
                   ├─→ QMediaCaptureSession → QMediaRecorder → MP4
QAudioBufferInput ─┘   （PCM 来自 miniaudio 解码）
```

**实测确认可用**（本机 `PySide6 6.12.0`）：

```
QtMultimedia.QVideoFrameInput   ✓
QtMultimedia.QAudioBufferInput  ✓
QtMultimedia.QMediaRecorder     ✓
QMediaFormat.VideoCodec: MPEG4 / H264 / H265 / VP8 / VP9 / AV1 / MotionJPEG …
QMediaCaptureSession.audioBufferInput / videoFrameInput   ✓
```

### 渲染循环（核心设计）

```
for i in range(total_frames):          # total = 时长 × fps
    t = i * 1000 // fps                # 毫秒
    state = frame_state(lines, t, style)   # 纯函数：当前该显示哪几行、每行 typed 到第几个字
    img = QImage(W, H, ARGB32); img.fill(bg)
    p = QPainter(img); render_frame(p, state, style); p.end()
    input.sendVideoFrame(QVideoFrame(img, timestamp_us))
```

「当前行放大 + 逐字进度」这套逻辑**已经有了**，不用重写：

| 现有件 | 位置 | 复用方式 |
|---|---|---|
| `_line_delta(is_current)` | `ui/lyrics_panel.py:44` | 直接调用（当前行 +6 号字） |
| `_typed_from_words(words, text, pos)` | `ui/lyrics_panel.py:142` | 有 `WordSpan` 时走逐字精确进度 |
| `_typed_split(main_len, sub_len, p)` | `ui/lyrics_panel.py:108` | 无字级数据时按行进度估算 |
| `_draw_line(painter, rect, text, font, metrics, baseline, typed, …)` | `ui/lyrics_panel.py:373` | 已接收 QPainter，**改造成独立函数即可离屏调用** |
| `WordSpan` | `app/lyrics.py:26` | 数据结构不变 |
| 主题配色 | `ui/theme.py`（`THEME_*` + `derive_accent`） | 导出时套用当前主题 |

**唯一的结构性改动**：`_draw_line` 目前是 `LyricsPanel` 的方法，读 `self.xxx`。需要把「取样式/取颜色」的参数显式传进去，抽成模块级函数，让 widget 和导出器共用同一份绘制代码——**否则导出画面会和屏幕上不一致**，这是这类功能最常见的翻车点。

---

## 3. 必须先验证的未知点（spike，1~2 小时）

在写任何产品代码之前，先跑一个最小脚本回答三个问题：

| 问题 | 为什么是风险 | 若不成立的退路 |
|---|---|---|
| Q1：能否**超实时**喂帧？ | 录制器可能按真实时钟节拍消费，4 分钟的歌就要等 4 分钟；也可能允许尽快灌完 | 接受「导出耗时≈歌曲时长」，但要在 UI 上明说进度是按实时走的 |
| Q2：**无窗口/离屏**环境能否录制？ | 回归测试和 CI 都要离屏跑 | 导出改成独立子进程（参考现有单测的独立进程策略） |
| Q3：音频能否同步混入？ | `QAudioBufferInput` 要喂 PCM，格式/时长对不齐会音画不同步 | 一期只出**无声视频**，二期做混流；或先出 MP4 + 单独音轨 |

> spike 产物是一份 `tools/probe_lyric_video.py`，跑 5 秒素材，用 `ffprobe` 核对时长/帧率/音轨。
> **这一步不通过，就不进入实现阶段**——避免写完才发现编码器不配合。

---

## 4. 建议的产品形态（分期）

### 一期：最小闭环（推荐先做）

- 入口：歌词区右键 / 播放页按钮 → 「导出歌词视频」
- 选项：分辨率（720p / 1080p）、帧率（30）、样式（2~3 个内置）
- 复用当前主题配色与「当前行自动放大」行为
- 进度可取消（沿用现有 `QThread` + `requestInterruption` 模式）
- 产物：`<歌名>.mp4` 存到歌曲同目录或用户选的目录

### 二期：样式与批量化

| 能力 | 说明 | 对应 JIZURA 概念 |
|---|---|---|
| 样式预设 | 居中大字 / 卡拉OK扫光 / 双语上下行 / 竖排 | Expression Pack |
| 字体 | 可选系统字体（**不打包商业字体**，只列举本机已装字体） | Google Fonts 按需 |
| 背景 | 纯色 / 渐变 / 使用封面模糊放大 | — |
| 批量 | 整张歌单排队导出 | — |

### 明确不做

- **透明通道视频**：MP4/H.264 不支持 alpha；VP9 alpha 在 Qt 后端能否编码未经验证，不承诺。
- **时间轴编辑器**：那是 AE 的活，做不过它。
- **4K / 60fps**：收益低、耗时翻数倍。

---

## 5. 预期效果与性能估算

以 4 分钟歌曲、1080p、30fps 计：共 7200 帧。

| 环节 | 估算 |
|---|---|
| 单帧 QPainter 文字渲染 | 5~15 ms（取决于行数、阴影/发光等效果） |
| QImage → QVideoFrame 拷贝 + 编码 | 5~20 ms |
| 纯 CPU 总耗时 | 约 **1.5~4 分钟**（若可超实时） |
| 若只能实时录制 | 约 **4 分钟**（等于歌曲时长） |
| 输出体积 | 1080p30 H.264 静态画面为主，约 **20~60 MB** |

> 文字 PV 画面变化少、大面积纯色，H.264 压缩率很高，体积通常远小于实拍视频。

---

## 6. 涉及的关键文件与模块

| 文件 | 改动 | 性质 |
|---|---|---|
| `ui/lyrics_panel.py` | 把 `_draw_line` 及样式参数抽成模块级纯函数 | **重构**（风险点，必须保证屏幕显示不变） |
| `app/lyric_video.py` | **新增**：`frame_state()` 纯函数（时间 → 可见行 + 逐字进度） | 新增，可纯单测 |
| `app/video_export.py` | **新增**：QMediaRecorder 封装（建会话、喂帧、喂 PCM、落盘、取消） | 新增，依赖 Qt |
| `app/lyrics_local_align.py` | 复用 `decode_mono()` 拿 PCM 给音频轨 | 不改 |
| `ui/export_dialog.py` | **新增**：选项 + 进度 + 取消 | 新增 |
| `ui/main_window.py` | 接入导出入口与 toast | 小改 |
| `ui/theme.py` | 导出时读取配色，不新增主题 | 不改 |
| `build.py` | **无需改**（QtMultimedia 与 FFmpeg 已在包内） | 无 |
| `tests/test_lyric_video.py` | **新增**：帧状态纯逻辑单测（不碰 Qt） | 新增 |
| `tests/test_video_export.py` | **新增**：导出 1 秒、校验文件存在/时长/帧数 | 新增，需真实编码器 |

---

## 7. 验证方法与验收标准

### 验收标准

1. **一致性**：同一时刻 t，导出帧与界面截图在同一主题下的文字位置/字号/颜色差异在可接受范围（建议逐像素对比，平均差 < 3%）。
2. **正确性**：导出的 mp4 用 `ffprobe` 校验——时长与音频一致（误差 < 200ms）、帧率 = 30、有音轨。
3. **完整性**：7200 帧无丢帧（用 `ffprobe -count_frames` 核对）。
4. **可取消**：导出中途取消后不留下半截文件（原子写 `.part` → 改名）。
5. **不回归**：全量回归全绿，屏幕歌词显示与导出前**逐像素一致**（这条是硬门槛）。
6. **体积**：不新增任何 DLL，安装包体积不变。

### 验证步骤

```
1. spike：tools/probe_lyric_video.py 跑 5 秒 → ffprobe 核对        ← 前置门槛
2. 纯逻辑单测：frame_state 在 0s/中间/结尾/空歌词/无 WordSpan 下正确
3. 离屏导出 1 秒 → 校验文件与帧数
4. 真实导出 4 分钟歌 → 抽帧比对界面截图
5. 全量回归 + 真实桌面手动播放验证
```

---

## 8. 风险清单

| 风险 | 等级 | 说明与缓解 |
|---|---|---|
| 录制器只支持实时喂帧 | **高** | 先 spike；若成立，导出耗时≈歌曲时长，UI 必须明示，不能让用户以为卡死 |
| 编码器在无窗口环境不可用 | 中 | 退路：导出逻辑放独立子进程；或仅在真实桌面提供该功能，测试降级为「只测 frame_state」 |
| 重构 `_draw_line` 导致屏幕显示变化 | **高** | 重构前先加「屏幕渲染快照」回归测试，改完逐像素比对；一次只动一个函数 |
| 音画不同步 | 中 | 音频以样本数为唯一时钟，视频时间戳由样本位置反推，不用墙钟 |
| 中文字体缺失 | 低 | 只允许选本机已装字体；回退到 Qt 默认中文字体 |
| 导出时 CPU 打满影响播放 | 低 | 导出前暂停播放，或限制并发为 1 |

---

## 9. 与 JIZURA 的差异（为什么不能照抄）

| 对比项 | JIZURA | 轻音播放器（若做） |
|---|---|---|
| 运行形态 | 浏览器单文件 / AE 面板 | 桌面 Qt 应用 |
| 编码器 | 浏览器自带 WebCodecs（H.264 硬件加速） | Qt Multimedia + FFmpeg（纯 CPU） |
| 素材来源 | 用户上传歌词文本 | **直接读曲库**：音频、歌词、封面、逐字时间轴都已在本地 |
| 优势 | 排版模板丰富、有 AE 生态 | **零导入成本**：不用再传一遍文件，歌词/封面/时间轴现成 |
| 劣势 | 需要手动导入、无法读曲库元数据 | 样式模板要从零积累 |

**核心优势在「零导入」**：JIZURA 要用户把歌词贴进去、选字体、对时间；而轻音播放器里这些数据本来就齐了，包括 AI 逐字对齐产出的字级时间轴——**这是它做不到的**。

---

## 10. 建议的下一步

1. 先跑 §3 的 spike（1~2 小时，只产出探针脚本和一份结论）。
2. spike 通过 → 按一期范围实现；不通过 → 回到本文更新路径（子进程 / 仅真实桌面 / 放弃音轨）。
3. 若采用，需按项目铁律升 `APP_VERSION`（新功能属于程序改动）。
