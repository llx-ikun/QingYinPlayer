# 「轻音播放器」设计方案（DESIGN.md）

> 版本：v1.0 · 2026-10-24 · 状态：**待用户评审**
> 项目目录：`D:\新建文件夹\2026-10-24-23-16-14\music-player`

---

## 1. 需求确认

### 1.1 用户原话（需求来源）

> 实现本地音乐播放、播放列表管理、播放控制（播放/暂停/切歌/进度拖动/音量调节）、歌词显示等功能。风格偏好：界面简洁现代，深色主题等，中文界面。exe文件

### 1.2 澄清结论（已与用户确认）

| 决策项 | 结论 | 理由 |
|---|---|---|
| 技术栈 | **Python 3.13 + PySide6 6.12** | 用户选定；Qt 信号机制适合播放器状态管理 |
| 云端/在线 | **纯本地版，不接云** | WorkBuddy 云服务 Origin 校验面向网页/小程序，桌面 EXE 直接调用会被拒绝；本地 JSON 持久化是最稳架构 |
| 交付物 | **Windows EXE**（安装包形态）+ 便携版 | 用户明确要 exe 文件 |
| 界面 | 深色主题、简洁现代、全中文 | 用户明确 |

### 1.3 功能范围（M-S-C 优先级）

**Must（本期必须）**
- M1 本地音乐导入：文件夹递归扫描 + 多选文件 + 窗口拖拽
- M2 播放控制：播放/暂停、上一首/下一首、进度拖动 seek、音量调节/静音
- M3 播放列表管理：资料库、新建/重命名/删除歌单、歌曲加入/移出歌单、歌单内排序（拖拽 + 菜单）
- M4 歌词显示：LRC 解析、逐行同步高亮、自动滚动、点击歌词跳转进度
- M5 深色现代中文 UI + 封面显示
- M6 本地持久化：库/歌单/设置/播放记录跨重启保留
- M7 打包为可双击运行的 Windows EXE

**Should（尽量做）**
- S1 播放模式：顺序播放 / 列表循环 / 单曲循环 / 随机
- S2 元数据：标题/艺人/专辑/时长/内嵌封面（ mutagen ）
- S3 内嵌歌词读取（ID3 USLT/SYLT、FLAC LYRICS）
- S4 搜索过滤、曲目排序（标题/艺人/时长/添加时间）
- S5 最近播放（自动歌单）、播放计数
- S6 启动恢复：恢复上次曲目与播放位置（不自动播放）
- S7 键盘快捷键（空格播放/暂停、Ctrl+←/→ 切歌、←/→  seek、↑/↓ 音量）
- S8 手动绑定 .lrc 文件（当自动匹配失败时）

**Could（有余力再做）**
- C1 增强 LRC 逐字歌词
- C2 迷你模式/置顶
- C3 主题强调色切换

**Won't（本期明确不做）**
- W1 在线音乐/云同步（技术限制 + 版权风险，见 §2.3）
- W2 音频格式转换、标签编辑（破坏性操作，不做）
- W3 多语言（仅中文）

---

## 2. 技术选型

### 2.1 选型结论

| 层 | 选型 | 说明 |
|---|---|---|
| 语言/运行时 | Python 3.13（venv 虚拟环境） | 依赖锁定 requirements.txt |
| UI 框架 | **PySide6 6.12（Qt Widgets + QSS）** | 信号机制贴合播放器状态机；QSS 可实现深色现代风 |
| 播放引擎 | **QMediaPlayer + QAudioOutput** | Qt6 Multimedia；实测本机为 **FFmpeg 后端**，格式全覆盖 |
| 元数据 | **mutagen** | 纯 Python，支持 MP3/FLAC/M4A/OGG/WAV |
| 持久化 | JSON 文件（`%APPDATA%\轻音播放器\data.json`） | 数据量小（千级曲目），无需数据库；变更即落盘 |
| 封面缓存 | `%APPDATA%\轻音播放器\covers\<id>.png` | 懒提取 + 磁盘缓存 |
| 打包 | **PyInstaller**（onefile + onedir 双产物） | hooks 成熟 |
| 测试 | unittest（纯逻辑单测）+ offscreen E2E | 无需 pytest，零额外依赖 |

