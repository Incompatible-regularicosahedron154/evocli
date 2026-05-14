"""
trace.py — Rule 10 (AI Programming Bible 3.0): Observability & Logging

Single Responsibility: Async-safe request tracing via contextvars.
Every tool call, session turn, and background task automatically
inherits the current session_id and request_id without explicit passing.

Usage:
    # At session start (handlers/agent_loop.py):
    with trace.session(session_id, model_id=model_id):
        await run_agent(...)

    # Inside any tool or function:
    from evocli_soul.trace import get_session_id, get_logger
    log = get_logger(__name__)
    log.info("tool_call", tool="fs_read", path=path)
    # → {"event": "tool_call", "tool": "fs_read", "session_id": "...", "ts": "..."}

Rule 9 note: This file MUST stay under 300 lines.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Generator

# ── Context variables (async-safe, no explicit passing needed) ────────────────

_session_id: ContextVar[str] = ContextVar("evocli_session_id", default="system")
_request_id: ContextVar[str] = ContextVar("evocli_request_id", default="")
_turn:        ContextVar[int] = ContextVar("evocli_turn", default=0)
_model_id:    ContextVar[str] = ContextVar("evocli_model_id", default="")


# ── Public accessors ──────────────────────────────────────────────────────────

def get_session_id() -> str:
    return _session_id.get()


def get_request_id() -> str:
    rid = _request_id.get()
    return rid or f"req_{uuid.uuid4().hex[:8]}"


def get_turn() -> int:
    return _turn.get()


def get_model_id() -> str:
    return _model_id.get()


# ── Context managers ──────────────────────────────────────────────────────────

@contextmanager
def session(
    session_id: str,
    *,
    model_id: str = "",
    turn: int = 0,
) -> Generator[None, None, None]:
    """
    Bind session context for the duration of an async agent run.

    Usage:
        with trace.session("ses_abc123", model_id="claude-3-5-haiku"):
            await handle_agent_stream(...)

    All log calls inside this context automatically include session_id.
    """
    tokens: list[Token] = [
        _session_id.set(session_id),
        _model_id.set(model_id),
        _turn.set(turn),
        _request_id.set(f"req_{uuid.uuid4().hex[:8]}"),
    ]
    try:
        yield
    finally:
        for tok in tokens:
            tok.var.reset(tok)


@contextmanager
def tool_span(tool_name: str) -> Generator[None, None, None]:
    """
    Track a single tool execution with timing and structured logging.

    Usage:
        with trace.tool_span("fs_read"):
            result = await _sc("fs.read", {"path": path})
    """
    log = get_logger("evocli.tool")
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.warning(
            "tool_error",
            tool=tool_name,
            error=str(exc)[:200],
            duration_ms=round(elapsed_ms, 1),
        )
        raise
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.debug(
            "tool_ok",
            tool=tool_name,
            duration_ms=round(elapsed_ms, 1),
        )


# ── Structured logger ─────────────────────────────────────────────────────────

class _StructuredLogger:
    """
    Thin wrapper around stdlib logging that auto-injects trace context.

    Produces structured log records:
      {"event": "tool_call", "session_id": "ses_abc", "tool": "fs_read", "ts": 1234567890}
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _extra(self, **kwargs: object) -> dict:
        return {
            "extra": {
                "session_id": _session_id.get(),
                "request_id": _request_id.get(),
                "turn":       _turn.get(),
                **{k: str(v)[:200] for k, v in kwargs.items()},
            }
        }

    def debug(self, event: str, **kwargs: object) -> None:
        self._log.debug(event, **self._extra(**kwargs))

    def info(self, event: str, **kwargs: object) -> None:
        self._log.info(event, **self._extra(**kwargs))

    def warning(self, event: str, **kwargs: object) -> None:
        self._log.warning(event, **self._extra(**kwargs))

    def error(self, event: str, **kwargs: object) -> None:
        self._log.error(event, **self._extra(**kwargs))

    def exception(self, event: str, **kwargs: object) -> None:
        self._log.exception(event, **self._extra(**kwargs))


def get_logger(name: str) -> _StructuredLogger:
    """
    Get a structured logger that auto-injects session_id / request_id.

    Usage:
        from evocli_soul.trace import get_logger
        log = get_logger(__name__)
        log.info("agent_started", model=model_id, turn=turn)
    """
    return _StructuredLogger(name)


# ── Integration helpers ───────────────────────────────────────────────────────

def bind_to_soul_loop(session_id: str, model_id: str = "", turn: int = 0) -> list[Token]:
    """
    Set trace context without a context manager (for asyncio.create_task contexts).
    Returns tokens needed for cleanup.

    Usage:
        tokens = trace.bind_to_soul_loop(session_id, model_id=model_id)
        try:
            await some_background_task()
        finally:
            for tok in tokens: tok.var.reset(tok)
    """
    return [
        _session_id.set(session_id),
        _model_id.set(model_id),
        _turn.set(turn),
        _request_id.set(f"req_{uuid.uuid4().hex[:8]}"),
    ]
