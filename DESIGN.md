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

- `ui/theme.py`：`Theme` dataclass（调色板）+ `THEMES = {"columbina": ..., "light": ...}` + `build_stylesheet(theme)`；`settings.theme` 持久化，默认 `"light"`。
- 深色 = 午夜深蓝夜空（`#141c3e` → `#0b1228` 渐变）+ 长春花蓝 `#8b9cf8`；浅色 = 冷调月白（`#eef2fb` 底 / `#f5f8fd` 面板）+ periwinkle `#7389cb`。两态循环（v2.3.5 按用户参考图重做了浅色，色值全部从截图采样）。
- **主题对外名写在 `THEME_LABEL`**（`{"columbina": "深色", "light": "浅色"}`）：设置对话框 radio、浮动条 tooltip、切换 toast 全部读这一张表，改中文名只需改一处；内部 id 仍是 `columbina`（历史命名，指向哥伦比娅的夜空视觉，不随显示名变动，避免动持久化数据）。
- 图标全部手绘且带颜色参数：新增 `bind_icon(button, kind, size, role)` 注册表 + `refresh_icons(theme)`，切主题时重绘全部图标（`EqualizerBars` 同步换色）。
- 切换入口：浮动工具条 羽毛/太阳 + 设置对话框；切换 = `setStyleSheet` + `refresh_icons`，即时生效，重启保持。

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
- 缩放：四边+四角 6px 热区 + `setMouseTracking`，自绘光标判定方向，然后交给
  `windowHandle().startSystemResize(Qt.Edges)` **原生缩放**（与拖拽同理，保留 Windows
  贴边/DPI 行为）。早期是手动 `setGeometry` 累加，无边框窗口上拖动边缘会让整窗**整体
  移位**（"缩放会移动"）；原生缩放天然无漂移，只剩「没有原生句柄」时才退回手动跟踪。
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

---

## 13. v2.1 本地视频导入与画面播放（2026-10-26）

### 13.1 需求确认

- 用户目标：「可以让视频导入，能听音乐」「可以选择显示视频画面」。
- 已确认：双击视频**默认显示画面并播放**；本期只支持**本地视频文件**，不做在线视频链接。
- 保留现有双主题、中文界面、歌单、播放队列、收藏、歌词、播放/暂停/切歌/进度/音量能力；原视频文件不被修改或转码。

### 13.2 技术方案与取舍

| 方案 | 内容 | 取舍 |
|---|---|---|
| **QVideoSink 自绘（采用）** | 复用 `QMediaPlayer`，用 `QVideoSink.videoFrameChanged` 取 `QVideoFrame`，在普通 `QWidget` 的 `paintEvent` 里用 `QPainter` 绘制；音画共用同一个播放器和进度 | 不新增依赖；画面控件是普通 QWidget，可自由 reparent 进全屏浮窗；与既有 QSS/主题管线一致 |
| 原生 `QVideoWidget` | `setVideoOutput(QVideoWidget)`，由 Qt 直接渲染到平台 surface | 原生 surface 在 Windows 走 D3D/flip model，与本项目「无边框 + 半透明 + 圆角 mask」顶层窗叠加易黑框/遮挡/驱动崩溃；且依赖平台 surface 层级，**无法 reparent 进全屏浮窗**；offscreen 下 grab 抓不到画面，不可测 |
| VLC 引擎 | `python-vlc` 接管音视频解码 | 冷门编码兼容性更强，但引入 VLC 运行库、打包体积和排错成本明显增加，第一版不做 |
| 先提取音轨 | FFmpeg 把视频音频转出后播放 | 能听但不能直接显示原画面，还增加缓存与等待，不符合本次目标 |

**路线修正记录（2026-10-26）**：初版设计为「原生 `QVideoWidget`」，落地前用探针脚本对比两条路线后改为自绘。实测数据：offscreen 下 QVideoSink 路线收到 11 帧、grab 取到 4 种颜色；QVideoWidget 路线 grab 仅 1 种颜色（抓不到画面）。自绘额外成本是每帧一次 YUV→RGB 转换（实测 320×240 约 0.1ms，1080p 约 3–6ms），对本机离线播放完全够用。

运行时不依赖 `ffmpeg.exe`，不引入转码流程。容器可导入不等于所有编码都可解码，实际播放能力以 Qt 自带 FFmpeg 后端为准。

### 13.3 功能范围（M-S-C）

**Must**
- 本地导入 `mp4 / mkv / mov / avi / wmv / flv / webm / m4v`；文件夹扫描、文件多选、拖拽沿用现有入口。
- 视频与音频混排在资料库/歌单，视频行显示「视频」徽标；双击视频自动进入视频页。
- 视频页支持播放/暂停、上一首/下一首、进度拖动、音量、队列、收藏；音乐模式切换不中断声音与进度。
- 视频全屏与退出（`F11` 切换、`Esc` 退出）；返回列表后声音继续。
- 上次播放的视频、断点、歌单与主题设置重启后保留；不支持/损坏文件沿用现有错误提示与跳过链。

**Should**
- 画面按比例缩放并居中，黑底，避免拉伸；音频/视频模式切换由当前曲目类型驱动。
- 视频无音轨时可正常显示画面，不因「没有声音」误报播放失败。

**Could（本期不做）**
- 视频缩略图、字幕、倍速、画面旋转/裁剪、在线视频、硬件解码设置、投屏。

### 13.4 页面与交互设计

主窗口保留 `stack[0]=歌曲列表`、`stack[1]=正在播放`。正在播放页内部再分为「音频模式」与「视频模式」，不新增第三套播放控制：

```text
音频模式（现有）                       视频模式（新增）
┌ 封面 280 ┐ ┌ 歌词 ┐                 [返回列表] [音乐模式]       [全屏 F11]
│          │ │      │                 ┌──────────────────────────────┐
└──────────┘ └──────┘                 │                              │
                                      │  VideoSurface（QVideoSink     │
                                      │  → QVideoFrame → QPainter     │
                                      │  等比居中黑底）                │
                                      │                              │
                                      └──────────────────────────────┘
                                      视频标题 · 格式 · 时长 · 文件名
──────────────── 底部沿用同一个 PlayerBar：播放/切歌/进度/音量/收藏/队列 ────────────────
```

- 双击音频保持原行为；双击视频播放并 `_show_page(1)` 进入视频模式。
- 「音乐模式」只切换正在播放页的子视图，**不调用 setSource、不重建播放器**，因此不中断声音/进度；视频模式可再切回。
- 返回列表不停止播放；点击「正在播放」按当前曲目类型进入对应模式。
- 自动切到下一首时更新当前曲目类型；若正在观看视频，新的音频显示封面/歌词，新的视频显示画面。
- 全屏只针对视频画面；`Esc` 在全屏时优先退出全屏，不触发清空搜索。

### 13.5 数据模型与接口

- `app/models.py`：新增 `VIDEO_EXTENSIONS`、`MEDIA_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS`；`Track.is_video` 按 `fmt` 派生，**不新增 JSON 字段**，旧数据无损兼容。
- `app/scanner.py`：保留 `collect_audio_files` 名称以控制改动，内部改用 `MEDIA_EXTENSIONS`（另提供 `collect_media_files` 主名 + 旧名别名）；导入文件过滤器同步加入视频格式。
- `app/metadata.py`：沿用 mutagen 可读的 MP4 标签；其他容器读不到元数据时以文件名兜底，时长由播放器加载后回填。
- `app/player.py`：新增 `set_video_output(target)`——`target` 为 `QVideoSink` 时走 `setVideoSink`，为 `QWidget` 时走 `setVideoOutput`，`None` 表示解绑；播放控制接口不变。
- `ui/video_view.py`（新建）：`VideoSurface`（画面绘制）/ `VideoSinkHost`（持有 sink）/ `VideoFullscreenOverlay`（全屏浮窗，负责 reparent 与还原）。
- `ui/now_playing.py`：新增视频子视图与 `set_media_mode(is_video)`、`video_host`、`media_mode_changed` / `back_to_list_requested` / `fullscreen_requested` 信号；保留现有音频页 API（`lyrics` / `set_track` / `set_synced` 等）。
- `ui/track_list.py`：`format_badge` 对视频扩展名返回「视频」；其余列、收藏、拖拽行为不变。

### 13.6 风险预演与验证

| 风险 | 对策 / 验证 |
|---|---|
| 容器支持但具体编码不能播放，或 Windows 显卡链路出现黑屏 | 真实 MP4 样本验证画面与声音；失败走现有 toast/跳过链，不承诺所有编码 |
| 无边框圆角/透明背景与原生视频表面冲突 | **已规避**：不走原生 surface，改 QVideoSink 自绘进普通 QWidget（黑底不透明）；真实平台截图确认无遮挡、无黑框异常 |
| 全屏后无法退出或 Esc 误清搜索 | 视频页独立全屏快捷键；全屏状态优先处理 Esc；真实平台验证 F11/Esc |
| 切音乐模式时重载媒体导致进度归零 | 只切子视图，复用同一 QMediaPlayer；测试切换前后 position/current_track 不变 |
| 大文件导入卡顿 | 扫描阶段不做转码/抽帧，元数据读取失败即文件名兜底；时长播放后回填 |
| offscreen 下 QMediaPlayer 累积死锁 | 视频 E2E 独立测试类、独立进程加入 `run_tests.py`；不把环境死锁误判为业务失败 |
| 沙箱无 FFmpeg CLI，视频夹具生成受限 | **已解决**：环境既无 `ffmpeg`/`ffprobe` CLI，`QMediaRecorder.isAvailable()` 亦为 False（无采集设备/编码器）。改为「Qt 合成 JPEG 帧 + 纯 Python 手写 RIFF/AVI 容器」，产出真实可解码的 MJPEG AVI（实测 `Duration: 00:00:02.00`、`Video: mjpeg (Baseline) 320x240 5fps`），无外部依赖 |
| QMediaPlayer 需 `QApplication` 而非 `QGuiApplication` | 视频 E2E 用 `QApplication`；另修复 `tests/make_fixtures.py` 中 `_cover_png` 自建 `QGuiApplication` 的隐患（会让后续 `QApplication` 永远建不出来 → QWidget 构造 exit 127） |

### 13.6.1 v2.1 实现收尾记录（2026-10-26）

- 画面输出：**QVideoSink 自绘**（详见 §13.2 路线修正记录），新增 `ui/video_view.py` 三个类。
- 视频夹具：`tests/make_fixtures.py` 新增 `ensure_video_fixture()`，产出 `tests/fixtures/我的视频/测试短片.avi`（约 20KB，5fps×10帧）。
- 播放链路：播放器长期绑定 sink（`set_video_output` 只调一次），切模式绝不重连媒体源。
- 全屏：`VideoFullscreenOverlay` 记录原父/布局/索引 → reparent → `showFullScreen()`；`leave()` 原样还原。
- Esc 优先级：全屏 > 清空搜索（主窗口 `_on_escape`）。

### 13.7 v2.1 验收标准

- [x] 常见本地视频可通过文件夹/文件/拖拽导入，列表显示「视频」徽标，原音频导入不回归。
  - 证据：`tests/test_video.py::TestMediaScan`（混合扫描/单文件/旧别名/大小写）；`TestE2EVideo.test_import_video_into_library` / `test_video_row_shows_video_badge`
- [x] 双击视频显示画面并播放；播放/暂停/切歌/进度/音量/队列/收藏与音频一致。
  - 证据：`TestE2EVideo.test_double_click_video_enters_video_page`、`test_video_frames_are_painted`（sink 收帧 + widget 出现非黑像素）、`test_video_supports_favorite_and_queue`
- [x] 音乐模式与视频模式切换不中断声音、不改变当前曲目和播放进度。
  - 证据：`TestE2EVideo.test_music_mode_switch_keeps_playback` —— 切换前后 `current_track` / `position_ms` / `source()` 三重断言
- [x] 返回列表声音继续；`F11` 全屏、`Esc` 退出，画面比例正常。
  - 证据：`test_back_to_list_keeps_playing` / `test_f11_shortcut_toggles_fullscreen` / `test_fullscreen_toggle_keeps_playback` / `test_escape_exits_fullscreen_before_clearing_search`；截图 `shots/dark-video_fullscreen.png`（画面 4:3 等比居中、两侧 letterbox、无残留主窗口 UI）
- [x] 上次视频与断点可恢复；不支持文件有友好提示，不卡死。
  - 证据：`test_video_duration_backfilled_after_load`（mutagen 读不出 AVI 时长 → 加载后回填并落盘）；既有错误提示/跳过链未改动
- [x] 视频相关测试通过，`run_tests.py` 全量回归全绿，`ruff check .` 干净。
  - 证据：11 个独立进程全绿（既有 122 + 新增 35 = **157 项**）；`ruff check .` → All checks passed
- [x] 真实平台视频页/音乐模式/全屏验证通过，双 EXE 重建并完成冒烟检查。
  - 证据：`shots/dark-video.png`、`shots/light-video.png`、`shots/dark-video_fullscreen.png`（真实 windows 平台，中文字体正常）；真实音频输出与拖拽手感待用户本机确认（沙箱无音频渲染）

## 14. v2.2 歌词联网补全 + 外观自定义（2026-10-27）

### 14.1 需求确认

用户原话：「可以识别歌曲歌词，对于自定义背景更多内容可自定义」。逐项澄清后确认：

| 问题 | 结论 |
|---|---|
| 歌词从哪来 | **联网匹配**：本地没有时按「歌名+艺人」从 LRCLIB 拉取并缓存，之后离线可用 |
| 背景类型 | **图片 + 纯色 + 渐变**三种都支持 |
| 还可调什么 | 背景不透明度 / 模糊 / 暗化、字体大小、强调色、**按页面分别设置** |

### 14.2 歌词：五级来源与身份门槛

```
手动绑定 .lrc → 同目录同名 .lrc → 内嵌歌词 → 本地缓存 lyrics_cache/<id>.lrc → 联网
```

- 前四级同步完成；第五级走 `LyricsFetchWorker`（QThread），不阻塞 UI
- 同一首只请求一次（`_online_attempted`）；失败也不重试，避免每次切歌都打网络
- 结果回来时比对 `current_track.id`，用户已切歌就只写缓存、不动面板
- **匹配宁缺勿滥**：候选必须带「身份信号」（歌名/艺人包含，或时长差 ≤3s），
  否则丢弃；`instrumental` 直接跳过。配错歌词比没歌词更糟
- 可关闭（`Settings.online_lyrics`），关闭后一次请求都不发

### 14.3 外观：一个色值 + 一档字号

- `derive_accent(base, accent)`：按底色亮暗算 hover（深底提亮 / 浅底压暗）、
  dim（压暗 30%）、soft（往 SURFACE 混 13%）、on_accent（白字对比度 ≥3:1 才用白）
- 硬约束（已固化为断言）：hover/dim 与主色通道差 ≥12；任意色的 `ON_ACCENT`
  对主色 ≥3:1；非法色值回落主题默认
- 字号：`build_stylesheet(font_scale=)` 用正则把全部 `font-size: Npx` 乘以系数，
  夹取 0.85~1.30、单处不低于 9px（固定行高 52 / 播放栏 84 不会再长）

### 14.4 背景：铺满 + 面板半透明

- `BackgroundLayer`：`_root` 的第一个子控件（天然最底层）、鼠标穿透、内缩 1px
  让圆角描边可见；图片 `KeepAspectRatioByExpanding` + 居中裁切；模糊用
  「降采样→平滑升采样」近似高斯（`QGraphicsBlurEffect` 太慢且边缘发黑）
- 有背景时 `build_stylesheet(scrim=0.78)`：
  1. 全局把 SURFACE 换成 `rgba(...,0.78)`、BG 换成 `rgba(...,0.33)`（页面底色要更透，
     否则深色主题下页头/列头变成压在图上的一条黑带）
  2. **末尾追加不透明覆盖**：`#WindowRoot` 用回原 BG（否则降低背景不透明度时
     透出的是桌面）、对话框/菜单/输入框/Toast 用回原 SURFACE（它们是独立顶层窗口）
- 按页面：`Settings.bg_all / bg_library / bg_now`，`bg_config(page)` 在 `inherit`
  为真时回退到 `bg_all`；切页调 `_refresh_background()`，只有「有没有背景」翻转时
  才重建整张 QSS
- 图片导入即复制进 `%APPDATA%/轻音播放器/bgs/`（`import_background`），原图删了不失效

### 14.5 数据模型增量

```python
@dataclass
class BackgroundConfig:
    type: str = "none"        # none | color | gradient | image
    color: str = "#3b82f6"    # 纯色 / 渐变起始
    color2: str = "#8b5cf6"   # 渐变终止
    image: str = ""           # 已复制到 bgs/ 的路径
    opacity: float = 1.0      # 0.2~1.0
    blur: int = 0             # 0~60
    dim: float = 0.0          # 0~0.7
    inherit: bool = True      # 仅分页面时有意义

class Settings:              # 新增
    online_lyrics: bool = True
    accent_color: str = ""            # "" = 跟随主题
    font_scale: float = 1.0
    bg_all / bg_library / bg_now: BackgroundConfig
```

### 14.6 验收标准（v2.2 增量）

- [x] 本地无歌词时自动联网补，命中后缓存、之后离线可看。
  - 证据：`tests/test_lyrics_online.py`（25 项，全程注入 fetch 不联网）；
    e2e `test_online_lyrics_fetched_once_then_cached`（清内存缓存后仍显示）
- [x] 本地已有歌词时一次网络都不打；可关闭联网。
  - 证据：e2e `test_local_lyrics_win_over_online`、`test_online_lyrics_respects_setting_and_skips_video`
- [x] 不配错歌：无身份信号的候选一律丢弃。
  - 证据：`test_rejects_unrelated_song`、`test_skips_instrumental`、`test_skips_hit_without_any_lyrics`
- [x] 强调色可自定义且处处生效（QSS / 图标 / 均衡器条 / 播放键投影）。
  - 证据：`test_accent_applies_and_persists`；截图 `shots/dark-library-orange.png`
- [x] 字号四档，任意档位布局不破。
  - 证据：`test_font_scale_rebuilds_qss_and_keeps_layout`（`PlayerBar.minimumSizeHint ≤ 1100`）；截图 `shots/light-library-big.png`
- [x] 背景支持图片/纯色/渐变，可调不透明度/模糊/暗化，可按页面分别设置。
  - 证据：`tests/test_background.py`（16 项）+ e2e 背景 6 项；截图
    `shots/dark-library-bggradient.png`、`shots/dark-library-bgimage.png`、`shots/light-library-bgcolor.png`
- [x] 背景不会因为原图被删而失效；关掉背景完全还原。
  - 证据：`test_same_image_reused`、`test_background_off_restores_opaque`
- [x] 全量回归全绿、`ruff check .` 干净、双 EXE 重建。
  - 证据：`run_tests.py` 21 进程；`ruff check .` → All checks passed

## 15. v2.3 「星月」默认主题（2026-10-27）

### 15.1 需求与边界

用户给了一张《原神》「空月之歌」角色立绘，原话：「用图案中的角色元素新做一个所有背景的
默认主题」。落实为三条：

| 项 | 结论 |
|---|---|
| 复刻什么 | **视觉语言**：深紫夜空基底、冰蓝月光强调色、莓红点缀、星点/月牙/羽毛元素 |
| 不复刻什么 | **不嵌入官方立绘**。版权素材不能随 EXE 分发，也不该成为界面默认背景 |
| 默认值 | 新装默认主题改为 `columbina`（「星月」），深色/浅色保留，主题钮改为**三态循环** |

### 15.2 配色：一个主题 = 一张色卡

```python
COLUMBINA = Theme(
    name="columbina",
    BG="#130e26", BG_ALT="#0b1526",          # 深紫夜空 → 更深的蓝紫
    SURFACE="#1c1632", SURFACE_HOVER="#251d3f", SURFACE_ACTIVE="#2f264c",
    BORDER="#3a2f56", TEXT="#f3eefc", TEXT_DIM="#a196bd",
    ACCENT="#7ec8e8", ACCENT_HOVER="#9ad9f3", ACCENT_DIM="#4a7f99",
    ACCENT_SOFT="#2c2546", DANGER="#ff6b7d", HEART="#ff5c8a", ON_ACCENT="#0f1622",
)
```

- **首版偏黑**：`BG #0e0a18` 与 `SURFACE #181226` 只差一点，整窗糊成一块黑，层次全无。
  修法两条：① 整套面板色提亮拉开；② 新增 `Theme.BG_ALT`，非空时窗口底走
  `qlineargradient(x1:0,y1:0,x2:0.65,y2:1)`，纯色底变斜向渐变，深度感来自光而不是靠深色
- 对比度实测：`TEXT/SURFACE=16.0`、`ACCENT/SURFACE=9.8`、`ON_ACCENT/ACCENT=9.8`、
  `TEXT_DIM/SURFACE=6.3`（全部 ≥4.5，已固化在 `test_theme` 的对比度断言里）
- `ON_ACCENT` 用深色而非白色：冰蓝偏亮，白字对比度仅 ~2.1:1

### 15.3 装饰层：星点 + 月牙

```python
def _paint_theme_decor(painter, rect, color):
    rnd = random.Random(_DECOR_SEED)     # 固定种子，缩放时星点不乱跳
    for _ in range(56): ...              # 半径 0.6~1.9px，alpha 22~72
    # 月牙：直径 = min(w,h)*0.38，圆心 (0.87w, 0.70h)，alpha 14
```

- 只在 **`columbina` + 背景类型为 none** 时画（用户自己设了背景就不叠加，否则是脏图）
- 画在 `BackgroundLayer.paintEvent` 里，**不参与 `is_active()`**：装饰不算自定义背景，
  所以不会触发面板转半透明（`test_theme_decor_is_not_custom_background`）
- alpha 上限刻意压到 72/14：装饰是氛围，不能跟歌词和封面抢注意力
- **月牙位置试了三版**（截图对比才看出来的问题）：
  ① 贴右下角 → 被 84px 播放栏压成一道残弧横穿音量条，像渲染脏点；
  ② 右上角故意裁出画面 → 月牙缺口被切掉，只剩一大块淡圆盘，像污渍；
  ③ 现在：**完整细月牙**放在右半区竖向 70%（歌曲行下方的空白带）。形状完整才
  读得出是月亮，alpha 14 又不会让列表里的字和爱心发灰
- `feather` 图标也返工过一次：首版是「羽轴 + 8 条细羽枝」的纯线条画法，
  16px 下糊成一小团灰点、和相邻 `settings`（细横线）撞气质；改为
  「实心羽片 + 镂空羽轴 + 两侧羽枝缺口」，靠实心轮廓站住（同 `gear` 的教训）

### 15.4 两态主题循环（深色 ↔ 浅色）

> 改名记录：`columbina` 的显示名先叫「星月」（v2.3）→「空月」（v2.3.3）→
> **「深色」**（用户要求，名字更直白地与「浅色」成对）。只改 `THEME_LABEL`，
> 内部 id 与持久化值不动。

```python
THEME_ORDER = ("columbina", "light")                # v2.8.3 两态
THEME_NEXT  = {…按 THEME_ORDER 环形生成…}
THEME_ICON  = {"columbina": "moon", "light": "sun"}
THEME_LABEL = {"columbina": "深色", "light": "浅色"}
DEFAULT_THEME = "light"
```

- 浮动条主题钮的**图标与 tooltip 都指向「点下去会切到哪个」**，不是当前主题
  （羽毛=深色 / 太阳=浅色）；`isChecked` 只在浅色时为真，保留原语义
