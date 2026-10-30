# 全面体检与 BUG 修复（v2.7.5 → v2.7.6）

> 起因：用户提出「优化软件 BUG」，未指定具体现象，选择「全部检查」。
> 结论：**代码在正常数据下健康（29/29 回归全绿），但数据层存在 2 个可实证的
> 数据丢失 BUG，另有 3 处会掩盖故障的隐患。**

## 一、体检覆盖

| 维度 | 方法 | 结果 |
|---|---|---|
| 功能回归 | `run_tests.py`，29 独立进程 | 全绿（8m20s） |
| 代码规范 | `ruff check .` | 全过 |
| 静默吞异常 | `tools/audit_silent_except.py`（AST 全项目扫） | 33 处，**1 处真问题** |
| 信号签名 | `tools/audit_signals.py`（43 处 emit 逐个比对） | 0 处不一致 |
| 文本编码 | 回退链审查 | utf-8-sig → utf-8 → gb18030，完整 |
| 播放器实例 | 是否复用 | 单例，无泄漏 |
| 裸 `print()` | windowed 下 stdout 为 None | app/ 与 ui/ 均 0 处 |
| 线程生命周期 | 引用、closeEvent、中断协议 | ⚠️ 1 处隐患 |

### 为什么 33 处静默异常只有 1 处是问题

绝大多数是**有意的降级**：读不出内嵌歌词就跳过、未知播放模式回落到默认、
封面解码失败就用占位图。给它们全加日志只会刷屏。判据是「失败后用户会不会
察觉到功能缺失且无从解释」，只有 `store.load()` 符合。

## 二、确认的 BUG

### BUG 1：一条坏数据毁掉整份配置（P0，数据丢失）

**症状**：老版本数据升级、手工编辑过 `data.json`、非正常退出写坏某个字段之后，
表现为「我的歌单全没了，设置也重置了」。

**根因**：`app/store.py` 的 `load()` 用一个 try 包住三段流程：

```python
try:
    for tid, td in (data.get("tracks") or {}).items():   # ← 第 2 首缺 path
        t = Track.from_dict(td)                          #   这里抛 KeyError
        self.tracks[t.id or tid] = t
    for pd in data.get("playlists") or []:               # ← 整段没执行
        ...
    self.settings = Settings.from_dict(...)              # ← 整段没执行
except Exception:
    pass                                                 # ← 一个字都不提示
```

`Track.from_dict` 用的是 `d["path"]` 硬索引，缺字段必抛。一旦抛出，循环中断，
**后面的曲目、全部歌单、全部设置都不再加载**，然后被 `except: pass` 吞掉。

**实证**（3 首歌 + 1 歌单 + 用户设置，第 2 首缺 `path`）：

```
期望：2 首歌 + 1 个歌单 + 音量 0.25 + 昵称「阿坤」
修复前：1 首歌 + 0 个歌单 + 音量 0.7  + 昵称「音乐爱好者」
修复后：2 首歌 + 1 个歌单 + 音量 0.25 + 昵称「阿坤」 ✅
```

**修复**：逐条隔离。每条 track / playlist 各自 try，坏条目跳过并计数，好数据
全部保住；有跳过时备份原文件为 `.bak`，记进 `load_skipped`，界面弹 Toast 明确
告知「启动时跳过 N 条损坏数据」。整体解析失败（JSON 语法坏、顶层不是对象）仍
走原来的备份重建降级。

### BUG 2：一个 `null` 让全部设置回默认（P1，配置丢失）

**根因**：`app/models.py` 的 `Settings.from_dict` 第一行就是
`float(d.get("volume", 0.7))`。`volume: null` 或 `"大声"` 直接抛异常，而它位
于函数开头——整个 Settings 构造失败，音量/主题/强调色/背景/昵称全部回默认。

**实证**：

```
期望：主题 columbina + 昵称「阿坤」保留
修复前：主题 light + 昵称「音乐爱好者」
修复后：主题 columbina + 昵称「阿坤」保留，音量单独回 0.7 ✅
```

