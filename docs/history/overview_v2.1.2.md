# v2.1.2 交付概述：导入弹窗关闭失效 + 浮动工具条改版

## 结论 ✅已验证
两处问题均已修复并随双 EXE 重建交付；全量回归 13 进程 163/163 全绿，ruff 清零。

## 修复 1：导入完成弹窗「关闭」按了没反应
- **根因**：`ImportProgressDialog` 完成后，底部按钮仍连接 `cancelled → worker.cancel()`。
  但 `ScannerWorker` 跑完后 `cancel()` 仅 `requestInterruption()`（no-op），
  `on_cancelled(dialog.reject)` 永不触发 → 弹窗关不掉。扫描中途点「取消」能关（worker
  在跑会真 cancel 并 reject），故仅「完成后」坏。
- **改法**（`ui/dialogs.py`）：加 `_finished` 标志 + `_on_button()` —— 扫描中点「取消」=
  发 `cancelled`；完成后点「关闭」= 直接 `self.accept()` 关闭。

## 修复 2：浮动工具条改版（用户要求）
- 主题 → **开关式切换按钮** `QPushButton#ThemeToggle`（checkable，icon-only，`:checked`
  高亮表示当前为浅色）；
- 其余三个 → **图标+文字** `QPushButton#FloatTextBtn`：「正在播放 / 数据目录 / 设置」。
- 文字按钮使条宽实测 ~294px，`ui/player_bar.py` 左缩进 190 → 330，浮动条 x=16 起到
  x=310，留出 20px 不压封面。
- `ui/theme.py` 将 `#FloatBtn` 样式替换为 `#ThemeToggle` + `#FloatTextBtn`。

## 验证证据
- 新增 `tests/test_dialogs.py`（3 项：完成后关闭=accept / 扫描中取消=emit / finish 状态）；
  `test_e2e.TestE2EV2.test_float_bar_*` 同步 `theme_btn→theme_toggle` + 文字断言。
- 全量回归 **13 进程 163/163 全绿**，`ruff check .` All checks passed。
- 双 EXE 重建：`--add-data` 落地，smoke + 真实平台 8s 检查通过。

## 交付物
- 单文件便携版：`dist/QingYinPlayer.exe`（54.9 MB）
- 目录版：`dist/QingYinPlayer-Portable/QingYinPlayer-Portable.exe`（2.2 MB）
- 提交：fix(ui) 导入弹窗关闭失效 + 浮动条改版（12 文件 +135/−22）