- 新增手绘 `feather` 图标（实心羽片 + 镂空羽轴 + 羽枝缺口），与相邻的 `settings` /
  `gear` 不同形：实心块 vs 细横线 vs 锯齿环，16px 下不会混
- 设置对话框按 `THEME_ORDER` 生成 radio；`light_radio` 保留为别名不破坏旧引用
  （原「深色」主题已删除，`dark_radio` 一并移除）
- toast 文案改由 `THEME_LABEL` 生成：循环表驱动，别写死「浅色 else 深色」

### 15.4b 主题与背景拆开 + 内置背景预设（v2.8.3）

把「主题 = 配色」与「背景 = 图片」彻底拆开：主题只留「浅色 / 深色」两套配色，
原来的「深色2 / 浅色2」两张内置图（星空 / 云海）从主题里挪到「背景」页，成为
**内置背景预设**（`BACKGROUND_PRESETS`，id `starry` / `clouds`）。任何主题都能配
任何背景，互不联动。

- 数据模型：`BackgroundConfig` 新增 `preset` 字段（预设 id）；`background_preset_config(id)`
  翻成 `BackgroundConfig`（type=image、preset=id、带预设默认 opacity/dim/blur）。
- **图片路径现解**：预设只存相对路径 `assets/theme_dark.jpg`，渲染时经
  `preset_image_path()` → `app/paths.resource_path()` 解成绝对路径。不能把 `_MEIPASS`
  临时路径写进 data.json（onefile 每次启动临时目录都变）。
- **不写用户设置里的主题**：选预设只改当前页的 `BackgroundConfig`，`Settings.theme`
  一个字不动；切主题也不碰背景。老数据 `columbina2/light2` 在 `Settings.from_dict`
  归一成 `columbina/light`。
- 打包：`build.data_args()` 统一出 `--add-data`（`BUNDLED_ASSETS` 与
  `BACKGROUND_PRESETS` 的 image 逐字一致，`test_bundled_paths_match_preset_definition` 钉住）
- 暗化值不是拍的：`tools/probe_theme_bg.py` 可复现对比图（现按 `--preset` 选图）。
  星空的月亮正好压在「大小 / 时长」列下，其 p90 亮度 0.347 ≈ `TEXT_DIM` 亮度 ——
  暗化 0.3 时对比度只有 0.84（字比背景还暗）。0.5 + 不透明度 0.9 后月亮主体回到
  3.2:1；月亮中心的镜面高光（纯白像素）仍压不住，这是「照片当背景」的固有上限。

### 15.5 验收标准（v2.3 增量）

- [x] 默认主题是「浅色」（v2.3 时曾为 `columbina`，后续按用户要求改为 `light`），新装与旧数据都落到 `light`。
  - 证据：`test_default_is_light`、`test_legacy_data_without_new_settings`
- [x] 主题循环闭环、每个主题都有图标与中文名。
  - 证据：`TestThemeCycle` 5 项（含「循环覆盖全部且闭环」「同族相邻」「循环表不写反」）
- [x] 装饰该画时画了、不该画时一个像素都不画；装饰不算自定义背景。
  - 证据：`TestThemeDecor` 3 项（`render(QImage)` 采样，**不用 `grab()`** —— 它先铺
    不透明白底，测不出「透明」与「极淡」）
- [x] 主题切换 / 持久化 / 浮动条按钮语义全部跟随两态。
  - 证据：e2e `test_theme_switch_applies_and_persists`、`test_float_bar_theme_toggle`
- [x] 视觉验收：整窗截图（星月/深色/浅色）+ 图标验收表含羽毛与齿轮对照。
  - 证据：`shots/columbina-library-v230r2.png`、`shots/columbina-maximized-v230r2.png`、
    `shots/columbina-playing-v230r2.png`；图标表 `shots/icons_v230.png`
    （7 个图标 72px 原图 + 16px 最近邻放大 8×，浅/深两版，
    顺序按界面相邻关系排：gear / settings / feather / moon / sun / folder / plus）

## 16. v2.3.5 浅色主题按参考图重做（2026-10-28）

用户第二次发来同一张参考图并说「浅色做成这样」—— 说明上一版只是"浅紫玻璃"，
没抓住参考图的三个特征：**冷调月白底、一支巨大的线描羽毛、近乎没有面板分界**。

### 16.1 色值全部从参考图采样

| token | 旧 | 新 | 依据 |
|---|---|---|---|
| `BG` | `#f4f2fc`（粉紫） | `#eef2fb` | 参考图直接采样（R238 G242 B251，蓝最高=冷调） |
| `SURFACE` | `#ffffff`（白卡片） | `#f5f8fd` | 参考图侧栏/内容/播放栏几乎同色，只差 1~2 阶 |
| `SURFACE_HOVER` | `#edeafb` | `#e6ecfa` | 参考图的搜索框是**比底更暗**的内凹，不是白胶囊 |
| `BORDER` | `#dcd6f2` | `#d9e1f5` | 层次靠细边框，不靠白卡片压浅底 |
| `TEXT` | `#262238` | `#2c3552` | 深蓝墨（不是纯黑），与冷底同源 |
| `ACCENT` | `#7c83f0`（偏紫） | `#7389cb` | 参考图播放键 ≈`#7f97d6`，但那色白字只有 2.88:1，压深到 3.4:1 才过可读性下限 |

`test_theme` 的蓝通道、对比度断言全部照旧通过 — 换色没换约束。

### 16.2 装饰层重写（`_paint_light_decor`）

参考图的疏朗感来自**「少而大」**：一支约 0.9 窗高的羽毛 + 一枚带光环的罗盘星 +
几点微光，其余全是留白。旧实现是"18 颗碎星撒满全窗 + 两片小叶子"，读起来是噪点。

几何按参考图逐点量：羽尖 `(0.955w, 0.155h)`、羽根 `(0.795w, 1.02h)`（落在窗口外，
裸羽轴伸出画面）、最宽处半宽 `0.135·length`、羽片从轴的 14% 处起、两侧不等宽
（右 100% / 左 92%）。

**三次返工，每次都是"形状对但读不出来"**：

1. **实心四角星 → 一坨蓝色菱形**。`_paint_four_point_star(k=0.32)` 在 90px 尺度下
   是块肥菱形；改描边又是"蜘蛛网"。最终用**腰部只有 7% 的细长实心尖刺**（4 长 + 4 短）。
2. **羽枝 26 对 → 梳子/梯子**。两个原因：羽枝太密；轮廓与羽枝各画一套贝塞尔，
   边和"齿"对不上。改为**两者共用同一个 `silhouette()` 生成器** + 疏到 16 根 +
   斜扫（沿轴推进 = 横移的 0.85）+ 到边线前收住。
3. **羽片根部硬截断**。`half_width` 直接对全轴取形，在 `t=0.14` 处留下 36% 宽的
   断口，两条边悬空像被剪过。修法：先把 `t` 重映射到"羽片自己的 0~1"再取形。

### 16.3 线色不是强调色（量化后的结论）

第一版用 `ACCENT` + 低 alpha，最深的线只到亮度 173（背景 244），而参考图是 140 ——
**差 1.4 倍浓度**，肉眼看就是"发虚、像脏点"。改为把强调色压深到 75%
（`ink = accent × 0.75`）再配高 alpha，逐轮采样校准到 p0.5=176 / p2=211（参考 193/219）。

方法沉淀：**别只凭观感调装饰浓度**。取同一块"无文字纯装饰区"统计 min / p0.5 / p2
三档灰度，与参考图对齐，两轮就能收敛。

### 16.4 装饰不能落在控件后面

装饰层在控件**下面**。星一开始放在 `(0.93w, 0.18h)`（参考图的相对位置），结果正好被
"排序"下拉框盖住半个，只剩一个孤零零的圆点 —— 看着像渲染 bug。最终挪到羽毛左侧
`(0.80w, 0.58h)` 的空档：构图略低于参考图，但**没有控件遮挡**优先。

### 16.5 验收

- 全量回归 22 进程 **345 项全绿**；`ruff check .` 干净
- 灰度分布对齐（见 16.3）；整窗截图 + 设置面板 + 深色主题回归目检
- 截图：`shots/light-v235-library.png`、`shots/light-v235-compare.png`（与参考图上下对比）

## 17. v2.3.6 深色主题按参考图重做（2026-10-28）

用户发来深色参考图（同一套 UI 的夜景版）说「深色做成这样」。上一版深色是
「一颗巨大实心亮月 + 撒满全窗的星点 + 三片线描羽」，参考图的语汇完全不同：
**玻璃质感的半透明月牙、套在外面的一圈轨道、环上的罗盘星、几片柔焦浮羽**。

### 17.1 分五层重画（`_paint_columbina_decor`）

| 层 | 做法 |
|---|---|
| 径向辉光 | `QRadialGradient`，半径 = 轨道环 × 2.55，中心 α58 → 边缘 0 |
| 星尘 | 24 颗四角星（α30~85）+ 36 个细点（α20~55），固定种子 |
| 轨道环 | 1px 细圈（α44）+ 24 个径向刻度（长短交替） |
| 月牙 | 两圆**差集** + 双层软内带 + 1.6px 亮边，内部只比背景亮 ~14 阶 |
| 罗盘星 | 内凹四角星 + 竖杆（3.6r）+ 4 组人字刻度 + 十字准线 |
| 浮羽 | `_paint_soft_feather()`：横向渐变填充（边缘透明）+ 羽枝 + 基部发亮的羽轴 |

### 17.2 三个关键坑

1. **两段圆弧拼不出月牙**。`arcMoveTo(outer, 78)` + `arcTo(inner, 282, -204)` 会在
   两个弧的端点之间留一条**直线弦**，月牙的尖角被削平成一个"灰色 D"。正确做法：
   `outerDisc.subtracted(innerDisc)` —— 尖角是两个圆真实相交处，天然锐利。
2. **发光不是"整体涂白"**。旧版把月牙填成 α205 的近白，深底上读成贴纸。参考图的
   亮在**边缘**、内部几乎透出底色：实测参考图「月亮内部 56 / 外侧背景 45」只差 11 阶，
   而涂白版差 30 阶。改成淡填充（α10/7/4）+ 双层软内带 + 亮边后收到 14 阶。
3. **羽毛不能"线描"**。深色的浮羽是柔焦写实质感，用轮廓线画会变线稿插图。
   改成**横向渐变填充**（两侧透明、中线有色）+ 10 根极淡羽枝 + 基部最亮的羽轴
   （羽轴自身用 `QPen(QBrush(渐变))`，朝羽尖渐隐）。

### 17.3 位置取舍

参考图的罗盘星在轨道环**右侧**，但我们右侧整片是列表列（时长 / 编辑），星会压在
图标上。改放环的**正下方**交点：同样"骑在轨道上"，那片是空的，竖杆还正好接上环的
竖直轴。**无遮挡优先于构图完全吻合**（同 v2.3.5 浅色的教训）。

另外 `_paint_concave_star()` 与 `_paint_soft_feather()` 拆成了独立小函数，浅色主题
将来要复用不必再写一遍。

### 17.4 验收

- 全量回归 22 进程 **345 项全绿**；`ruff check .` 干净
- 灰度采样对齐（月内/月外差 14 vs 参考 11；最近/最远辉光差 12.3 vs 6.0）
- 截图：`shots/columbina-v236-library.png`、`shots/columbina-v236-compare.png`

## 18. v2.4.0 联网歌词检索改进（2026-10-28）

v2.2 的联网歌词只有**一条**结构化查询（`/api/search?track_name=&artist_name=`）
和一套宽松打分。真实曲库的标签很脏（`晴天 (Live)`、`01. 晴天`、`周杰伦/费玉清`、
`Hotel California - 2013 Remaster`），一条查询匹配不上就是零结果；而宽松打分又会在
"艺人对得上、歌名对不上"时给出别的歌的歌词。v2.4 从两方面同时改。

### 18.1 从"一次查询"到"有序查询计划"

`lookup_plan()` 按**精确在前、宽泛在后**生成最多 4 条查询，重复 URL 去重：

| 序 | 查询 | 作用 |
|---|---|---|
| 1 | `/api/get?track_name&artist_name[&album_name][&duration]` | 精确端点，一次请求最高精度；未命中返回 404 |
| 2 | `/api/search?track_name&artist_name`（清洗后标题 + **原始**艺人） | 结构化检索 |
| 3 | `/api/search?track_name&artist_name`（清洗后标题 + **主**艺人） | 多艺人标签的降级 |
| 4 | `/api/search?q=`（清洗后标题） | 自由文本，覆盖任意字段，最不准所以垫底 |

**早停**：任一条命中且得分 ≥6.5（无时长信息时 ≥4.5）就停，不再往下打。实测
`晴天`/`周杰伦` 第 1 条即命中，只发 1 个请求。

`duration` 只在 1..3600 秒之间才拼进 URL —— 越界会被服务端 400 拒绝。

### 18.2 标签清洗（`clean_title` / `clean_artist`）

原则是**只删明确的噪声**，不做激进切分：

- 全角 ASCII 与全角空格 → 半角（否则全角括号组根本匹配不到）
- 括号组只在**内容含噪声词**时删除（live / remaster / 伴奏 / 主题曲 / 版 …）；
  `Song (Part 2)` 这种括号是歌名的一部分，必须保留
- 前导音轨号分两种形态：`[07] 歌名` 括号本身即强信号；`01. 歌名` 裸号码必须跟分隔符
  ——否则 Taylor Swift 的《22》会被当音轨号吃掉
- 破折号尾巴只在**最后一段含噪声词**时砍（`晴天 - Remastered 2011`），
  `Jay-Z - 99 Problems` 原样保留
- 多艺人只按 `; / ／ 、 | feat.` 切分，**不切 `&` 和 `,`**：
  `Simon & Garfunkel`、`Earth, Wind & Fire` 是单一艺人名

洗空了退回原文，绝不返回空串（空串会被 `lookup_plan` 判成"没歌名"直接放弃）。

### 18.3 打分收紧

| 信号 | 分值 |
|---|---|
| 标题完全相等 / 包含且长度相近 | +3.0 / +2.0 |
| 艺人完全相等 / 包含 | +1.5 / +1.2 |
| 时长差 ≤2s / ≤5s / ≤10s | +3.0 / +2.0 / +1.0 |
| 有可用的同步稿 | +0.5 |
| 标题对上但艺人和时长**双双不符** | −1.5（同名翻唱） |

- **身份门槛**：`标题对得上 or 时长差 ≤2s`。v2.2 还允许"只有艺人对得上"，
  但"不同歌手唱同一首"正好落在这个口子上，是配错歌词的主要来源，已移除。
- **包含式匹配加长度校验**：否则歌名"雨"会匹配到"下雨天"。
- **同步稿单独分区**：只要同一首歌有带时间轴的稿子，就绝不用纯文本稿——
  不能滚动高亮的歌词体验差得多，宁可分低一点也要同步稿。
- **可用性校验**（`usable_text`）：纯空白、只有 `[00:01.00]` / `[Chorus]` 标记的
  一律不算歌词。

### 18.4 负缓存与手动重试

- 确认没找到 → 写 `lyrics_cache/<track_id>.miss`（时间戳，TTL 7 天）。
  否则每启动一次就为一首冷门歌/纯音乐打 3~4 个请求。
- 歌词区**右键「重新联网匹配歌词」**（`LyricsPanel.retry_online_requested`
  → `MainWindow._retry_online_lyrics`）清掉 `.miss` 与"本次已试过"，强制重来。
- 空状态文案区分三态：默认"暂无歌词" / 检索中"正在联网匹配歌词…" /
  没找到"未找到歌词 + 右键重试提示"。

### 18.5 限流不能当成"没有歌词"

**这是真实联网验证才暴露的坑**。LRCLIB 匿名 ~45 请求/分钟、标识 UA ~90/分钟，
超限 429 + `Retry-After`，服务过载 503。

第一次批量验证时连发十几个请求被 429，`fetch_lyrics` 返回 None，上层就把它当
"未命中"写进了负缓存——一首明明有歌词的歌被记住 7 天。修法是让结果带上原因：

```python
@dataclass(frozen=True)
class FetchOutcome:
    text: str | None = None
    aborted: bool = False     # 限流/预算中止，不能据此写入负缓存
```

`LyricsFetchWorker` 只在 `aborted=False` 且无歌词时才发 `missed`；中止时改发
`aborted` 信号，界面据此把「正在找」换成「失败可重试」，同样不落负缓存——
否则一次网络抖动就会让歌词区永远卡在加载提示（v2.6.2 修）。
另外按官方建议在请求之间加 250ms 间隔（`_throttle()`，只作用于真实 HTTP 路径，
注入的 `fetch` 不受影响，测试不变慢）。

### 18.6 效果（真实联网，同一批脏标签）

| 标题 | 艺人 | v2.2 | v2.4 |
|---|---|---|---|
| 晴天 (Live) | 周杰伦 | ✓ | ✓ |
| 01. 晴天 | 周杰伦 | × | ✓ |
| 晴天 | 周杰伦/费玉清 | × | ✓ |
| 海阔天空 (Live) | Beyond | × | ✓ |
| Count On Me - Acoustic | Bruno Mars | × | ✓ |
| Bohemian Rhapsody - Remastered 2011 | Queen | ✓ | ✓ |
| 平凡之路（电影《后会无期》主题曲） | 朴树 | ✓ | ✓ |
| Hotel California - 2013 Remaster | Eagles | ✓ | ✓ |
| Yellow (Live) | Coldplay | ✓ | ✓ |
| 不存在的歌名 XYZ | Nobody | × | × |

**命中率 6/11 → 10/11**；那首真实不存在的歌两边都正确地判为未命中。
请求数反而更少：多数歌第 1 条 `/api/get` 就命中，只发 1 个请求。

### 18.7 验收

- `tests/test_lyrics_online.py` **71 项**（原 33）；`tests.test_e2e.TestE2ELyricsOnline` 6 项
- 全量回归 22 进程全绿；`ruff check .` 干净

## 19. v2.5.0 图标清晰度与齿轮重画（2026-10-28）

用户发来整窗截图，用红圈标出左下浮动条的**设置齿轮**，说「优化一下图案」。

### 19.1 先量，别先画

把红圈区域按原图坐标裁出来放大 12 倍并叠 1 像素网格，数出来两个数字：

- 圆形按钮直径 ≈ 45 设备像素
- 里面的齿轮只有 **9×10 设备像素**，而且是一团斜向的灰影，看不出齿

16 逻辑像素的图标在 125%~150% 缩放的屏幕上应该占 20~24 设备像素。实际只剩 9~10 ——
说明图标不是"画得不好看"，是**被放大绘制糊掉了**。

根因在 `ui/icons.py`：`_paint()` 一直按 `QPixmap(size, size)` 生成 16×16、DPR=1 的位图。
高分屏上 Qt 要把它画进 20~24 设备像素的矩形，只能平滑放大 → 边缘全糊。
齿轮齿数多、特征细，是全场最先崩的那个（主题钮的太阳是"点 + 8 根细射线"，
结构简单，糊了也还认得出）。

### 19.2 修法：图标按设备像素渲染

```python
def device_ratio() -> float:          # 125% 屏 → 1.25；无 QGuiApplication → 1.0
def _paint(kind, size, color, dpr=1.0):
    px = max(1, round(size * dpr))    # 画布用设备像素
    pm = QPixmap(px, px)
    ...
    pen.setWidthF(max(1.2 * dpr, px * 0.085))   # 笔画粗细跟着分辨率走
    u = px                                      # 绘制单位 = 设备像素
    ...
    pm.setDevicePixelRatio(dpr)       # 告诉 Qt 按逻辑尺寸画
```

`make_icon()` 的缓存键加上 `dpr`，换屏幕不会拿到旧比例的小图。
另外补了 `make_pixmap()`：`QIcon.pixmap(18, 18)` 这个两参重载默认按 DPR=1 取图，
会把高分屏位图又降采样回去，所以 sidebar / title_bar / queue_panel 三处直接
`setPixmap` 的地方改用它。

效果（本机 125%）：同一份代码，左边是旧的"放大绘制"，右边是按设备像素直接渲染。
齿的边界、中心孔、齿谷全部变得锐利。

### 19.3 齿轮本身也重画了

修完清晰度再看 20 设备像素下的齿形，旧的 8 齿仍然读成"多角星"而不是齿轮。
参数是**在 20px / 24px 上逐轮对比**定的（在 16px 上判断会得出错误结论 ——
这是这一轮最浪费时间的一步）：

| 参数 | 旧 | 新 | 理由 |
|---|---|---|---|
| 齿数 | 8 | 8 | 8 齿是最"齿轮"的齿数；6 齿读成六角螺母，10 齿糊成花边 |
| 齿深 | 0.16（0.45/0.29） | 0.12（0.47/0.35） | 环体必须占主导，齿只是环上的凸起 |
| 齿顶平台 | 0.28 步 | 0.44 步 | **齿顶是宽平面而非尖角**，这是"齿轮"和"星形"的分水岭 |
| 齿面斜边 | 0.16 步 | 0.09 步 | 陡峭的齿面才像啮合齿 |
| 轴孔 | Ø0.28 | Ø0.30 | 20px 下孔径 6px、环宽 4px，两面都稳 |

走过两轮弯路，记下来避免以后再踩：

1. **齿深加大 → 变星星**。第一轮把齿深从 0.16 加到 0.19、齿数降到 6，结果六个尖角
   读成"风车/多角星"，比原版更像装饰图形。
2. **参数矩阵漏了"齿谷"那一段**。我的四折点公式里把第 4 点写成
   `2*斜边+平台`，导致齿谷宽度恒为 0（两个齿在齿根处直接相接），整批变体都成了锯齿边。
   改成显式的 `平台/斜边` 两个参数、齿谷 = 1 − 平台 − 2×斜边 之后才对。

### 19.4 验收工具也补了一行

`tools/probe_icons.py` 原来只出「72px + 16px 放大 8 倍」。16px 只是逻辑尺寸，
真实界面按 16×DPR 渲染，所以**只看这一行根本发现不了糊掉的问题**。现在多出第三行：
按设备像素渲染再放大同样倍数。以后判断小图标一律看这一行。

### 19.5 验收

- 齿轮在浅色/深色两套主题下都是清晰的实体齿轮，与相邻的太阳（点 + 细射线）一眼可分
- 浮动条尺寸未变：`sizeHint() = (224, 82)`，右缘仍为 236（≤ 侧栏内容右边界）
- 全量回归 22 进程全绿；`ruff check .` 干净
- 截图：`shots/v250-icons.png`（三行验收表）、`shots/v250-float-bar.png`

## 20. v2.5.1 主题钮图标改为月亮（2026-10-28）

用户发来整窗截图，红圈标出左下浮动条**上方那个圆钮**（主题切换），只说了三个字：画成月亮。

### 20.1 先确认「这是哪个按钮、原来画的是什么」

浮动条左列是上下两个正圆钮：上=主题切换，下=设置齿轮。红圈落在上面那个。
按原图坐标裁出该区域并扫描深色像素行段，确认钮内字形只有 9×10 设备像素，
内容是 `feather`（羽毛）——由 `THEME_ICON` 表决定：

```python
THEME_ICON = {"columbina": "moon", "light": "sun"}   # v2.5.1
# 原来是 {"columbina": "feather", "light": "sun"}
```