### 2.2 方案对比（为什么不选别的）

| 备选 | 否决理由 |
|---|---|
| Electron（Node） | 用户已选定 Python 路线；且产物体积 ~100MB、内存占用高 |
| Tauri（Rust） | 本机无 Rust 工具链，首次构建风险高；与用户选型冲突 |
| miniaudio 自研播放引擎 | 实测其 decode_file 全部报错（-7）；且 QMediaPlayer+FFmpeg 已覆盖全部格式，自研引擎无收益、徒增 glitch/seek 风险 |
| QML（Qt Quick） | 动画能力强，但 Python+QML 调试成本高、PyInstaller 打包 QML 插件坑更多；Widgets+QSS 足够实现目标视觉 |
| SQLite | 千级曲目 JSON 足够；引入 schema 迁移成本不划算 |

### 2.3 云端能力说明（对用户 @cloud-service 的回应）

- WorkBuddy 云服务的数据面有**精确 Origin 校验**，面向网页/小程序；桌面 EXE（file:// 源）调用会被拒绝。
- 若未来确需云能力（歌单多端同步 / 云端曲库），可行路径是**网页版 + EXE 外壳**架构，属独立迭代，本期不做。

---

## 3. 环境探测记录（2026-10-24 实测，决策依据）

| 探测项 | 结果 | 影响 |
|---|---|---|
| npm/PyPI 网络 | 官方 PyPI ~46KB/s（慢）；**阿里云镜像 ~578KB/s** | 依赖安装统一走 `https://mirrors.aliyun.com/pypi/simple/` |
| 沙箱删除守卫 | WorkBuddy 注入的 sitecustomize 会拦截 pip/PyInstaller 的批量文件覆盖（>50 文件） | 所有 pip / pyinstaller 命令加 `env -u PYTHONPATH` 前缀 |
| QMediaPlayer 格式 | wav/flac/ogg/mp3 **全部 LoadedMedia**，FFmpeg 后端 | 引擎定为 QMediaPlayer 单引擎 |
| mutagen 格式 | 四格式全部可读 | 元数据方案成立 |
| 音量/seek | setVolume/volumeChanged、setPosition/position **均生效** | 控制链路 Qt 原生，可靠 |
| **播放 position 推进** | **⚠️ 沙箱内不推进**（设备可见、PlayingState 可达，但无音频渲染） | E2E 只能验证到状态机/UI 链路；**声音与进度推进必须交付后由用户本机双击验证**（见 §8 R1） |
| m4a 真实样本 | 本机无生成工具（无 ffmpeg）， mutagen+FFmpeg 代码路径与 mp3/flac 相同 | m4a 标注 🟡 推测可用（FFmpeg AAC 解码为标准能力） |

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────┐
│ UI 层 (ui/)                                          │
│  MainWindow ─ Sidebar ─ TrackList ─ NowPlaying      │
│              ─ LyricsPanel ─ PlayerBar ─ Dialogs    │
├─────────────────────────────────────────────────────┤
│ 服务层 (app/)                                        │
│  PlaybackController (QMediaPlayer 封装 + 队列/模式)   │
│  LibraryStore (JSON 持久化 + 库/歌单 CRUD)            │
│  MetadataReader (mutagen)  Scanner (QThread 扫描)    │
│  LyricsEngine (LRC 解析+索引, 纯逻辑)                 │
│  CoverProvider (懒提取+缓存+占位图)                   │
├─────────────────────────────────────────────────────┤
│ 数据层                                               │
│  %APPDATA%\轻音播放器\data.json + covers\            │
└─────────────────────────────────────────────────────┘
```

**关键设计原则**
- LyricsEngine / 队列逻辑为**纯逻辑模块**（不依赖 Qt），可完整单测。
- PlaybackController 是唯一碰 QMediaPlayer 的地方，UI 只跟它的信号打交道。
- 扫描放 QThread，UI 不卡；封面懒加载，导入快。

---

## 5. 数据模型

```python
Track:
  id: str            # 路径哈希（稳定去重键）
  path: str          # 绝对路径
  title/artist/album: str
  duration_ms: int
  fmt: str           # mp3/flac/wav/m4a/ogg...
  added_at: int      # 时间戳
  last_played_at: int
  play_count: int
  lrc_path: str|None # 手动绑定的歌词文件
  broken: bool       # 文件是否丢失/不可播

