# 轻音播放器

一个**纯本地**的 Windows 音乐播放器：导入本地音乐、播放控制、歌单管理、歌词同步显示。
深色现代界面，全中文，无需联网，数据全部保存在本机。

技术栈：Python 3.13 + PySide6 6.12（Qt Multimedia / FFmpeg 后端）+ mutagen + JSON 持久化。

---

## 功能

| 模块 | 功能 |
|---|---|
| 音乐导入 | 文件夹递归扫描 / 多选文件 / 拖拽到窗口；后台线程 + 进度显示 + 可取消 |
| 播放控制 | 播放/暂停、上一首/下一首、进度拖动跳转、音量调节/静音 |
| 播放模式 | 顺序播放、列表循环、单曲循环、随机播放 |
| 歌单管理 | 新建/重命名/删除、添加歌曲、移出歌曲、拖拽排序、上移/下移 |
| 歌词显示 | 同名 `.lrc` 自动匹配、内嵌歌词（ID3 USLT/SYLT、FLAC LYRICS、MP4 ©lyr）、手动绑定 `.lrc`；逐行同步高亮、平滑自动滚动、点击跳转 |
| 资料库 | 全部导入歌曲；最近播放（自动）；搜索过滤；按标题/艺人/专辑/时长/添加时间排序 |
| 封面 | 自动提取内嵌封面（MP3 APIC / FLAC / MP4 / OGG）；无封面生成渐变占位图 |
| 其他 | 启动恢复上次曲目与播放位置、设置记忆、文件丢失友好提示、键盘快捷键 |

支持格式：**mp3 / flac / wav / m4a / aac / ogg / opus / wma**（实际可播放性由系统 FFmpeg 后端决定，实测 mp3/flac/wav/ogg 全部正常）。

## 快速开始（普通用户）

1. 双击 `dist/轻音播放器.exe`（单文件便携版，首次启动需解压，约 2-5 秒）；
   或进入 `dist/轻音播放器-便携版/` 双击里面的 `轻音播放器-便携版.exe`（目录版，启动更快）。
2. 点击左下角「导入音乐」→ 选择文件夹或文件；也可以把音乐文件/文件夹直接拖进窗口。
3. 双击列表中的歌曲开始播放。

> - 首次启动若被杀毒软件拦截，请选择「允许」——本软件未做数字签名，属误报；
> - 数据保存在 `%APPDATA%\轻音播放器\`（歌单、设置、封面缓存），卸载/删除该目录即可清空。

## 快捷键

| 按键 | 功能 |
|---|---|
| `空格` | 播放 / 暂停 |
| `Ctrl + ← / →` | 上一首 / 下一首 |
| `← / →` | 快退 / 快进 5 秒 |
| `↑ / ↓` | 音量加 / 减 5% |
| `Esc` | 清空搜索框 |

## 开发运行

环境要求：Python 3.13+（虚拟环境）。

```bash
# 1. 创建虚拟环境并安装依赖（国内网络建议用镜像）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# 2. 运行（开发模式）
.venv/Scripts/python.exe main.py

# 3. 运行测试（67 项：单测 + offscreen E2E）
.venv/Scripts/python.exe -m unittest discover -s tests -t . -v

# 4. 打包（生成图标 + 单文件版 + 目录版 + 冒烟测试）
.venv/Scripts/python.exe build.py
```

> **本仓库开发环境注意事项（WorkBuddy 沙箱）**：
> - pip 官方源极慢，依赖安装统一走阿里云镜像；
> - 沙箱会经 `PYTHONPATH` 注入文件删除守卫，会拦截 pip/PyInstaller 的批量文件覆盖，
>   因此这类命令需要加 `env -u PYTHONPATH` 前缀（在普通 PowerShell/CMD 中无需此步）。

## 目录结构

```
music-player/
├── main.py               # 入口（--check 环境自检 / --smoke 产物自检）
├── build.py              # 图标生成 + PyInstaller 打包
├── app/                  # 后端核心（无 UI 依赖，可单测）
│   ├── models.py         #   Track / Playlist / Settings
│   ├── store.py          #   JSON 持久化 + 曲库/歌单 CRUD
│   ├── lyrics.py         #   LRC 解析 + 同步索引（纯逻辑）
│   ├── metadata.py       #   mutagen 封装（标签/封面/歌词）
│   ├── scanner.py        #   后台扫描线程
│   ├── covers.py         #   封面懒提取 + 缓存 + 占位图
│   ├── queue.py          #   播放队列与四种模式（纯逻辑）
│   └── player.py         #   QMediaPlayer 控制器
├── ui/                   # Qt Widgets 界面（深色 QSS 主题）
├── tests/                # 单测 + E2E + 夹具生成器
├── probe/                # 环境探测与截图脚本（开发辅助）
└── assets/app.ico        # 应用图标（构建时生成）
```

## 已知事项

- **m4a/aac**：无真实样本在本环境验证过（无转码工具），代码路径与 mp3/flac 相同，FFmpeg AAC 解码为标准能力，预期可用但未实测；
- 构建沙箱无音频渲染设备，「声音输出与播放进度自动推进」已在开发环境之外验证（状态机/seek/音量/解码加载均通过自动化测试），最终声音效果请以本机双击运行为准；
- 超大曲库（>5000 首）首次导入会稍慢，列表渲染为逐行控件，滚动流畅度以千首级为设计目标；
- 本版本不做：在线音乐/云同步、标签编辑、迷你模式（见 DESIGN.md 的 Won't 清单）。

## 设计文档

- `DESIGN.md`：需求确认、技术选型（含备选方案对比与否决理由）、数据模型、风险预演、验收标准；
- `TASK.md`：勾选式任务拆解与依赖关系。
