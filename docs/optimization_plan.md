# 轻音播放器 优化方案（资源占用 / 打包体积）

> 目标软件：轻音播放器（`music-player/`，PySide6 本地播放器）
> 方案类型：优化提案（未改代码）。落地前需按 §8 验证，保持现有功能与接口不变。

---

## 1. 优化目标

- **主目标**：减少资源占用 —— 缩小打包体积（单文件 exe 与目录版解压体积）、缩短首次启动时间、减少内存中无用 DLL 的加载。
- **子目标**：消除一处误导性注释（`app/lyrics_asr.py` 关于 `av` 可排除的错误结论），提升可维护性。
- **非目标**：不改任何现有功能、不改对外接口（命令、数据格式、UI 行为均不变）；不碰 AI 逐字对齐的识别质量。

---

## 2. 当前问题与瓶颈

实测（`dist/QingYinPlayer-Portable/_internal`，目录版解压 316M，其中 `_internal` 304M）：

| 组件 | 体积 | 实际用途 | 结论 |
|---|---|---|---|
| PySide6（Qt 框架整体） | ~116M | GUI | **部分可裁** |
| ├ Qt6Quick + Qt6Qml + Qt6QmlModels + Qt6QmlMeta | ~12.9M | QML/Quick（纯 QWidgets 应用，未 import） | 可裁 |
| ├ Qt6Pdf | ~4.5M | PDF（未 import） | 可裁 |
| ├ Qt6VirtualKeyboard | ~0.4M | 虚拟键盘（未 import） | 可裁 |
| ├ opengl32sw.dll + Qt6OpenGL | ~21.9M | 软件 OpenGL（应用只用 QPainter 光栅） | 谨慎可裁 |
| ├ translations/ | ~7.4M | Qt 多语言（应用仅中文） | 可裁 ~7.2M |
| ├ Qt6Core/Gui/Widgets/Multimedia + FFmpeg 动态库 | 其余 | 核心 GUI + 音视频播放 | **保留** |
| PyAV（`av` + `av.libs`） | ~68M | whisper 的「传文件路径」解码链 | **可裁（需 stub）** |
| ctranslate2 | ~62M | whisper 推理引擎（C++ 扩展） | 保留 |
| numpy + numpy.libs | ~28M | `rms_fast`/whisper 数值 | 保留 |
| tokenizers | ~7.5M | 分词 | 保留 |
| libcrypto + libssl | ~9.3M | 模型下载的 https | 保留 |
| python313.dll 等 | ~10M | 运行时 | 保留 |

**核心瓶颈：存在两份 FFmpeg，其中一份完全没用到。**

1. `PySide6/avcodec-63.dll`、`avformat-63.dll` 等（约 19.5M）是 **QtMultimedia 自带** 的 FFmpeg，用于 QMediaPlayer 音视频播放 —— **必需**。
2. `av.libs/`（约 65M）+ `av/`（约 2.8M）是 **PyAV 自带** 的另一套 FFmpeg，只被 `faster_whisper` 的「直接传音频文件路径」解码路径用到 —— **本项目从不用这条路**（`app/lyrics_asr.py:decode_for_asr` 用 `miniaudio` 自己解码成 numpy 再喂 whisper）。

**发现的一处已知问题（文档 bug）**：`app/lyrics_asr.py:128-130` 注释声称「还让 `av`（68MB）可以从安装包里整个排除」。**这个结论是错的** —— 实际上 `av` 至今仍被打进包（本次实测确认 68M 还在），因为 `faster_whisper/__init__.py:1` 顶层 `from faster_whisper.audio import decode_audio`，而 `faster_whisper/audio.py:15` 顶层 `import av`。也就是说 **`import faster_whisper` 时 `av` 是硬依赖**，直接 `--exclude-module av` 会让 AI 对齐变成 `import_failed`。要真正排除必须配一个 stub（见 §3.1）。

---

## 3. 优化方案

