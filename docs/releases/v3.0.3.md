# v3.0.3 — 提高 AI 逐字对齐准确率

## 结论

✅ 三块改进全部落地并单测通过：**信号处理（onset 峰吸附）** + **语言自动识别（英文歌）** + **质量档位（大 beam）**。

全量回归：**34 模块全绿**（11m37s），ruff 干净。

## 这次做了什么

用户需求「减少 AI 逐字对齐误差、提高准确率」，范围拍板为「全都要 + 英文歌按汉字占比猜 + 手动指定」。

### 误差源诊断（按影响排序）

| # | 误差源 | 修法 |
|---|--------|------|
| 1 | `_spread` 纯均分（whisper 常把 3~7 字并成一个词，等分让节奏错位） | 词窗内用 onset 峰定位字边界 |
| 2 | `snap_to_energy` 只找 RMS 谷（谷=换气口/句间，字间边界其实在能量上升沿） | 新增 onset 峰吸附，与谷吸附互补 |
| 3 | `language="zh"` 写死（英文歌识别成乱码 → 匹配率 0） | 汉字占比猜语言 + 右键/设置手动指定 |
| 4 | int8 + beam=5 精度上限 | 质量档位 → beam 可调（fast/balanced/quality） |

### 改了什么（文件级）

- **`app/lyrics_asr.py`**（核心）
  - 新增 `onset_envelope(rms, hop_ms, diff_ms)`：半波整流的短时能量增量，抓音节起音上升沿。
  - 新增 `snap_to_onset(...)`：字边界 ±120ms 内吸到 onset 峰，`best_val > 0` 守卫让静音/稳态不挪。
  - `align_lyrics(..., onset=)`：流水线 `_spread` → `_fill_gaps` → `snap_to_energy`（谷）→ `snap_to_onset`（峰）。
  - `align_track` 一次 `rms_fast` 后派生 onset 透传。
  - 新增 `guess_language(lines)`：CJK 汉字数 ≥ 拉丁字母数 → zh，否则 en，纯标点回退 zh。
  - `LyricsAsrWorker` 默认 `language="auto"`、新增 `quality` 参数，`run()` 解析语言 + 映射 beam。
  - `transcribe`/`align_track` 增 `beam_size`；`AI_QUALITY_BEAM = {fast:1, balanced:5, quality:10}`。
- **`app/models.py`**：新增 `LYRICS_AI_LANGUAGES`/`LYRICS_AI_QUALITIES` 常量 + `Settings.lyrics_ai_language`/`lyrics_ai_quality` 两字段（含 to_dict/from_dict 收敛）。
- **`ui/settings_dialog.py`**：AI 逐字对齐区新增「识别语言」「识别质量」两个下拉。
- **`ui/lyrics_panel.py`**：右键「AI 对齐歌词（逐字）」改成子菜单（自动识别语言 / 按中文 / 按英文），信号带语种。
- **`ui/main_window.py`**：单曲对齐按右键语种传参、批量对齐用全局设置；新增两个设置回调。
- **`ui/dialogs.py`**：批量对话框透传语言 + 质量给 worker。
- **`app/version.py`**：3.0.2 → 3.0.3。

## 关键设计取舍

1. **onset 峰吸附为什么和 RMS 谷吸附不冲突**：谷适合句间（换气口），峰适合字间（音节起音）。静音段 onset 全 0，`best_val > 0` 守卫会让边界留在谷里不动；有声段才拽到起音点。找不到峰就保持均分，**保证不退步**。
2. **语言不用 whisper 自判**：中英混杂/粤语会误判，汉字占比是确定性逻辑、可单测。whisper 不吃 `"auto"`，所以在 worker `run()` 里先解析成具体语种再喂。
3. **「换大模型」其实早已支持**：模型档位 tiny/base/small 本就可换，这次补的是 beam 大小（质量档位）。

## 测试

- 新增 14 例单测：`onset_envelope`（4）、`snap_to_onset`（5）、`guess_language`（6）、onset 集成（2，含零回归）。
- 更新 2 处既有测试：`_FakeWorker` 加 language/quality 参数；右键菜单语言信号从无参改带 str。
- ruff 全绿；全量回归 34 模块全绿（11m37s）。

## 量化口径（诚实说明）

逐字时间轴**没有 ground truth**，无法直接量「误差多少 ms」。这次用两层兜住正确性：

- **合成包络单测**：已知起音点位置，断言「吸附后边界比均分更接近真值」。
- **真实曲库观察**：匹配率 / 平均置信度 / `max_shift_ms` 这些已有指标继续观察趋势；行级误差量化仍待真人声素材（遗留 E4，未变）。

## 遗留 / 待办（未变）

- 行级误差量化 `tools/eval_align.py` 缺真人声素材。
- av（68MB）stub 优化需单独验证冻结后 import。
- 纯文本歌词「AI 打行轴」（`retime_lines` 已备）。