**修复**：新增 `_as_float` / `_as_int` / `_as_str` 三个收敛函数，所有字段统一
过一遍——脏值回默认、超范围夹到合法区间、非法枚举回默认。`NaN` 单独判
（`nan != nan`）。顺带补上了 `play_mode` / `lyrics_effect` 的枚举校验：之前
文件里写什么就直接塞进播放队列。

## 三、隐患与处理

| # | 位置 | 问题 | 处理 |
|---|---|---|---|
| 3 | 全局 | 无异常钩子、无日志。**实测槽内异常不会闪退**（打印 traceback 后继续跑），但 windowed 打包后 stderr 是 None，traceback 彻底消失 | 新增 `app/crashlog.py`：`sys.excepthook` + `threading.excepthook` + Qt 消息处理器，滚动写 `logs/app.log`（1MB × 3） |
| 4 | `closeEvent` | 歌词/对齐线程只 `wait(2000)`，**没有 `requestInterruption()`**。单源网络超时 4.5s，2 秒必然等不到，线程游离到窗口析构 | 先喊停再等，上限提到 5000；worker 内 `emit` 前检查 `isInterruptionRequested()` |
| 5 | `store.save()` | 十几个 UI 槽裸调用无兜底，磁盘满/无权限时 OSError 穿透到槽里 | 内部捕获，记 `save_failed` + 落日志；主窗口 4 秒轮询一次，发现就 Toast 提示后清标志 |

### 隐患 4 的能力边界（如实说明）

多源抓歌词是 `ThreadPoolExecutor` 并行，**请求发出去就收不回来**。所以
`requestInterruption()` 在本场景的收益是有限的：它保证「线程晚一步收工时不
会把信号投递给正在析构的窗口」，但不能让已经发出的 HTTP 请求立刻中止。真正
根治要把网络层改成可取消的分批请求，成本远大于收益，本次不做。

## 四、验证

| 项 | 结果 |
|---|---|
| 新增回归 `TestDamagedData`（`tests/test_store.py`） | 8 项全过 |
| 全量回归 | **29/29 模块全绿，599 项，8m42s** |
| `ruff check .` | All checks passed |
| `tools/probe_damaged_data_ui.py`（真实建窗验证提示） | 8/8 通过 |
| 打包 + smoke | 见下方验收记录 |

> 首轮回归出过 2 个错误：`TestE2ELyricsOnline` —— 测试桩 `FakeWorker`
> 没有 `requestInterruption()`，closeEvent 调它时 `AttributeError`。真实 worker
> 都是 QThread（天然有此方法），所以是**测试桩没跟上接口**，补上即可，不改产品
> 代码。

`TestDamagedData` 的 8 条用例分别锁死：单条坏曲目不拖累其余、坏歌单只跳过自己、
`null` 音量不带走其他设置、越界值夹紧、顶层非对象按损坏处理、跳过必写日志、
写盘失败不抛且不留半截临时文件、保存成功清除失败标志。

## 五、设计决定

1. **为什么不让 `save()` 直接抛自定义异常**：调用点有十几处分散在 UI 槽里，改
   成逐个 try 既侵入又容易漏。就地记账 + 低频轮询是更小的面。
2. **为什么日志目录跟随数据目录**：便携模式 / 用户自定义数据位置时，日志应该跟
   着一起搬走，而不是永远写死在 APPDATA。
3. **为什么 `install()` 不写「启动」日志**：`--smoke` 自检会中途改写 `APPDATA`
   做隔离，此时写一行就等于污染用户真实目录。启动分隔线由调用方在路径确定后写。
4. **为什么新建 `app/crashlog.py` 而不是塞进 `paths.py`**：`store` 会调用它，而
   store 必须保持「无 Qt 依赖、可单测」。crashlog 只依赖 stdlib + paths，Qt 部
   分放在 `install_qt()` 里延迟导入。