### 3.1 高置信可裁：PyAV 双份 FFmpeg（省 ~68M，收益最大）

**做法**（二选一，推荐 A）：

- **方案 A（推荐）**：打包期 stub
  1. 新建 `packaging/av_stub/av/__init__.py`（空模块，仅 docstring 说明用途）。
  2. `build.py` 增加 `--paths <项目>/packaging/av_stub`，使 `import av` 命中 stub；
     同时 `--exclude-module av --exclude-module av.libs`，把真实 PyAV（及其 FFmpeg 库）整个剔除。
  3. 效果：`import av` 成功 → `faster_whisper` 正常导入；`decode_audio` 只在被真正调用时才会报错，
     而本应用**始终**走「预解码 numpy 喂 whisper」，永不调用它。
- **方案 B（零风险兜底）**：不排除 `av`，只修正 `lyrics_asr.py:128-130` 的错误注释，避免误导后续维护。

**关键验证点**：`faster_whisper/audio.py` 里唯一用 `av.` 的是 `decode_audio` 函数体（`av.audio.resampler`、
`av.open`、`av.error`、`av.audio.fifo`），`pad_or_trim` 是纯 numpy。顶层只有 `import av` 这一行。
因此空 stub 即可让「导入成功 + 永不调用 decode」成立。落地前必须用冻结产物实测（§8）。

### 3.2 高置信可裁：未使用的 Qt 模块（省 ~17.8M）

已 `grep` 确认 `app/`、`ui/`、`main.py` **没有任何** `QtQuick/QtQml/QtPdf/QtVirtualKeyboard/QtOpenGL/QtSvg` import。
在 `build.py` 增加：

```
--exclude-module PySide6.QtQuick
--exclude-module PySide6.QtQml
--exclude-module PySide6.QtPdf
--exclude-module PySide6.QtVirtualKeyboard
```

> 注意：PySide6 的 PyInstaller hook 可能仍会收集这些 DLL；需在打包后复核 `du -sh`，未生效再改用
> 自定义 hook 精确剔除对应 `Qt6*.dll`。QtSvg（596K）虽未显式 import，但 QIcon 可能经 imageformats
> 插件用到，体积小，先保留观察。

### 3.3 中置信可裁：Qt 多语言翻译（省 ~7.2M）

`_internal/PySide6/translations/` 打包了全部语言（7.4M）。应用文案为硬编码中文，仅需保留
`qtbase_zh_CN.qm`（约 200K）。做法：`--exclude-module` 无法精确到单个 `.qm`，需在构建后脚本里
删除非中文 `.qm`，或保留（影响很小，属锦上添花）。

### 3.4 谨慎可裁：软件 OpenGL（省 ~21.9M，风险最高）

`opengl32sw.dll`（20M）+ `Qt6OpenGL.dll`（1.9M）仅当 Qt 回退到软件 OpenGL 时才需要。
应用是纯 QPainter 光栅渲染，理论上不需要；但 QtMultimedia 的视频渲染、部分机器的显卡驱动路径
可能引用 RHI/OpenGL。**建议最后单独验证**：剔除后跑真实平台 + 播放视频，确认无崩溃再保留。

---

## 4. 预期效果

| 指标 | 当前 | 优化后（保守：3.1+3.2+3.3） | 优化后（激进：+3.4） |
|---|---|---|---|
| 目录版解压体积 | 316M | ~223M（-29%） | ~201M（-36%） |
| `_internal` | 304M | ~211M | ~190M |
| 单文件 exe（约 ×0.39 压缩） | ~123M | ~87M（-29%） | ~78M |
| 首次启动（解压 + 加载 DLL） | 基准 | 预计减少，随体积线性下降 | 更明显 |
| AI 逐字对齐可用性 | 正常 | **必须保持正常**（回归重点） | 同上 |

> onefile 的压缩比非均匀（DLL 已是编译产物），上表为按当前 0.39 折算的估算值，以最终打包实测为准。

---

## 5. 验收标准

