# -*- coding: utf-8 -*-
"""打 GitHub Release 发布包。

前置：先跑过 `build.py`（它产出 `dist/QingYinPlayer.exe` 与
`dist/QingYinPlayer-Portable/`）。本脚本只做"把成品装进 zip"，不重新构建。

产出到 `dist/release/`：

- `QingYinPlayer-vX.Y.Z-win64-onefile.zip`  单文件版（一个 exe，双击即用）
- `QingYinPlayer-vX.Y.Z-win64-onedir.zip`   目录版（启动快，整文件夹解压）
- `RELEASE_NOTES.md`                        从 `docs/releases/vX.Y.Z.md` 取，供粘贴

两个 zip 里都附 `README.md` / `LICENSE` / `CHANGELOG.md`，离线解压也有说明可看。

为什么 exe 只能当 Release 附件：GitHub 对**入库单文件**有 100MB 硬上限，而单文件版
exe 约 120MB，推不上去；Release 附件上限 2GB，放这里正合适。所以 `.gitignore`
把 `dist/` 整个排掉，发布物靠本脚本现做。

用法：
    python tools/make_release.py            # 打两个包
    python tools/make_release.py --onefile  # 只打单文件版（省时间）
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.version import APP_NAME, APP_VERSION  # noqa: E402

DIST = ROOT / "dist"
OUT = DIST / "release"
ONEFILE = DIST / "QingYinPlayer.exe"
ONEDIR = DIST / "QingYinPlayer-Portable"
# 顺手塞进包里的文本：解压后离线也能看懂怎么用、什么许可
DOCS = ("README.md", "LICENSE", "CHANGELOG.md")
# 目录版里那个 exe 的旧名字，改名成与单文件版一致，用户看到的名字统一
ONEDIR_EXE = "QingYinPlayer-Portable.exe"
ONEDIR_EXE_NEW = "QingYinPlayer.exe"


def _human(size: int) -> str:
    mb = size / (1024 * 1024)
    return f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"


def _sha256(path: Path) -> str:
    """流式算哈希：两个包都上百 MB，一次性读进内存不值得。"""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_inputs(need_onedir: bool) -> None:
    """构建产物缺失/过期时提前报错，别打出半成品包。

    「过期」判据用 mtime 对比 `app/version.py`：改了代码却没重新 build，
    打出来的包版本号对不上，是最容易发错的一种事故。
    """
    if not ONEFILE.is_file():
        raise SystemExit(f"缺少 {ONEFILE}，先跑 build.py")
    if need_onedir and not (ONEDIR / ONEDIR_EXE).is_file():
        raise SystemExit(f"缺少 {ONEDIR / ONEDIR_EXE}，先跑 build.py")

    artifacts = [ONEFILE] + ([ONEDIR / ONEDIR_EXE] if need_onedir else [])
    version_mtime = (ROOT / "app" / "version.py").stat().st_mtime
    if max(p.stat().st_mtime for p in artifacts) < version_mtime:
        print("⚠ 构建产物比 app/version.py 旧，可能不是当前版本；建议重跑 build.py")


def _add_docs(zf: zipfile.ZipFile) -> None:
    for name in DOCS:
        path = ROOT / name
        if path.is_file():
            zf.write(path, f"轻音播放器/{name}")


def _build_onefile() -> Path:
    target = OUT / f"QingYinPlayer-v{APP_VERSION}-win64-onefile.zip"
    print(f"打包单文件版 → {target.name}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as zf:
        zf.write(ONEFILE, f"轻音播放器/{ONEFILE.name}")
        _add_docs(zf)
    return target


def _build_onedir() -> Path:
    target = OUT / f"QingYinPlayer-v{APP_VERSION}-win64-onedir.zip"
    print(f"打包目录版 → {target.name}（{len(list(ONEDIR.rglob('*')))} 个条目，稍慢）")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                         allowZip64=True) as zf:
        for path in sorted(ONEDIR.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(ONEDIR)
            # 目录版 exe 改名：用户在两个包里看到的启动文件名保持一致
            arcname = Path("轻音播放器") / (
                Path(ONEDIR_EXE_NEW) if rel.as_posix() == ONEDIR_EXE else rel)
            zf.write(path, arcname.as_posix())
        _add_docs(zf)
    return target


def _write_notes() -> Path | None:
    """把 docs/releases/vX.Y.Z.md 复制成 RELEASE_NOTES.md，方便直接粘到 GitHub。"""
    source = ROOT / "docs" / "releases" / f"v{APP_VERSION}.md"
    if not source.is_file():
        return None
    target = OUT / "RELEASE_NOTES.md"
    shutil.copyfile(source, target)
    return target


def main(argv: list[str]) -> int:
    only_onefile = "--onefile" in argv
    OUT.mkdir(parents=True, exist_ok=True)

    _check_inputs(need_onedir=not only_onefile)

    built: list[Path] = [_build_onefile()]
    if not only_onefile:
        built.append(_build_onedir())
    notes = _write_notes()

    print(f"\n{APP_NAME} v{APP_VERSION} 发布包：")
    for path in built:
        size = path.stat().st_size
        print(f"  {path.name}")
        print(f"    大小   {_human(size)}")
        print(f"    SHA256 {_sha256(path)}")
    if notes is not None:
        print(f"  发布说明 {notes.name}（可整段粘到 GitHub Release）")
    else:
        print(f"  ⚠ 没找到 docs/releases/v{APP_VERSION}.md，发布说明需自己写")

    print(f"\n全部产出在 {OUT}")
    print("上传步骤：GitHub → Releases → Draft a new release → 填 tag "
          f"v{APP_VERSION} → 拖入上面两个 zip → 粘贴发布说明 → Publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
