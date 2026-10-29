# 历史归档

本目录存放项目演进过程中的历史交付说明、一次性预览与早期开发脚本。它们已不再参与
当前构建或测试，仅作留档，方便回溯「某个版本当时做了什么、为什么这么做」。

当前主线文档在仓库根目录：`README.md`（概览）、`DESIGN.md`（设计决策与版本史）、
`ACCEPTANCE.md`（逐版本验收）、`TASK.md`（任务清单）。

## 目录说明

- `overview_v2.1.x.md` / `overview_v2.2.md` —— v2.1 各小版本及 v2.2 的交付说明
  （每个版本当时的改动摘要，内容已沉淀进 `DESIGN.md` 的对应章节）
- `overview_icon_fix.md` —— 早期图标修复记录
- `交付报告.md` —— v2.1 阶段的一次性交付报告
- `icon_preview/` —— 应用图标不同尺寸的预览图
- `probe/` —— 早期开发探针脚本与素材：
  - `probe_formats.py` —— 音频格式兼容性检查
  - `take_shots.py` —— 整窗截图脚本
  - `files/tone.*` —— 各格式的合成测试音源
  - `shots/` —— 主题截图

> 正式的可复用探针工具已收在仓库 `tools/` 目录（`probe_icons.py`、`probe_float_bar.py`、
> `probe_player_bar.py`、`probe_columns.py` 等），此处仅保留早期一次性脚本。