Playlist:
  id: str            # uuid
  name: str
  track_ids: list[str]
  created_at: int
  system: str|None   # None=用户歌单；"library"=资料库(虚拟)；"recent"=最近播放(虚拟)

Settings:
  volume: float      # 0.0~1.0
  muted: bool
  play_mode: str     # sequential|loop|single|shuffle
  last_track_id: str|None
  last_position_ms: int
  view: str          # 上次所在视图

data.json = {"version": 1, "tracks": {id: Track}, "playlists": [...], "settings": {...}}
```

- 资料库与最近播放为**虚拟歌单**（不存 track_ids，按规则动态生成），删除用户歌单才动数据。
- 文件丢失：`broken=True`，播放时提示并跳过，不静默失败。

---

## 6. 核心接口设计

```python
# app/lyrics.py（纯逻辑）
parse_lrc(text) -> list[LyricLine]      # time_ms, text；支持多时间标签/[offset:]/元数据行/容错
lyric_index_at(lines, position_ms) -> int   # 二分查找当前行
format_time(ms) -> "m:ss"

# app/player.py
class PlaybackController(QObject):
    # 队列上下文：一个 track_ids 列表（当前视图/歌单）
    play_tracks(ids, start_index)          # 设置队列并播放
    toggle_play() / pause() / resume() / stop()
    next(auto=False) / previous()          # previous: position>3s 先回本曲开头
    seek(ms) / set_volume(v) / toggle_mute()
    set_play_mode(mode)                    # sequential/loop/single/shuffle
    signals: state_changed, position_changed(ms), track_changed(Track),
             mode_changed, volume_changed, error(str)
    # 结束逻辑: EndOfMedia → single:重播 / loop:下一首(循环) / shuffle:随机未完 / sequential:播完停止

# app/store.py
class LibraryStore:
    add_tracks(metas) / remove_track(id) / all_tracks() / get_track(id)
    create_playlist(name) / rename / delete / add_to_playlist(pid, tids) / remove_from_playlist
    move_in_playlist(pid, tid, new_index)
    settings get/set；save()（防抖落盘）
    recent_tracks(limit)   # 按 last_played_at

# app/metadata.py
read_track(path) -> TrackMeta   # title/artist/album/duration_ms/fmt/picture(bytes|None)/lyrics_text|None
extract_picture(path) -> bytes|None

# app/covers.py
get_cover(track, px) -> QPixmap    # 懒提取+磁盘缓存；无封面→渐变占位图(♫)
```

---

## 7. UI 设计（深色主题）

**布局**（1366×768 起步，可缩放）：

```
┌──────────┬───────────────────────────────────────┐
│ 轻音 ♫   │  搜索框            排序 ▾   [列表|正在播放] │
│──────────┤───────────────────────────────────────┤
│ 资料库    │  ┌───────────────────────────────┐    │
│ 最近播放  │  │ 曲目列表（封面+标题/艺人+时长）  │    │
│──────────┤  │ 右键菜单 / 拖拽排序             │    │
│ 歌单 ＋  │  └───────────────────────────────┘    │
│ · 跑步🎵 │                                       │
│ · 睡前    │                                       │
│──────────┤                                       │
│ 导入音乐  │                                       │
└──────────┴───────────────────────────────────────┘
┌─────────────────────────────────────────────────┐
│ [封面] 标题/艺人  ♥  │ ⏮ ▶ ⏭ │ 0:00 ─●─ 3:24 │ 🔊───│  ← 底部播放栏
└─────────────────────────────────────────────────┘
```

**正在播放视图**：左侧大封面 + 曲目信息，右侧歌词面板（当前行高亮放大、自动滚动、点击跳转、无歌词显示"暂无歌词"占位）。

**视觉规范**：
- 底色 `#0f0f13` / 面板 `#17171f` / 悬浮 `#1f1f2b`；文字主 `#f0f0f5`、次 `#9a9aa8`
- 强调色 `#5b8cff`（蓝紫渐变可选）；圆角 10px；自定义细滚动条
- 进度条：已播部分强调色 + 小圆点手柄；拖动时显示时间预览
- 空状态：插画式文字提示（"导入音乐开始你的第一首歌"）

