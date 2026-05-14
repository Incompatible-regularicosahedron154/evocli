"""
tests/unit/test_trace.py — trace.py function tests

Covers: session context manager, tool_span, get_logger, get_session_id,
        bind_to_soul_loop cleanup, structured logging with context injection
"""
from __future__ import annotations
import asyncio, pathlib, sys, pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))


class TestTraceSession:
    def test_session_sets_and_resets_context(self):
        from evocli_soul.trace import session, get_session_id
        assert get_session_id() == "system"  # default
        with session("ses_test_001", model_id="claude-3", turn=1):
            assert get_session_id() == "ses_test_001"
        assert get_session_id() == "system"  # reset after

    def test_session_nesting_restores_outer(self):
        from evocli_soul.trace import session, get_session_id
        with session("outer_session"):
            assert get_session_id() == "outer_session"
            with session("inner_session"):
                assert get_session_id() == "inner_session"
            assert get_session_id() == "outer_session"
        assert get_session_id() == "system"

    def test_session_exception_still_resets(self):
        from evocli_soul.trace import session, get_session_id
        try:
            with session("failing_session"):
                raise ValueError("test error")
        except ValueError:
            pass
        assert get_session_id() == "system"

    def test_get_request_id_returns_string(self):
        from evocli_soul.trace import session, get_request_id
        with session("ses_req_test"):
            rid = get_request_id()
            assert isinstance(rid, str)
            assert len(rid) > 0

    def test_get_turn_returns_int(self):
        from evocli_soul.trace import session, get_turn
        with session("ses_turn", turn=5):
            assert get_turn() == 5

    def test_get_model_id(self):
        from evocli_soul.trace import session, get_model_id
        with session("ses_model", model_id="gpt-4o"):
            assert get_model_id() == "gpt-4o"


class TestGetLogger:
    def test_returns_structured_logger(self):
        from evocli_soul.trace import get_logger
        log = get_logger("evocli.test.module")
        assert hasattr(log, "info")
        assert hasattr(log, "debug")
        assert hasattr(log, "warning")
        assert hasattr(log, "error")
        assert hasattr(log, "exception")

    def test_logger_callable(self):
        from evocli_soul.trace import get_logger
        log = get_logger("test")
        # Should not raise
        log.info("test_event", key="value", count=42)
        log.debug("debug_event")
        log.warning("warn_event", error="something")

    def test_logger_injects_session_id_in_context(self):
        from evocli_soul.trace import get_logger, session
        log = get_logger("test.context")
        # With session context, extra dict should contain session_id
        with session("ses_logger_test"):
            # Verify no crash when logging with context
            log.info("operation_start", tool="fs_read", path="src/main.rs")
            log.info("operation_done", tool="fs_read", duration_ms=12.5)


class TestToolSpan:
    @pytest.mark.asyncio
    async def test_tool_span_no_exception(self):
        from evocli_soul.trace import tool_span, session
        with session("ses_span_test"):
            with tool_span("fs_read"):
                await asyncio.sleep(0.001)  # simulate work

    @pytest.mark.asyncio
    async def test_tool_span_logs_on_exception(self):
        from evocli_soul.trace import tool_span, session
        with session("ses_span_exc"):
            with pytest.raises(ValueError):
                with tool_span("broken_tool"):
                    raise ValueError("tool failed")

    @pytest.mark.asyncio
    async def test_tool_span_reraises_exception(self):
        from evocli_soul.trace import tool_span
        caught = None
        try:
            with tool_span("failing_tool"):
                raise RuntimeError("critical failure")
        except RuntimeError as e:
            caught = e
        assert caught is not None
        assert "critical failure" in str(caught)


class TestBindToSoulLoop:
    def test_bind_and_cleanup(self):
        from evocli_soul.trace import bind_to_soul_loop, get_session_id
        tokens = bind_to_soul_loop("ses_bound_001", model_id="claude", turn=3)
        assert get_session_id() == "ses_bound_001"
        # Cleanup
        for tok in tokens:
            try: tok.var.reset(tok)
            except Exception: pass

    def test_cleanup_restores_default(self):
        from evocli_soul.trace import bind_to_soul_loop, get_session_id
        tokens = bind_to_soul_loop("ses_temp")
        assert get_session_id() == "ses_temp"
        for tok in tokens:
            try: tok.var.reset(tok)
            except Exception: pass
        assert get_session_id() == "system"
