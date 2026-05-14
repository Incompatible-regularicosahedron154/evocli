"""
context_mentions.py — @mention context provider parsing (Continue.dev + OpenCode pattern)

Extracted from context_engine.py to give @mention handling its own module.

Single responsibility: parse @xxx mentions from user prompts and inject
the corresponding content (file content, web pages, terminal output, etc.)
into the context window.

Supported syntax:
  @file:<path>       — inject file content
  @url:<url>         — fetch and inject web page content
  @terminal          — inject last terminal output
  @diff              — inject current git diff
  @problems          — inject diagnostic instructions
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger("evocli.context.mentions")


async def parse_mentions(bridge, goal: str) -> "tuple[str, dict]":
    """
    Parse @ context provider mentions from user prompt.

    Args:
        bridge: HostBridge instance for RPC calls (fs.read, web.fetch, git.diff)
        goal:   Raw user prompt (may contain @mentions)

    Returns:
        (cleaned_goal, injected_context_dict)
        - cleaned_goal: prompt with @mention tokens removed
        - injected_context_dict: {key → markdown_content} for each resolved mention
    """
    injected: dict[str, str] = {}

    # @file:<path> — inject file content
    file_pattern = re.compile(r"@file:(\S+)")
    for m in file_pattern.finditer(goal):
        path = m.group(1)
        try:
            content = await bridge.call("fs.read", {"path": path})
            if isinstance(content, str):
                injected[f"@file:{path}"] = f"## File: {path}\n```\n{content[:3000]}\n```"
                log.debug("@file provider: %s (%d chars)", path, len(content))
        except Exception as e:
            log.debug("@file: %s failed: %s", path, e)
    goal = file_pattern.sub("", goal).strip()

    # @url:<url> — fetch and inject web page content (OpenCode pattern)
    url_pattern = re.compile(r"@url:(https?://\S+)")
    for m in url_pattern.finditer(goal):
        url = m.group(1)
        try:
            result = await bridge.call("web.fetch", {"url": url, "max_chars": 4000})
            if isinstance(result, str) and result.strip():
                injected[f"@url:{url}"] = f"## Web: {url}\n{result[:3000]}"
                log.debug("@url provider: %s (%d chars)", url, len(result))
            elif isinstance(result, dict):
                text = result.get("text", result.get("content", ""))
                if text:
                    injected[f"@url:{url}"] = f"## Web: {url}\n{text[:3000]}"
        except Exception as e:
            log.debug("@url: %s failed: %s", url, e)
    goal = url_pattern.sub("", goal).strip()

    # @terminal — inject last stored terminal output
    if "@terminal" in goal:
        try:
            from evocli_soul.state import get_terminal_output
            last_output = get_terminal_output()
            if last_output:
                injected["@terminal"] = (
                    f"## 最近终端输出\n```\n{last_output[-2000:]}\n```"
                )
            else:
                injected["@terminal"] = (
                    "## Terminal Context\n"
                    "暂无最近终端输出。使用 `run_and_capture('命令')` 获取终端输出。"
                )
        except Exception:
            injected["@terminal"] = (
                "## Terminal Context\n"
                "使用 `run_and_capture('命令')` 获取终端输出。"
            )
        goal = goal.replace("@terminal", "").strip()

    # @diff — inject current git diff
    if "@diff" in goal:
        try:
            diff_result = await bridge.call("git.diff", {})
            if isinstance(diff_result, str) and diff_result.strip():
                injected["@diff"] = f"## 当前 Git Diff\n```diff\n{diff_result[:3000]}\n```"
            else:
                injected["@diff"] = "## Git Diff\n暂无未提交的修改。"
        except Exception as e:
            log.debug("@diff failed: %s", e)
        goal = goal.replace("@diff", "").strip()

    # @problems — inject current file diagnostics
    if "@problems" in goal:
        injected["@problems"] = (
            "## 代码诊断\n"
            "使用 `fs_lint_file(path)` 检查特定文件的错误和警告。\n"
            "使用 `shell_run('cargo check')` 检查整个项目的编译错误。"
        )
        goal = goal.replace("@problems", "").strip()

    return goal, injected