注意这里画的**不是当前主题**，而是「点下去会切到哪个主题」（`set_theme_icon` 取 `THEME_NEXT`）。
所以浅色主题下显示月亮（→ 切深色），深色主题下显示太阳（→ 切浅色）。
用户截图是浅色主题，圆钮上正是羽毛。

旧羽毛的问题不是"羽毛画得不像"，而是在 24 设备像素里要同时承载轮廓 + 16 根羽枝，
糊完之后读成一块斜网格/蝴蝶结，既不像羽毛也不像任何可辨认的对象。

### 20.2 月亮怎么画：两圆差集，不要拼弧

```python
p.save(); p.translate(u*0.5, u*0.5); p.rotate(-30); p.translate(-u*0.5, -u*0.5)
outer = QPainterPath(); outer.addEllipse(外圆 R=0.42)
inner = QPainterPath(); inner.addEllipse(内圆 0.90R 右移 0.16)
p.fillPath(outer.subtracted(inner), color)
p.restore()
```

`arcMoveTo + arcTo` 拼两段弧会在两个弧端点之间连出一条**直线弦**，月牙的尖角被削平成
「灰色 D」。这是 v2.3.6 深色背景装饰月牙已经踩过的坑（DESIGN §17.2 / MEMORY #59），
这次直接复用结论：**尖角必须是两个圆真实相交的位置**。

### 20.3 参数在设备像素上定，不凭观感

| 参数 | 取值 | 理由 |
|---|---|---|
| 外圆半径 | 0.42 | 画布 84%，留 8% 边距；再大在小尺寸下会被裁 |
| 内圆半径 | 0.90 × R | 月牙最厚处 ≈0.42−0.29=0.13u，24px 下约 3px，不会断成细线 |
| 内圆偏移 | +0.16 | 开口宽度 ≈0.16u+，20px 下仍能看出"开口"而不是一条缝 |
| 整体旋转 | −30° | 经典月亮姿态；不转的月牙看着像被咬了一口的圆 |

**尺寸断言**：在 20/24/72/96 px 上量包围盒，宽度 77~80%、高度 85~90%。
测试阈值取 `width ≥ 0.72` / `height ≥ 0.80`——按实测留一档余量，
而不是写死某个像素数（早期两版断言分别死在 7 vs 6、73 vs 79 这种差一像素上）。

### 20.4 只改表，不改调用点

主题钮的图标来源始终只有一张表：`THEME_ICON`。这次改动只动了
`ui/icons.py`（画法）、`ui/theme.py`（表里 feather→moon）、`ui/float_bar.py`（初始值）。
设置页 radio、浮动条 tooltip、toast 三处显示名仍统一读 `THEME_LABEL`，
`data.json` 里持久化的仍是 `columbina`/`light`，无数据迁移。

### 20.5 验收

- 浅色主题：圆钮内是月牙，与下方齿轮一眼可分（圆但与"厚度均匀的环"完全不同）
- 深色主题：仍是太阳（点 + 8 根细射线）
- 浮动条尺寸未变：`sizeHint() = (224, 82)`
- 新增回归：`test_moon_is_crescent_not_disc`（中心必须被挖空）、
  `test_moon_fills_the_canvas`（不能画成一弯细线）、`test_theme_icons_are_moon_and_sun`
- 对比图：`shots/v251-moon-before-after.png`（圆钮实景 / 72px 原图 / 24px 设备像素三行）

## 21. v2.6.0 数据目录可选择（2026-10-28）

用户提出：新电脑上要能直接用，同时希望能自己选数据放哪，"或者直接放到软件目录里"。

### 21.1 数据在哪，一直是隐性的

v2.5 之前数据固定在 `%APPDATA%\轻音播放器\`（data.json / covers / library /
lyrics_cache / bgs）。三条后果：

- 曲库跟着系统盘走，C 盘紧的用户没得选
- 换机器想带走曲库，得自己去 AppData 里翻
- exe 本身是"绿色"的（拷走就能跑），但数据不是 —— 拷走等于空库

### 21.2 四级优先级

```python
def resolve_root() -> str:
    if env := os.environ.get("QY_DATA_DIR"):   return env        # 1 测试/自检
    if os.path.isdir(exe_dir()/ "data"):       return 该目录      # 2 便携模式
    if pointer := read_pointer():              return pointer    # 3 用户选的位置
    return default_root()                                        # 4 %APPDATA%
```

排序有明确理由，不是随手定的：

| 级别 | 为什么在这个位置 |
|---|---|
| `QY_DATA_DIR` 环境变量 | 必须能压过一切，否则自检/测试无法隔离（见 21.4） |
| 便携模式（软件目录 `data/`） | 用户把整个文件夹拷到 U 盘就该带着数据走，不能被上次留下的指针拽回原机器 |
| 指针文件 | 用户在设置里选的位置，写在**默认目录**的 `location.txt` 里 |
| 默认 `%APPDATA%` | 兜底 |

**为什么用指针文件而不是把位置存进 data.json**：data.json 本身就要被搬走，
把"它在哪里"记在它自己身上，一搬家就找不着了。指针放在默认目录（不会搬），
读它才知道数据搬去了哪 — 这是唯一不会自相矛盾的位置。

指针指向的目录**不存在时按默认处理**（U 盘拔了 / 用户删了），不会把程序钉在一个
空目录上假装"曲库空了"。

### 21.3 便携模式只在打包后生效

```python
def portable_root():
    if not _frozen():          # 源码运行时一律 None
        return None
    ...
```

不是偷懒。开发态 `exe_dir()` 就是仓库根目录，如果有人在 `music-player/` 下手建一个
`data/`，那么所有依赖「改 `APPDATA` 做隔离」的测试（`test_e2e` / `test_e2e_video` /
`tools/shot.py`）都会静默写到那个目录，**进而污染用户真实曲库**。一个功能目录能
破坏整个测试隔离体系，代价太大。

设置页里"放到软件目录"按钮在源码态直接禁用并给出提示，避免用户点了之后数据被搬到
仓库里、程序却因为忽略便携模式而不认账。

### 21.4 `--smoke` 的隔离要跟着加一层

原来只需把 `APPDATA` 指向临时目录。现在多了两条绕过 APPDATA 的路（便携模式优先级更高、
指针文件指向别处），所以 smoke 必须**同时**设 `QY_DATA_DIR`：

```python
os.environ["APPDATA"] = _smoke_appdata
os.environ["QY_DATA_DIR"] = os.path.join(_smoke_appdata, "data")   # 压过便携/指针
```

回归 `test_env_beats_portable` 守的就是这条：软件目录里有 `data/` 也不能让自检写进去。

### 21.5 迁移：先复制、核对、再删源

搬的是整个曲库，可能是几个 GB，所以流程必须每一步都能回退：

1. 目标必须是**空目录或不存在** —— 不做覆盖/合并，就不会出现"两套数据搅在一起"
2. 先复制到目标，`plan()` 出的清单逐文件核对字节数
3. 全部对上才删源；`remove_source=False` 时干脆不删
4. 任何失败 / 用户取消 → 清掉目标里我们写过的顶层条目，**源一动不动**

几个实现上的坑：

- **统计和复制必须用同一份清单**。最初 `total` 用 `tree_bytes()`（会把 `.part`/`.bak`
  也算进去），复制时却跳过这些，结果核对永远对不上，迁移必然报"可能磁盘空间不足"。
  现在统一走 `plan()`。
- **顶层目录下的文件容易丢文件名**。写 `rel = name if inner == "." else ...` 时，
  `library/a.mp3` 会被算成 `library` 这个"文件"，迁移后 `library` 变成文件、打不开。
- 递归防护：目标目录不能在源里面（反之亦然），否则复制自己会无限膨胀。
- 可写性用"真写一个探针文件再删掉"判断，`os.access` 在只读网络盘/UAC 目录上会骗人。

UI 侧迁移跑在 `QThread` 里（`StorageMoveWorker`），逐文件回调进度；关闭对话框时
`requestInterruption()` + `wait()` —— QThread 带 parent，销毁时若还在跑 Qt 会直接崩。

### 21.6 生效方式：重启，不热切换

迁移完成后当前进程还握着旧路径（`LibraryStore` / `CoverProvider` / QMediaPlayer
都持有打开的文件和缓存），热切换要重建整个窗口状态，风险远大于收益。
所以迁移完成后弹一次"请重新启动"，并用 toast 提醒。

### 21.7 验收

- 默认/自定义/便携三种模式在设置页显示正确，路径与实际解析结果一致
- 迁移后 `data.json`、`library/`（含子目录）、`covers/` 全部就位，`.part` 残留不搬
- 取消 / 目标非空 / 目标嵌套 / 目标不可写 → 源数据完好，目标无残留
- 恢复默认会删掉指针文件，回到 `%APPDATA%`
- `test_storage` 27 项；设置页 E2E 1 项

## 22. v2.6.1 浮动工具条改为单行（2026-10-28）

### 22.1 需求

用户截图圈出左下浮动工具条的四个入口（主题圆钮 / 设置齿轮 / 导入音乐 / 数据目录），
要求「这四个并成一排」。此前是 3×2 网格：左列竖排两个圆钮，右侧两个按钮各占两行、
文字折成「导入\n音乐」。整条 224×82，占满 84 高的播放栏。

### 22.2 宽度算术（这是本版唯一真正的约束）

侧栏 248 − 左右各 12 = **224** 是整条的硬上限（右缘必须停在 x=236，不能跨进内容区；
也不能超过播放栏的左缩进，否则压封面）。四个控件塞进这一行：

```
[主题 38] 4 [设置 38] 4 [导入音乐 68] 4 [数据目录 68] = 224
```

- **68 是余量，不是随手定的**：224 − 38×2 − 4×3 = 132，两个文字按钮各 66 才对半分；
  取 68 是把圆钮间也压到 4 才换来的（38+38+68+68 = 212，三个间距 4 = 224）。
  换句话说现在这行已经铺满，**再加宽只能改布局或加宽侧栏**。
- **68 的依据是字号放大上限**：设置里字号可到 1.30 倍，`#FloatTextBtn` 的 12px → 16px，
  4 个中文字 = 64px；按钮可绘制宽 = 68 − 2×1 边框 = 66，刚好放得下。曾经试过 65 宽，
  在 1.30 倍下会裁掉 1px —— 肉眼几乎看不出，但属于「设置里调大字号就坏」的隐患，
  不值得为 3px 留着。
- **QSS 必须 `padding: 0px`**：基础 `QPushButton{padding:6px 10px}` 会再吃掉 20px，
  那样 4 个字在任何字号下都放不进 68。

回归 `test_single_row_layout_is_exactly_sidebar_width` 锁死「总宽 224、高 38、四控件不重叠、
最后一个控件顶到右缘」；`test_float_bar_fits_player_bar_indent` 守文字按钮宽度下限。

> **v2.8.0 补充：播放栏左缩进 312 → 248。** 312 是更早「竖排两列」浮动条
> （宽约 294，右缘 x≈310）时代留下的数，单行化后一直没人回头改 —— 等于在播放栏
> 左侧白扔 76px，还顺手把 `PlayerBar.minimumSizeHint().width()` 顶到 1064，
> 进而把窗口最小宽锁死。可见「改布局时没清理配套数字」的代价会延后很久才爆发。

### 22.3 高度与竖直定位

整条高度 = 圆钮直径 = 38（原来 82）。**高度一变，定位方式也得跟着变**：

- 旧版 82 高塞进 84 高的播放栏，只能贴底（底边留 4px，贴太近会被窗口圆角遮罩削掉一块）
- 现在 38 高，若继续贴底，整条会"沉"到播放栏下半截，与封面/按钮的重心错位
- 改为**在播放栏内垂直居中**：`y = H − PLAYER_BAR_HEIGHT + (PLAYER_BAR_HEIGHT − 条高) // 2`
  （800 高窗口 → y=739，条中心 758 = 播放栏中心）

为此把 `PlayerBar` 里写死的 `84` 提成模块常量 `PLAYER_BAR_HEIGHT`，窗口侧直接引用，
避免两处各写一个 84 而悄悄错位。

### 22.4 视觉验收

`tools/probe_float_bar.py --theme {light,columbina} --scale 5` → `shots/float_v261_*.png`：

- 四个控件同一水平线、间距均匀
- 「导入音乐」「数据目录」四字单行完整，无裁切/无省略号
- 圆钮仍是正圆（radius 19 = 38/2），文字按钮是半径 13 的圆角矩形（≤ 半高 19，不会退化成直角）

### 22.5 被改写的旧断言

单行布局推翻了四处历史断言，全部按新几何重写而不是删掉：

| 旧断言 | 问题 | 现在 |
|---|---|---|
| `test_float_bar_not_overlap_cover` 断言齿轮在主题钮**下方** | 不再有上下关系 | 断言四控件 `top()` 相同、整条高 = 圆钮高 |
| `test_float_bar_fits_player_bar_indent` 要求文字按钮宽 `> 70` | 实际 68 | 下限改 60，仍能挡住「被父控件裁成 0 宽」 |
| `test_left_column_has_two_circle_buttons`（左列竖排） | 概念过期 | 改名 `test_two_circle_buttons_same_size_and_row`，断言同行且主题在左 |
| e2e `test_sidebar_nav_aligned_with_float_bar` 断言两个圆钮都对齐侧栏导航 x | 设置齿轮已排到 x=42 | 只比最左的主题钮（唯一还在 x=12 的） |

## 23. v2.6.2 歌词：手动导入 / 联网进度与来源 / 匹配率（2026-10-29）

### 23.1 需求

用户三条：「歌词可以自己导入并识别」「联网匹配歌词可以显示进度和来源」「提高匹配率」。

### 23.2 手动导入 + 识别

- 单曲：右键「导入歌词文件…」（曲目行菜单与歌词区右键菜单都有入口），`_bind_lyrics_file()`
  先 `lyrics_from_text()` **识别**——不是有效 LRC（没有任何歌词行）就不绑定并提示
  「未识别到歌词行」；识别成功报告「识别到 N 行同步歌词 / 纯文本歌词 N 行」。
- 批量：歌词区右键「批量导入歌词…」选文件夹，递归扫 `*.lrc`，
  `app/lyrics_import.match_lrc_files()` 按文件名认到曲库。
- 匹配键（`normalize_key` 归一化：小写 + 只留字母数字）：音频文件名 → 标题 → 艺人 →
  「标题+艺人」「艺人+标题」。**歧义跳过**：一个键命中多首不同曲目就不绑，宁可少配不错配。

### 23.3 联网进度与来源

- 进度：`fetch_outcome(..., progress=cb)` 每发一个查询前回调 `(cur, total)`，
  `LyricsFetchWorker.progress = Signal(int,int)`；界面空状态显示「正在联网匹配歌词…（2/4）」。
- 来源：`_resolve_lyrics` 返回三元组 `(同步, 纯文本, 来源)`，`LyricsPanel.set_source()`
  在列表下方显示小字——本地·手动绑定 / 本地·同名 .lrc / 本地·内嵌 / LRCLIB（缓存）/ LRCLIB。
  `_lyrics_cache` 的值同步扩成三元组。

### 23.4 匹配率

- `lookup_plan` 末尾追加 `q=标题+主艺人` 全文兜底——结构化参数对艺人写法略不一致很敏感，
  全文搜常能捞回来。
- `_NOISE_WORDS` 增补：`国语 / 粤语 / 日语 / 闽南语 / mv / live at`。
- 真实联网抽查 5/5 命中（晴天 / 夜曲 / 海阔天空 / Count On Me / 稻香）。

## 24. v2.6.4 在线搜索歌词 + 歌词播放动效（2026-10-29）

### 24.1 在线搜索歌词

- 需求：本地/联网都匹配不到时，用户在软件内打开网页自己找。
- `build_web_search_url(标题, 艺人)` 拼 `https://lrclib.net/search?q=标题 艺人`
  （人类网页，非 `/api/` JSON）；`QDesktopServices.openUrl` 开系统默认浏览器。
- 入口：歌词区右键「在线搜索歌词…」。

### 24.2 歌词播放动效

- 单选 `Settings.lyrics_effect`：`none / zoom / typewriter / karaoke`，持久化。
- `ui/lyrics_panel.py` 改用 `QStyledItemDelegate` 自绘行；保留
  `QListWidgetItem.text()/foreground()` 兼容旧测试。
- 行内进度：`update_position` 算 `_line_progress`（0..1），最后一行固定 3000ms 行时长。
- 字号缩放：zoom +6px、其余 +3px；**必须像素优先**（`_bump_font` 判 `pixelSize()>0` 用
  `setPixelSize`，否则 `setPointSize(-1+Δ)` 会把当前行缩成 2pt 小截）。
- karaoke 未唱部分用半透明 `TEXT_DIM`（alpha 90）才有「已唱亮 / 未唱暗」分界。
- 平滑：PySide6 `QMediaPlayer` 无 `setNotifyInterval`，改主窗口 100ms `QTimer` 播放时轮询
  `position()`（暂停/停止即停）。

## 25. v2.6.5 纯文本 .txt 歌词导入识别（2026-10-29）

- 需求：浏览器下载的歌词常为 `.txt`，头部带「歌名 / 作词 / 作曲 / 编曲…」信息块。
- `strip_meta_lines()`：`_PLAIN_META_LABEL` 正则匹配「作词/作曲/编曲/填词/词曲/演唱/歌手/
  混音/制作/出品/发行/和声/吉他/贝斯/鼓/键盘/弦乐/钢琴/旁白…」+ 冒号行剔除；
  首行歌名仅当「下一非空行是职员表行」才删（避免误删第一句歌词）。
- `lyrics_from_text()` 在 `parse_plain()` 前统一过 `strip_meta_lines()`——手动绑定 /
  同名文件 / 内嵌 / 缓存 / 联网各路径一致生效。
- 导入入口收 `.txt`：手动对话框过滤 `*.lrc *.txt`；批量扫描同时收两种扩展名。
  `match_lrc_files()` 只取去扩展名 basename，天然兼容无需改逻辑。

## 26. v2.6.6 纯文本歌词联网对齐成带时间轴 LRC（2026-10-29）

### 26.1 需求与选型

- 需求：用户「歌词导入进去可以自动跟歌识别，可以滚动」。纯文本歌词（无时间戳）
  本无法逐行跟歌，必须先把每行配到音频时间轴。
- 澄清后选定「联网自动对齐（自备 Key）」，触发方式「导入后询问 + 右键手动」。
- 选型：**LyricTimestamps API**——支持 multipart 直接上传本地音频（QuickLRC 只收
  公开 URL，本地文件给不了）；免费 15 分钟/月、最长 12 分钟/首、直传 30MB。

### 26.2 实现

- `app/lyrics_align.py`：
  - `verify_key`：GET /v1/usage，`plan != anonymous` 才算有效；
  - `align_lyrics(audio, lyrics, key, fetch=, progress=)`：本地预检 → 校验 key →
    POST multipart 创建任务 → 轮询状态 → GET /exports/lrc 下载；错误码统一分类；
  - `describe_error(code)`：错误码 → 中文提示；
  - `LyricsAlignWorker(QThread)`：done / soft_fail / failed / progress 信号。
- `Settings.lyrics_align_api_key`（v2.6.6）：存 data.json，**不进日志**。
- 设置「歌词与统计」页：Key 输入框（editingFinished 才保存，避免每键写盘）。
- 触发：导入纯文本后 `_maybe_offer_align` 弹「是否联网对齐」；歌词区右键
  「联网对齐歌词」。对齐成功：写 `lyrics_cache/<id>.lrc` + 解除纯文本手动绑定
  （让缓存里的对齐结果优先生效）+ 立即刷新滚动。

### 26.3 关键坑（照 docs 实现不猜）

- **错误 key 在读端点被当匿名游客**：只回 60 秒预览。所以创建任务前必须先
  `verify_key`，否则会拿到「只有前 60 秒」的残缺结果。
- **必须 multipart form-data**：JSON body 会被静默接受然后 `400 missing_audio`。
- `/exports/lrc` 的响应就是文件本身，没有签名 URL。
- `done` 可能带 `soft_fail`（对齐完成但服务端不信任），此时 LRC 仍可用但提示核对。

## 27. v2.6.7 .txt 转 .lrc 文件：对齐产物写成同名 .lrc（2026-10-29）

- 需求：用户「添加一个可以把 .txt 文件转 .lrc 文件的功能，歌曲能识别歌词」。
- 澄清：时间轴来源复用联网对齐（LyricTimestamps），产物位置选「歌曲同目录同名 .lrc」。
- 增量：`_apply_aligned_lrc` 从「写缓存」改为「写同名 .lrc」——`sidecar_lrc_path()` 算
  路径、`write_sidecar_lrc()` 原子写（`.part` + `os.replace`）。
- 为什么同名 .lrc 优于缓存：它是 `_resolve_lyrics` 第 2 级来源（优先级高于第 4 级缓存），
  磁盘可见、可拷贝迁移、可手动编辑；歌曲移走后缓存随之失效，同名 .lrc 跟着歌曲走。
- 边界：写同名 .lrc 前若已存在则弹覆盖确认；写失败（目录只读）提示「未生成 .lrc」。
  对齐后仍需解除 `track.lrc_path`（纯文本绑定，第 1 级）否则纯文本会盖过同名 .lrc。

## 28. v2.6.8 多源联网歌词：LRCLIB + 网易云 + QQ音乐（2026-10-29）

- 需求：用户「添加其他音乐平台用于识别歌词」，且确认「离线显示」要成立。
- 澄清：目标平台选网易云 + QQ音乐；接入方式「免 key 直连」；降级策略「多源并行取最优」。
- 离线显示本身**无需新做**：命中即写 `lyrics_cache/<id>.lrc`（或同名 .lrc），断网照常读。
  多源只是把「联网这一级」的来源变多，缓存落盘链路不变。
- 接口事实（2026 实测，均非官方，可能失效 → 做成降级链）：
  - 网易云：搜索 `music.163.com/api/search/get?s={kw}&type=1&limit=8`，歌词
    `music.163.com/api/song/lyric?id={id}&lv=1&kv=1&tv=-1`，需 `Referer: music.163.com/`。
  - QQ：搜索 `c.y.qq.com/soso/fcgi-bin/client_search_cp?w={kw}&format=json&n=8&p=1`，歌词
    `c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={mid}&format=json&nobase64=1`，
    需 `Referer: y.qq.com/`（缺了返回 -1310），`nobase64=1` 直接回明文 LRC。
- 架构（新增 `app/lyrics_multi.py`，`lyrics_online.py` 只增一个 `fetch_best_hit` 纯增量）：
  - 每个源「搜索 → 遍历前 3 个候选拉歌词 → 转 `LyricHit` → 复用 `pick_best` 门槛过滤」，
    返回 `(hit, aborted)`；`fetch` 可注入（测试不联网）。
  - `fetch_outcome_multi` 用 `ThreadPoolExecutor` 并行跑三源，收集 `(来源, hit)` 后统一
    `pick_best` 跨源打分取最优；`aborted` 语义 = 「至少一源限流/超时且全都没命中」，
    此时不落负缓存（与单源 `fetch_outcome` 一致）。
  - `MultiSourceWorker(QThread)` 的 `found` 比旧 `LyricsFetchWorker` 多一个来源名
    （"LRCLIB"/"网易云"/"QQ音乐"），界面据此标注；旧 worker 保留（其测试仍覆盖）。
- 为什么「并行取最优」而非「LRCLIB 优先」：用户明确要最优；同分时 `pick_best` 保留
  首个（源列表 LRCLIB 在最前），LRCLIB 在并列时仍占先。
