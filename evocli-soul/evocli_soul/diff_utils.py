"""
diff_utils.py — Python-side diff application using whatthepatch

研究来源：
- pylsp (python-lsp-server) 使用 whatthepatch 应用 yapf/black 格式化 diffs
- Aider 使用 whatthepatch 处理 udiff 格式的代码修改
- whatthepatch 比手写 diff 解析更健壮（支持多种 diff 格式，处理行尾符等）

这个模块提供：
1. apply_unified_diff() — 应用 unified diff 到文件内容
2. parse_diff() — 解析 diff 文本，返回结构化数据

作为 Rust-side fs.apply_diff 的 Python 补充层：
- 当 Rust 侧 diff 应用失败时，尝试 Python whatthepatch
- 为 LLM 生成的 SEARCH/REPLACE 格式提供额外支持

需要：pip install "evocli-soul[code]" (包含 whatthepatch)
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("evocli.diff_utils")

_WHATTHEPATCH_AVAILABLE = importlib.util.find_spec("whatthepatch") is not None


def apply_unified_diff(original: str, patch_text: str) -> Optional[str]:
    """
    Apply a unified diff patch to file content.

    Uses whatthepatch (research-backed: pylsp + Aider use this library).
    Falls back to None on failure (caller should use Rust-side fs.apply_diff).

    Args:
        original:   Original file content as string
        patch_text: Unified diff text (--- / +++ / @@ format)

    Returns:
        Patched content string, or None if application failed.
    """
    if not _WHATTHEPATCH_AVAILABLE:
        log.debug("whatthepatch not available — cannot apply Python-side diff")
        return None

    try:
        import whatthepatch

        patches = list(whatthepatch.parse_patch(patch_text))
        if not patches:
            log.debug("whatthepatch: no patches found in diff text")
            return None

        diff      = patches[0]
        new_lines = whatthepatch.apply_diff(diff, original)
        if new_lines is None:
            log.debug("whatthepatch: apply_diff returned None (patch does not apply cleanly)")
            return None

        return "\n".join(new_lines)

    except Exception as e:
        log.debug("whatthepatch apply failed: %s", e)
        return None


def apply_diff_to_file(file_path: str | Path, patch_text: str) -> bool:
    """
    Apply a unified diff patch to a file on disk.

    Returns True on success, False on failure.
    """
    path = Path(file_path)
    if not path.exists():
        log.warning("diff_utils: file not found: %s", path)
        return False

    try:
        original = path.read_text(encoding="utf-8", errors="replace")
        patched  = apply_unified_diff(original, patch_text)
        if patched is None:
            return False
        path.write_text(patched, encoding="utf-8")
        log.info("diff_utils: applied patch to %s", path)
        return True
    except Exception as e:
        log.warning("diff_utils: failed to apply patch to %s: %s", path, e)
        return False


def parse_diff_stats(patch_text: str) -> dict:
    """
    Parse a unified diff and return statistics.
    Useful for validating LLM-generated patches before applying.

    Returns:
        {
            "files_changed": int,
            "lines_added": int,
            "lines_removed": int,
            "hunks": int,
        }
    """
    if not _WHATTHEPATCH_AVAILABLE:
        return {"files_changed": 0, "lines_added": 0, "lines_removed": 0, "hunks": 0}

    try:
        import whatthepatch

        stats = {"files_changed": 0, "lines_added": 0, "lines_removed": 0, "hunks": 0}
        for diff in whatthepatch.parse_patch(patch_text):
            stats["files_changed"] += 1
            if diff.changes:
                stats["lines_added"]   += sum(1 for c in diff.changes if c[0] is None)
                stats["lines_removed"] += sum(1 for c in diff.changes if c[1] is None)
                stats["hunks"]         += 1
        return stats
    except Exception as e:
        log.debug("parse_diff_stats failed: %s", e)
        return {"files_changed": 0, "lines_added": 0, "lines_removed": 0, "hunks": 0}
