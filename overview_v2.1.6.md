# v2.1.6 交付概览：播放栏视觉打磨

> 日期：2026-10-27 · 基线：v2.1.5 (`a802188`) · 触发：用户截图圈出播放控制区「美化一下」

## 一、截图里能看到的问题

用户圈的是「循环 / 上一首 / 播放键 / 下一首 + 进度条」。放大到 3 倍逐个对比后，问题分成两类 —— 一类是审美，一类是**功能缺陷**：

| 现象 | 性质 |
|---|---|
| 循环图标画成「一段圆弧 + 两条斜线当箭头」，16px 下像刷新按钮 | 审美（语义误导） |
| 上一首的图标是 ▶\|（前进形状）、下一首是 \|◀ | **缺陷：方向画反了** |
| 进度手柄白心白环，压在白底上**完全看不见** | **缺陷：手柄隐形** |
| 时间 0:49 / 2:57 与滑块之间的留白不均匀 | 审美 |
| 控制行与进度行只隔 2px，几乎贴住 | 审美 |
| 播放键在浅色底上「平」，缺少层次 | 审美 |

## 二、改了什么

### 1. 控制图标重画（`ui/icons.py`）

- **`loop`**：改为标准 repeat 图形 —— 上下两条横线 + 两端反向箭头。
- **`repeat_one`**：同 repeat 中间加「1」。注意「1」用**矢量**画（竖笔 + 左上小旗），不用 `drawText`：16px 下字体渲染会歪。
- **`shuffle`**：原来是 7 段互不相连的碎线（完全读不出形状），改为两条交叉「车道」+ 右端箭头。
- **`prev` / `next` 方向修正**：prev = `|◀`、next = `▶|`。
- **`pause`** 竖线加宽（0.14 → 0.16）、**`play`** 三角略收窄。

### 2. 滑块质感（`ui/theme.py`）

轨道 4 → 3px；手柄改为**强调色实心圆 + SURFACE 外环**。

QSS 手柄有三个坑，必须同时对上，否则不是隐形就是方块：

1. **钮芯必须是有色实心** —— 白心 + 白环压在白底上等于隐形（这就是用户看不到手柄的原因）。
2. **`border-radius` = (width + 2×border) / 2** —— 按内容宽度算会得到圆角方块。
3. **`margin` 决定手柄盒高 = 轨道高 + 2×|margin|，必须 ≥ 手柄总高** —— 给不够 Qt 会把圆压成方块（seek 总高 14 → `-6`；音量 12 → `-5`）。

结论写了 5 个候选做过像素级对比才定下来（`shots/_handle_variants.png`）。

### 3. 播放键层次（`ui/player_bar.py`）

图标 18 → 20px，外加 `QGraphicsDropShadowEffect` 强调色柔和投影（QSS 没有 box-shadow）。主题切换由 `PlayerBar.refresh_theme()` 重染颜色。

### 4. 排版呼吸

- 控制行 / 进度行间距 2 → 6px。
- 按钮间距 6 → 4px（五个控件成组更紧凑）。
- 时间标签 `#TimeLabel` 12px，左端**右对齐**、右端**左对齐**，宽度 36 → 38 —— 时间贴住滑块两端，两侧留白对称。

### 5. 顺手修掉一个潜伏的抖动隐患（`ui/widgets.py`）

`ElidedLabel` 继承 `QLabel.minimumSizeHint()`，它是按**完整文本**算宽度的。一首 `Blazing Heart (英文版)` + 长艺人名，就能把 `PlayerBar` 最小宽度顶到 **1185px > 窗口最小宽 1100** —— 正是 v2.1.3 那个「窗口抖动 + 副标题被省略成 `…`」的成因。

本控件本来就负责省略文本，最小宽度给 0 才对。修复后同样长标题下实测 **1042**。

## 三、验证

| 项目 | 结果 |
|---|---|
| 手柄可见性（浅/深色） | `TestSliderKnob::test_handle_visible_on_light` / `_on_dark`：value=0 时扫手柄区，必须存在饱和蓝像素 |
| 手柄必须是圆 | `test_handle_round_not_square`：外接框四角不得被钮芯色填满 |
| 音量手柄同样不隐形 | `test_volume_handle_visible_on_light` |
| 时间标签对齐 | `test_time_labels_snug_to_slider` |
| 长标题不顶爆最小宽度 | `test_player_bar_fits_min_window_with_long_title`（1042 ≤ 1100） |
| 全量回归 | **17 个独立进程 240 项全绿** |
| 静态检查 | `ruff check .` → `All checks passed!` |
| 双 EXE | `build_v216.log`：smoke + 真实平台 8s 存活检查通过 |

**反向验证**（确认测试不是摆设）：
- 把 handle 的 `background` 改回 `#ffffff` → 手柄可见性 2 项立即失败。
- 移除 `ElidedLabel.minimumSizeHint()` 覆盖 → 长标题用例立即失败。

## 四、新增的调试工具

`tools/probe_player_bar.py`：真实平台单独渲染 `PlayerBar`（可指定主题 / 放大倍数），并打印 `minimumSizeHint().width()`。

```bash
env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_player_bar.py --out shots/bar.png --scale 3 --theme light
```

改播放栏这种 1-2px 级别的细节，全窗截图看不出来，必须单独放大到 3 倍逐像素对比 —— 手柄「隐形」就是靠它才发现的。

## 五、需要你确认的

- 观感：图标与滑块已按像素级对比调整，但**好不好看以你的眼睛为准**。
- 深色主题同步验证过（手柄同样可见、glow 亮度略高），如果你平时用深色，切过去扫一眼。