- 已知坑（沿用既有防错，不重复踩）：网易云伴奏版常排第一且无歌词 → 遍历候选；配错词
  比没词更糟 → 复用 `pick_best` 的「标题对上或时长差 ≤2s」门槛；`usable_text` 滤空歌词。
- 边界：繁体歌名不转简体（避免引入 zhconv/opencc 依赖），记为已知限制。

## 29. v2.6.9 本地歌词对齐：离线「纯文本 → 带时间轴 LRC」（2026-10-29）

- 需求：用户「软件内制作一个类似 LyricTimestamps 的功能」——把纯文本歌词配到音频
  时间轴，去掉对联网 LyricTimestamps 的 Key + 上传依赖。
- 澄清（两轮）：技术路线选「轻量离线对齐」（静音检测 + 行均分，非 AI）；与联网对齐
  的关系选「本地优先、联网兜底」（联网 LyricTimestamps 保留为手动可选）。
- 选型：解码用 **miniaudio**（纯 C、无 numpy、打包 +1~2MB），替代 numpy+soundfile
  （+30MB）。实测 `decode_file()` 对**中文路径**解码失败（C 层 ANSI），改为
  `open().read()` + `decode(bytes)` 绕开；`samples` 是 `array.array('f')`，纯 Python
  分帧算 RMS 对 3 分钟歌 ~0.2s，不必引入 numpy。
- 算法（`app/lyrics_local_align.py`，纯信号处理）：
  1. `decode_mono`：解码到 mono 16kHz float32；
  2. `rms_envelope`：20ms 帧 / 10ms 步进算 RMS；
  3. `detect_speech`：动态阈值（非零 RMS 中位数 × 0.15）识别有声段，短段当噪声、
     相邻近段合并 → 前奏/间奏/尾奏的静音被识别；
  4. `assign_timestamps`：歌词行均匀铺在「有声段」上（取行中点映射回实际时间），
     跳过前奏/间奏/尾奏；无有声段时退化为全时长均分；
  5. `align_local` → `[mm:ss.xx]` 格式 LRC（与 `parse_lrc` 兼容）。
- 精度定位：**近似对齐**（让歌词大致跟着唱），非逐字卡点。想要精准仍可走联网对齐。
- 集成：歌词区右键「转成 .lrc 文件（本地对齐）」默认；「联网对齐」保留为兜底；
  导入纯文本后的询问改默认走本地。本地覆盖 mp3/flac/wav/ogg，m4a/aac/wma/opus 走
  「decode_failed → 提示用联网对齐」的降级。
- 关键坑：miniaudio 中文路径 -7；`array.array` 切片返回新 array、纯 Python 遍历足够快；
  LRC 时间戳必须 `[mm:ss.xx]` 百分秒（`parse_lrc` 只认 mm:ss 两位百分秒/三位毫秒）。


## 30. v2.6.9 打包事故复盘：cffi 后端漏收 + smoke 挂死（2026-10-29）

版本号升到 2.6.9 后打包，`dist/QingYinPlayer.exe` 能产出，但 `--smoke` **永久挂住**
（19 分钟无返回）。逐层排查后的两个独立问题：

1. **`_cffi_backend` 没被收进包**（真正的 bug）
   - 现象：`--smoke` 无输出、无返回码；把子进程输出重定向到文件后才看到
     `ModuleNotFoundError: No module named '_cffi_backend'`（`miniaudio.py` → `_miniaudio.pyd`）。
   - 原因：`_miniaudio.pyd` 在 **C 层运行时** `import _cffi_backend`，PyInstaller 的
     PE 依赖扫描只看静态导入表，看不到这类运行时导入，于是 cffi 的编译后端被漏收。
   - 修法：`build.py` 加 `--hidden-import _cffi_backend`；`requirements.txt` 显式声明
     `cffi`（它此前只是 miniaudio 的传递依赖）。
   - 结构性加固：`app/lyrics_local_align.py` 改成**延迟导入** miniaudio（`_decoder()`），
     并把解码器不可用映射成新的 `no_decoder` 错误码。理由：本地对齐是可选能力，
     它的依赖缺失绝不该让主程序连窗口都起不来 —— 最坏只是「本地对齐不可用，请走联网」。
2. **`smoke_test` 用了会挂死的管道**（放大器，不是根因）
   - onefile 是父子进程，子进程继承 stdout 管道句柄；`subprocess.run(capture_output=True)`
     在超时杀掉父进程后仍等不到 EOF。叠加 windowed 产物异常时会弹**错误对话框**等人点
     确定，返回码永远拿不到 → 构建无限等待。
   - 修法：输出重定向到临时文件 + `Popen` + 超时 `taskkill /T /F` 杀整棵树 + 失败时把
     已写日志打出来（`_real_platform_check` 早就这么写了，这次把 `smoke_test` 补齐）。

验证（两变体都过）：
- `dist/QingYinPlayer.exe --smoke <夹具>` → `smoke decoder: miniaudio OK` /
  `smoke media: status=BufferedMedia duration=2037ms` / `smoke ok (含音频解码)`；
- `dist/QingYinPlayer-Portable/QingYinPlayer-Portable.exe --smoke` → `smoke ok`；
- 真实平台检查两变体各持续运行 8s 未崩溃；产物 67.4 MB（单文件）/ 5.1 MB + `_internal`。

附带修正：
- `_read_logs` 不再假设日志是 UTF-8 —— windowed 产物按 cp936 写且不认
  `PYTHONIOENCODING`，改 utf-8 → gbk 回退，否则失败诊断整片变成替换字符（`tests/test_build.py`）；
- `build.py` 的 `generate_icon()` 改为**仅图标缺失时**才生成：offscreen 下字体库为空，
  无条件生成会把仓库里的正式图标降级覆盖（本轮就靠手工注释+备份绕，属于易踩的坑）。

## 31. v2.6.10 双语歌词：一句 = 原文 + 译文（2026-10-29）

- 需求：用户给了一份浏览器导出的双语 `.txt`（英文原文行 + 中文译文行交替），反馈
  「这种双语歌词跟歌曲匹配不上，双语歌词的歌词效果应该一起实现」。
- 现象（✅ 实测复现）：文件解析出 **74 行**，但实际只有 **37 句**。本地对齐把 74 行
  各铺一个时间槽，56 秒有声段内每行只占 0.76 秒 → ①整首时间轴被压缩一半、提前唱完；
  ②每句译文比原文晚 0.76 秒；③放大/打字机/颜色覆盖动效对译文单独再走一遍。
  联网对齐同理：74 行双语文本一起发给服务端，服务端只能按 74 行返时间轴。
- 澄清（三选）：排版选「原文大字 + 译文小字」；动效选「两行都逐字推进」（进度按两行
  字符总数算）；识别选「整份文件严格交替才配对」。
- 方案取舍：
  - **方案 A（采用）**：`LyricLine` 增加 `translation` 字段，「句」升为一等公民。
    对齐按句铺、渲染一条目两行、动效按句、写回 LRC 用「同时间戳两行」。
    改动 4 个文件，但句的概念在对齐/高亮/滚动/动效/写回五处天然一致。
  - 方案 B（否决）：不改模型，渲染层按「同时间戳」临时分组。改动小，但句的概念散落
    在五处各判一遍，逐字进度与滚动定位最容易漏，将来加「隐藏译文」更麻烦。
- 实现：
  1. `app/lyrics.py`：`has_cjk` / `is_bilingual_alternating` / `pair_bilingual` /
     `merge_translations` / `format_lrc_stamp` / `format_lrc`；`lyrics_from_text`
     的同步分支自动合并同时间戳两行。
  2. `app/lyrics_local_align.py`：先 `pair_bilingual` 取原文行铺时间轴，再把译文以
     同一时间戳写到原文行之后。
  3. `app/lyrics_align.py`（联网）：只上传原文行，拿回 LRC 后按行序回填译文；
     **行数对不上就原样返回**（硬配会把译文挂到错的句子，配错词比没词更糟）。
  4. `ui/lyrics_panel.py`：delegate 一层画两行（译文小 3px + 降透明度），item 高度
     按层数自适应；`_typed_split` 把「两行总字符进度」抽成可测函数；`set_plain`
     也按句配对（未对齐的双语 txt 不再显示成流水账）。
- 关键坑：
  - **误配对风险**：纯中文歌里夹一句英文副歌时，只看相邻两行会把它和下一句中文
    错误配对。所以双语判定看**整份文件**：两种语种各占 ≥25% 且相邻异类比例 ≥85%。
  - 副歌同一句重复两次（同时间戳）不能被合并成「原文+译文」，`merge_translations`
    要求两行文本不同。
  - 深色主题下译文压到 alpha 150 会糊进夜空底色，实测提到 165 才清晰可读。

## 30 节遗留（v2.6.9 打包）与本节的共同教训

「行数」是歌词链路里最容易被忽略的隐含契约：`assign_timestamps`、`parse_lrc`、
`lyric_index_at`、逐字进度都按「一行 = 一句」写。任何改变行数形态的东西（译文、
注释行、空行）都会同时打歪时间轴、滚动和动效 —— 所以要么在入口把「句」归一化
（本节做法），要么在五处各判一遍（方案 B，已否决）。

## 32. v2.6.11 修歌词自动滚动「一直往上滚」（2026-10-29）

- 反馈：用户「歌词播放时一直往上滚动」。
- 复现（✅ 实测，`tools/probe_lyrics_scroll.py`）：逐句推进播放位置，记录滚动条实际值
  与目标值。修复前每句只前进 8px 左右（一行 36px），而 `rect.top()` 从 188 一路涨到
  360 —— 当前句越来越沉到视口底部。
- 根因（一句话）：**把视口坐标当内容坐标用了**。
  - `QListWidget.visualItemRect(item)` 返回的是**视口坐标**（该项相对当前可视区左上角
    的位置，随滚动变化）；`bar.value()` 才是**内容坐标**（像素偏移）。
  - 原代码 `target = rect.top() + rect.height()//2 - viewport.height()//2` 直接拿视口
    坐标当滚动目标，漏掉了「已经滚过多少」。于是目标值恒偏小 `bar.value()` 那么多：
    每句只挪一点点，当前句永远滚不到中间，视觉上就是「一直在往上滚但始终滚不到位」。
  - 为什么现在才发现：单语歌词行高 36px、视口能显示 8 行，滞后不明显；双语条目
    变成两层（58px），视口只显示 5 行，偏差立刻刺眼。属**老 bug 被新功能放大**。
- 修法：换算成内容坐标再算目标，抽成可测函数 `_scroll_target(item)`：
  ```python
  target = bar.value() + rect.top() + rect.height() // 2 - viewport.height() // 2
  ```
  动画进行中重复调用也安全：`bar.value()` 与 `rect.top()` 的中间值相加仍等于该项内容
  坐标，不会因半路重算而漂移（这点专门验证过）。
- 验证（`tools/probe_lyrics_scroll.py`）：
  - 单语：目标值逐句 28→64→100→136→172→208（每句 = 一行高），`rect.top()` 恒 188；
  - 双语：逐句 +58（一行高），`rect.top()` 恒 199，第 3 句起居中偏差 0；
  - 修复前同样的探针：`目标` 每句比 `应有` 少整整一个 `bar.value()`（第 10 句 108 vs 208）。
- 回归：`TestLyricsAutoscroll` 2 项 —— 「滚到目标后必须真的居中(≤2px)」与
  「目标必须等于 value + 视口偏移」(后者直接钉死老 bug)。原先还写了一条「动画结束后
  居中偏差 ≤6px」的用例，在 offscreen 下因布局像素对齐有 13px 抖动而删掉：**动画终值
  精度不该进回归**，语义正确性用 setValue 直接验。

## 33. v2.6.12 前奏长的歌歌词对不上：加权分配 + 偏移微调 + 把两种对齐说清楚（2026-10-29）

- 反馈：用户「歌曲前奏长歌词匹配不对」，自查确认他描述的那首 `.lrc` 是**本地对齐**
  产物（他自己以为是联网对齐）。
- **定位过程（先量后改）**：
  1. `tools/probe_align_intro.py` 量真实曲库 3 首：`detect_speech` 判出的「有声」占
     全曲 **90~93%** —— 静音检测在真实歌曲上形同失效。
  2. 决定性验证：拿用户那份 `.lrc` 的原文行喂给本地对齐重跑，**37/37 逐句时间戳
     完全一致** → 确认产物来自本地对齐，不是联网对齐（他的 Key 也从未配置过）。
  3. 时间戳间隔恒定 3.1s（37 句铺满「有声」114.7s）——机器等分特征，不是真人演唱。
- **误差量化（关键）**：`tools/eval_align.py` 用联网歌词当**真值**（LRCLIB 命中
  《何者》30 句），把真值的纯文本行喂给本地对齐，再逐句比对时间差：

  | 方案 | 首句误差 | 中位绝对 | 最大 |
  |---|---|---|---|
  | 改动前（有声段均匀铺） | −6.78s | 7.24s | 19.75s |
  | 全时长均匀铺 | −10.03s | 8.57s | 23.51s |
  | 全时长按字数加权 | −10.03s | 6.79s | 17.78s |
  | 完美起唱点 + 均匀 | 0.00s | 7.51s | 16.15s |
  | 完美起唱点 + 按字数加权 | 0.00s | 5.84s | 10.62s |

- **被否决的三条路（都实测过，别再试）**：
  - 调静音合并阈值 350→35ms：段数只从 13 涨到 18，够不上 30 句（这首歌连续演唱）；
  - 人声频段带通 300–3400Hz（一阶 IIR 高通+低通）：前奏/人声段能量比 1.12 vs 全频段
    1.10 → **无增益**；
  - 相对能量分位门限（0.3~0.8）：中位误差反而升到 10~12s，0.80 时首句跳到 27.8s。
- **为什么天花板就在这儿**：真值间隔是 `11.9, 11.4, 3.0, 2.9, 2.8…` 秒，而前两句只有
  10/12 字（和后面 6 字句差不多）——**字数完全不解释时长**，拖音和句内间奏在纯文本里
  没有任何信息。纯信号处理 + 行数，能到 6 秒级就是极限；要逐句卡准必须做音频-文本
  强制对齐（联网 LyricTimestamps）。
- 方案（用户确认）：**按字数加权 + 整体偏移微调 + UI 区分两种对齐**。
  1. `app/lyrics_local_align.py`：新增 `line_weight()`（可见字符数，至少 1），
     `assign_timestamps` 由「均匀」改「权重中点」分配。等长句退化为原均匀铺
     （`(acc + w/2) / total_w` 在权重全等时等于 `(i+0.5)/n`），旧断言零改动通过。
     实测：《何者》中位 7.24 → **6.04s**、最大 19.75 → **13.70s**。
  2. `app/lyrics.py`：新增 `shift_lrc(lrc, delta_ms) -> (新文本, 实际增量)`。只动**行首
     连续时间标签**（正文方括号、`[ar:]` 元数据不碰），一行多标签全部平移，双语同时间戳
     两行一起动；**钳位**：实际增量取 `max(delta, -最早时间戳)`，否则第一句被压到 0 秒、
     后面几句糊在同一时刻。输出统一百分秒（`format_lrc_stamp` 的既定格式）。
  3. `ui/lyrics_panel.py`：菜单拆出 `_build_menu()`（可单测）；两个对齐项改名
     「本地近似·免 Key」/「联网精确·需 Key」；新增「整体提前/延后 0.5 秒」（未同步时置灰）。
  4. `ui/main_window.py`：`_shift_current_lyrics()` 平移 → 写回 sidecar `.lrc` → 重载歌词
     → 按当前播放位置重新高亮；本地对齐完成提示改为明确「近似、可能差几秒，可微调」；
     未配 Key 时提示「联网精确对齐需要 API Key」。
- 新增验收工具：`tools/probe_align_intro.py`（每秒能量条形图 + 段结构）、
  `tools/eval_align.py`（联网歌词当真值的逐句误差评估，真值缓存到 `shots/eval_cache/`）。

## 34. v2.8.0 窗口尺寸自适应屏幕（2026-10-30）

### 34.1 需求：一句话，但根因有三层

用户原话：「屏幕这个占比太大了」。没有数值，只能自己量。

先把现象量化（用户机器 1920×1080 @125%，`availableGeometry` 实测 **1536×864**）：

| | 旧值 | 占可用区 | 问题 |
|---|---|---|---|
| 初始尺寸 | 1280×800 | 83% 宽 / **93% 高** | 一开就像「最大化」，桌面只剩一条边 |
| 最小尺寸 | 1100×720 | 72% 宽 / **83% 高** | 用户想拉小，**拉不动** |

三层根因，一层比一层深：

1. **写死，完全不看屏幕**：`self.resize(1280, 800)`。同一份二进制在 4K 屏上
   显得小、在 1366×768 上直接溢出 —— 尺寸本应由「在什么屏上跑」决定。
2. **最小尺寸没有依据**：`setMinimumSize(1100, 720)`。而窗口
   `minimumSizeHint()` 实测只有 **1042×564** —— 高的 720 是纯拍脑袋，
   多出来的 156px 换来的是「拉不小」。
3. **最隐蔽的一层**：宽度 1100 之所以降不下来，是因为
   `PlayerBar.minimumSizeHint().width()` = **1064**。而它的左缩进是 **312**，
   浮动条右缘却在 **236** —— 中间 **76px 是纯空白**，是 v2.6.1 把浮动条
   从竖排两列（宽约 294）改成单行之后**忘了回收的旧数字**。

> 教训：布局里「为某控件预留的空间」必须跟那个控件绑在一起算，否则控件瘦身了，
> 预留值还留在原地，两年后会以「窗口最小宽降不下来」的形式重新出现。

### 34.2 方案对比

| 方案 | 做法 | 取舍 |
|---|---|---|
| A 只改初始尺寸 | 1280×800 → 1200×760 之类 | ❌ 治不了「拉不小」，用户照样卡在 1100×720 |
| **B 比例自适应 + 最小尺寸取实测**（采用） | 初始 = 可用区 × 系数并夹上下限；最小 = layout hint + 余量 | ✅ 一改解决前两层；任何屏幕都合适 |
| C 记住上次窗口尺寸 | `Settings` 加 `window_w/h`，关窗写、启动读 | ⏸ 本轮不做：改数据 schema + `closeEvent`（那里已有 worker 收尾逻辑，动它风险高），而 B 已经能解决当下的抱怨 |

B 内部还有一个取舍：**系数取多少**。没有客观答案，只能定原则——
「不占满屏、但内容区不至于挤成一条缝」：

- 宽 0.68 → 1536 上 1044（内容区 796，三列弹性列仍能显示标题）
- 高 0.74 → 864 上 639（内容区 515 ≈ 列头 + 9 行）
- 上限 1440×900：4K 屏也不许开成一堵墙
- 下限直接取布局实测值，不再人为抬高

### 34.3 改完才发现的问题：播放栏没有余量

尺寸一缩就暴露了隐藏假设 —— **播放栏在 1044 宽时横向已经没有任何余量**，
被压缩的全是那条弹性最大的列，也就是标题/艺人。实测：

| 窗口宽 | 标题列（固定 200 进度条） | 标题列（弹性 120~200） |
|---|---|---|
| 1010 | **10px**（只剩一个字） | **76px** |
| 1044 | **44px**（「周杰伦…」） | **84px** |
| 1105 | 99px | 99px |
| 1280 | 143px | 143px |

改法是让**进度条先让位**：`setFixedWidth(200)` → `最小 120 / 最大 200 / Expanding`。
理由很直白——「进度条短一截」是审美问题，「歌名只显示一个字」是功能问题。
而且 ≥1105 宽时进度条仍是满宽 200，大尺寸下观感与改动前完全一致。

> 这一条如果没查，交付出去就是「窗口变小了，但歌名变成一个点」——
> 用户的下一句投诉已经在路上了。

### 34.4 实现

`ui/player_bar.py` 两处：

1. 左缩进 312 → **248**。248 = 浮动条右缘 236 + 12 呼吸，同时**正好等于侧栏宽**
   —— 封面左缘与列表左边界落在同一条竖线上。
2. 进度条 200 固定 → 120~200 弹性（见 34.3）。

`ui/main_window.py`：尺寸收成一组模块常量 + 一个纯函数。

```python
WINDOW_MIN_WIDTH = 1010      # 不是布局下限（PlayerBar 实测 898），而是「标题还能读」的下限
WINDOW_MIN_HEIGHT = 580      # 窗口 minimumSizeHint 实测 566 + 14
WINDOW_MAX_WIDTH = 1440
WINDOW_MAX_HEIGHT = 900
WINDOW_W_RATIO = 0.68
WINDOW_H_RATIO = 0.74


def initial_window_size(available: QSize) -> QSize:
    w = min(int(available.width() * WINDOW_W_RATIO), WINDOW_MAX_WIDTH)
    h = min(int(available.height() * WINDOW_H_RATIO), WINDOW_MAX_HEIGHT)
    w = max(min(w, available.width()), WINDOW_MIN_WIDTH)   # 夹可用区 → 再托底
    h = max(min(h, available.height()), WINDOW_MIN_HEIGHT)
    return QSize(w, h)
```

**夹取顺序不能换**：先上限（大屏不许溢出）→ 再可用区（小屏不许超出屏幕）
→ **最后托底到最小尺寸**。托底放最后，才能保证任意输入下结果都 ≥ 最小尺寸；
放前面的话 1024×600 的小屏会先被可用区夹到 696、再被最小尺寸顶回去，白算一遍。

`_apply_initial_geometry()` 负责取 `primaryScreen().availableGeometry()`、
调纯函数、**并在可用区内居中**。无边框窗口系统不会替你居中 —— 之前尺寸写死
1280×800 时靠「差不多能看」蒙混过去，尺寸一变小位置不对就很显眼。

> `WINDOW_MIN_WIDTH` 故意比 `PlayerBar.minimumSizeHint().width()`(898) 大 112px：
> 前者保「不崩」，后者保「能读」。两个数字含义不同，不要合并。

### 34.4 验收

`tools/probe_window_size.py`（真实平台，不是 offscreen —— offscreen 字体库是空的，
`minimumSizeHint` 会给出完全不同的数字）：

```
屏幕：可用区 1536×864（DPR 1.25）
计划初始尺寸 1044×639  = 可用区 68% 宽 / 74% 高
字号 ×1.00  实际窗口 1044×639 | 最小提示 898×566 | setMinimum 1010×580 | 播放栏最小宽 898
字号 ×1.30  实际窗口 1044×639 | 最小提示 898×576 | setMinimum 1010×580 | 播放栏最小宽 898
尺寸约束全部成立
```

四条断言：播放栏最小宽 ≤ 窗口最小宽、`setMinimum` ≥ `minimumSizeHint`、
浮动条右缘 ≤ 播放栏左缩进、初始尺寸 ≥ 最小尺寸。

单测（`tests/test_widgets.py`）：

- `TestWindowSize` 5 条：常见屏比例、小屏托底、不溢出屏幕、4K 撞上限、中间尺寸走比例
- `test_title_keeps_readable_width_at_min_window`：最小窗口下标题列 ≥ 60px
  （34.3 那个坑的守门员 —— 光测「窗口能缩到 1010」是不够的，还得测「缩到 1010 之后还能看」）

截图（`tools/shot.py` 新增 `--size` 参数，留空 = 用应用自身初始尺寸，
否则截的永远是工具里写死的那个尺寸、验不到真东西）：`shots/*-v280*.png`。

### 34.5 连带影响

