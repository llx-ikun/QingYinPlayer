# v3.0.6 — AI 对齐后自动校正行轴

## 一句话结论

「歌词对不上人声」的根因不是 AI 对齐算错，而是**算对了字、没校正行**。v3.0.6 把
`retime_lines()` 接入渲染链，AI 对齐后自动用每行首字的实测时刻重打行时间轴，纯内存、零副作用。

## 现场与根因

《唯有追赶风的方向》LRC 首句标 `[00:03.50]`，但人声实测 8.9s 才起——本地近似对齐
前奏没算对，整条时间轴偏早 5.4s。

whisper 逐字对齐其实**已经算对了字级时刻**（sidecar 里首句 words 从 8920ms 开始），
但 sidecar 的 key 仍是原始 LRC 时间（3500ms）。渲染时：

- 行高亮按 `line.time_ms`（3500）提前亮
- 逐字扫光按 `line.words[0].start_ms`（8920）才动

两者错位 5.4s，视觉上就是「歌词对不上人声」。**重跑对齐没用**，根子在行轴。

## 修复

`retime_lines()` 从 v3.0.0 就写好且单测过，却一直没接入——当时的决策是「不自动写回
.lrc（改用户文件是破坏性动作）」。但实际上**行轴校正根本不需要写 .lrc**：

```python
def apply_track_words(lines, track_id, base_dir=None):
    return retime_lines(attach_words(lines, load_line_words(track_id, base_dir)))
```

贴完逐字数据后，内存里用每行 `words[0].start_ms` 重打 `time_ms`，`.lrc` 与 sidecar 都不动。

## 改动清单

| 文件 | 改动 |
|------|------|
| `app/lyrics_words.py` | `retime_lines()` 迁入；`apply_track_words()` 改为 `retime_lines(attach_words(...))` |
| `app/lyrics_asr.py` | 删本地 `retime_lines`，re-export 保 `la.retime_lines` 兼容 |
| `app/lyrics_multi.py` | 一处以 `v3.0.5` 开头的 docstring 触发版本号 AST 扫描，改 `自 3.0.5` |
| `app/version.py` | 3.0.5 → 3.0.6 |
| `tests/test_lyrics_words.py` | +2 例（复现 3500→8920 场景、min_gap 递增） |
| `DESIGN.md` | 决策 6 改写为「内存 retime」 |

## 验证

- **真机端到端**（真实 LRC + 真实 sidecar）：37 行全部有 words，首句 3500→8920、
  末句 120870→118060，5.4s 偏移消除；仅 1 行因 min_gap 被推 20ms（相邻实测首字只差
  100ms，预期行为）。
- **歌词相关 415 例** + `test_lyrics_multi` 47 例 + `test_build` 20 例全绿；ruff 干净。
- **全量回归** 36 个独立进程，唯一失败是 `test_build` 版本号扫描（v3.0.5 遗留 docstring），已修。

## 用户如何生效

**不用重新跑 AI 对齐**。sidecar 的逐字数据已经在，v3.0.6 的修复是「渲染时自动校正」。
重新打包后，直接播放这首歌，行高亮与逐字扫光就会同步对准人声。

## 遗留（诚实）

- **逐句色回归风险**：`lyrics_colors/<track_id>.json` 的键也是行 time_ms。AI 对齐**前**
  手动设的逐句色，在 retime 后键失配、静默回退全局色。边缘场景（先逐句设色再跑 AI 对齐），
  本次未处理，需要时可做「旧 time_ms → 新 time_ms」迁移。
