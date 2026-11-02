# v3.0.8 — 移除右键「在线搜索歌词（去网页找）」

## 一句话结论

按截图点名删除歌词区右键的「在线搜索歌词（去网页找）」子菜单，并**连底层 3 个
URL 构造函数一起删干净**，不留死代码。功能面完全不变：自动三源（LRCLIB / 网易云 /
QQ音乐）联网匹配、导入歌词文件、AI 逐字对齐全部原样保留。

## 删了什么（四层，一次清楚）

| 层 | 位置 | 删除内容 |
|----|------|----------|
| UI 菜单 | `ui/lyrics_panel.py` | `search_online_requested` 信号、平台子菜单构造（LRCLIB/网易云/QQ音乐） |
| 主窗口 | `ui/main_window.py` | 信号连接、`_open_lyrics_search()` 槽（19 行）、`web_search_url` import |
| 业务层 | `app/lyrics_multi.py` | `WEB_SEARCH_TEMPLATES`、`build_web_search_urls()`、`web_search_url()`、对应 import |
| 单源工具 | `app/lyrics_online.py` | `build_web_search_url()` |
| 测试 | 3 个文件 | 9 例：`test_widgets` 1 + `test_lyrics_multi` 5（整个 `TestWebSearchUrls` 类）+ `test_lyrics_online` 3 |
| 文档 | `README.md` | 功能表里「可**在线搜索歌词**（浏览器打开网页自己找）」一句 |

## 为什么连底层函数一起删

这是本次唯一需要判断的地方，走了「彻底删」而不是「只删菜单项」：

1. **三个 URL 函数除了这条菜单没有任何其他调用方**（grep 全库确认）。留着就是死代码，
   将来接手的人会以为功能还在、只是入口藏起来了。
2. **测试会继续测没人调用的纯函数** —— 覆盖率数字好看，实际在守一座空城。
3. **联网匹配主链路完全不依赖它们**：`lyrics_multi` 走的是 `fetch_best_hit` /
   `pick_with_consensus` 那条线；`urllib.parse` 在两个模块里都另有用途，不存在
   「删了冒未使用 import」的连带问题（ruff 已确认）。

**没动的**：`DESIGN.md` / `TASK.md` / `overview_v3.0.4.md` 里的历史记录保持原样。
它们是决策流水账，记录「当时为什么这么做」；改写历史会让后来的人看不出这功能
存在过、又为什么被拿掉。新决策追加在 DESIGN.md §40.22，与历史并存。

## 风险预演

| 风险 | 评估 | 处理 |
|------|------|------|
| 外部脚本 import 了 `build_web_search_url`（v2.6.4 起就是公开函数） | 项目无对外 API 承诺，`tools/` 下无引用 | 可接受；需要时 `git show 02461e9:app/lyrics_online.py` 取回 |
| 删 import 后 ruff 报未使用 | 两个模块的 `urllib.parse` 都另有用途 | ruff 已跑，All checks passed |
| 误伤联网匹配主链路 | 无调用关系 | 受影响三模块 + 全量回归 |
| 界面还显示旧菜单 | 用户跑的是 EXE | 重新打包 v3.0.8 |

## 验证

| 验证项 | 结果 |
|--------|------|
| 全库 grep 残留引用 | 代码侧 **0 处**（只剩 md 历史档案） |
| ruff check | All checks passed |
| `test_widgets` / `test_lyrics_multi` / `test_lyrics_online` | 三个模块全绿 |
| 全量回归（30 独立进程） | **全部通过** |
| 冻结产物版本自证 | `--check-ai` 首行 `轻音播放器 v3.0.8 AI 自检` |

## 交付

| 项目 | 结果 |
|------|------|
| 版本号 | `app/version.py` 3.0.7 → **3.0.8** |
| 提交 | 见 `git log`（`feat: 移除右键「在线搜索歌词」`） |
| 打包 | onefile 122.9MB + 目录版，双 smoke 通过 |
| 直接运行 | `dist/QingYinPlayer.exe` |