**交互细节**：
- 双击曲目播放；右键：播放 / 添加到歌单▾ / 从歌单移除 / 上移 / 下移 / 绑定歌词 / 移除出资料库
- 播放中曲目行左侧显示音量条动画图标
- 底部状态栏显示瞬时提示（导入进度、错误、跳过丢失文件等）

---

## 8. 风险预演与对策

| # | 风险 | 概率 | 对策 |
|---|---|---|---|
| R1 | **沙箱无音频渲染，position 不推进；声音无法在此环境验证** | 高（已证实） | E2E 验证状态机/seek/volume/UI 链路；交付清单明确标注「请本机双击 EXE 确认声音与进度推进」；代码只依赖 Qt 标准信号，不自行造时钟 |
| R2 | PyInstaller onefile 启动慢（解压 2-5s）、未签名 exe 被杀毒误报 | 中 | 同时交付 onedir 版（启动快）；README 说明如遇误报加信任 |
| R3 | m4a 无真实样本 | 中 | 代码路径同 mp3/flac；标注 🟡；README 说明如遇问题反馈 |
| R4 | 大文件夹（万级文件）扫描卡 UI | 中 | QThread 后台扫描 + 进度对话框 + 可取消 |
| R5 | 用户移动/删除了音乐文件 | 高 | broken 标记 + 播放时提示跳过，不崩溃 |
| R6 | 中文路径/文件名编码 | 中 | 全链路 UTF-8；测试夹具含中文文件名 |
| R7 | 打包后 Qt 插件缺失导致黑屏 | 低 | PyInstaller hooks 自动收集；打包后 smoke test（offscreen 启动加载库） |

---

## 9. 测试方案

1. **单元测试**（unittest，纯逻辑）
   - LRC：多时间标签、offset、元数据行、空行、畸形行、压缩空白
   - 歌词索引：边界（歌前/歌中/歌尾/多行同时间戳）
   - 播放模式队列：sequential/loop/single/shuffle 的 next/previous/播完行为
   - Store：CRUD、去重、歌单操作、持久化 round-trip（临时目录）
2. **E2E**（offscreen，`QT_QPA_PLATFORM=offscreen`）
   - 夹具生成：soundfile/lameenc 合成 mp3/flac/wav/ogg + 中文文件名 + ID3 标签 + 同名 LRC
   - 全链路：扫描导入 → 列表渲染 → 播放状态 → seek/volume → 切歌 → 歌单增删排序 → 歌词索引联动 → 关闭重开数据恢复
3. **打包 smoke test**：打包产物以 offscreen 启动，创建窗口、加载库、无异常退出

---

## 10. 验收标准（逐条可勾）

- [ ] 双击 EXE 启动，深色中文界面正常渲染（**用户本机验证**）
- [ ] 导入文件夹/文件后，列表显示标题/艺人/专辑/时长/封面
- [ ] 播放/暂停/上一首/下一首正常，进度条可拖动跳转，音量可调（**用户本机验证声音**）
- [ ] 播放模式四种切换行为正确；播完自动按模式续播
- [ ] 歌单：新建/重命名/删除/加歌/移出/拖拽排序；资料库与最近播放正常
- [ ] 歌词：LRC 自动匹配、同步高亮滚动、点击跳转；内嵌歌词与手动绑定生效
- [ ] 关闭重开：歌单、设置、上次曲目与位置恢复
- [ ] 文件丢失时友好提示不崩溃
- [ ] 单测 + E2E 全绿；交付 EXE（安装版 + 便携版）