1. **功能不变**：全量回归 `env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py` 全绿（含 `test_build`、`test_lyrics_asr`）。
2. **AI 对齐可用**：冻结产物 `QingYinPlayer.exe --check-ai` 报告首行 `轻音播放器 vX.Y.Z AI 自检`，
   且真实跑通一次逐字对齐（加载模型 → 识别 → 落盘 sidecar），**不出现 `import_failed` / segfault**。
3. **启动正常**：`build.py` 的 smoke test 与真实平台检查均通过。
4. **体积达标**：打包后 `du -sh` 对比，目录版 ≤ 目标值；`tools/make_release.py` 产物 SHA256 与体积记录更新。
5. **注释准确**：若采用方案 A，`lyrics_asr.py` 注释改为描述「已通过 stub 排除 av」的真实机制。

---

## 6. 涉及的关键文件与模块

| 文件 | 改动 |
|---|---|
| `build.py` | 增加 `--exclude-module av / av.libs / PySide6.QtQuick / QtQml / QtPdf / QtVirtualKeyboard`；`--paths` 指向 stub；可选构建后清理非中文 `.qm` |
| `packaging/av_stub/av/__init__.py` | **新增**：空 stub 模块（方案 A） |
| `app/lyrics_asr.py` | 仅改 `decode_for_asr` 上方注释（128-130 行），描述真实的 av 排除机制 |
| `tests/test_build.py` | 若该文件用 AST 扫 `build.py` 的 exclude 列表（防回归），需同步更新预期 |
| `tools/make_release.py` | 无需改（自动读取产物体积）；仅发布说明更新体积数字 |

---

## 7. 验证方法与测试 / 对比指标

**对比指标（打包前后各取一次）**：
- `du -sh dist/QingYinPlayer-Portable/_internal`、`ls -l dist/QingYinPlayer.exe`
- 首次启动耗时：`--smoke` 日志里的时间戳差值（同机同盘）

**验证流程（顺序执行，任何一步失败即回滚）**：

1. **基线回归**：优化前跑一次全量回归，留绿作为对照。
2. **改 `build.py` + 新增 stub**，`ruff check .` 通过。
3. **重打包**：`env -u PYTHONPATH .venv/Scripts/python.exe build.py`（约 4~5 分钟）。
4. **体积对比**：`du -sh` 确认是否达到 §4 预期；未生效则查 PyInstaller hook 是否仍收集。
5. **冻结自检**：`dist/QingYinPlayer.exe --check-ai`，读 `%TEMP%/qy_ai_check.txt` 首行确认 `vX.Y.Z AI 自检`。
6. **真实 AI 对齐**：用 `QY_DATA_DIR` 临时目录触发一次单曲逐字对齐，确认「解码→识别→落盘」全链无 `import_failed`。
7. **回归**：全量 `run_tests.py` 全绿（`test_player` 单独复跑、其余模块补跑，避免 offscreen 累积死锁误判）。
8. **激进项单独验证**：若做 §3.4，额外在真实桌面播放一段视频 + 滚动歌单，确认无崩溃。

**回滚**：本方案纯增量（新增 stub + 加 exclude），回退即删除对应 `--exclude-module` 与 stub 目录重新打包，无数据/接口风险。

---

## 8. 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| `av` 排除后 AI 对齐 `import_failed` | 高（功能损坏） | 必须配 stub + 冻结产物实测，未实测不合并 |
| QtQuick/Qml 被某条隐藏依赖引用 | 中（启动崩溃） | grep 已确认无 import；打包后 smoke + 真实平台双验证 |
| 软件 OpenGL 被显卡驱动路径引用 | 中（特定机器崩溃） | §3.4 放最后单独验证，可放弃 |
| PyInstaller hook 忽略 exclude | 低（省不下来） | 打包后 `du` 复核，必要时自定义 hook |
| 体积下降导致「下载更快」被误当版本差异 | 低 | 文档 + CHANGELOG 说明 |
