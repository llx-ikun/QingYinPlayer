# v3.0.1 交付说明 —— 修「AI 模型下载失败」

## 一句话结论

v3.0.0 的 AI 模型下载把「4 个静态文件」这条路绑在了 8 个三方包上，还在失败时把真实
异常吞成了一句「检查网络」。v3.0.1 换成标准库直连下载，**错误码能区分「网络」和
「磁盘」，失败时把真实原因原样打给用户**。

## 用户看到的现象

设置页选好档位 → 点 AI 对齐 → 弹「AI 对齐失败：AI 模型下载失败（检查网络）」。
开发环境同样代码能下完（tiny 75MB / 54 秒），差别只在冻结产物。

## 定位（拿证据，不猜）

| 查了什么 | 结果 | 能排除什么 |
|---|---|---|
| 用户 `models/small/` 目录 | 只有一个 4KB 的 `.cache/huggingface/trees/*.json`，模型文件一个没有 | 网络/DNS/TLS 是通的，**元数据请求成功了** |
| 那份 json 内容 | `model.bin` = 483,546,902 字节，带 `xet_hash` | 该仓库走 Xet 存储，大文件通道与元数据不同 |
| C 盘剩余空间 | 43G | 不是磁盘满 |
| PyInstaller `warn-*.txt` | `httpx2` / `httpcore2` / `anyio` 均已被分析收进；`sniffio` 缺失在 venv 里同样缺失（anyio 有兜底） | **不是漏收模块** |

结论：`snapshot_download` 这条链在「大文件 + 国内镜像 + 冻结产物」三件事叠加下不可靠，
且它把自己的异常包得看不出根因。

## 改了什么

| 文件 | 改动 |
|---|---|
| `app/lyrics_asr.py` | 重写模型下载：`urllib` 直连 `<endpoint>/<repo>/resolve/main/<file>`；`ensure_model` 返回 `(目录, 错误码, 详情)` |
| `app/lyrics_asr.py` | 新增 `download_file()` / `_fetch_once()`：`.part` 原子落盘、Range 续传、30 秒卡顿超时、3 次重试、`416` 丢掉坏片段重来 |
| `app/lyrics_asr.py` | 错误码拆分：网络 → `download_failed`，本地写入 → `disk_failed`；4xx 除 408/429 立刻收手 |
| `app/lyrics_asr.py` | `LyricsAsrWorker` 把详情拼进失败提示，不再只显示「检查网络」 |
| `main.py` | 新增 `--download-model [档位]`：下载 + `WhisperModel` 加载，报告写 `%TEMP%\qy_ai_check.txt` |
| `app/version.py` | 3.0.0 → 3.0.1 |
| `tests/test_lyrics_asr.py` | 新增 16 例下载器/ensure_model 单测 |
| `tests/test_build.py` | 新增 4 例 `--download-model` 单测 |
| `DESIGN.md` / `TASK.md` | 40.17 事故复盘 + F/G 章节 |

## 关键取舍

**为什么不修打包，而是换掉 huggingface_hub。** 即使这次猜中了漏收的包，下次升级
`huggingface_hub` 又会换一茬依赖。我们要的只是 4 个静态文件——断点、重试、超时这
60 行自己写得起，而依赖越少，冻结产物越可预测。

## 测试换来的真 bug

写 `test_416_discards_bad_part` 时发现：坏片段已经删掉了，`download_file` 却把 416
当普通 4xx 直接判死。已修。这也说明「错误分类」一旦写成产品行为，就必须有测试钉住。

## 验证

- ✅ ruff `All checks passed!`
- ✅ 全量回归 **34 模块 / 767 用例全绿**，16m52s
- ✅ 开发环境 `--download-model tiny` 端到端：下载 → 就绪 → `WhisperModel` 加载 OK
- ✅ **冻结产物在全新数据目录里跑 `--download-model tiny`**：从零下完 75MB，加载 OK
- ✅ 冻结产物跑 `--check-ai`（small 档 + 夹具音频）：import / 解码 / 推理全 OK
- ✅ 重打包：onefile 122.8MB / onedir 11.5MB，双 smoke + 真实平台 8s 通过
- ✅ 真实数据目录里 `small`（461MB）**3 分 35 秒下完**，四个文件字节数与仓库完全一致

## 对用户的操作建议

模型档位不用改。新版第一次点 AI 对齐会自动把模型下到
`%APPDATA%\轻音播放器\models\<档位>\`；`small` 约 461MB，下载支持断点续传，
中途断网重试会接着下、不从头来。