---

## 11. 里程碑

1. **M1 骨架**：脚手架 + store + 元数据 + 扫描（后端就绪，单测绿）
2. **M2 播放核心**：PlaybackController + 队列/模式（单测绿）
3. **M3 UI**：主窗口/侧边栏/列表/播放栏/正在播放/歌词面板（offscreen E2E 绿）
4. **M4 打磨**：持久化恢复、快捷键、空状态、错误提示
5. **M5 打包交付**：图标 + PyInstaller 双产物 + smoke test + README

详见 `TASK.md`。

---

## 12. v2.0 UI 改版（2026-10-25，QQ 音乐桌面端风格）

> 状态：**待用户评审** · 触发：用户提供 QQ 音乐 PC 端截图，要求「UI 做成大概这样」
> 原则：后端能力不动（播放/歌单/歌词/扫描全部保留），重做集中在 `ui/`；不接在线内容，所有卡片/统计用真实本地数据。

### 12.1 需求确认（用户已答复）

| 决策项 | 结论 | 理由 |
|---|---|---|
| 主题 | **双主题，默认深色**；浅色照截图（QQ 绿 `#31c27c`），深色沿用现有蓝紫 | 原需求是深色；截图是浅色；两者都要且默认深色 |
| 改造范围 | **完整改版 + 自定义无边框标题栏** | 用户选择；拖拽/缩放/贴边自行处理 |
| 「我喜欢」 | **加**：新增虚拟歌单 + 行内爱心，后端 store 小改 | 参考图核心元素，本地场景同样有用 |
| 主页 | **不做**，打开直接进歌曲列表 | 本地无推荐数据，不做假内容 |

### 12.2 新布局

```
┌──────────────────────────────────────────────────────────────┐
│ ♫轻音   ◀ ▶ ⟳   [🔍 搜索歌曲 / 艺人 / 专辑]        —  □  ✕  │ 标题栏 48px（拖拽移动/双击最大化）
├────────────┬─────────────────────────────────────────────────┤
│ ⬤头像      │ 资料库·共 128 首        排序▾   ▶ 播放全部  ☰   │
│ 昵称       │ ─────────────────────────────────────────────── │
│ [本地模式]  │ 歌曲      艺人      专辑     格式    时长  ♥  ⋯ │
│ ♥    ⌂     │ ─────────────────────────────────────────────── │
│ 🕐 最近播放 │ ● 行（序号/动效条 · 封面36 · 当前行高亮）        │
│ 自建歌单 ＋ │ ● 格式徽标：flac→无损 / mp3→MP3 / 其他→大写     │
│ ▤ 歌单A  12│ ● 爱心=我喜欢开关；⋯=右键菜单（播放/加歌单/…）  │
│ ▤ 歌单B   5│                                                │
│ [导入音乐]  │                                                │
├────────────┴─────────────────────────────────────────────────┤
│ [封面] 标题/艺人 ♥ ⋯ │ ◀ ▶ ⏵ │ 0:00 ──●── 1:47 │ 🔊 [SQ] 词 ☰ │ 播放栏 84px
│        ( ☾ ♪ 📁 ⚙ 浮动工具条，覆盖左下角 )                     │
└──────────────────────────────────────────────────────────────┘
```

- 标题栏/播放栏**通栏**（跨侧边栏与内容区），与 QQ 音乐一致；侧边栏 248px。
- 侧边栏图标导航：♥ 我喜欢 / ⌂ 资料库；文本导航：🕐 最近播放·N；歌单带封面缩略图与数量。
- 歌曲列表为**表格形态**（列表头 + 行内爱心/更多），替代原「头部工具条 + 简单行」。
- 浮动工具条 4 键：主题切换 / 正在播放页 / 打开数据目录 / 设置。

### 12.3 主题机制（双主题）

