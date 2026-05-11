"""
code_search.py — WIRE-1: grep-ast 上下文感知代码搜索

使用 grep-ast（Aider 同款）替代简单字符串匹配，搜索结果显示符号上下文：
- 旧：file.rs:42: result.unwrap()
- 新：fn parse_input() > if let Some(...) { result.unwrap() }

grep-ast 使用 tree-sitter 解析 AST，每个匹配行自动附带其所在函数/类/方法名称，
让 LLM 更准确理解修改位置。

Research sources:
- Aider: uses grep-ast for code context rendering
- Continue.dev: uses pathspec for .gitignore-aware file walking
- OpenCode: uses ripgrep (rg) which also respects .gitignore
改进：
- 用 pathspec 替代硬编码 _SKIP_DIRS，正确读取 .gitignore 规则

安装：pip install "evocli-soul[code]" 或 pip install grep-ast tree-sitter-languages pathspec
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Generator

log = logging.getLogger("evocli.code_search")

_GREP_AST_AVAILABLE = importlib.util.find_spec("grep_ast") is not None
_PATHSPEC_AVAILABLE = importlib.util.find_spec("pathspec") is not None

# 支持的文件扩展名
_CODE_EXTENSIONS = {
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".java", ".cpp", ".c", ".h", ".cs",
    ".rb", ".php", ".swift", ".kt", ".scala",
    ".toml", ".yaml", ".yml", ".json", ".md",
}

# Fallback skip dirs (used only when pathspec / .gitignore is unavailable)
# Research note: Continue.dev / OpenCode / Aider all use .gitignore-aware walking.
# When pathspec IS available, _iter_code_files respects the project's actual .gitignore.
_SKIP_DIRS_FALLBACK = {
    "__pycache__", ".git", "node_modules", "target",
    ".venv", "venv", "dist", "build", ".evocli",
}


def search_with_context(
    pattern: str,
    root: str | Path,
    max_results: int = 100,
) -> list[dict]:
    """
    上下文感知代码搜索（WIRE-1）。

    当 grep-ast 可用时：返回包含 AST 上下文（所在函数/类）的结果。
    当不可用时：退回到简单字符串搜索。

    返回格式：
    [
      {
        "file":    "src/main.rs",
        "line":    42,
        "content": "result.unwrap()",
        "context": "fn parse_input() > result.unwrap()",  # grep-ast 上下文
      },
      ...
    ]
    """
    if _GREP_AST_AVAILABLE:
        return _search_grep_ast(pattern, root, max_results)
    else:
        return _search_plain(pattern, root, max_results)


def _search_grep_ast(pattern: str, root: str | Path, max_results: int) -> list[dict]:
    """使用 grep-ast 进行上下文感知搜索"""
    from grep_ast import TreeContext

    results = []
    root_path = Path(root)

    for filepath in _iter_code_files(root_path):
        if len(results) >= max_results:
            break
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            lines   = content.splitlines()
            matches = []

            # 找到所有匹配行号（1-based）
            for i, line in enumerate(lines, 1):
                if pattern.lower() in line.lower():
                    matches.append(i)

            if not matches:
                continue

            # 使用 grep-ast 获取 AST 上下文
            try:
                rel_path = str(filepath.relative_to(root_path))
                ctx      = TreeContext(
                    rel_path,
                    content,
                    color=False,
                    verbose=False,
                    line_number=True,
                )
                ctx.add_lines_of_interest(matches)
                ctx.add_context()
                formatted = ctx.format()

                # 解析 grep-ast 输出，提取每个匹配行的上下文
                for lineno in matches:
                    if len(results) >= max_results:
                        break
                    line_content = lines[lineno - 1].strip()
                    # 从 formatted 中提取该行的上下文
                    context_snippet = _extract_context_for_line(formatted, lineno, rel_path)
                    results.append({
                        "file":    rel_path,
                        "line":    lineno,
                        "content": line_content,
                        "context": context_snippet or line_content,
                    })
            except Exception as e:
                # grep-ast 解析失败（不支持的语言等），退回纯文本
                log.debug("grep-ast parse failed for %s: %s", filepath.name, e)
                for lineno in matches[:5]:
                    if len(results) >= max_results:
                        break
                    results.append({
                        "file":    str(filepath.relative_to(root_path)),
                        "line":    lineno,
                        "content": lines[lineno - 1].strip(),
                        "context": lines[lineno - 1].strip(),
                    })
        except Exception as e:
            log.debug("Error reading %s: %s", filepath, e)

    return results


def _search_plain(pattern: str, root: str | Path, max_results: int) -> list[dict]:
    """简单字符串搜索（grep-ast 不可用时的 fallback）"""
    results = []
    root_path = Path(root)

    for filepath in _iter_code_files(root_path):
        if len(results) >= max_results:
            break
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(content.splitlines(), 1):
                if pattern.lower() in line.lower():
                    results.append({
                        "file":    str(filepath.relative_to(root_path)),
                        "line":    i,
                        "content": line.strip(),
                        "context": line.strip(),
                    })
                    if len(results) >= max_results:
                        break
        except Exception:
            pass

    return results


def _iter_code_files(root: Path) -> Generator[Path, None, None]:
    """
    Recursively iterate code files, respecting .gitignore rules.

    Strategy (research-backed, matches Continue.dev + Aider approach):
    1. If `pathspec` is available: load .gitignore and filter accordingly
    2. Fallback: use hardcoded skip list (fragile but always available)

    pathspec reads the actual .gitignore rules, so project-specific ignores
    (e.g., "*.generated.ts", "vendor/", "*.pb.go") are respected automatically.
    """
    if _PATHSPEC_AVAILABLE:
        yield from _iter_with_pathspec(root)
    else:
        yield from _iter_simple(root)


def _iter_with_pathspec(root: Path) -> Generator[Path, None, None]:
    """pathspec-aware iteration — respects .gitignore (Continue.dev pattern)."""
    import pathspec

    # Load .gitignore from repo root
    spec = None
    gitignore = root / ".gitignore"
    if gitignore.exists():
        try:
            with open(gitignore) as f:
                spec = pathspec.PathSpec.from_lines("gitwildmatch", f.readlines())
        except Exception:
            pass

    for dirpath, dirnames, filenames in os.walk(root):
        # Always skip hidden dirs and known non-source dirs
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d not in {"target", "node_modules", "__pycache__", "dist", "build"}
        ]
        for filename in filenames:
            full = Path(dirpath) / filename
            if full.suffix not in _CODE_EXTENSIONS:
                continue
            # Respect .gitignore
            if spec:
                try:
                    rel = str(full.relative_to(root))
                    if spec.match_file(rel):
                        continue
                except ValueError:
                    pass
            yield full


def _iter_simple(root: Path) -> Generator[Path, None, None]:
    """Simple fallback when pathspec is not available."""
    for entry in root.iterdir():
        if entry.is_dir():
            if entry.name not in _SKIP_DIRS_FALLBACK and not entry.name.startswith("."):
                yield from _iter_simple(entry)
        elif entry.suffix in _CODE_EXTENSIONS:
            yield entry


def _extract_context_for_line(formatted: str, lineno: int, filename: str) -> str:
    """从 grep-ast 输出中提取指定行的上下文摘要"""
    # grep-ast 输出格式：每行开头有行号标记
    lines = formatted.splitlines()
    target_marker = f"{lineno}│"
    for i, line in enumerate(lines):
        if target_marker in line:
            # 向上找函数/类定义行（通常是缩进层级更低的行）
            context_lines = []
            for j in range(max(0, i - 5), i + 1):
                context_lines.append(lines[j].strip())
            return " > ".join(l for l in context_lines if l and "│" in l)[:200]
    return ""