- **断言去硬编码**：`test_widgets.py` / `test_e2e.py` 里 6 处写死的 `1100` 全部改成
  引用 `WINDOW_MIN_WIDTH`。窗口尺寸与播放栏最小宽必须**同源**，否则就是 v2.7.6
  「界面版本号自己写死」的翻版。
- **offscreen 下窗口变小**：测试环境的虚拟屏只有 800×800，`initial_window_size`
  会算出 1010×592（而不是原来的 1280×800）。E2E 全套已回归通过 —— 说明现有断言
  都不依赖窗口绝对尺寸（对齐类断言比的是相对位置）。
- **多显示器**：只按主屏算初始尺寸。窗口开在副屏时用户自己拖过去即可；
  没做记忆功能，见 34.2 方案 C。

## 35. v2.8.1 正在播放页分栏：封面让位给歌词（2026-10-30）

### 35.1 需求：v2.8.0 的直接后遗症

用户截图 + 一句话：「左边显示太大，右边歌词显示不全」。

这是 v2.8.0 把窗口调到 1044×639 之后立刻暴露的隐藏假设 —— 之前窗口固定 1280，
正在播放页的分栏**从来没被测过窄窗**。窗口 1044 时实测（真实平台）：

| 元素 | 实测 | 说明 |
|---|---|---|
| 内容区 | 796×507 | 1044 − 侧栏 248，高 − 标题栏 − 播放栏 |
| 封面 | **280×280 写死** | 占内容区高度的 **55%** |
| 左列宽 | **444** | 封面 280 反而更窄 —— 撑开它的是标题 |
| 歌词面板 | **268** | viewport 258 |
| 单行歌词需要 | 原文 242px + 译文 | 实际更长 |

两个独立成因，缺一不可：

1. **封面写死 280×280**：窗口一矮，它就独占半屏高度，「左边太大」。
2. **左列宽度由文字的 minimumSizeHint 决定**：标题是普通 `QLabel`，
   「唯有追赶风的方向 (Only By Chasing the Wind)」的 `minimumSizeHint()` = **444px**，
   于是左列 444 > 封面 280 —— **画面上的大封面其实还不是元凶，文字才是**。
   左列吃掉 444，歌词只剩 268。

3. 而歌词 `_draw_line` 是**居中 `drawText`，不折行也不省略** —— 一行 300px 的
   歌词塞进 258px 的视口，超出的部分被硬裁，看起来就是「少半句」。

### 35.2 方案

| 方案 | 做法 | 取舍 |
|---|---|---|
| A 把封面改小到 220 | 只改一个数字 | ❌ 治不了「歌词只剩 268」——左列仍被标题撑到 444 |
| **B 左列定宽 = 封面边长 + 封面自适应**（采用） | 左列装进定宽容器；标题/艺人/专辑开 `wordWrap` | ✅ 一次解决两个成因，且歌词拿到「剩余全部宽度」 |
| C 歌词改折行 | 按面板宽 `QTextLayout` 折行 | ❌ 逐字动效（typewriter / karaoke）按字符分段绘制，折行后要重写整套坐标计算；风险远大于收益。改成「超宽省略」兜底 |

B 的关键不是「封面变小」，而是**把左列的宽度从「文字说了算」反转成「封面说了算」**：

```python
_COVER_MAX = 220      # 上限：别让封面重新变成主角
_COVER_MIN = 140      # 下限：窗口再小也不缩成缩略图
_COVER_W_RATIO = 0.26
_COVER_H_RATIO = 0.44   # 矮窗口下封面先让位


def cover_side_for(view_w: int, view_h: int) -> int:
    side = min(_COVER_MAX, int(view_w * _COVER_W_RATIO), int(view_h * _COVER_H_RATIO))
    return max(_COVER_MIN, side)
```

```python
# 左列：定宽容器，宽度 = 封面边长；标签在框内折行
root.addWidget(self.left_box)
self.lyrics = LyricsPanel()
root.addWidget(self.lyrics, 1)      # 吃掉左列之外的全部宽度
```

`resizeEvent` 里调 `_fit_cover()` 重算，**尺寸没变直接 return**——
`setFixedWidth` 会触发一次 LayoutRequest，不设这道闸 resize → 布局 → resize 会抖。

标题保留 `wordWrap` 而不是改 `ElidedLabel`：这个用户的库里同一首歌有
「(英文版)」「(Only By Chasing the Wind)」多个版本，**括号里那截正是区分版本的唯一信息**，
省略掉等于看不出来在放哪一版。宁可折成三行。

歌词侧只加一层兜底：`_draw_line` 里先 `elidedText(ElideRight)` 再画，
保证「宽到放不下」时是「…」而不是硬切。

### 35.3 效果（实测）

| | 修复前 | 修复后 |
|---|---|---|
| 封面 | 280 | **206**（1044 窗口）/ 220（1280 窗口） |
| 左列 | 444 | **206 / 220**（= 封面边长） |
| 歌词面板 | 268 | **506 / 728** |

歌词可用宽从 268 → 506，用户截图里那几句（最长原文 255px、最长译文 182px）
全部落在 494px 可用宽内，不再裁剪。

### 35.4 验收

新增探针 `tools/probe_now_playing.py`：喂「长标题 + 长双语歌词」，多个窗口尺寸各截一张，
并打印封面/左列/歌词宽度与「最长行是否会省略」。

```bash
env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_now_playing.py \
    --out shots/np_v281 --size 1044x639 1280x800
# 1044x639: 封面 206 / 左列 206 / 歌词 506（视口 506）/ 最长原文 255px → 完整
# 1280x800: 封面 220 / 左列 220 / 歌词 728（视口 728）/ 最长原文 255px → 完整
```

单测（`tests/test_widgets.py`）：

- `TestNowPlayingLayout` 4 条：封面有上限且正方、**左列宽度 == 封面边长**、
  796 宽视图里歌词 ≥ 480px、**长标题不许把歌词挤窄**
- `TestCoverSide` 5 条（纯函数）：常规视图走比例、大视图撞上限、小视图托底、
  矮窗口让位、随视图尺寸单调不减

> 为什么用 `shot.py` 截不出这个问题：仓库夹具曲目的歌词都很短，怎么排都不会超宽。
> 必须专门喂长句 —— **「验收数据不代表用户数据」是这一类视觉 bug 的共同成因**。



## 36. v2.8.2 联网歌词：503 不再判死 + 专辑参与身份匹配（2026-10-30）

### 36.1 问题

用户报「https://lrclib.net/tracks/34711120 有歌词但匹配不到」。本地曲目：

- `title="痴人说梦"`、`artist="HOYO-MiX"`、`album="崩坏星穹铁道-痴人说梦 Ravings"`、`duration_ms=115449`
- LRCLIB id=34711120 的 `trackName="Ravings"`（**英文**）、`artistName="HOYO-MiX"`、
  `albumName="崩坏星穹铁道-痴人说梦 Ravings"`、`duration=115.0`、有 `syncedLyrics`

两层根因（都实测复现）：

1. **503 被当成限流判死（主因）**。LRCLIB `/api/get`（应用发的第一个查询）间歇返回
   **503 ServerOverloaded**（curl 连测 try1=503、try2/3=404）。旧代码把 503 与 429 混为
   `RateLimited`，第一个 `get` 一撞 503 就 `return aborted`，整轮中止——根本走不到那个
   真正能命中的 `q=痴人说梦` keyword 查询（该查询稳定返回 id=34711120）。
2. **标题语言不一致**。`_norm("痴人说梦")` 与 `_norm("Ravings")` 零交集，`title_ok=False`；
   `get`/`search` 两个标题端点都命中不了（`/api/get?track_name=痴人说梦` 直接 404）。
   唯一桥梁是专辑名「崩坏星穹铁道-痴人说梦 Ravings」**同时含中英两种写法**，且与本地
   专辑逐字一致——但旧代码的 `score_hit` 完全不看 album（只在 `build_get_url` 里拼 URL）。

### 36.2 修复

**A. 拆 503 / 429**（`app/lyrics_online.py`）

- 新增 `ServerBusy`（503）与 `RateLimited`（429）两个异常。
- `_http_get_json`：429 → `RateLimited`（立即收手）；503 → `ServerBusy`（跳过这条试下一条）。
- `fetch_outcome` / `fetch_best_hit`：捕获 `ServerBusy` 记 `saw_busy=True` 后 `continue`；
  最终若一条都没中且 `saw_busy`，返回 `aborted=True`（**不写负缓存**），而不是 `missed`。

**B. 专辑参与身份打分**

- `score_hit` 增加 `album` 参数：专辑相等 +2.0、`_overlap(floor=0.6)` +1.2；
  门槛扩为 `title_ok or duration_ok or (album_ok and artist_ok)`——专辑这条**要求艺人同时相符**，
  避免同一张多曲专辑里配错曲。
- `album` 线程化进整条链：`score_hit / _best_of / pick_best / fetch_outcome / fetch_best_hit`
  与多源层的 `_pick_lyric / fetch_netease / fetch_qq / _best_with_source / fetch_outcome_multi`。

修复后该曲匹配得分：artist(1.5) + duration(3.0) + album(2.0) + synced(0.5) = **7.0 ≥ GOOD_ENOUGH(6.5)**，
keyword 查询命中即早停，少打请求、少撞限流；无时长时 album+artist 也能过门槛（score 4.0）。

### 36.3 单测

- `tests/test_lyrics_online.py`：
  - `TestAlbumBridge` 3 条（痴人说梦↔Ravings 靠专辑命中、无时长命中、专辑同艺人不同被拒）
  - `TestFetchStrategy` 2 条（503 跳过继续命中、全 503 → aborted 不写负缓存）
- `tests/test_lyrics_multi.py`：`test_album_bridges_language_mismatch_across_sources`（多源统一打分传 album）

### 36.4 关键事实

- `/api/search?q=痴人说梦` 返回 id=34711120（因为 album 含中文），而 `/api/get?track_name=痴人说梦` 404、
  `/api/search?track_name=痴人说梦` 空——**标题端点对语言不一致的歌是盲区，`q=` 全文搜才兜得住**。
- LRCLIB 服务端不稳是常态，`/api/get` 偶发 503；但 503 ≠ 没歌词，绝不能据此写 7 天负缓存。

---

## 37. v2.9.0 歌词自定义颜色覆盖：动态渐变 + 逐句取色（2026-10-31）

### 37.1 需求确认（AskUserQuestion 结论）

| 维度 | 选择 | 说明 |
|---|---|---|
| 颜色来源 | **逐句右键取色 + 自动动态渐变** | 两者都要；不支持 LRC 内嵌颜色标签 |
| 触发节奏 | **可按进度 / 按时间切换** | 默认按歌词进度 |
| 渐变形态 | **双色线性渐变** | 方向可调（横/竖/斜） |
| 动效范围 | **仅当前句** | 其他句保持常态色，保性能 |

### 37.2 现状（动手前的事实）

- 歌词行是 `QListWidget + _LyricDelegate` 自绘（`ui/lyrics_panel.py`）。
- 颜色**写死在代码里**：当前句 `ACCENT`、未唱 `TEXT_DIM@alpha90`、交界固定 6px 软过渡
  （`_draw_line` 的 `blend = 6.0`）。**没有任何用户可配的颜色层。**
- 动效是单选枚举 `LYRICS_EFFECTS = ("none","zoom","typewriter","karaoke")`，存
  `Settings.lyrics_effect`。effect 只决定**遮罩/几何**：放大、逐字揭示、已唱/未唱切分。
- 性能关键：`update_position` 每帧只 `_update_row(当前行)`，绝不整块重绘。新功能必须沿用这条。

### 37.3 方案对比

- **A. 只做全局动态渐变**：零配置好看，但满足不了「可指定每行/每句颜色」的硬需求。
- **B. 只做逐句取色（静态）**：能精确指定，但没有「灵动流畅的动态变化」。
- **C（采用）分层正交**：把「颜色」与「遮罩」拆成两个维度 ——
  - **effect** 继续管遮罩/几何（放大 / 逐字揭示 / 已唱未唱切分），**不改**；
  - 新增**颜色覆盖层**只回答「这段文字用什么颜色」；
  - 颜色来源（逐句自定义 / 全局渐变）× 触发（进度 / 时间）× 形态（双色线性）= 可组合。
  
  理由：这样 4 种 effect 与颜色覆盖天然兼容（不是各写一套），旧逻辑在 `enabled=False`
  时走原分支，零风险回滚。

### 37.4 数据模型

**全局**（`app/models.py`，存 `Settings`）：

```python
COLOR_TRIGGERS   = ("progress", "time")
COLOR_DIRECTIONS = ("horizontal", "vertical", "diagonal")

@dataclass
class LyricsColorConfig:
    enabled: bool = False          # 总开关；False 时完全走旧逻辑（零开销）
    trigger: str = "progress"      # progress | time
    gradient: bool = True          # True=双色渐变，False=单色
    color_a: str = ""              # ""=跟随主题 ACCENT
    color_b: str = ""              # ""=由 color_a 派生（提亮版）
    direction: str = "horizontal"
    speed: float = 0.25            # time 模式：每秒相位推进（0.05~2.0）
    transition: float = 0.08       # 已唱/未唱交界软过渡宽度（占行宽 0~0.3）
```

`Settings.lyrics_color: LyricsColorConfig`，`to_dict/from_dict` + `_as_*` 钳位/校验；
非法枚举回默认，不整块炸（沿用 v2.7.5 容错约定）。

**每曲逐句颜色**（新纯逻辑模块 `app/lyrics_colors.py`）：

- 存放：`paths.lyrics_colors_dir()/<track_id>.json`，形如
  `{"version": 1, "lines": {"12340": "#ff6b9d", ...}}`，键是**行时间戳 time_ms**。
- 为什么用 time_ms 而不是行号：插入/删除行不漂移；换歌词文件时可能对不上，提供「清除本曲颜色」。
- 接口：`load_line_colors(track_id, base_dir=None) -> dict[int,str]` /
  `save_line_colors(...)` / `set_line_color` / `clear_line_color` / `clear_song_colors`。
- 容错：坏 JSON / 非法色值一律跳过，不抛；空映射删文件。

### 37.5 渲染管线（`ui/lyrics_panel.py`）

颜色解析（每行）：

```
line_color = sidecar.get(line.time_ms)        # 逐句优先
a = line_color or cfg.color_a or theme.ACCENT
b = cfg.color_b or derive_lighten(a)          # 未配则派生
```

- **进度模式（默认）**：已唱段用 `a→b` 渐变，交界处以 `transition*行宽` 软过渡到
  未唱色（未唱 = `a` 压 alpha ~90，保可读）。行为等价于现有 karaoke，但颜色可配。
- **时间模式**：整行用 `a→b` 渐变，渐变**相位** `phase=(t*speed)%1` 随时间平移
  （一条高光带扫过），与唱到哪无关；仍受 effect 遮罩约束。
- **与 effect 正交**：none/zoom=整行着色；typewriter=只给已揭示部分着色；karaoke=
  已唱用 `a→b`、未唱用 dim。译文行用「a 提亮 + 降透明」的次级色，不参与强扫光。
- 非当前行永远 `_normal_color()`，零动效。

### 37.6 性能设计（硬约束）

1. 动画只在 `enabled && trigger=="time" && visible && mode=="synced"` 时启动
   `QTimer(33ms≈30fps)`；`hideEvent/showEvent` 停/启。
2. 每 tick **只** `_update_row(当前行)`，绝不 `viewport().update()` 全量重绘。
3. 复用 `_font_cache`；每行解析出的 `(a,b)` 缓存在 panel，配置/歌词变更才重算。
4. `enabled=False` → 所有新分支第一行早退，开销≈0。
5. `QLinearGradient` 每帧仅当前 1 行构建一次（可接受）。

### 37.7 接口与接线

- `LyricsPanel`：
  - `set_color_config(cfg)`、`set_line_colors(mapping: dict[int,str])`（键=行下标）
  - 新信号：`line_color_requested(int idx)`、`line_color_clear_requested(int idx)`、
    `song_colors_clear_requested()`
  - 右键菜单仅 `mode=="synced"` 时插入这三项
- `SettingsDialog`：歌词页加「歌词颜色覆盖」区（启用开关 / 触发 / 方向 / A、B 颜色 /
  速度 / 过渡），发 `lyrics_color_changed(object)`。
- `MainWindow`：
  - 切歌/加载歌词后 `load_line_colors(track_id)` → `panel.set_line_colors`
  - `line_color_requested` → `QColorDialog` → 保存 sidecar → 重新下发
  - `_on_settings_lyrics_color` → 存 Settings + `panel.set_color_config`

### 37.8 验收标准

- `enabled=False`：既有 646 项测试**零回归**，肉眼与现在完全一致。
- 启用 + 进度：当前句已唱部分按 `a→b` 随进度扫过，交界软宽可调。
- 启用 + 时间：渐变相位按 `speed` 流动，视觉连续；仅当前行。
- 逐句取色：该句覆盖全局色；切歌再回来仍保留；「清除本曲」可复原。
- 与 4 种 effect 组合均不崩、不糊：karaoke 仍分已唱/未唱，typewriter 仍逐字揭示，zoom 仍放大。
- 性能：动画时只有当前行重绘（用计数断言之）；ruff 干净；全量回归全绿；打包 smoke + 真实平台通过。
- 版本升 `2.9.0`。

### 37.9 风险与回滚

- **右键菜单冲突**：现有 6 个动作，新增 3 个；只 synced 模式插入并加分隔线。
- **time_ms 键漂移**：换歌词文件后逐句色可能错位 → 提供「清除本曲歌词颜色」。
- **测试里的模态框**：`QColorDialog` 必须 patch 模块级名字（见记忆：拦 Qt 模态框要 patch 模块级符号）。
- **offscreen QMediaPlayer 累积死锁**：新 E2E 单独成类/独立进程。
- **回滚**：`enabled=False` 即旧行为；如需彻底移除，只删新增文件与新分支，不动旧路径。

---

## 38. v2.9.1 双语译文「不跟着变色」修复（2026-10-31）

### 38.1 现象与复现

用户反馈（截图 + 一句「这种带翻译的歌词不会一起变色」）：双语歌词里**原文行**有粉→紫
→粉的流动渐变，**紧跟其下的译文行**却是一整行均匀的淡紫灰，完全没有渐变。

复现（浅色主题、`#ae5df3 → #f5d90a`、双语三句、当前句行内进度 0.7）：

| 动效 | 原文 | 译文 |
|---|---|---|
| `karaoke`（颜色覆盖） | 已唱段紫→黄渐变，未唱尾段淡掉 | **整行 `_dimmed(pair[0])` 单色** |
| `none` / `zoom` | 完整流动渐变 | 完整渐变，但压了 alpha 205，明显发灰 |

### 38.2 根因（两个，叠在一起）

1. **karaoke 的逐字进度按「两行字符总数」推进**。`_typed_split(35, 14, p)` 意味着
   扫光要走完 35 个英文字符才开始碰到译文（p > 0.71）。在这之前 `sub_typed == 0`，
   走的是 `if typed <= 0: painter.setPen(unsung)` —— 整行一个 `_dimmed(pair[0])`
   （alpha 90 单色）。用户看到译文的那几秒，正好都落在这一段里。
2. **译文还被额外压了 alpha 205 当「次级色」**（v2.9.0 的设计）。深色主题下不明显，
   浅色主题下叠在淡色高亮底上，几乎被洗成灰。
3. 顺带暴露的第三个问题：`_flow(rect, ...)` 用的是**整条 item 的 rect**。vertical /
   diagonal 方向下，双语 item 高两行，译文行只能取到渐变的下半段 → 退化成单色。

### 38.3 方案对比

| 方案 | 做法 | 取舍 |
|---|---|---|
| A 只提透明度 | 205 → 255 | 修不了 karaoke 的 `typed<=0` 单色，主线问题仍在 |
| B 译文不参与扫光（**采用**） | `_draw_line(sweep=False)`：译文整行直接铺完整渐变 | 一行改动，语义清楚：**扫光属于「正在被唱的那一行」**；译文是同一句的另一种文字，整句一起着色才对 |
| C 按各自行字符数拆进度 | 原文一档、译文一档，各扫各的 | 与 v2.6.10「两行连着打出」的 typewriter 语义冲突，要改的地方多 |

选 B，并同时去掉 alpha 205：层级改由**字号（-3px）**承担。颜色保持一致才有
「整句一起流动」的观感 —— 这本来就是用户要的。

### 38.4 改动清单

- `ui/lyrics_panel.py`：
  - `_paint_block`：`sub_pair` 删除，译文直接复用 `pair`；给两行各算一条 `band`
    （`(top, top+main_h)` / `(top+main_h, top+main_h+sub_h)`）；译文传 `sweep=False`。
  - `_draw_line`：新增 `band=None`、`sweep=True`；karaoke 分支在 `typed` 判断**之前**
    加 `if not sweep and use_grad:` → 整行铺 `_flow()`。
  - `_flow(band, ...)`：签名 `rect → band`，vertical/diagonal 用本行上下边界。
- `tests/test_widgets.py::TestLyricsColor` 新增 2 项：
  - `test_bilingual_translation_shares_pair_and_skips_sweep`（patch `_LyricDelegate._draw_line`
    记录实参：译文必须拿到与原文同名同 alpha 的 pair，且 `sweep is False`）
  - `test_flow_uses_each_line_band`（vertical 用给定 band，horizontal 轴必须是水平）
- `app/version.py → 2.9.1`

### 38.5 验收标准

- 双语 + `karaoke`：译文行与原文同步呈现同一渐变（像素采样能在译文行找到 `#f5d90a`
  级的 `color_b` 峰值）。
- 双语 + `none/zoom/typewriter`：译文与原文同色；typewriter 仍按进度逐字揭示。
- 三种 direction 下译文都有颜色；vertical/diagonal 各自在本行范围内渐变。
- 非双语（单行）歌词零变化；`enabled=False` 完全走旧路径。
- 全量回归全绿、ruff 干净、打包 smoke 通过、`--check` 输出 v2.9.1。

### 38.6 风险

- **译文比原文更亮**：karaoke 下原文未唱尾段是 `_dimmed` 单色，而译文整行满色，
  可能显得译文更抢眼。可接受（译文更小、更短），若用户仍觉得跳，再把译文整体乘
  0.85 亮度。
- **多语言行数 > 2**：目前 `LyricLine` 只有原文 + 译文两层，`band` 按两层算；若将来
  加第三行，需要改成按行循环分配 band。

---

## 39. v2.9.2 译文行与主歌词「同步扫光」（2026-10-31）

### 39.1 为什么要改回扫光

v2.9.1 的 38.3 选了「译文整行直接铺满渐变、不参与扫光」，理由是「扫光属于正在被唱的
那一行」。交付后用户反馈：**「效果跟主歌词同步」** —— 译文整行满色、原文在扫，两条线的
观感仍然是脱节的，只是从「译文太暗」变成了「译文太亮且不动」。

第一性原理：karaoke 的扫光其实是「这一句唱到哪儿」的指示器。译文是**同一句**的另一种
文字，它应该在同一个时刻表示同一个进度。所以正确做法不是把译文排除在外，而是让它
**用同一个进度、各自按自身长度**推进。

### 39.2 根因回顾（38.2 的补充）

`_typed_split(35, 14, p)` 把两行拼成一个 49 字的总长度来算进度：

