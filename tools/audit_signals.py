"""静态审计：Signal 定义与 emit 调用参数个数是否一致。

背景（v2.7.2 事故）：`_on_online_lyrics_progress` 的槽比信号多一个参数，
每次 emit 都抛 TypeError，进度文案整整一个版本没显示过，而界面上只是
"什么都没发生"，没人发现。

策略：
  1. 全项目收集 `name = Signal(A, B, ...)` → 名字 → 参数个数
  2. 全项目收集 `.emit(a, b, ...)`    → 名字 → [(文件, 行, 实参个数)]
  3. 只在"该信号名全项目只有一个定义"且"没有 *args / 关键字参数"时比对
     —— 信号可能定义在 Qt 自带的基类里，此时定义不可见，跳过不报。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/audit_signals.py
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "dist", "build", "node_modules", "__pycache__", ".git"}


def iter_py_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def count_signal_args(call: ast.Call) -> int | None:
    """Signal(int, str) → 2；含 *args 展开时返回 None（无法静态确定）。"""
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            return None
    return len(call.args)


def main() -> int:
    defs: dict[str, list[tuple[str, int, int]]] = defaultdict(list)   # name -> [(file, line, n)]
    emits: dict[str, list[tuple[str, int, int]]] = defaultdict(list)  # name -> [(file, line, n)]
    dynamic_emits: list[tuple[str, int, str]] = []

    for path in iter_py_files(ROOT):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            # 定义：xxx = Signal(...)
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                value = node.value
                if (
                    isinstance(target, ast.Name)
                    and isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "Signal"
                ):
                    n = count_signal_args(value)
                    defs[target.id].append((rel, node.lineno, -1 if n is None else n))
            # 调用：obj.xxx.emit(...)
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "emit"
                    and isinstance(func.value, ast.Attribute)
                ):
                    name = func.value.attr
                    if any(isinstance(a, ast.Starred) for a in node.args) or node.keywords:
                        dynamic_emits.append((rel, node.lineno, name))
                        continue
                    emits[name].append((rel, node.lineno, len(node.args)))

    problems = 0
    checked = 0
    for name, def_list in sorted(defs.items()):
        if len(def_list) != 1:
            continue                      # 同名多处定义，无法可靠归属
        d_file, d_line, d_n = def_list[0]
        if d_n < 0:
            continue                      # Signal(*args) 之类，跳过
        for e_file, e_line, e_n in emits.get(name, []):
            checked += 1
            if e_n != d_n:
                problems += 1
                print(
                    f"MISMATCH  {name}: 定义为 {d_n} 参（{d_file}:{d_line}）"
                    f" 但 {e_file}:{e_line} emit 了 {e_n} 个"
                )

    if dynamic_emits:
        print("\n[跳过的动态 emit —— 需人工确认]")
        for rel, line, name in dynamic_emits:
            print(f"  {rel}:{line}  {name}.emit(*args / **kwargs)")

    print(f"\n比对 {checked} 处 emit，定义可确定的信号 {len(defs)} 个；不一致 {problems} 处")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
