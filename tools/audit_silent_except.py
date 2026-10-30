"""静态审计：找出「静默吞异常」的位置。

判定口径（只报高风险，不刷噪音）：
  A. 裸 except（`except:`）—— 连 KeyboardInterrupt / SystemExit 都吞
  B. handler body 只含 pass / continue / ...（真·什么都没做）
  C. handler body 里没有 raise / return / log / print / emit / 赋值给非局部状态

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/audit_silent_except.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", "dist", "build", "node_modules", "__pycache__", ".git", "tests"}


def iter_py_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def is_noop(node: ast.stmt) -> bool:
    """handler 里的这条语句是否等于「什么都没做」。"""
    if isinstance(node, ast.Pass):
        return True
    if isinstance(node, ast.Continue):
        return True
    if isinstance(node, ast.Break):
        return True
    # 裸字符串 / docstring / ...
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)


def mentions_side_effect(nodes: list[ast.stmt]) -> bool:
    """handler 里是否出现过任何有副作用的动作。"""
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.Raise, ast.Return, ast.Yield, ast.YieldFrom)):
                return True
            if isinstance(child, ast.Call):
                func = child.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in {
                    "warning", "warn", "error", "critical", "exception",
                    "debug", "info", "print", "emit", "write",
                }:
                    return True
            if isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                # 赋值给 self.xxx / 全局名，视为记下了状态
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for t in targets:
                    if isinstance(t, ast.Attribute):
                        return True
    return False


def audit(path: Path) -> list[tuple[int, str, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [(0, "READ_FAIL", str(exc))]
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [(exc.lineno or 0, "SYNTAX", str(exc))]

    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        lineno = node.lineno
        if node.type is None:
            hits.append((lineno, "BARE", "except: 会吞掉 KeyboardInterrupt"))
            continue
        noop = [s for s in node.body if is_noop(s)]
        if len(noop) == len(node.body):
            hits.append((lineno, "NOOP", "handler 里只有 pass/continue"))
            continue
        if not mentions_side_effect(node.body):
            hits.append((lineno, "SILENT", "handler 无 raise/return/日志/状态记录"))
    return hits


def main() -> int:
    total = 0
    files = 0
    for path in iter_py_files(ROOT):
        hits = audit(path)
        if not hits:
            continue
        files += 1
        rel = path.relative_to(ROOT).as_posix()
        for lineno, kind, reason in hits:
            total += 1
            print(f"{rel}:{lineno}  [{kind}] {reason}")
    print(f"\n合计 {total} 处 / {files} 个文件")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