| p | 合并口径 main / sub | 同步口径 main / sub |
|---|---|---|
| 0.25 | 12 / **0** | 9 / 4 |
| 0.5 | 25 / **0** | 18 / 7 |
| 0.75 | 37→35 / 2 | 26 / 11 |
| 1.0 | 35 / 14 | 35 / 14 |

合并口径下，译文要到 p>0.714 才开始亮 —— 那之前它在画面上就是一片暗色。
「不同步」的根源在这里，不在颜色。

### 39.3 方案

| 方案 | 做法 | 取舍 |
|---|---|---|
| A 保持 38.3 的整行满色 | 不动 | 用户已明确否决 |
| B 缩短合并分母 | 用 `max(main_len, sub_len)` 之类折中 | 还是错位，只是错得少一点 |
| C 两行各按自身长度乘同一 p（**采用**） | `_typed_split(..., sync=True)` | 一行改动，语义最直白：同一时刻亮起的**比例**相同 |

`sync` 只在 **karaoke** 打开。**typewriter 保持合并口径**（v2.6.10 的「原文打完再打译文，
两行连着打出」是打字机应有的手感，且用户没有异议）—— 这也是本次唯一的破坏性规避点：
不开 karaoke 就零变化。

另外把 `_dimmed()` 的未唱 alpha 从 90 抬到 110：90 时未唱段几乎只剩一团灰，
双语歌词里译文行经常整行处在未唱区，太暗会被误读成「没变色」。

### 39.4 改动清单

- `ui/lyrics_panel.py`
  - `_typed_split(main_len, sub_len, progress, sync=False)`：新增 `sync` 分支
    （`round(main_len*p)` / `round(sub_len*p)`，各自夹到自身长度）。
  - `_paint_block`：`_typed_split(..., sync=(effect == "karaoke"))`；译文恢复参与扫光
    （删掉 v2.9.1 的 `sweep=False`），保留 `band`。
  - `_draw_line`：删除 `sweep` 参数（一次版本内就退休，避免留下第二个口径）。
  - `_dimmed()`：alpha 90 → 110。
- `tests/test_widgets.py::TestLyricsColor`
  - `test_bilingual_translation_shares_pair_and_scans_in_sync`（24 字原文 / 8 字译文，p=0.5
    → 12 / 4，并断言两行 band 不同）
  - `test_karaoke_sync_typewriter_staggered`（karaoke 同步、typewriter 错位、单语一致）
- `app/version.py → 2.9.2`

### 39.5 验收标准

- 双语 + karaoke：任一进度下，两行「已亮 / 未亮」的分界**按各自行内比例**对齐
  （25% 时两行都只有前 1/4 亮）。
- typewriter：行为与 v2.6.10 完全一致（原文打完才轮到译文）。
- 单语歌词：`sync` 有无结果相同，零变化。
- 全量回归全绿、ruff 干净、打包 smoke 通过、`--check` 输出 v2.9.2。

### 39.6 已知遗留

- karaoke 的「已唱 / 未唱」交界渐变目前恒为**水平**，不跟随 `direction` 设置。
  `direction` 只作用于已唱段内的双色色带。极端情况下（vertical + 双语）交界仍是竖切，
  视觉可接受，若要彻底一致得改成「clip + 两遍绘制」，会牺牲 `transition` 软边。

---

## 40. v3.0.0 本地 AI 强制对齐：逐字时间轴（2026-10-31，方案待确认）

### 40.1 需求确认（AskUserQuestion 结论）

| 维度 | 选择 | 说明 |
|---|---|---|
| 对齐引擎 | **内置 AI 模型** | faster-whisper + ctranslate2，本地推理，不上传音频 |
| 精度目标 | **逐字卡准** | 每个字的时间戳来自声学对齐，不再靠行内插值 |
| 触发方式 | **单曲右键 + 全库批量** | 单曲即时；批量挂机跑，带进度与中断 |

### 40.2 为什么现在做、为什么必须用模型

现状三个事实（都是本项目自己实测留下的记录）：

1. **渲染层的「逐字」是假的**：`ui/lyrics_panel.py` 的 typewriter / karaoke 按
   「行内进度 × 字数」线性推进。一句 4 秒 20 字 → 每 200ms 亮一个字，与人声无关。
2. **行级对齐的天花板是 6 秒**：v2.6.12 记录《何者》按字数加权后中位误差 **6.04s**，
   并明确写下 *「字数完全不解释时长，拖音和句内间奏在纯文本里没有任何信息……要逐句
   卡准必须做音频-文本强制对齐」*。
3. **强制对齐这条路走过一次，是云端方案**：v2.6.6 接了 LyricTimestamps（multipart
   上传音频、自备 Key、免费 15 分钟/月），v2.7.0 因「上传音频 + 需 Key」移除。

所以本次不是新增一个花哨功能，而是**把当年被砍掉的能力用本地方案补回来**，
并且一路做到字级。

### 40.3 技术选型

| 候选 | 结论 | 理由 |
|---|---|---|
| faster-whisper + ctranslate2（**采用**） | 依赖 `ctranslate2 4.8.4`（**已验证有 cp313-win_amd64 wheel**）+ `faster-whisper 1.2.1`（纯 py） | 纯离线；int8 量化 CPU 可用；`word_timestamps=True` 直接给词级时间 |
| openai-whisper（torch） | 否 | torch 单独 +200MB，启动与内存都不可接受 |
| whisper.cpp（自编译） | 否 | 需 MSVC 工具链，跨平台维护成本高，打包不可控 |
| wav2vec2 + torchaudio forced_align | 否 | 学术最优，但同样背 torch |
| 纯信号处理升级到「字级」 | **兜底** | 不占体积、离线必成；但行级只能到 6 秒，字级更是估计值。作为 AI 失败时的回退 |

### 40.4 算法：五层，每层都能独立降级

```
音频文件
  │
  ├─ L1 声道预处理：stereo → mid = (L+R)/2（人声通常居中，零成本压掉宽立体声伴奏）
  │      失败/单声道 → 直接用原信号
  ├─ L2 faster-whisper（int8）→ 词级时间戳 [(start, end, text), ...]
  │      模型不可用/超时 → 直接跳到兜底
  ├─ L3 difflib.SequenceMatcher：识别词序列 ↔ 原歌词字序列
  │      逐字时间戳 = 匹配到的识别词时间窗内按字均分
  ├─ L4 能量包络微调：用现有 rms_envelope 把字边界吸附到能量谷（换气/辅音起点）
  └─ L5 置信度自检：matched_ratio < 阈值 → 丢弃结果，回退信号处理并提示用户
```

**为什么必须 L3**：Whisper 在**唱歌**上会听错词（尤其带伴奏的中文歌）。直接用识别的
文本当歌词就是错的；我们要的是**时间戳**，文本用用户自己的。L3 把「识别时间轴」映射
回「原文时间轴」，听错个别字不影响整体对齐。

**为什么必须 L4**：Whisper 的词时间戳是「整词一个窗」，中文词往往 2~3 个字。窗口内
按字均分仍是估计；用能量谷吸附能把误差从 ±150ms 压到 ±80ms 量级。

**为什么必须 L5**：唱歌识别可能整段失败（纯乐器间奏被识别成歌词、或全程听不懂）。
没有自检就会「静静地生成一份错歌词」，比不做还糟。

### 40.5 数据模型

```python
@dataclass(frozen=True)
class WordSpan:
    start_ms: int
    end_ms: int
    text: str            # 该字/词对应原文里的片段

@dataclass
class LyricLine:
    time_ms: int
    text: str
    translation: str = ""
    words: tuple[WordSpan, ...] = ()   # v3.0.0：空 = 没有字级数据，回到线性插值
```

`words` 为空时**渲染路径与现在完全一致**，这是零回归的保证。

持久化：`%APPDATA%/轻音播放器/lyrics_words/<track_id>.json`
```json
{"version": 1,
 "lines": {"12345": [[12500, 12680, "故"], [12680, 12820, "事"]]}}
```
键是行时间戳（与 `lyrics_colors` 同构，换歌词文件也不会错位到别的行）。
`终点 == 0` 表示「终点未知」（增强 LRC 末段没有结尾戳），渲染按下一个字或行尾兜底。

`model` / `confidence` **刻意先不落盘**：现在没有任何界面消费它们，存下来就是死字段；
`version` 留好了，等 D2 要做「对齐质量」展示时再加字段即可，旧文件读起来不受影响。

### 40.6 渲染接入

`_paint_block` 取 `line.words`：
- 有 words → `typed` 由「当前播放位置落在第几个字的窗口内」决定（逐字真同步）
- 无 words → 现有 `_typed_split` 线性插值（karaoke 同步口径保持 v2.9.2 行为）

颜色覆盖（v2.9.x）不动，两条路径正交。

**关键实现取舍**：`_draw_line` 的接口只有一个整数 `typed`（`text[:typed]` + 按字宽算交界
x），所以「逐字对齐」不需要碰任何画法，只需把 `typed` 的来源换掉 —— 这是零风险的根。
`_typed_from_words()` 返回 `None` 表示「数据不可用」（时间倒退 / 空 / 行文本为空），
调用方回退线性插值：**坏 sidecar 的后果只能是「退化」，不能是「乱跳」**。

译文行没有自己的词元（数据模型里没有这个字段），按 `typed / len(text)` 的比例推进，
与 v2.9.2 的「两行同步扫光」口径一致。

### 40.7 体积与模型分发（**需二次确认**）

依赖体积（估）：

| 组件 | 体积 |
|---|---|
| ctranslate2（含 DLL） | ~40 MB |
| av（PyAV，含 FFmpeg） | ~40 MB |
| onnxruntime（VAD） | ~15 MB |
| numpy（ctranslate2 硬依赖，当前被 build.py 排除） | ~15 MB |
| tokenizers / huggingface_hub 等 | ~5 MB |
| Whisper base int8 模型 | ~74 MB |
| **合计** | **≈ +190 MB** |

三档分发策略：

| 策略 | onefile 体积 | 首次使用 | 取舍 |
|---|---|---|---|
| A 全内置 | ~245 MB | 开箱即用 | **onefile 每次启动要解包 245MB，启动会明显变慢** |
| B 运行时内置 + 模型首下（**推荐**） | ~170 MB | 需联网下 74MB | 启动影响可控；模型可换可删 |
| C 全首下 | ~57 MB | 需联网下 ~145MB | 包体不变，但首次体验差、离线用户不可用 |

### 40.8 界面

- 歌词右键新增：「AI 对齐歌词（逐字）」——排在「本地近似·免 Key」上方，标注精度差异
- 设置 → 歌词页新增「AI 对齐」区：模型档位（base / small）、批量对齐入口、清空字级数据
- 批量对齐：独立进度对话框（可中断），逐首处理，失败的列出来但不中断整体

### 40.9 验收标准（量化，不靠肉眼）

1. **精度**：用 `tools/eval_align.py`（以联网歌词为真值）对同一批歌对比，
   行级误差中位数 6.04s → **< 0.5s**；这是硬指标。
2. **字级**：抽 3 首人工核对，逐字亮起时刻与人声起点偏差 **< 200ms**。
3. **零回归**：`words` 为空的歌，渲染/滚动/颜色覆盖全部与 v2.9.2 逐字节一致。
4. **兜底可用**：拔掉模型目录 → AI 对齐项置灰并提示，其余功能不受影响。
5. 全量回归全绿、ruff 干净、打包 smoke 通过、`--check` 输出 v3.0.0。

### 40.10 风险与回退

| 风险 | 概率 | 应对 |
|---|---|---|
| **打包 ctranslate2 / av 失败**（C++ 扩展 + FFmpeg DLL） | 中 | Phase 0 先验证；失败则退到「外部依赖 + 设置里指定路径」 |
| **唱歌识别率低** | **高** | L1 声道增强 + L3 文本比对 + L5 自检回退；实在不行只用 L4 能量切分 |
| numpy 解禁影响现有构建 | 中 | build.py 只放行 numpy，其余排除项不动；跑全量回归 |
| 内存峰值（模型加载 ~500MB） | 中 | 批量模式复用同一个 session，不逐首重建 |
| onefile 启动变慢 | 高（若选策略 A） | 推荐策略 B |

**回退**：所有新功能都在 `words` 为空时失效，删掉 `app/lyrics_asr.py` + 右键项即回到 v2.9.2。

### 40.11 Phase 0：可行性关卡（先验证再写业务代码）

动手前必须先跑通这 4 条，任何一条失败就改方案而不是硬着头皮写：

1. `pip install faster-whisper` 在 venv 里装成功（含 ctranslate2 / av / onnxruntime）。
2. 用合成音频跑一次 `transcribe(word_timestamps=True)`，确认能出词级时间戳。
3. PyInstaller 打一个最小探针 exe，确认能加载 ctranslate2 并完成推理。
4. 记录真实体积增量，回填 40.7 的数字。

> ⚠️ 本地没有真人演唱样本（fixtures 全是合成音），**唱歌对齐质量只能由用户在自己的
> 歌上验证**。所以 L5 自检 + 一键回退不是可选装饰，是交付前提。

### 40.12 Phase 0 实测结果（2026-10-31，已验证）

| 关卡 | 结果 | 关键结论 |
|---|---|---|
| P0-1 依赖安装 | ✅ | 21 个包，1m55s。`ctranslate2` 有 cp313-win_amd64 wheel |
| P0-2 推理 | ✅ | 模型加载 0.9s、2 秒音频推理 1.25s、词级时间戳结构正确 |
| P0-3 打包 | ✅ **但需锁版本** | PyInstaller 产物能加载模型并完成推理 |
| P0-4 体积 | ✅ | 见下表，**比预估大 65MB** |

**实测体积（onedir，不含 PySide6）**

| 组件 | 体积 |
|---|---|
| ctranslate2（含 61MB DLL） | 62 MB |
| **av + av.libs（PyAV 自带 FFmpeg）** | **68 MB** |
| numpy + numpy.libs | 27 MB |
| tokenizers | 7.5 MB |
| 小包（huggingface_hub / tqdm / click …） | ~5 MB |
| **AI 增量合计** | **≈ 164 MB** |
| Whisper base 模型（`model.bin`） | **142 MB**（不是估的 74MB：int8 只是推理时量化，磁盘仍是 fp16） |

按策略 B（运行时内置 + 模型首下）：安装包 **≈ 220 MB**，首次用 AI 再下 **142 MB**。
若砍掉 av（见下），安装包可降到 **≈ 152 MB**。

### 40.13 Phase 0 踩到的坑（全部实测，别再踩）

1. **ctranslate2 4.8.4 在 PyInstaller 产物里加载模型必 segfault**（exit 139，零输出、
   无异常）。onedir / onefile 都一样，补 `libiomp5md.dll`、手动 `os.add_dll_directory`、
   限制 `OMP_NUM_THREADS=1` 全都无效。**降到 4.6.0 立刻正常**。
   代价：4.6.0 依赖 `pkg_resources`，需 `setuptools<81`（81 起移除）。
   → 依赖必须锁死：`ctranslate2==4.6.0`、`setuptools<81`。
2. **`--collect-binaries ctranslate2` 必须加**，否则 `libiomp5md.dll`（Intel OpenMP）
   不会被打进去，缺失时同样是 segfault 而不是 ImportError，极难排查。
3. **`av` 是 68MB 的隐形大头**，但我们根本不用它：faster-whisper 传**文件路径**时走
   `av.open(...)`，而 `av 19` 删掉了 `metadata_errors` 参数，1.2.1 还在传 → 直接
   `TypeError`。**必须自己用 miniaudio 解码成 numpy 数组传进去**（顺带做了 L1 声道提取）。
   既然不用 av，打包可用一个 stub `av` 模块顶掉 `import av`，省 68MB（列为 P0 后续优化）。
4. **HF 镜像不支持 Xet**：`hf-xet` 会去 `cas-server.xethub.hf.co` 取文件并拿到
   `401 Unauthorized`。必须 `HF_HUB_DISABLE_XET=1`。顺带证明 `hf_xet`（9MB）可排除。
5. **直接传 `"base"` 会联网查版本**，离线/网络不通时抛 `ProxyError`。必须走本地目录路径
   `WhisperModel(<dir>)`，这也正是「首下后永远本地加载」的设计。
6. **onnxruntime（45.6MB）可整个排除**：只被 VAD 用，`vad_filter=False` 时不需要。
   打包验证通过。
7. **幻觉置信度可自动识别**：合成音（无语音）测试里 whisper 仍"听"出 7 个字，
   但 `probability` 只有 0.03~0.12。L5 自检用这个指标即可判「不可信」，无需人耳。

### 40.14 Phase A / C 实施记录（2026-10-31，已完成 ✅）

**A. 数据层**

`app/lyrics.py`：
- `WordSpan(start_ms, end_ms, text)` + `LyricLine.words`（默认空元组 = 零回归开关）。
- `_parse_word_tags()` 解析增强 LRC 的行内 `<mm:ss.xx>`。四个必须守住的细节：
  1. **段落不 strip**：英文靠空格分词，拆完拼回去必须与「删标签后的纯文本」逐字符相等；
  2. **末尾空段 = 结尾时间戳**：`...事<00:13.00>` 那个标签没有后续文字，是给「事」补
     `end_ms` 的，不能当成空词元塞进序列；
  3. **首个标签前的残留文字并入第一段**：`前<00:01.00>奏` 里「前」没有自己的时间；
  4. **`offset` 必须同步平移逐字**（漏了的话：行高亮到了、字还停在原地）。
  另外一行挂多个时间标签（副歌重复）时，逐字按 `t - times[0]` 整体平移，
  否则第二遍的逐字全挤在第一句的位置。
- `merge_translations()` 保留原文那一行的 `words`；译文行的逐字标签丢弃（模型里没有
  「译文词元」，硬塞会破坏「字元拼接 == 行文本」的对位前提）。

`app/paths.py`：`lyrics_words_dir()` + `DATA_SUBDIRS` 增 `lyrics_words`
（漏了这行 → 用户换数据目录时这份 sidecar 会被迁移逻辑孤立丢弃）。

`app/lyrics_words.py`：sidecar 读写，接口 `load_line_words / save_line_words /
attach_words / apply_track_words / save_from_lines / clear_song_words`。
`attach_words()` 的硬门槛：**`words` 拼起来的字符串必须等于该行 `text`**，否则整行丢弃
退回线性插值。理由：sidecar 可能配到被替换过的 .lrc 上，时间戳碰巧撞上、文本却不同，
硬贴会让高亮按错误字数切片（表现为「扫光跑到句子中间」）。校验失败只影响该行。

**C. 渲染接入**

`ui/lyrics_panel.py`：
- `_typed_from_words(words, text, position_ms, line_end_ms)`：按真实字时间窗求字符下标。
  落在某字窗口内按比例折算并四舍五入；末字「终点未知」用已知窗口平均时长或行尾兜底；
  时间不单调 / 空数据返回 `None` → 回退 `_typed_split`。
- `_paint_block` 里 words 优先、译文按 `typed/len(text)` 比例推进；
- `LyricsPanel._row_words()` / `_line_bounds()` 两个小助手，`_line_progress` 改用
  `_line_bounds` 保证「逐字求解」与「句内进度」同源。
- `ui/main_window.py::_load_lyrics` 显示时 `apply_track_words(synced, track.id)`，
  缓存里存的是**没有**逐字数据的基准行 → 重新对齐后无需清缓存即可生效。

**验证**
- `tests/test_lyrics_words.py` 22 例；`tests/test_widgets.py` 新增 6 例，其中
  `test_paint_block_without_words_keeps_v2_9_2` 断言「无 words 时与 v2.9.2 逐字节一致」。
- `tools/probe_lyrics_words.py` 视觉探针：同一句、同一进度，两行分别是线性插值 /
  逐字时间窗。2000ms（进度 50%）实测：线性亮到第 4 字「随记忆一」，逐字亮到第 7 字
  「随记忆一直晃到」—— 与 stdout 打印的 `线性=4 / 逐字=7` 一致。
  截图 `shots/lyrics_words_2000.png`。

### 40.15 Phase B / D 实施记录（2026-10-31，已完成 ✅）

**B. 对齐引擎 `app/lyrics_asr.py`**

五层全部落地，**每一层的失败都只是一种降级，不是崩溃**：

| 层 | 实现 | 失败时的行为 |
|---|---|---|
| L1 | `decode_for_asr()`：miniaudio 立体声解码 → `(L+R)/2` | 伪立体声/解码失败 → 退回单声道；`av` 完全不参与 |
| L2 | `transcribe()`：faster-whisper int8，`word_timestamps=True` | 缺依赖/模型缺失 → 错误码，不抛异常 |
| L3 | `_match_windows()` + `_spread()` + `_fill_gaps()`：difflib 三件套 | 匹配率低 → L5 拒绝整份结果 |
| L4 | `snap_to_energy()`：±120ms 找 RMS 极小点 | 拿不到包络 → 跳过吸附，均分照用 |
| L5 | 匹配率 `<0.55` 或平均概率 `<0.25` → `low_confidence` | **不写盘**，`lines` 原样返回 |

关键决策与理由：

1. **必须自己解码，不能把文件路径交给 whisper**。faster-whisper 1.2.1 走
   `av.open(metadata_errors=...)`，而 av 19 已删掉该参数 → 直接 `TypeError`。
   自己解码成 numpy 数组喂进去既绕开这个雷，又顺带做了 L1，还让 `av`（68MB）
   将来可以从安装包里整个排除。
2. **L3 用 difflib 而不是「按字数比例切分」**。唱歌时 whisper 必错字，但错的只是
   **文本**；`SequenceMatcher` 会把错字当成插入/删除跳过，剩下的匹配块照样给出时间。
   单测里「黄→苦」听错一个字，匹配率 5/6 仍然过门槛，逐字数据完整。
3. **`_spread()` 不能省**。一个中文词往往 2~3 个字共享一个词窗，不拆开的话
   「故事的小黄花」会整句同时亮，逐字效果直接退化成整行。
4. **`_fill_gaps()` 靠邻居插值**。只识别出前半句时，后半句按最后一个字的结束时间
   外推，保证 `words` 覆盖整行 —— 渲染层要求「字元拼接 == 行文本」。
5. **`rms_fast()` 取代 `rms_envelope()`**。后者是纯 Python 双重循环，4 分钟歌要过
   960 万个采样点（十几秒）；向量化后用平方累积和做滑窗，几十毫秒。单测直接比对
   两者输出，钉死「同口径」。
6. **`retime_lines()` 是「行级 6.04s → <0.5s」的落点**，v3.0.6 起接入渲染链：
   行轴校正根本不需要写回 .lrc——`apply_track_words()` 贴完逐字数据后，用每行首字
   的实测时刻在**内存里**重打 `time_ms`，副作用为零。改用户的歌词文件仍属破坏性动作、
   依旧不自动写回；但「行高亮对不上人声」这个后果已被内存 retime 消除，界面那段
   「建议先逐句打轴」的兜底提示保留（只在偏差仍 >1s 且用户没跑 AI 对齐时才有意义）。
7. **拖音会让逐字扫光卡在一个字符上（v3.0.7）**。whisper 把整段拖长音算给某一个音节
   （实测 "Freely, aloud~~~~" 的 'u' 独占 4770ms），渲染时按真实字窗比例推进，扫光就
   在这一个字上停近 5 秒，用户看到的是「这句唱完了、歌词却卡在中间，很久才切下一句」。
   修复在**渲染层**（`_typed_from_words`，不动 sidecar）：字窗夹到 `CHAR_SWEEP_MAX_MS`
   （1200ms），一旦某字被压缩其后字**全部顺延**（有效时间轴严格连续），拖音剩余时间
   整句保持高亮。只夹 `end` 不解决——句内会留空隙，照样卡。字窗都 ≤ 上限的行零回归。

