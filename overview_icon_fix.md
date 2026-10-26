# 窗口/任务栏图标修复 · 交付概述（v2.1.1）

## 结论 ✅已验证
用户报告的「软件打开的图标」显示为 broken-image 占位符已修复，并已 git 提交（`main`，`d18f451`）。修复后经 3 重验证：规范 ICO 目录项、QIcon 全尺寸可加载、`assets/app.ico` 渲染为真实 logo（白音符 + 蓝紫渐变圆角方块，见 `icon_preview/icon_256.png`），不再退化成占位符。

## 根因
1. `build.generate_icon()` 把 PNG 写进 ICO 容器时，目录项填了 `planes=1 / bitcount=32`（BMP 写法）。资源管理器常容忍，但 **Windows 任务栏/标题栏图标加载器更严格会拒绝加载** → 窗口图标退化成占位符。
2. 叠加因素：`main.py` 正常启动与 `--smoke` 两分支都未显式 `app.setWindowIcon(...)`，仅靠 EXE 内嵌图标，任一环节失效即空白。

## 改动（N1–N4）
| 项 | 文件 | 内容 |
|---|---|---|
| N1 | `build.py::generate_icon` | 目录项 `struct.pack("<BBBBHHII", dim,dim,0,0,1,32,len,off)` → `...,0,0,...`（planes/bitcount 改 0/0） |
| N2 | `build.py::_pyinstaller` | 命令加 `"--add-data", f"{ICON_PATH}{os.pathsep}assets"`，随包打入 `sys._MEIPASS/assets/app.ico` |
| N3 | `main.py` | 新增 `_resolve_app_icon()`（优先 `_MEIPASS/assets`，回退源码 `assets/`）+ `_apply_app_icon(app)`；两启动分支均调用 |
| N4 | `tests/test_icon.py` + `run_tests.py` | 3 项回归测试（规范目录项 / 7 尺寸可加载 / 运行时定位）；接入全量回归 |

## 验证证据
- `tests/test_icon.py`：**3/3 pass**
- 全量回归：**12 进程 160/160**（157 既有 + 3 新增），`ruff check .` All checks passed
- 双 EXE 重建：`--add-data` 落地，`assets/app.ico`（14885 bytes / 7 尺寸）；smoke + 真实平台 8s 检查通过
- 视觉：QIcon 渲染 `icon_preview/icon_256.png` 为真实 logo，非占位符

## 关键教训（已沉淀记忆）
- ICO 容器装 PNG 时目录项 `planes/bitcount` 必须为 0（铁律 22）
- 双保险：EXE 内嵌图标 + 运行时 `setWindowIcon` 显式设置
- 解析 ICO/二进制头部的切片务必用 `data[off:off+4]`，而非 `data[off:4]`（off>4 时返回空）

## 已交付物
- 提交 `d18f451`（7 文件 +123/−4）
- 文档：`TASK.md` 第 N 节全勾选、`ACCEPTANCE.md` 新增「v2.1.1 窗口图标修复」验收表 + 根因
- 记忆：`.workbuddy/memory/MEMORY.md`（铁律 22、测试 160 项）、`2026-10-26.md` 图标修复段
- 可视化：`icon_preview/icon_256.png`、`icon_48.png`、`icon_32.png`