## 六、已知未做

- 网络请求不可中途取消（见隐患 4 的能力边界）
- `data.json` 无版本迁移机制：目前只靠逐字段容错兜底，没有 `version` 字段驱动的
  升级脚本。字段语义发生不兼容变化时仍需专门处理。

---

# 追加：界面版本号骗了所有人（v2.7.6）

> 这个 BUG 不是体检发现的，是**体检之后被现场打脸**发现的 —— 属于必须记下来的那种。

## 事故经过

用户发来一张运行截图，右下角写着 `v2.6.12 · 本地音乐与视频`。我据此判断
「用户在跑旧版，所以前面几轮的修复都没生效」，还让他去换 exe。

结果查了全盘只有 v2.7.5 的产物，再翻 `logs/app.log`：

```
[10:30:47] 轻音播放器 v2.7.5 启动，数据目录 ...
```

**他跑的就是 v2.7.5。** 界面显示 2.6.12 是因为版本号是写死的字符串：

```python
# ui/main_window.py:225
self.version_label = QLabel("v2.6.12 · 本地音乐与视频", self._root)
# ui/settings_dialog.py:401
about = QLabel("轻音播放器 v2.2 · 本地音乐与视频，歌词可联网补全")
```

从写下这两行的那天起，它们就没再跟随过 `APP_VERSION`。`main.py` 里的版本号
一路从 2.6.12 升到 2.7.5，界面上一个字没变。

## 为什么这不只是「显示不好看」

界面在**撒谎**，而版本号是所有排查的第一个锚点。它直接导致：

1. 用户以为更新没生效（他自己的判断也是错的，但他无从知道）
2. 开发者（我）基于界面下结论，方向完全跑偏，白查一轮
3. 「关于」里还写着 `v2.2`，落后得更多

## 修复：收敛到单一真相源

新增 `app/version.py`：

```python
APP_NAME = "轻音播放器"
APP_VERSION = "2.7.6"
APP_TAGLINE = "本地音乐与视频"

def version_text(tagline: str | None = None) -> str:
    tail = APP_TAGLINE if tagline is None else tagline
    return f"v{APP_VERSION} · {tail}" if tail else f"v{APP_VERSION}"
```

- `main.py` 改为 `from app.version import APP_NAME, APP_VERSION`，不再自己定义
- `ui/main_window.py` 右下角用 `version_text()`
- `ui/settings_dialog.py`「关于」用 `f"{APP_NAME} {version_text()}，歌词可联网补全"`

`version_text` 的 `tagline` 默认取 `None` 而不是 `""`：空串表示「只要版本号不要
副标题」，`None` 才用默认副标题。用 `or` 会把「显式传空」也吃成默认，语义含糊。

## 防回归（4 条，全部通过）

| 用例 | 锁死什么 |
|---|---|
| `test_version_text_contains_current_version` | 展示串含当前版本 |
| `test_version_text_accepts_custom_tagline` | `None` / 空串 / 自定义三种语义 |
| `test_no_hardcoded_version_literal_in_source` | **AST 扫描** `app/` 与 `ui/`，凡是以 `v数字.数字` 开头的字符串常量一律报错（注释不算常量，历史标注不受影响） |
| `test_main_takes_version_from_app_version` | `main.py` 必须转发，不许自己定义 `APP_VERSION` |

外加 E2E 一条：`test_version_label_follows_app_version` —— 真实建窗后断言右下角
文本等于 `version_text()`，且不含 `v2.6.12`。

## 教训

**「状态显示」和「状态本身」是两套东西，必须由同一个来源生成。** 凡是界面上要
显示版本、路径、数量、统计这类事实的地方，都得问一句：「这个数字是从哪儿来的？
会不会有一天跟真相分叉？」第三个测试用 AST 扫描而不是正则扫全文，就是为了让
这条规则能自动执行，而不是靠下次再被人发现。
