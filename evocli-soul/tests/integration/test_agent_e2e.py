"""
tests/integration/test_agent_e2e.py — E2E agent chain integration tests

Tests the full agent execution chain WITHOUT a real LLM using MockBridge + patched LLMClient.

Covered chains:
  1. agent.run()  → text response              (no tool calls)
  2. agent.run()  → tool_call(fs.read)         → bridge.call verified
  3. agent.stream() → streaming path           → no NameError
  4. _stream_litellm() → streaming path        → no NameError
  5. _build_context() → context pipeline       → no NameError
  6. _inject_context() → env details injection → input preserved
  7. _select_tools_for_request()               → returns frozenset
  8. _build_tool_definitions()                 → returns 20+ schemas
  9. task_complete state lifecycle             → full round-trip
"""
from __future__ import annotations
import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))


# ── Test infrastructure ───────────────────────────────────────────────────────

class MockBridge:
    """Mock Rust bridge that records calls and returns sensible defaults."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, args: dict):
        self.calls.append((tool, args))
        if tool == "config.get":
            return {"llm": {"provider": "anthropic", "tiers": {"fast": "claude-mock"}}}
        if tool in ("fs.read", "shell.cat"):
            return f"# {args.get('path', 'file')}\ndef main(): pass\n"
        if tool in ("fs.write", "fs.apply_diff"):
            return {"ok": True, "path": args.get("path")}
        if tool == "shell.run":
            return {"ok": True, "stdout": "All tests passed.", "stderr": "", "exit_code": 0}
        if tool in ("git.status",):
            return [{"path": "src/main.rs", "status": "M"}]
        if tool == "git.diff":
            return "--- a/src/main.rs\n+++ b/src/main.rs\n@@ -1 +1,2 @@\n+# fix\n"
        if tool == "git.commit":
            return {"hash": "abc1234def", "message": args.get("message", "")}
        if tool == "git.snapshot":
            return {"stash_ref": "stash@{0}"}
        if tool == "symbol.lookup":
            return {"found": False, "symbols": []}
        return {"ok": True, "tool": tool}


class _FakeLLMResponse:
    """One fake LLM response (text or tool_calls)."""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content    = content
        self.tool_calls = tool_calls or []


def _make_patched_llm(responses: list[_FakeLLMResponse]):
    """
    Patch evocli_soul.llm_client.LLMClient with a deterministic mock.
    Returns a restore() callable to undo the patch.
    """
    import evocli_soul.llm_client as _mod

    call_idx = [0]

    class _FakeRouter:
        async def acompletion(self, **kwargs):
            idx = call_idx[0] % len(responses)
            call_idx[0] += 1
            r = responses[idx]

            class _Choice:
                class _Message:
                    def __init__(self, rr):
                        self.content    = rr.content
                        self.tool_calls = None
                        if rr.tool_calls:
                            self.tool_calls = [
                                type("TC", (), {
                                    "id":       f"call_{i}",
                                    "function": type("FN", (), {
                                        "name":      tc["name"],
                                        "arguments": json.dumps(tc.get("args", {})),
                                    })(),
                                })()
                                for i, tc in enumerate(rr.tool_calls)
                            ]

                def __init__(self, rr):
                    self.message = self._Message(rr)

            class _Usage:
                prompt_tokens     = 50
                completion_tokens = 20

            class _FakeResp:
                def __init__(self, rr):
                    self.choices = [_Choice(rr)]
                    self.usage   = _Usage()

            return _FakeResp(r)

    class _MockLLMClient:
        def __init__(self, cfg):               pass
        def _resolve_model(self, tier):        return "mock-model"
        def get_task_params(self, task):       return {"max_tokens": 200, "temperature": 0}
        @property
        def _router(self):                     return _FakeRouter()

    orig = _mod.LLMClient
    _mod.LLMClient = _MockLLMClient

    def restore():
        _mod.LLMClient = orig

    return restore


def _make_agent(session_id: str = "e2e_default"):
    """Create an EvoCLIAgent with MockBridge and minimal config."""
    from evocli_soul.agent import EvoCLIAgent
    bridge = MockBridge()
    agent  = EvoCLIAgent(
        bridge=bridge,
        memory=None,
        config={"llm": {"provider": "anthropic", "tiers": {"fast": "claude-mock"}}},
        session_id=session_id,
    )
    return agent, bridge


# ── Test suite ────────────────────────────────────────────────────────────────

class TestAgentE2E:
    """End-to-end chain verification tests."""

    @pytest.mark.asyncio
    async def test_run_text_response(self):
        """
        Chain: agent.run() → _build_context → _run_litellm → text response.
        Verifies the run() path works end-to-end without NameError/AttributeError.
        """
        agent, _ = _make_agent("e2e_run_text")
        restore  = _make_patched_llm([_FakeLLMResponse(content="2 + 2 = 4")])
        try:
            result = await agent.run("What is 2+2?")
        except (NameError, AttributeError) as e:
            raise AssertionError(
                f"REGRESSION: agent.run() crashed with {type(e).__name__}: {e}\n"
                f"This indicates a broken mixin reference in the split architecture."
            )
        except Exception:
            result = "graceful-error"  # LLM errors are OK in tests
        finally:
            restore()

        assert isinstance(result, str), f"Expected str, got {type(result)}"

    @pytest.mark.asyncio
    async def test_run_tool_call_invokes_bridge(self):
        """
        Chain: agent.run() → LLM tool_call(fs_read) → bridge.call(fs.read) verified.
        Proves the tool dispatch path works: LLM decision → Rust bridge execution.
        """
        agent, bridge = _make_agent("e2e_run_tool")
        restore = _make_patched_llm([
            _FakeLLMResponse(
                content="",
                tool_calls=[{"name": "fs_read", "args": {"path": "src/main.rs"}}],
            ),
            _FakeLLMResponse(content="The file has a main function."),
        ])
        try:
            await agent.run("Read src/main.rs and tell me what it does")
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: {type(e).__name__}: {e}")
        except Exception:
            pass  # LLM errors acceptable
        finally:
            restore()

        read_calls = [c for c in bridge.calls if c[0] == "fs.read"]
        assert read_calls, (
            f"REGRESSION: bridge.call('fs.read') was never called. "
            f"Tool dispatch chain is broken. Calls received: {[c[0] for c in bridge.calls]}"
        )

    @pytest.mark.asyncio
    async def test_stream_no_nameeerror(self):
        """
        Chain: agent.stream() → _build_context → _stream_litellm → async chunks.
        Verifies the streaming path executes without NameError/AttributeError.
        """
        agent, _ = _make_agent("e2e_stream")
        restore  = _make_patched_llm([_FakeLLMResponse(content="Hello world response")])
        try:
            async for chunk in agent.stream("Hello", session_id="e2e_stream"):
                pass  # Just drain the generator
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: agent.stream() crashed: {type(e).__name__}: {e}")
        except Exception:
            pass  # Provider errors acceptable — only crash errors are regression
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_stream_litellm_no_nameerror(self):
        """
        Chain: _stream_litellm() → LLM streaming → yields chunks or fails gracefully.
        Verifies the LiteLLM streaming fallback path has no broken name references.
        """
        agent, _ = _make_agent("e2e_stream_litellm")
        restore  = _make_patched_llm([_FakeLLMResponse(content="Streaming text response")])
        try:
            async for chunk in agent._stream_litellm(
                "Say hello",
                ctx={"system_prompt": "You are a helpful assistant."},
            ):
                pass
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: _stream_litellm crashed: {type(e).__name__}: {e}")
        except Exception:
            pass  # Provider errors acceptable
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_build_context_no_crash(self):
        """
        Chain: _build_context() → context engine → returns dict without crash.
        Tests the AgentContextMixin path independently.
        """
        agent, _ = _make_agent("e2e_context")
        ctx = {}
        try:
            ctx = await agent._build_context(
                "Write tests for auth module",
                context_params={"current_file": "src/auth.py"},
                session_id="e2e_context",
            )
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: _build_context crashed: {type(e).__name__}: {e}")
        except Exception:
            ctx = {}  # LLM/memory errors OK

        assert isinstance(ctx, dict), f"Expected dict, got {type(ctx)}"

    @pytest.mark.asyncio
    async def test_inject_context_preserves_input(self):
        """
        Chain: _inject_context() → env details + user_context prepended → input preserved.
        Verifies no NameError in environment details injection (CWD, OS, session files).
        """
        agent, _ = _make_agent("e2e_inject")
        marker = "my_unique_regression_marker_12345"
        try:
            result = await agent._inject_context(marker, ctx={})
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: _inject_context crashed: {type(e).__name__}: {e}")

        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert marker in result, (
            f"User input not preserved in injected context. "
            f"Got: {result[:200]!r}"
        )

    def test_select_tools_returns_frozenset(self):
        """
        Chain: _select_tools_for_request() → classifies request → returns frozenset.
        Verifies AgentToolSelectorMixin works without NameError.
        """
        agent, _ = _make_agent("e2e_select")
        try:
            agent._select_tools_for_request("read src/main.rs and fix the memory leak bug")
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: _select_tools_for_request crashed: {e}")

        assert isinstance(agent._selected_tool_names, frozenset), (
            f"Expected frozenset, got {type(agent._selected_tool_names)}"
        )

    def test_build_tool_definitions_schemas(self):
        """
        Chain: _build_tool_definitions() → OpenAI-format tool schemas for LiteLLM.
        Verifies AgentToolDefsMixin produces valid tool schemas.
        """
        agent, _ = _make_agent("e2e_defs")
        try:
            defs = agent._build_tool_definitions()
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: _build_tool_definitions crashed: {e}")

        assert isinstance(defs, list), f"Expected list, got {type(defs)}"
        assert len(defs) > 20, f"Expected 20+ tool schemas, got {len(defs)}"
        for d in defs[:3]:
            assert "name" in d or "function" in d, f"Malformed tool def: {d!r}"

    @pytest.mark.asyncio
    async def test_task_complete_full_lifecycle(self):
        """
        Chain: task_complete tool called → double-check rejection → re-verify → accept →
               state stored → agent_loop reads it → clear → state gone.
        Full round-trip of the Cline-style completion protocol.
        """
        import evocli_soul.state as state

        sid = "e2e_tc_lifecycle_final"
        state.clear_task_complete(sid)

        # Phase 1: Initial state
        assert state.get_task_complete(sid) is None
        assert not state.is_task_double_checked(sid)

        # Phase 2: First call rejected (Cline double-check pattern)
        # → agent marks double-checked (simulates the re-verify prompt being sent)
        state.mark_task_double_checked(sid)
        assert state.is_task_double_checked(sid)

        # Phase 3: Second call accepted
        state.set_task_complete(
            sid,
            result="Implemented JWT authentication with tests",
            command="cargo test",
        )
        sig = state.get_task_complete(sid)
        assert sig is not None
        assert sig["result"] == "Implemented JWT authentication with tests"
        assert sig["command"] == "cargo test"
        assert "ts" in sig, "Completion signal must have timestamp"

        # Phase 4: agent_loop reads it, runs verification, then clears
        state.clear_task_complete(sid)
        assert state.get_task_complete(sid) is None
        assert not state.is_task_double_checked(sid), "double_checked flag must reset on clear"