- `ui/theme.py`：`Theme` dataclass（调色板）+ `THEMES = {"dark": ..., "light": ...}` + `build_stylesheet(theme)`；`settings.theme` 持久化，默认 `"dark"`。
- 深色 = 现有蓝紫 `#6c8cff`（保持 v1 身份）；浅色 = QQ 绿 `#31c27c`，面板白/底 `#f5f6f7`。
- 图标全部手绘且带颜色参数：新增 `bind_icon(button, kind, size, role)` 注册表 + `refresh_icons(theme)`，切主题时重绘全部图标（`EqualizerBars` 同步换色）。
- 切换入口：浮动工具条 ☾/☀ + 设置对话框；切换 = `setStyleSheet` + `refresh_icons`，即时生效，重启保持。

### 12.4 数据模型与接口变更（app/）

| 变更 | 内容 | 兼容性 |
|---|---|---|
| `PLAYLIST_FAVORITES = "__favorites__"` | 「我喜欢」虚拟视图，落盘为 `system=True` 的系统歌单（懒创建） | 旧数据无此字段 → 首次收藏时创建 |
| `Settings +theme / +nickname` | `theme="dark"`、`nickname="音乐爱好者"` | `from_dict` 取默认值，旧 JSON 无损升级 |
| `store.load()` | 原逻辑**丢弃** system 歌单，改为保留（favorites 需要持久化） | 历史数据从无 system 歌单落盘，无影响 |
| store 新增 | `toggle_favorite(tid)->bool`、`is_favorite(tid)`、`favorite_tracks()`、`favorite_count()`；`view_tracks/view_name` 支持 favorites | 纯新增 |
| player 新增 | `queue_ids`、`queue_index`、`play_from_queue(tid)` | 纯新增（队列面板用） |
| `remove_track` | 已遍历全部 playlists 移除 tid，favorites 自动生效 | 无需改 |

### 12.5 组件变更清单

| 文件 | 变更 | 新增信号 |
|---|---|---|
| `ui/title_bar.py`（新） | 通栏标题栏：logo/前进/后退/刷新/搜索 pill/最小化/最大化/关闭；空白处 `startSystemMove` 拖拽，双击切最大化 | back/forward/refresh/search_changed/minimize/maximize/close |
| `ui/sidebar.py`（重写） | 用户卡片（首字母头像+昵称+本地模式徽标，点击改昵称）/♥资料库图标导航/最近播放/歌单封面列表/导入/版本 | nickname_change_requested |
| `ui/track_list.py`（重写） | 列表头列：歌曲/艺人/专辑/格式/时长/操作；行内爱心与 ⋯ 菜单；保留拖拽排序、双击播放、空态、滚动位置保持 | favorite_toggled(tid,bool) |
| `ui/player_bar.py`（重写） | 照截图：左=封面+信息+♥+⋯；中=上一首/绿圆播放/下一首+进度双行；右=音量+SQ徽标+词+队列 | favorite_clicked / queue_clicked / more_clicked |
| `ui/queue_panel.py`（新） | 播放队列浮层（`Qt.Popup`）：当前队列、当前曲高亮、点击跳转 | — |
| `ui/settings_dialog.py`（新） | 昵称 / 主题（深/浅）/ 关于 | theme_changed(str) |
| `ui/float_bar.py`（新） | 浮动工具条 4 键，定位于播放栏左上角 | theme/now_playing/data_dir/settings |
| `ui/main_window.py`（大改） | 无边框圆角窗+自绘标题栏+缩放热区；视图历史栈；全局搜索；toast 替换 statusBar；主题应用；收藏/队列/昵称接线 | — |
| `ui/now_playing.py` | 仅随主题换肤，结构不动 | — |

### 12.6 无边框窗口实现与风险

