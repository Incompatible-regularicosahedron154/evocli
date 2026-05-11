"""
EvoCLI Soul — Unified logging

Writes to ~/.evocli/logs/evocli.log alongside Rust Host logs.
All Soul log entries are prefixed with [SOUL] for easy filtering.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path


class _TuiEventHandler(logging.Handler):
    """Forwards WARNING+ log records to the TUI as inline System messages.

    Uses rpc._send() directly (thread-safe via _stdout_lock) so it works
    both from the main asyncio thread and from background daemon threads.
    The handler is best-effort: any I/O or import error is silently swallowed
    to ensure logging itself never crashes the Soul process.

    Level policy:
      WARNING  → ⚠️  shown in TUI (user-visible, non-fatal)
      ERROR    → ⛔  shown in TUI with first traceback line (always show)
      CRITICAL → ⛔  same as ERROR, bold
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        try:
            from evocli_soul.rpc import _send  # local import avoids circular deps
            # Truncate the message to the first non-empty line to avoid flooding
            # the TUI with multi-line error strings (e.g. security whitelist dumps).
            # The full message + traceback is always available in evocli.log (F12).
            raw_msg = record.getMessage()
            first_line = next(
                (l for l in raw_msg.splitlines() if l.strip()),
                raw_msg,
            )
            # Hard cap at 200 chars so even first-line errors can't overflow the panel.
            if len(first_line) > 200:
                first_line = first_line[:197] + "…"

            exc_text = None
            if record.exc_info and record.exc_info[0] is not None:
                # Show last 2 lines of traceback (root cause), truncated.
                lines = traceback.format_exception(*record.exc_info)
                relevant = [l.strip() for l in "".join(lines[-2:]).splitlines() if l.strip()]
                if relevant:
                    exc_text = relevant[-1][:160] + ("…" if len(relevant[-1]) > 160 else "")

            _send({
                "method": "event.emit",
                "params": {
                    "type":    "log",
                    "level":   record.levelname.lower(),
                    "logger":  record.name,
                    "message": first_line,
                    "exc":     exc_text,
                },
            })
        except Exception:
            pass  # Never let the logging subsystem raise


def setup_logging(debug: bool = False) -> None:
    """Configure Soul-side logging.

    - Always writes to ~/.evocli/logs/evocli.log
    - When *debug* is True, also prints to stderr
    - WARNING+ messages are forwarded to the TUI inline (via _TuiEventHandler)
    - Format: ``timestamp [SOUL] LEVEL name: message``
    """
    log_dir = Path(os.path.expanduser("~/.evocli/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "evocli.log"

    level = logging.DEBUG if debug else logging.INFO

    # ── evocli.* namespace (Soul business logic) ──────────────────────────────
    root = logging.getLogger("evocli")
    root.setLevel(level)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [SOUL] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # File handler — always active, captures everything
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Stderr handler — debug mode or warnings+
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG if debug else logging.WARNING)
    sh.setFormatter(logging.Formatter("[soul] %(levelname)s %(message)s"))
    root.addHandler(sh)

    # TUI event handler — forwards WARNING+ to TUI chat inline
    tui_h = _TuiEventHandler()
    tui_h.setLevel(logging.WARNING)
    root.addHandler(tui_h)

    # ── Third-party library loggers ────────────────────────────────────────────
    # Route ERROR+ from external libraries to the same file and TUI handler so
    # users can see LiteLLM auth failures, httpx network errors, pydantic_ai
    # crashes, etc. — without swamping the TUI with library DEBUG noise.
    _third_party_loggers = [
        "LiteLLM", "litellm", "httpx", "httpcore",
        "pydantic_ai", "openai", "anthropic",
        "lancedb", "fastembed",
    ]
    for name in _third_party_loggers:
        lib_log = logging.getLogger(name)
        # Don't override level if already set lower — just attach our handlers.
        if lib_log.level == logging.NOTSET or lib_log.level > logging.ERROR:
            lib_log.setLevel(logging.ERROR)
        # Avoid duplicate handlers on repeated setup_logging() calls
        handler_types = {type(h) for h in lib_log.handlers}
        if logging.FileHandler not in handler_types:
            fh2 = logging.FileHandler(str(log_file), encoding="utf-8")
            fh2.setLevel(logging.ERROR)
            fh2.setFormatter(fmt)
            lib_log.addHandler(fh2)
        if _TuiEventHandler not in handler_types:
            tui_h2 = _TuiEventHandler()
            tui_h2.setLevel(logging.ERROR)
            lib_log.addHandler(tui_h2)

    root.info("Soul logging initialized (debug=%s)", debug)
