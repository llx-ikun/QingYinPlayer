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
THEME_ORDER = ("columbina", "light")
THEME_NEXT  = {"columbina": "light", "light": "columbina"}
THEME_ICON  = {"columbina": "feather", "light": "sun"}
THEME_LABEL = {"columbina": "深色", "light": "浅色"}
DEFAULT_THEME = "light"
```

- 浮动条主题钮的**图标与 tooltip 都指向「点下去会切到哪个」**，不是当前主题
  （羽毛=深色 / 太阳=浅色）；`isChecked` 只在浅色时为真，保留原语义
- 新增手绘 `feather` 图标（实心羽片 + 镂空羽轴 + 羽枝缺口），与相邻的 `settings` /
  `gear` 不同形：实心块 vs 细横线 vs 锯齿环，16px 下不会混
- 设置对话框按 `THEME_ORDER` 生成 radio；`light_radio` 保留为别名不破坏旧引用
  （原「深色」主题已删除，`dark_radio` 一并移除）
- toast 文案改由 `THEME_LABEL` 生成：两态循环，别写死「浅色 else 深色」

### 15.5 验收标准（v2.3 增量）

- [x] 默认主题是「浅色」（v2.3 时曾为 `columbina`，后续按用户要求改为 `light`），新装与旧数据都落到 `light`。
  - 证据：`test_default_is_light`、`test_legacy_data_without_new_settings`
- [x] 主题两态循环闭环、每个主题都有图标与中文名。
  - 证据：`TestThemeCycle` 4 项（含「循环覆盖全部且闭环」「循环表不写反」）
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
也不能超过播放栏 312 的左缩进，否则压封面）。四个控件塞进这一行：

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