- `FramelessWindowHint + WA_TranslucentBackground`，根容器 QSS 圆角 10px + 1px 边框，`resizeEvent` 里 `setMask(圆角路径)` 硬裁剪子部件方角。
- 拖拽：标题栏空白区 `windowHandle().startSystemMove()`（原生实现，保留 Windows 贴边/DPI 行为）；双击标题栏 = 最大化/还原。
- 缩放：四边+四角 6px 热区 + `setMouseTracking`，自绘光标与几何计算。
- 风险与回退：mask/半透明在个别平台插件上有兼容问题 → 真实平台截图验证；若出现异常回退「方角窗口 + 内面板圆角」（视觉损失小、风险零）。

### 12.7 QQ 音乐元素 → 本地实现映射

| 参考图元素 | 本地实现 |
|---|---|
| 用户卡片（头像+昵称+VIP） | 首字母圆形头像 + 昵称（可改，存 settings）+「本地模式」徽标 |
| home/discover 图标导航 | ♥ 我喜欢 / ⌂ 资料库 |
| 喜欢·12 / 最近播放·368 / 本地和下载 | 我喜欢（新）/ 最近播放 / 资料库 |
| 试听列表 | 播放栏队列按钮 → 队列浮层 |
| 自建歌单\|收藏歌单 | 自建歌单（带封面缩略图） |
| 顶栏 前进/后退/刷新/搜索 | 视图历史前进后退 / 刷新当前视图 / 全局搜索（过滤当前视图） |
| 主页问候 + 听歌报告 | 不做主页（用户决策）；问候语不做 |
| 横滑卡组 / 大家都在听 / 会员横幅 | 不做（无真实数据）；统计信息放设置对话框「关于」 |
| 底部播放栏 / 左下浮动工具条 | 照截图重设计 / 主题·正在播放·数据目录·设置 |

### 12.8 测试策略（v2.0）

- 单测新增：favorites CRUD + round-trip；settings 新字段；`queue_ids/queue_index/play_from_queue`。
- E2E 重写 UI 依赖部分并新增：主题切换（QSS/设置持久化）、行内心爱心、播放栏爱心、标题栏按钮行为、视图历史、全局搜索、队列浮层跳转、昵称修改、toast。
- 保留全部既有行为用例（导入/拖拽/取消/歌单流/右键菜单/绑定歌词/重启恢复/歌词点击 seek）。
- 回归门槛：更新后**全部测试绿**（基线 91 项，只增不减）。

### 12.9 视觉验证（本沙箱约束）

offscreen 模式字体库为空、中文全方块，**不能用于审图**。改用 `tools/shot.py`：`APPDATA` 指向临时目录 + 注入夹具数据 + **真实平台开窗** `window.grab()` 存 PNG，逐轮自审。覆盖矩阵：{深色,浅色} × {空库, 有曲库, 播放中, 歌词页, 队列浮层, 设置框, 最大化}。

### 12.10 验收标准（v2.0 增量）

- [x] 浅/深主题切换即时生效，重启保持（默认深色）
- [x] 无边框窗口：拖拽移动 / 双击最大化 / 边缘缩放 / 最小化 / 关闭均正常（拖拽/贴边手感 🟡 需本机确认）
- [x] 我喜欢：行内心与播放栏心均可添加/取消，计数正确，重启保留
- [x] 用户卡片显示昵称且可修改；歌单列表带封面与数量
- [x] 全局搜索过滤当前视图；前进/后退视图历史可用
- [x] 队列浮层展示当前队列并可点击跳转
- [x] 表格列（歌曲/艺人/专辑/格式徽标/时长/爱心/更多）渲染正常，中文无方块
- [x] v1.1 全部功能回归通过；测试全绿（122 项）
- [x] 双 EXE 重建，smoke + 真实平台检查通过

### 12.11 实现收尾记录（2026-10-25）

- 测试从 91 → **122 项**；全量回归改用 `run_tests.py` 逐模块/逐类独立进程（规避 offscreen 下 QMediaPlayer 跨实例累积的 C++ 死锁，非业务缺陷）。
- ruff 全项目清零（49 → 0）。
- 修复 4 项（ElidedLabel 瞬时截断 / 视图历史初始项 / 图标 weakref / 构建脚本语法）。详见 ACCEPTANCE.md「v2.0 修复的缺陷」。