**真机验证（合成音频，无人声）**：
whisper-base 仍幻觉出「你认识了我吗」，`probability` 只有 0.02~0.48 →
L3 匹配率 0% → L5 判定 `low_confidence`，`words` 保持空元组。
**这正是设计要的结果：宁可不给，也别给错。**

**D. 界面**

- 歌词右键：「AI 对齐歌词（逐字）」+「清除本曲逐字数据」，无同步歌词时置灰
  （AI 对齐解决的是「字在什么时候亮」，行时间轴得先有 —— 文案与置灰状态都说明这点）。
- 设置 → 歌词与统计：「AI 逐字对齐」区（档位 tiny/base/small + 批量入口 + 清空字级数据）。
- 批量 `AiBatchAlignDialog`：逐首串行（并行只会抢 CPU 且内存翻倍）、失败不中断、
  可停止、失败有清单；**跑着的时候 `closeEvent` 直接忽略**，避免带活线程析构。
- 打开批量**不预扫全库**：`_resolve_lyrics` 每首都可能触发 mutagen 读标签，
  几千首会把界面卡住；改成对话框逐首判断，没有歌词的标「跳过」。
- 模型缺失 → 弹「需要下载 XX MB」确认后再下（142MB 不该在用户不知情时发生）；
  下载在 worker 里做，界面不冻。

### 40.16 Phase E 验收记录（2026-10-31）

| 验收项（40.9） | 结果 |
|---|---|
| 零回归：`words` 为空的歌与 v2.9.2 逐字节一致 | ✅ 单测 `test_paint_block_without_words_keeps_v2_9_2` 直接对比 `_typed_split` 输出 |
| 兜底可用：拔掉模型 → AI 项不可用且不静默 | ✅ 菜单项按「有无同步歌词」置灰；模型缺失弹下载确认；失败收敛成中文 toast |
| 全量回归全绿 | ✅ **34 模块 / 746 用例**，12m28s |
| ruff 干净 | ✅ `All checks passed!` |
| 打包 smoke 通过 | ✅ onefile + onedir 双产物，含音频解码 smoke + 真实平台 8s 不崩 |
| `--check` 输出 v3.0.0 | ✅ |
| **打包后能加载模型**（Phase 0 的最大风险） | ✅ **用冻结产物实跑 `--check-ai`：import OK / 模型就绪 / 解码 OK / 推理 OK** |
| 行级误差 6.04s → <0.5s（`tools/eval_align.py`） | ⏳ 待办：需要一首**真人声**的歌做真值对比，现有夹具全是合成音（无唱词），无法量化 |
| 字级偏差 <200ms（人工抽 3 首） | ⏳ 同上，等真实音频 |

**体积**：onefile 56.8MB → **122.8MB**（+66MB，AI 增量）。
onefile 压缩后仍比预估的 164MB 增量小，因为 DLL 压缩率不错。
`av`（68MB）本轮**没有**用 stub 顶掉 —— 这条优化只省体积，但会让「打包后 import av
到底行不行」变成运行时才暴露的风险，必须单独验证，不能塞进这一版一起上。

**新增诊断入口**：`main.py --check-ai <模型目录> [音频]`。
windowed 产物没有 `sys.stdout`，所以报告写到 `%TEMP%\qy_ai_check.txt`。
它的存在理由就是上面那个打勾项 —— 「冻结后加载模型 segfault」这种失败**不抛异常、
不打印任何东西**，只能靠一个能跑通的命令来证伪。

### 40.17 v3.0.1 事故复盘：模型下载在真实环境必失败（2026-10-31）

**现象**：v3.0.0 出货后，用户在设置页选好档位、点 AI 对齐，弹「AI 对齐失败：AI 模型
下载失败（检查网络）」。开发态同一份代码能下完（tiny 75MB / 54s）。

**定位过程**（关键是别猜，拿证据）：

