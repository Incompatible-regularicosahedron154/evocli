"""
watch_mode.py — Aider-style file watch mode (// AI! triggers)

研究来源:
- Aider (watch.py): 使用 watchfiles 监控文件变更
- 触发模式: // AI! 或 # AI? 注释
- 库: watchfiles>=0.21 (Aider 同款)

功能:
- WatchMode.start(): 启动文件监控
- 检测 // AI!, # AI!, -- AI!, ; AI! 注释
- 触发回调（用于通知 agent 处理）

需要: pip install "evocli-soul[code]" (包含 watchfiles)
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import re
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("evocli.watch_mode")

_WATCHFILES_AVAILABLE = importlib.util.find_spec("watchfiles") is not None

# Aider 触发模式正则 (aider/watch.py)
AI_TRIGGER_PATTERN = re.compile(
    r"(?:#|//|--|;+)\s*(ai\b.*|.*\bai[?!]?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# 支持的代码文件扩展名
WATCH_EXTENSIONS = {".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".cpp", ".c"}


class WatchMode:
    """
    文件监控模式 — 检测 // AI! 注释并触发 agent。
    研究: Aider 的 --watch 模式，使用 watchfiles 库监控文件系统。
    """

    def __init__(
        self,
        root: str | Path = ".",
        on_trigger: Optional[Callable[[str, str], None]] = None,
    ):
        self.root       = Path(root).resolve()
        self.on_trigger = on_trigger or self._default_trigger
        self._task: Optional[asyncio.Task] = None

    def _default_trigger(self, file_path: str, trigger_text: str) -> None:
        """默认触发处理：打印触发信息。"""
        log.info("AI trigger detected in %s: %s", file_path, trigger_text[:80])
        print(f"\n🚀 [EvoCLI Watch] AI trigger in {file_path}:\n  {trigger_text[:120]}")

    def extract_trigger(self, content: str) -> Optional[str]:
        """从文件内容中提取 AI 触发注释。"""
        match = AI_TRIGGER_PATTERN.search(content)
        if match:
            return match.group(0).strip()
        return None

    async def start(self) -> None:
        """
        Start watching the directory for AI trigger comments.
        Uses watchfiles.awatch() for async file system monitoring.
        Research: Aider uses watchfiles.watch() with the same pattern.
        """
        if not _WATCHFILES_AVAILABLE:
            log.warning("watchfiles not installed — watch mode disabled. "
                        "Install: pip install 'evocli-soul[code]'")
            return

        from watchfiles import awatch, Change

        log.info("Watch mode started: monitoring %s for AI triggers", self.root)
        print(f"👁️  [EvoCLI Watch] Monitoring {self.root} for AI triggers (// AI!, # AI!)")
        print("     Add '// AI! <your request>' to any file to trigger the agent.")

        async for changes in awatch(str(self.root)):
            for change_type, file_path in changes:
                if change_type == Change.deleted:
                    continue
                path = Path(file_path)
                if path.suffix not in WATCH_EXTENSIONS:
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    trigger = self.extract_trigger(content)
                    if trigger:
                        self.on_trigger(file_path, trigger)
                except Exception as e:
                    log.debug("watch_mode: error reading %s: %s", file_path, e)

    def start_background(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start watch mode as a background asyncio task."""
        if not _WATCHFILES_AVAILABLE:
            log.info("watchfiles not available — skipping watch mode")
            return
        try:
            # Use the caller-provided loop, or get the RUNNING loop (correct Python 3.10+ API).
            # get_event_loop() is deprecated in 3.10+ and may raise RuntimeError in 3.12+.
            lp = loop or asyncio.get_running_loop()
            self._task = lp.create_task(self.start())
            log.info("Watch mode task started")
        except RuntimeError:
            # No running loop (called from sync context) — defer startup to async context.
            log.debug("watch_mode: no running loop available, start_background must be called from async context")
        except Exception as e:
            log.debug("watch_mode: failed to start background task: %s", e)

    def stop(self) -> None:
        """Stop the background watch task."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