1. 检查用户真实数据目录 `%APPDATA%\轻音播放器\models\small\`：里面**只有一个 4KB 的
   `.cache/huggingface/trees/*.json`**，一个模型文件都没有 → 说明**元数据请求成功了**
   （网络通、DNS 通、TLS 通），挂在拉实际文件那一步。
2. 该 json 里 `model.bin` 是 483,546,902 字节并带 `xet_hash` → 这个仓库是 **Xet 存储**，
   大文件走的是完全不同于小文件的下载通道。
3. C 盘剩余 43G → 排除磁盘空间。
4. 检查 PyInstaller warn 文件：`httpx2` / `httpcore2` / `anyio` 都被正常分析进去了，
   `sniffio` 缺失在 venv 里同样缺失（anyio 有兜底），**不是漏收模块**。

也就是说：这不是「少打包了一个包」，而是 **`snapshot_download` 这条链在大文件 + 镜像
+ 冻结三件事叠加下不可靠，而且它把自己的异常包得看不出根因**。

**根因（两层）**：

- 直接原因：`ensure_model()` 写了 `except Exception: return "download_failed"`，
  把真实异常整个吞掉。界面因此只能显示「检查网络」—— 这句话是**猜的**，不是读到的。
  这是设计违例：项目既有约束是「不允许静默失败」。
- 结构性原因：为了下 4 个静态文件，把 `huggingface_hub` + `httpx2` + `httpcore2` +
  `anyio` + `fsspec` + `click` + `tqdm` + `filelock` 八个三方包塞进冻结产物的关键路径。
  每多一个包，就多一个「只能出货后才发现」的失败面。

**修法（v3.0.1）**：

| 项 | 改法 |
|---|---|
| 下载通道 | 直接用 `urllib.request` 打 `<endpoint>/<repo>/resolve/main/<file>`，**零三方依赖** |
| 错误可读 | `ensure_model` 返回 `(目录, 错误码, 详情)`，详情是 `HTTP 503 xxx` / `URLError: ...` / `OSError: 磁盘已满` 这类真实原因，toast 原样带出 |
| 错误分类 | 网络失败 `download_failed`；本地写入失败单独 `disk_failed`（用户能据此判断该换盘还是换网） |
| 大文件 | `.part` 原子落盘 + `Range` 续传 + 卡顿 30s 超时 + 3 次重试；`416` 丢掉坏片段重来；服务端不认 Range 回 200 时从 0 重写 |
| 4xx 策略 | 除 408/429 外立刻收手，不让用户白等三次超时 |
| 诊断入口 | `--download-model [档位]`，在冻结产物里跑一遍真实下载 + `WhisperModel` 加载，报告写 `%TEMP%\qy_ai_check.txt` |

**为什么不用「修打包」这条路**：即使这次猜中了漏收的包，下次升级 `huggingface_hub`
又会换一茬依赖，而它能提供的能力（断点、重试、并发）我们用得上、且 60 行就能自己写。
**依赖越少，冻结产物越可预测。**

**测试换来的真 bug**：写 `test_416_discards_bad_part` 时发现 `download_file` 把 416
当成普通 4xx 直接判死 —— 坏片段明明已经删了却没重试。已修。这条正好说明：
错误分类写成产品行为之后，**必须有测试钉住**，否则「分类」只是注释。

### 40.18 v3.0.2 事故复盘：批量对齐窗口关不掉（2026-10-31）

**现象**：批量 AI 对齐跑到「第 1 / 6 首」时，用户点「关闭」没反应；再看「停止」是灰的。
进度条停在 0%。整个窗口成了一条死路。

**拆开看是三个问题叠在一起，全部是设计缺陷，不是偶发**：

1. `_on_stop` 只翻了个 `self._stop` 标志位、顺手把按钮置灰，**从没调
   `worker.requestInterruption()`** —— worker 该跑多久还跑多久。
2. `closeEvent` 无条件写「正在处理，先点「停止」再关闭」。可这时停止按钮已经被
   第 1 步灰掉了 —— **提示的是一条做不到的指令**，用户无路可走。
3. `transcribe()` 的分段循环里**没有任何中断检查点**，所以就算调了
   `requestInterruption()`，也要等整首歌推理跑完（几分钟）。

另外「0%」是误读：那根进度条统计的是**首数**（0/6），不是当前这首的推理进度。
用户看到 0% 自然会以为卡死了。

**修法（v3.0.2）**：

| 层 | 改法 |
|---|---|
| 推理 | `transcribe(..., interrupted=谓词)`：whisper 的 `segments` 是生成器，**每段问一次**，段粒度通常几秒 |
| 下载 | `download_file(..., interrupted=谓词)`：分块循环里检查，中断返回 `cancelled`，`.part` 留着下次续传 |
| 传导 | `align_track` / `ensure_model` 透传；`LyricsAsrWorker` 传 `self.isInterruptionRequested` |
| 语义 | 「停止」= 请求中止 + 留在窗口看结果；「关闭」/窗口 X = 请求中止 + **完成后自动关闭** |
| 线程回收 | `_retire()` 把 worker 移交 `_retired`，`wait(3000)` + `finished` 双保险；`closeEvent` 检查**所有**活线程，不止当前那个 |
| 文案 | 进度条改 `%v / %m 首`，不再用 0% 冒充推理进度 |
| 计数 | 用户主动中断不计入「失败」，汇总里不会出现「失败 1 首：已取消」 |

顺带修掉一个既有瑕疵：`align_track` 里 `detail=asr.detail or describe_error(asr.error)`
会让界面显示「没有识别到任何人声（没有识别到任何人声）」。现在只带 `asr.detail`。

**教训**：给用户提示一个动作之前，先确认那个动作在当前状态下**还能做**。这次是
「提示点停止」而停止已灰；上一版是「提示检查网络」而网络本来没坏。同一个病：
**提示是拍脑袋写的，不是根据真实状态生成的**。

**测试**：`TestInterruption` 4 例钉住下载/ensure_model/worker 传导/detail 不重复；
对话框新增 6 例钉住「关闭永远有出路」「中止不计失败」「进度条不是百分比」。

#### 40.18.1 真机验收又抓出两个（所以「自测通过」不等于「能用」）

在**真实歌曲**上跑一遍才发现的，单测和肉眼都没覆盖到：

| bug | 表现 | 根因 |
|---|---|---|
| 进度完全是死的 | 进度条永远 0%、没有任何阶段文字（用户截图里的样子） | `LyricsAsrWorker.progress` 声明成 `Signal(int, str)`，两个接收方（主窗口 / 批量对话框）都按 `(track_id, percent, stage)` 写 → **每次推送都抛 TypeError**；windowed 产物 `sys.stderr` 是 None，异常完全不可见 |
| 关闭后队列还在跑 | 中止完当前这首，下一首照常开始，永远收不了尾 | `_on_close_clicked` 只设了 `_close_when_done`，**忘了设 `_stop`** → `_on_failed` 照常 `_start_next` |

第二个尤其值得记：假 worker 是瞬时返回的，`_stop` 漏设**看不出来**；真机上一首 2 分钟，
问题才暴露成「窗口 240 秒都没关」。

**顺带修**：`_retire()` 里原来 `wait(3000)` 阻塞 UI。实测中止要等首段算完（60~90 秒），
3 秒必然超时，超时后 worker 仍在 `_retired` 里而没有任何东西再触发关闭 —— 等于把死路
推迟 3 秒。现在改成 `wait(0)` + `finished` 回调（跨线程自动排队到主线程）+
`_maybe_close()` 收口，全程不阻塞 UI。

**验收方法**：`tools/verify_abort_real.py` —— 用真实歌曲起批量，第 4 秒模拟点关闭，
断言 `QDialog.finished` 真的触发且无残留活线程。实测 10.2 秒完成中止并自动关窗。

注意这个脚本必须 `dialog.show()`：`QDialog::closeEvent` 在**不可见**时只 accept、
不触发 `finished`，我第一次验证时因此误判成「关不掉」。

**一个观察（🟡 未深究）**：上一轮 bug 状态下「中止后立刻接下一首」时，何者的匹配率
只有 34%（干净状态跑同一首是 69%、置信度同为 0.76）。怀疑与两个 `WhisperModel`
实例短暂共存有关。现在「关闭 = 停止整个队列」，该路径已不存在，暂不追。

### 40.19 v3.0.3 提高逐字对齐准确率（2026-11-01）

**需求**：减少 AI 逐字对齐误差、提高准确率。用户拍板范围：全都要（含换大模型/大 beam），
英文歌语言用「按汉字占比猜 + 手动指定」。

**误差源排序（读码定位）**：

| # | 误差源 | 为什么 |
|---|---|---|
| 1 | `_spread` 纯均分 | whisper 对中文常把 3~7 字并成一个 word，等分让「拖长音」和「快字」节奏一样 |
| 2 | `snap_to_energy` 只找 RMS 谷 | 谷是换气口/元音尾（句间边界），**字间边界在能量上升沿**（辅音/咬字起音） |
| 3 | `language="zh"` 写死 | 英文歌识别成中文乱码，匹配率 0、直接失败 |
| 4 | int8 + beam=5 | 词级时间戳精度上限 |

**修法（三块）**：

1. **P0 信号处理**（纯逻辑、零速度代价）：
   - 新增 `onset_envelope(rms, hop_ms, diff_ms)`：半波整流的短时能量增量，抓音节起音上升沿。
   - 新增 `snap_to_onset(...)`：字边界 ±120ms 内吸到 onset **峰**，与 RMS **谷**吸附互补；
     守卫 `best_val > 0` 让静音/稳态处不挪（留在谷里）。
   - `align_lyrics` 增 `onset` 参数；`align_track` 一次 `rms_fast` 后派生 onset 再喂给对齐。
   - 流水线变为：`_spread`（均分保底）→ `_fill_gaps` → `snap_to_energy`（谷）→
     `snap_to_onset`（峰）。找不到峰就保持均分，**保证不退步**。

2. **P1 语言**：
   - 新增 `guess_language(lines)`：CJK 汉字数 ≥ 拉丁字母数 → "zh"，否则 "en"，两者都 0 回退 "zh"。
   - `LyricsAsrWorker` 默认 `language="auto"`，`run()` 里解析成具体语种再喂 whisper（whisper 不吃 "auto"）。
   - 设置页新增「识别语言」下拉（auto/zh/en，`Settings.lyrics_ai_language`），
     右键「AI 对齐歌词（逐字）」改子菜单（自动/中文/英文）按首覆盖。

3. **P2 质量/大 beam**：
   - `transcribe`/`align_track` 增 `beam_size` 参数；`AI_QUALITY_BEAM = {fast:1, balanced:5, quality:10}`。
   - 设置页新增「识别质量」下拉（`Settings.lyrics_ai_quality`）；模型档位本就可换 tiny/base/small。

**为什么不用 whisper 自判语言**：中英混杂/粤语会误判，汉字占比是确定性的、可单测。

**量化口径（诚实）**：逐字无 ground truth，不能直接量「误差」。用合成包络单测钉「吸附后边界
比均分更接近已知起音点」；真实曲库靠匹配率/置信度/字均时长分布观察趋势（见遗留 E4）。

**验收**：`onset_envelope` / `snap_to_onset` / `guess_language` / onset 集成 / 语言信号 共 13 例新单测；
ruff 干净；全量回归（本轮见 TASK K）。

### 40.20 v3.0.4 收尾两条旧待办 + 建歌词匹配评测集（2026-11-01）

**背景**：任务清单里 #94（崩溃日志）、#98（扩展歌词搜索 + 平台与进度显示）从早期一直挂着。
核实后：**功能主体其实早就随 v2.7.5 / v2.6.x 落地了，只是没标完成**，真正缺的是收尾。

**#94 崩溃日志（功能不动，补测 + 修 bug）**
- 现状：`app/crashlog.py` 的 `install`/`install_qt`/日志轮转/线程钩子都在，`main.py` 已装、
  `store.py` 已接入。缺的是专门单测（原来只有 `test_store` 间接覆盖）。
- 新增 `tests/test_crashlog.py`（10 例）：日志写入/追加、写失败静默、超限轮转、
  **多次轮转最多保留 KEEP 份**、两处钩子安装、excepthook 落盘、thread_excepthook 忽略
  SystemExit、install_qt 可调用。
- **顺带修一个真 bug**：`_rotate` 从 `range(KEEP-1,0,-1)` 起挪，会多产生一份 `.KEEP`，
  实际留 KEEP+1 份（注释写「连当前共 3 份」）。改成 `range(KEEP-2,0,-1)`。测试抓出来的。

**#98 扩展歌词搜索（补最后一块：手动在线搜索多平台）**
- 现状：自动多源（LRCLIB/网易云/QQ）、`联网匹配 cur/total · 返回源名` 进度、`来源：xxx`
  显示**都已具备**。唯一缺口：右键「在线搜索歌词」只打开 lrclib.net，另两个平台没入口。
- 新增 `lyrics_multi.build_web_search_urls(title, artist)` / `web_search_url(platform, ...)`：
  按 `DEFAULT_SOURCES` 同一份清单生成各平台「给人看的」网页搜索地址（LRCLIB 复用
  `lyrics_online.build_web_search_url`，避免两处编码逻辑分叉）。
- 右键「在线搜索歌词」改成子菜单（LRCLIB / 网易云 / QQ音乐），信号带平台名。
- **不做**「再加酷狗当第 4 个自动源」：逆向无样本接口、易失效，风险 > 收益（明确取舍）。

**歌词匹配评测集（回应「准确率 90%+」需求的第一步）**
- 为什么先建：没有逐曲标注真值，「90%」无法验收。匹配逻辑 `pick_best` 是纯函数，
  用「query + 候选 + 期望」的**构造式黄金集**即可离线、可复现地量化。
- 新增 `tools/eval_match.py` + `tests/fixtures/lyrics_eval/cases.json`（14 条，覆盖
  中/英/日/韩 × 正版/同名不同曲/繁简/版次/feat./伴奏/纯音乐/跨语言专辑桥）。
- **基线（v3.0.4，构造集）**：用例 14｜应命中 12｜配 11 全对（误配 0）｜漏配 1
  → **precision 100% / recall 92% / 误配率 0%**。唯一漏配是「繁简差异（秘密/祕密）」。

**下一轮算法改进（有基线后逐项改、每步用 eval 量化）**
1. 归一化：NFKC + 繁→简高频映射（补繁简漏配）+ 去标点；
2. 相似度：difflib ratio + 分语言 token（中日韩字符 bigram / 拉丁词级）；
3. 权重重构：标题 > 艺人 > 时长 > 专辑（时长从与标题等价降到佐证级）+ 伴奏/翻唱负信号；
4. 跨源投票 + 置信分档：≥2 源一致提置信，low 不写盘（对齐「precision 优先」）。
- 依赖策略：标准库为主，运行时检测到 rapidfuzz 则用于增强（不硬依赖）。

### 40.21 v3.0.5 歌词匹配算法重构：归一化 / 分语言相似度 / 权重 / 置信分档（2026-11-01）

需求原文：「优化中文歌词匹配逻辑，准确率提升到 90% 以上，同时保证英/日/韩等
其他语言同等标准；说明算法、关键词权重、去噪与归一化、分语言适配策略。」

已确认的三项决策（用户拍板）：
- 依赖：**标准库为主，rapidfuzz 可选**（不装也能工作，装了只提速）；
- 验收口径：**precision 优先**（宁可配不到，也不配错词）；
- 顺序：**先建评测集再改**（v3.0.4 已完成，基线 recall 92%）。

#### 1. 为什么旧实现只有 92%

旧打分（v2.4~v3.0.4）的核心是 `_overlap(a, b, floor)`：**子串包含 + 长度比 ≥ floor**。
它只有「是/否」两档，于是有三类必然漏配：

| 场景 | 旧行为 | 根因 |
|---|---|---|
| 繁简差异（秘密/祕密） | 漏配 | 字符不同 → 无子串 → 0 分 |
| 候选标题带艺人前缀（`周杰伦 - 稻香`） | 漏配 | 2/6 = 0.33 < floor 0.5 |
| 候选带年份括号（`夜曲 (2005)`） | 漏配 | 纯数字括号不在噪声表里，变成噪声字符 |
| 错一个字（`夜空中最亮的星`/`夜空中最亮星`） | 漏配 | 无子串 → 0 分 |
| 短标题配长标题（`晴天`/`晴天娃娃`） | **误配** | 2/4 = 0.5 ≥ floor，判定为匹配 |

也就是说：**同一个「包含式」判据，一边漏掉真匹配，一边放进假匹配**。

#### 2. 三层结构（`app/lyrics_match.py`，新增）

把「文字怎么比」从「歌词怎么发请求」里彻底剥出来，纯函数、无网络、无 Qt。

**第一层 归一化**
```
NFKC          → 全角字母/兼容字符（Ｖｉｖａ→viva、①→1、ﬁ→fi）
NFKD + 去 Mn  → 拆变音符号（Beyoncé→Beyonce）
NFC           → 【必须】把韩文谚文重组回来
casefold      → 大小写
繁简归并      → 500 组高频字，多对一
去标点        → 只留字母数字
```
> **NFC 那一步是测试抓出来的 bug**：NFKD 会把 `봄` 拆成 `봄`（相容字母），
> 不重组的话韩文标题退化成字母串，bigram 全乱。

> **繁简表不需要「正确」**：匹配只关心两个变体是否落到**同一个**规范形，
> 不关心规范形是简体还是繁体。所以个别字映射方向写反也无害，这让表可以
> 只收高频字，不必引入 `opencc`（几十 MB）。`test_all_pairs_are_two_chars`
> 把表里打错的字（长度≠2）钉死在测试里。

**第二层 分词（分语言适配的核心）**

| 文字系统 | 切法 | 理由 |
|---|---|---|
| 汉字 / 假名 / 谚文 | 字符 **bigram**（单字退 unigram） | 没有空格，按词切要词典；bigram 无依赖且能吃到语序 |
| 拉丁 / 西里尔 | **词级** token | 按字符切会被长词淹没 |

`晴天` → `{晴天}`；`下雨天` → `{下雨, 雨天}` —— 交集为空。这就是
「单字歌名不该匹配到更长的歌」在算法上的来源，不再依赖 floor 这种魔数。

**第三层 相似度**
```
similarity(a,b) = max(字符级 SequenceMatcher.ratio(), token 级 Dice 系数)
```
取最大值而不是加权平均：标题这种短串，只要一条路认出「就是同一个」，
另一条路分数低并不构成反证。装了 rapidfuzz 就用
`Levenshtein.normalized_similarity`（同为 0~1、更快），**没装行为一致**。
`autojunk=False` 是硬要求：长串里重复字符多时默认去重会让比例失真。

**第四层 候选侧去装饰**（`prepare_title`）

查询侧和候选侧**都要**清洗，以前只洗查询侧：
- 噪声括号（含 live/伴奏/主题曲…）、纯数字括号（年份/版次）、前导音轨号、`feat.` 尾；
- **艺人前缀**：`周杰伦 - 稻香` → `稻香`；`稻香 - 周杰伦` → `稻香`；
  `打上花火 / DAOKO×米津玄師` → `打上花火`（斜杠只认两边带空格的，
  `AC/DC`、`Jay-Z` 里的连字符绝不切）。

#### 3. 关键词权重（标题 > 艺人 > 时长 > 专辑）

| 信号 | 档位（相似度） | 权重 |
|---|---|---|
| 标题 | ≥0.95 / ≥0.85 / ≥0.70 | **4.0 / 3.2 / 1.6** |
| 艺人 | ≥0.95 / ≥0.80 / ≥0.55 | 2.0 / 1.6 / 0.9 |
| 时长 | ≤2s / ≤5s / ≤10s | 2.5 / 1.6 / 0.6 |
| 专辑 | ≥0.95 / ≥0.80 | 1.2 / 0.8 |
| 同步稿 | 有可用时间轴 | +0.4 |
| 版次负信号 | 被删片段含伴奏/翻唱/live | **-0.4** |
| 翻唱负信号 | 标题对上、艺人时长双不符 | **-1.5** |

排序理由：标题是用户点开这首歌的理由；艺人是防「同名不同曲」的第二道闸；
时长是客观物理量但易受前奏/尾奏剪辑影响（本地与线上差 8~20s 很常见）；
专辑最脏（各种精选集），只作跨语言桥梁。

**版次负信号为什么要单独存在**：`晴天` 与 `晴天 (伴奏)` 清洗后完全一样，
身份信号打平、谁先出现谁赢。删噪声解决「搜得到」，负信号解决「选得对」，
两件事不能互相替代。它**只看被删掉的那部分**，所以 `Live and Let Die`
这种歌名里本来就含 live 的正常标题不会被误伤。

**跨书写系统豁免翻唱扣分**：`BTS` vs `방탄소년단` 做字符比对必然 0 分——
不是「不像」，是**无从比较**。不区分这两件事，跨语言的正确候选会被当成
「艺人对不上」而扣分，越认真越吃亏。`scripts_disjoint()` 负责判定。

#### 4. 置信分档 + 跨源投票

三档（`classify_confidence`）：

| 档位 | 条件 | 处置 |
|---|---|---|
| high | 标题强匹配 **且** 另有艺人或时长佐证 | 直接采用 |
| medium | 只有一条信号但够硬（标题强 / 时长精确+艺人相符 / 专辑+艺人双向） | 采用 |
| low | 只有弱标题（0.70~0.85）一项 | **默认拒收** |

`low` 那一档正是「晴天 → 晴天娃娃」「Pieces → Pieces of Me」的温床。
评测实测：`--allow-low` 放行后 precision 从 100% 掉到 95%（多 2 个误配）。

跨源投票（`lyrics_multi.pick_with_consensus`）：三源并行后按歌词正文指纹
（剥时间戳后取前 240 字归一化）比对，每多一个源给出同一份正文 +0.6，
**上限 1.2**。理由是单源命中有「某平台把同名不同曲排第一且勉强过关」的风险；
但投票只用来打破平局，不该盖过身份信号（一个源标题精确 vs 三个源标题全错，
仍选前者——有单测钉住）。

#### 5. 量化结果（同一份 45 例黄金集，新旧对照）

| 实现 | precision | recall | 误配 | 漏配 |
|---|---|---|---|---|
| v3.0.4（旧） | 88% | 86% | 4 | 5 |
| **v3.0.5（新）** | **100%** | **100%** | **0** | **0** |

修好的 9 例：繁简差异、繁简+时长漂移、艺人前缀+时长漂移、年份括号+时长漂移、
标题漏一个字、`Alone`/`Alone Again`（旧误配）、`晴天`/`晴天娃娃`（旧误配）、
`Pieces`/`Pieces of Me`（旧误配）、`Rise`/`Rise Up`（旧误配）。

**黄金集的自我校准**：v3.0.4 那 14 例里旧实现能过 13 例——因为大多数用例
时长与本地完全一致，「时长差 ≤2s」一条就把结果兜住了，标题写得再烂也能过。
所以 v3.0.5 专门加了「硬题·」前缀的一批：**时长漂移 8~20s、无专辑可依**，
只有标题/艺人信号能定胜负。这才是真正有区分度的题。

#### 6. 风险与已知局限

- 45 例构造集仍然偏小、偏乐观；**真实曲库的 precision 未验证**（与 v3.0.4 同一遗留）。
  下一步该做的是从真实曲库抽样 50~100 首人工标注，作为增量回归集。
- 跨书写系统的**罗马字/译文**标题（`Lemon` vs `レモン`、`Spring Day` vs `봄날`）
  无论怎么归一都对不上，只能靠艺人+时长兜；两者都没有时**会漏配**（按 precision
  优先的决策，这是有意为之，不是 bug）。
- `rapidfuzz` 当前环境**未安装**，走的是标准库路径；实测 60 个候选 `pick_best`
  5.6 ms/次（单次联网超时 4.5 s），匹配耗时完全不是瓶颈，所以没装也不追。
- 权重是手工定的，没有做网格搜索——因为没有足够大的标注集，搜出来的
  数字只会过拟合这 45 例。

### 40.22 v3.0.8 移除右键「在线搜索歌词（去网页找）」（2026-11-01）

**需求**：用户看图点名「这个功能不要了」。需求本身没有争议——自动三源（LRCLIB /
网易云 / QQ音乐）已经覆盖「本地没有歌词」的绝大多数情况，还搜不到的歌，让它跳到
浏览器让用户自己找 .lrc 再回来「导入歌词文件」，是把播放器的活推给用户。

**决策：彻底删，不留死代码**。牵连四层，全部清掉：

| 层 | 位置 | 删除内容 |
|----|------|----------|
| UI 菜单 | `ui/lyrics_panel.py` | `search_online_requested` 信号、平台子菜单构造 |
| 主窗口 | `ui/main_window.py` | 信号连接、`_open_lyrics_search()` 槽、`web_search_url` import |
| 业务层 | `app/lyrics_multi.py` | `WEB_SEARCH_TEMPLATES`、`build_web_search_urls()`、`web_search_url()` |
| 单源工具 | `app/lyrics_online.py` | `build_web_search_url()` |
| 测试 | 3 个文件 | 9 例（`test_widgets` 1 + `test_lyrics_multi` 5 + `test_lyrics_online` 3） |

**为什么连 URL 构造函数一起删**（而不是只删菜单项）：

1. 三个函数**除了这条菜单没有任何其他调用方**（grep 全库确认），留着就是死代码，
   将来接手的人会以为「这功能还在，只是入口藏起来了」，白查一遍。
2. 测试会继续测没人调用的纯函数——看起来覆盖率很高，实际在守一座空城。
3. 联网匹配主链路完全不依赖它们：`lyrics_multi` 用的是 `fetch_best_hit` /
   `pick_with_consistency` 那条线，`urllib.parse` 在两个模块里都另有用途，
   不存在「删了出未使用 import」的连带问题（ruff 已确认）。

**保留的部分**：`DESIGN.md` / `TASK.md` / `overview_v3.0.4.md` 里的历史记录**不改**。
它们是决策流水账，记录「当时为什么这么做」；改写历史会让后来的人看不出这个功能
曾经存在、又为什么被拿掉。新决策追加在本节，与前文并存。

**风险预演**：唯一真实风险是外部脚本 import 了 `build_web_search_url`
（v2.6.4 起就是公开函数）。本项目没有对外 API 承诺，`tools/` 下也没有引用，
判定为可接受；真需要时从 git 历史（`git show 02461e9:app/lyrics_online.py`）取回即可。

**验证**：grep 全库确认代码侧零残留（只剩 md 历史档案）、ruff 全绿、受影响三模块
全绿、全量回归全绿、重新打包后冻结产物自证 `v3.0.8`。

### 41. v3.1.0 主题迁入背景页 + 扩到四套配色（2026-11-01）

**需求**：把「主题」从「外观」页挪到「背景」页统一管理，并新增两个纯色主题
（黑色-深色 / 白色-浅色），明确各主题的归类与命名，切换逻辑与原有保持一致。

#### 1. 先分清「挪位置」和「合并概念」

v2.8.3 曾把「主题」和「背景」**刻意拆开**：主题只管配色，背景只管底图，两者
正交，任何主题配任何背景。本次是**换位置**，不是回退那个决策 —— 选项已向用户
确认：「同页分两区，主题与背景仍正交」。

界面结构（背景页）：

```
配色主题   [深色系]  星夜 · 深色    曜石 · 纯黑
           [浅色系]  月白 · 浅色    珍珠 · 纯白
背景图案             星空            云海
类型 / 作用页面 / …
```

「归类」= 按明暗分深色系 / 浅色系两组（`THEME_GROUPS`），组名直接显示在界面上。

#### 2. 命名：意象名 + 明暗说明，拆成两个字段

| id | 意象名 `THEME_LABEL` | 明暗 `THEME_TONE` | 旧名 |
|----|--------------------|------------------|------|
| `columbina` | 星夜 | 深色 | 深色 |
| `obsidian` | 曜石 | 纯黑 | （新增） |
| `light` | 月白 | 浅色 | 浅色 |
| `pearl` | 珍珠 | 纯白 | （新增） |

界面用 `theme_caption()` 拼成「星夜 · 深色」。为什么不写死成一个字符串：浮动条
的 tooltip 只需要意象名（「切换到星夜主题」），塞进「· 深色」会变成「切换到星夜 ·
深色主题」，读着别扭。

**id 保持不变**（`columbina` / `light`），旧配置零迁移。

#### 3. 新配色的两条硬约束

新主题必须过 `tests/test_theme.py` 已有的质量门槛：所有字段 `#rrggbb`、
正文对比 ≥7:1、强调色在面板上 ≥3:1、强调色底上白字 ≥3:1。据此定值：

- **曜石** `BG=#0a0a0c`（不是 `#000000`）：纯 0 会让窗口边界、阴影、面板与窗口底
  的层次全部消失（对比 1.0），看着像没渲染完。留 2% 灰，肉眼仍是纯黑。
  强调色冰蓝 `#3585dc`（近黑面板上 4.9:1，白字压上去 3.8:1），不用紫是为了和
  「星夜」一眼分开。
- **珍珠** `BG=#ffffff`、`SURFACE=#fafafa`：面板与窗口底同色同样没有层次，必须
  差一档白。强调色石墨蓝 `#2f6fde`（白底 4.5:1，白字 4.7:1），比「月白」的陶土橙
  冷一档，两个浅色主题分得开。

#### 4. 切换逻辑：4 态循环，且刻意交替

`THEME_ORDER = ("columbina", "light", "obsidian", "pearl")` —— **深→浅→深→浅**，
不是「先两个深再两个浅」。浮动条那个按钮的历史语义就是「按一下明暗翻转」，分成
两段会出现连按两次还是一片深色，手感变了。分组展示是设置页的事
（`THEME_GROUPS`），与循环顺序无关。

图标暂时复用月亮/太阳（同色系内重复）：图标是装饰，真正的区分在 tooltip 与设置页
文案上。将来要画四个专属图标属于视觉优化，不影响功能。

#### 5. 风险与验证

| 风险 | 处理 |
|------|------|
| 旧配置读不出来 | id 不变，`Settings.from_dict` 无需改动 |
| 新配色读不清 | 过 `test_theme` 全部对比度门槛 |
| 单选搬页漏掉某个主题导致选不到 | 新增 `test_groups_cover_every_theme_exactly_once`（不漏不重） |
| 循环顺序退化成「深深浅浅」 | 新增 `test_order_alternates_dark_and_light` |
| 「纯黑/纯白」名不副实 | 新增 `test_pure_themes_are_actually_pure`（亮度 <0.02 / >0.97） |

---

### 42. v3.2.0 拖拽排序取代「上移/下移」，纯色主题归入「外观」页

> 两个需求同一轮落地：①「曜石/珍珠」两个纯色主题从「背景」页挪到「外观」页；
> ② 删掉右键「上移/下移」，改成任意列表拖拽排序 + 实时插入位置预览。

#### 1. 主题按「有没有装饰底纹」分页，不按明暗分页

v3.1.0 把四套配色都塞进了「背景」页。用户看过真实界面后要求把两个**纯色**主题
（曜石/珍珠）放到「外观」。这不是随手挪位置，背后有一条能站住的划分：

| 页 | 主题 | 共同点 |
|----|------|--------|
| 设置 → **外观** | 曜石 · 纯黑 / 珍珠 · 纯白 | 只换配色，**不含任何底纹**，和强调色、字号是同一类"看起来怎样" |
| 设置 → **背景** | 星夜 · 深色 / 月白 · 浅色 | 带装饰底纹（渐变/光雾），要和背景图案一起权衡才配得好看 |

明暗归类（`THEME_GROUPS` 的深色系/浅色系）**保留**，它承载的是"这一套是深还是浅"，
与摆放位置正交 —— 所以两页都用同一套渲染函数 `_add_theme_rows(root, bucket)`，
只是传入的 bucket 不同（`THEME_SOLID` / `THEME_PATTERNED`）。

#### 2. 单选跨页必须用 QButtonGroup，不能靠 parent 互斥

`QRadioButton` 的互斥是**按 parent 分组**的。四套单选分到两个页面控件下之后，
默认会各亮一个 —— 界面上同时显示两套配色被选中。修法：

- 四套单选**一次性建好**（顺序按 `THEME_GROUPS`），再分别 `addWidget` 进两页；
- 全部 `addButton` 进同一个 `QButtonGroup(self)`，由它跨页互斥。

「建好再分发」比"各页自己建"好处在状态只有一个来源：不存在两处不同步。
`test_theme_radios_exclusive_across_pages` 专门钉住这条，防止有人把它"优化"成各自建。

#### 3. 删「上移/下移」的理由：两条路径必然打架

原来右键菜单有「上移/下移」，歌单视图还能拖。两个入口操作同一个 `track_ids`，
但**拖拽是"整块搬到某个位置"，上移是"和邻居换一次"** —— 多选拖拽时前者搬的是一段，
后者只能挪一首，两种语义混在一起，用户没法预期。删掉按钮，只留拖拽。

#### 4. 拖拽的语义：存"看到的顺序"，不是"做一次 swap"

`_on_reordered(tids, new_index)` 收到的是**新位置**，但落盘用的是：

```python
ids = [t.id for t in self._displayed]   # 屏幕上这个列表，从前往后
picked = [tid for tid in tids if tid in ids]
for tid in picked: ids.remove(tid)
ids[new_index:new_index] = picked       # 整块插回去
store.set_view_order(view_id, ids)
```

为什么绕这一圈而不直接 `move(tid, new_index)`：拖动发生在用户眼前那个列表上，而它
可能正被「按艺人排序」重排过、也可能属于某个歌单。用户认定的"新顺序"就是屏幕上的
样子 —— 整份存下来，无论当前用哪种排序，结果都和眼睛看到的一致，也不用为每种视图
各写一套下标换算。

配套的三件事缺一不可：

1. **拖完自动切「自定义顺序」**（否则下次 `refresh_list()` 按原规则重排，表现就是
   「拖了弹回去」）。切的时候同步 `_sort_by_view`，离开再回来还是这个选择。
2. **落盘位置分两处**：歌单改 `Playlist.track_ids`（和 `move_in_playlist` 同一处，
   不另存一份）；音乐库/我喜欢 存 `Settings.view_orders`（`tracks` 字典的插入序
   不能动，动了会连带影响「最近导入」）。
3. **多选要整块报**：`reordered` 信号从 `(str, int)` 改成 `(list, int)`。原来只报
   `moved[0]`，拖一整段时上层只能看到第一首，落盘顺序和眼睛看到的差一截。

#### 5. 两种视图禁拖，理由都是"拖了立刻被覆盖"

| 视图 | 为什么不给拖 |
|------|------------|
| 最近播放 | 按播放时间动态排，放下后一刷新就变回原样 |
| 搜索中的任意列表 | 显示的是子集，按可见顺序落盘会把没显示的曲子挤到末尾 |

#### 6. 实时预览：自己画，因为原生指示线看不见

每行都是 `setItemWidget` 塞进去的自定义控件，Qt 原生的 drop indicator 画在行控件
**底下**，被完全盖住。所以 `_TrackListWidget` 自己来：

- `dragMoveEvent` 里 `indexAt(pos)` + 与行中线比较 → 插入位置（上半行插前、下半行插后，
  空白区=末尾）；
- `paintEvent` 里在目标行的上/下边缘画 2px 强调色横线 + 两端小圆点（一条光秃秃的线
  容易被当成行分隔线）；
- `setDropIndicatorShown(False)` 关掉原生那条，否则两条同时出现像有两个落点。

#### 7. 风险与验证

| 风险 | 处理 |
|------|------|
| 纯色主题挪走后界面选不到 | `test_pages_partition_every_theme_exactly_once`（不漏不重） |
| 跨页单选双亮 | `test_theme_radios_exclusive_across_pages` |
| 拖完弹回去 | `test_library_drag_switches_to_custom_and_saves` 断言 `_sort_id` 变 custom |
| 关软件丢顺序 | 同一例用新 `LibraryStore(data_file())` 复读验证 |
| 新导入的歌毁掉手排顺序 | `apply_manual_order` 把没记录的接到末尾（`test_new_tracks_go_last_...`） |
| 幽灵 id / 脏 JSON | `_as_view_orders` 逐条隔离 + 去重（`test_bad_view_orders_do_not_wipe_settings`） |
| 一次拖拽弄丢歌单里没显示的曲子 | `set_view_order` 用 `rest` 兜住（`test_playlist_order_keeps_tracks_missing_from_display`） |
| 自绘插入线画崩 | `test_paint_with_drop_row_does_not_crash` 逐个位置 `grab()` |

---

### 43. v3.2.1 移除「放大当前行」：放大是默认行为，不是选项

**需求**：删掉动效下拉里的「放大当前行」，改为当前播放行始终自动放大。

#### 判定：这是「把一个选项降级为默认」，不是「删功能」

用户要的从来不是"能不能放大"，而是"歌词好看好读"。把放大做成四个选项之一，
代价是**默认体验次优**：不选它的用户一直在看小字号当前行，还得先发现、再选一遍。

所以做法不是简单删一项，而是：

1. `LYRICS_EFFECTS` 从 4 个减到 3 个（none / typewriter / karaoke）；
2. 当前行字号增量**无条件生效**，取原来 zoom 的 `+6`（不是 none 的 `+3`）——
   既然要替掉那个选项，效果就得和它一样；
3. `_line_delta(is_current)` 的签名里**故意没有 effect**：从结构上保证没人能再让它
   依赖动效（旧代码就是 `_ZOOM_DELTA if effect == "zoom" else _NORMAL_DELTA`）。

#### 兼容

老配置 `lyrics_effect="zoom"` 读出来会落到 `"none"`（`Settings.from_dict` 按
`LYRICS_EFFECTS` 收敛），表现正好等于「只是放大」这一默认行为 —— 用户不会看到
效果变化，也不会丢别的设置。`set_effect("zoom")` 同样安静回退，不抛异常。

#### 为什么要专门写一条防回归测试

`test_zoom_is_not_an_option_anymore` 同时在两处断言「没有 zoom」：`LYRICS_EFFECTS`
（数据层）与 `LYRICS_EFFECT_OPTIONS` 的文案里不含「放大」（界面层）。
理由：这类"加回去更灵活"的改动看起来无害，但会把默认体验重新做差一次。

---

### 44. v3.3.0 动态背景（跟随音乐能量）（2026-11-03）

#### 为什么是「实时」而不是视频

参考 [852wa/JIZURA](https://github.com/852wa/JIZURA) 之后确认过一件事：它产出的是
**独立成片**（文字即画面主体），而播放器要的是**背景**——一层实时渲染、压在歌词
后面、不能盖住可读性的东西。用视频当背景的流程是「先在浏览器渲染整首 → 存成素材 →
再播放」，换一首歌就没有素材了，实时性完全是假的。所以这条路从一开始就排除。

#### 先量再画

这类功能最常见的翻车方式不是画得难看，而是**把播放拖卡**。所以先写
`tools/probe_live_bg.py`，画一帧「比实际更重」的典型内容（渐变 + 160 粒子 + 48 段
环形条 + 暗角）并计时：

| 方案 | 平均 | 最差 | 占 33ms 预算 |
|---|---|---|---|
| 全分辨率 1280×760 | 5.18ms | 12.14ms | 15.6% |
| 半分辨率 + 平滑放大 | 5.52ms | 8.79ms | 16.6% |
| 三分一 + 平滑放大 | 4.62ms | 6.73ms | 13.9% |

**结论：全分辨率就够，不要降采样** —— 半分辨率画得快一点，但平滑放大的开销把它
全吃掉了，还额外引入一次模糊。这个反直觉的数字必须实测，凭感觉会做错方向。

#### 能量从哪来

Qt 6 没有 PCM/频谱回调（QAudioProbe 已废弃），所以不是"实时取音量"，而是
**离线解码成包络 + 播放时查表**：

```
解码 8kHz mono（miniaudio，约 1.2ms/秒音频）
  → 50ms 一档的 RMS（20Hz）
  → 95 分位归一化 + 0.65 次幂做感知补偿 + 三点平滑
  → <track_id>.json 落盘（带 size:mtime 指纹）
播放时：energy_at(envelope, position_ms) 线性插值
```

三个选择值得记：
1. **归一化用 95 分位不用最大值**。流行歌里常有一两个特别响的爆点，用最大值当分母
   会把其余部分压成一条平线，背景看起来「不动」——那正是这个功能最容易被误判成坏了。
2. **平滑必须有**。压缩音频的块边界会让包络每 26ms 抖一下，画到背景上像接触不良。
3. **查表的开销是零**：一次下标 + 一次插值，跟逐帧取频谱差两三个数量级。

#### 与背景配置的关系

`BackgroundConfig.type` 增加第五种 `live`，风格 id 存在 `preset` 里 —— 复用现有字段
而不是新造一套配置，好处是「一次只有一种背景」这个约束天然成立（本来就只有一个
`type`）。选动态背景会和静态图案互斥，这是有意的：背景只有一层，叠加必然打架。

**踩过的坑**：`_on_bg_type_changed` 里原本有「离开 image 就清空 preset」的逻辑，
直接沿用会把动态背景的风格 id 一起抹掉（表现是选哪个都变成第一个）。必须按类型分支。

#### 可读性

这类功能做砸的方式是「很好看，但字看不清」。三层保障：
1. 所有图元 alpha 很低（最高 90/255），只做氛围；
2. 动态背景额外画一层**专用暗角**（`paint_live_scrim`，中间留空、四周压暗）——
   有它才敢让动画铺满整窗；静态背景不加，免得改动老观感；
3. 面板本来就是半透明的（`build_stylesheet(scrim=...)`），会再压一层。

#### 两处几何修正（出图后才发现）

单元测试只能证明「画出来了、能量有影响」，证明不了「好看」。所以把四套风格各渲一张
640×400 样张逐一看，抓到两个问题：
- **音频环被裁**：半径 0.40 × (1 + 最长柱 0.31) = 0.53 > 0.5，顶部柱子直接切平。
  改 0.33 后 × 1.31 = 0.43，留 7% 余量。
- **极光是硬边色块 + 自交楔形**：实心填充读起来像色板不像极光。改成「闭合路径 +
  纵向渐变（透明→有色→透明）」，并把三条带中心压到 0.24/0.50/0.76、厚度上限 0.31h，
  保证不出画。顺带修了闭包晚绑定（`ruff B023`）——不修的话三条带会共用最后一轮的
  相位，变成完全同步的三条平行带。

#### 生命周期

- 计时器只在「type == live 且控件可见」时跑；`hide()` 立即停。
- 播放 30fps、暂停 10fps：暂停时动作还在，CPU 掉到 1/3。
- 能量线程是 `QThread`，**只在真的选了动态背景时**才启动（否则白解码整首歌）。
- 关窗/切歌都 `requestInterruption()` + `wait(3000)`；算完时若已切歌则**丢弃结果**
  （否则会拿上一首的节奏驱动下一首的画面）。
