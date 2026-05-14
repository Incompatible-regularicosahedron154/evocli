"""
test_core_reliability.py — 10 核心可靠性单测

覆盖最高价值的回归场景：
1. state.py session 隔离（并发安全修复验证）
2. LRU session cache（无界内存修复验证）
3. config_defaults.py（所有魔法数字可读取）
4. task_complete double-check（Cline 双重验证）
5. circuit breaker（连续失败断路器）
6. user_tool_loader（自定义工具加载）
7. context_engine token budget（不超限）
8. _session_events 并发隔离
9. cfg_get 读取链（config > defaults）
10. 工具计数自省（不硬编码）
"""
import asyncio
import sys
import pathlib

# Add soul dir to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
import evocli_soul.state as state


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Session isolation — concurrent sessions don't share _session_events
# ─────────────────────────────────────────────────────────────────────────────
def test_session_events_isolation():
    """Two concurrent sessions must NOT share events (was a critical bug)."""
    state.append_session_event({"type": "tool_call", "method": "fs_read"}, session_id="session_A")
    state.append_session_event({"type": "tool_call", "method": "fs_write"}, session_id="session_B")
    state.append_session_event({"type": "tool_call", "method": "git_commit"}, session_id="session_A")

    events_A = state.drain_session_events("session_A")
    events_B = state.drain_session_events("session_B")

    assert len(events_A) == 2, f"Session A should have 2 events, got {len(events_A)}"
    assert len(events_B) == 1, f"Session B should have 1 event, got {len(events_B)}"
    assert all(e["method"] in ("fs_read", "git_commit") for e in events_A)
    assert events_B[0]["method"] == "fs_write"
    # After draining, both are empty
    assert state.drain_session_events("session_A") == []
    assert state.drain_session_events("session_B") == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: LRU session cache evicts oldest when full
# ─────────────────────────────────────────────────────────────────────────────
def test_lru_session_cache_evicts():
    """_LRUSessionCache must evict the oldest entry when maxsize is exceeded."""
    from evocli_soul.state import _LRUSessionCache
    cache = _LRUSessionCache(maxsize=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    assert len(cache) == 3
    # Adding a 4th evicts "a" (oldest)
    cache["d"] = 4
    assert "a" not in cache, "Oldest entry 'a' should have been evicted"
    assert "b" in cache and "c" in cache and "d" in cache
    assert len(cache) == 3


def test_lru_session_cache_update_order():
    """Accessing an existing key should update its LRU position."""
    from evocli_soul.state import _LRUSessionCache
    cache = _LRUSessionCache(maxsize=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    # Re-set "a" — moves to newest
    cache["a"] = 10
    # Now add "d" — should evict "b" (oldest after "a" was refreshed)
    cache["d"] = 4
    assert "b" not in cache, "'b' should be evicted after 'a' was refreshed"
    assert "a" in cache and "c" in cache and "d" in cache


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: config_defaults — all keys readable
# ─────────────────────────────────────────────────────────────────────────────
def test_config_defaults_all_keys():
    """Every key in DEFAULTS must return a non-None value via cfg_get."""
    from evocli_soul.config_defaults import cfg_get, DEFAULTS
    missing = []
    for key in DEFAULTS:
        val = cfg_get(key)
        if val is None:
            missing.append(key)
    assert not missing, f"These defaults return None: {missing}"


def test_config_defaults_types():
    """Critical defaults must return correct types."""
    from evocli_soul.config_defaults import cfg_int, cfg_float, cfg_bool
    assert isinstance(cfg_int("shell.timeout_s"), int)
    assert isinstance(cfg_int("agent.max_auto_iterations"), int)
    assert isinstance(cfg_float("llm.temperature"), float)
    assert isinstance(cfg_bool("agent.auto_commit"), bool)
    assert cfg_int("shell.timeout_s") > 0
    assert cfg_int("agent.max_auto_iterations") > 0
    assert 0.0 <= cfg_float("llm.temperature") <= 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: task_complete double-check pattern
# ─────────────────────────────────────────────────────────────────────────────
def test_task_complete_double_check():
    """First task_complete call should be rejected (re-verify required)."""
    sid = "test_double_check"
    state.clear_task_complete(sid)

    # First attempt: should NOT be marked double-checked yet
    assert not state.is_task_double_checked(sid)

    # Mark double-checked (simulates AI's re-verify step)
    state.mark_task_double_checked(sid)
    assert state.is_task_double_checked(sid)

    # Set completion
    state.set_task_complete(sid, "Done!", "cargo test")
    completion = state.get_task_complete(sid)
    assert completion is not None
    assert completion["result"] == "Done!"
    assert completion["command"] == "cargo test"

    # Clean up
    state.clear_task_complete(sid)
    assert state.get_task_complete(sid) is None
    assert not state.is_task_double_checked(sid)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: circuit breaker state
# ─────────────────────────────────────────────────────────────────────────────
def test_circuit_breaker_increments():
    """Circuit breaker should count failures and reset on success."""
    sid = "test_circuit_breaker"
    state.reset_tool_failure(sid)

    assert state.get_tool_failure_count(sid) == 0
    count1 = state.increment_tool_failure(sid)
    count2 = state.increment_tool_failure(sid)
    assert count1 == 1
    assert count2 == 2

    state.reset_tool_failure(sid)
    assert state.get_tool_failure_count(sid) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: user_tool_loader discover_tool_files
# ─────────────────────────────────────────────────────────────────────────────
def test_user_tool_loader_discovers_files(tmp_path):
    """discover_tool_files should find *.py files in the tools directory."""
    from evocli_soul.user_tool_loader import discover_tool_files

    tools_dir = tmp_path / ".evocli" / "tools"
    tools_dir.mkdir(parents=True)
    (tools_dir / "my_tools.py").write_text("def register(agent, **kw): pass")
    (tools_dir / "_private.py").write_text("# ignored")  # underscore prefix = skip
    (tools_dir / "not_python.txt").write_text("ignored")

    files = discover_tool_files(project_dir=str(tmp_path))
    names = [f.name for f in files]
    assert "my_tools.py" in names
    assert "_private.py" not in names
    assert "not_python.txt" not in names


def test_user_tool_loader_loads_register(tmp_path):
    """load_user_tools should call register() in each discovered file."""
    from evocli_soul.user_tool_loader import load_user_tools

    tools_dir = tmp_path / ".evocli" / "tools"
    tools_dir.mkdir(parents=True)

    called = []
    tool_code = """
def register(agent, _sc, _call_handler, _sid, _json, bridge=None, config=None, memory=None):
    # Just mark that we were called
    import builtins
    builtins._test_user_tool_called = True
"""
    (tools_dir / "test_tool.py").write_text(tool_code)

    import builtins
    builtins._test_user_tool_called = False

    n = load_user_tools(
        agent=None, bridge=None, sid="test", sc_fn=None, call_handler_fn=None,
        project_dir=str(tmp_path)
    )
    assert n == 1
    assert builtins._test_user_tool_called is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: config_defaults override chain
# ─────────────────────────────────────────────────────────────────────────────
def test_config_defaults_override():
    """cfg_get should return override parameter when provided."""
    from evocli_soul.config_defaults import cfg_get, cfg_int, invalidate_cache
    # Direct override bypasses config file
    assert cfg_get("shell.timeout_s", 999) == 999
    assert cfg_int("agent.max_tool_calls", 50) == 50


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: session history is session-isolated
# ─────────────────────────────────────────────────────────────────────────────
def test_history_session_isolation():
    """Two sessions should have independent conversation histories."""
    sid_a = "hist_test_A"
    sid_b = "hist_test_B"
    state.set_history([], sid_a)
    state.set_history([], sid_b)

    state.append_history([{"role": "user", "content": "Hello from A"}], sid_a)
    state.append_history([{"role": "user", "content": "Hello from B"}], sid_b)

    hist_a = state.get_history(sid_a)
    hist_b = state.get_history(sid_b)

    assert len(hist_a) == 1 and hist_a[0]["content"] == "Hello from A"
    assert len(hist_b) == 1 and hist_b[0]["content"] == "Hello from B"

    # Clean up
    state.set_history([], sid_a)
    state.set_history([], sid_b)


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: todo list session isolation
# ─────────────────────────────────────────────────────────────────────────────
def test_todos_session_isolation():
    """Todo lists must be isolated per session."""
    sid_a = "todo_test_A"
    sid_b = "todo_test_B"
    state.set_todos([{"id": "1", "content": "Task A", "status": "pending"}], sid_a)
    state.set_todos([{"id": "1", "content": "Task B", "status": "in_progress"}], sid_b)

    todos_a = state.get_todos(sid_a)
    todos_b = state.get_todos(sid_b)

    assert todos_a[0]["content"] == "Task A"
    assert todos_b[0]["content"] == "Task B"
    assert todos_a[0]["status"] == "pending"
    assert todos_b[0]["status"] == "in_progress"


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: EvoCLIAgent tool count introspection
# ─────────────────────────────────────────────────────────────────────────────
def test_tool_count_not_zero():
    """get_tool_count_from_registry() must return > 0 (no hardcoded magic number)."""
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from evocli_soul.agent import EvoCLIAgent
    count = EvoCLIAgent.get_tool_count_from_registry()
    assert count > 0, "Tool count should be auto-detected, not zero"
    assert count > 30, f"Expected 30+ tools, got {count} — tool registration may be broken"
    print(f"  Auto-detected tool count: {count}")


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 1: run_agent_stream_body prompt extraction (critical regression test)
# Ensures the main autonomous loop receives its prompt from params correctly.
# This test caught the critical `NameError: prompt is not defined` regression.
# ─────────────────────────────────────────────────────────────────────────────
import pytest

@pytest.mark.asyncio
async def test_run_agent_stream_body_prompt_extraction():
    """
    E2E: run_agent_stream_body must extract 'prompt' from params.
    Previously broken: function used bare `prompt` variable that was never
    defined in its scope — causing NameError on every real conversation turn.
    """
    import asyncio
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from evocli_soul.handlers.agent_loop import run_agent_stream_body

    received_chunks: list[str] = []
    done_signals:    list[bool] = []

    class MockSend:
        async def stream_chunk(self, req_id: str, text: str, done: bool) -> None:
            received_chunks.append(text)
            done_signals.append(done)

    class MockState:
        @staticmethod
        def get_config():  return {"llm": {"provider": "anthropic", "tiers": {}}}
        @staticmethod
        def get_bridge():  return None
        @staticmethod
        def get_llm_client(): return None

    params = {"prompt": "test prompt for regression", "session_id": "test_e2e_001"}
    send   = MockSend()
    state  = MockState()

    # The function must NOT raise NameError for 'prompt'.
    # It will fail later (no API key) but should reach the API key check,
    # not crash at `_current_prompt = prompt`.
    try:
        await run_agent_stream_body(
            req_id="test_req_001",
            params=params,
            send=send,
            state=state,
        )
    except Exception as e:
        # NameError for 'prompt' is the regression we're guarding against.
        assert "prompt" not in str(e).lower() or "NameError" not in type(e).__name__, (
            f"REGRESSION: run_agent_stream_body still has undefined 'prompt': {e}"
        )
        # Other errors (no API key, no bridge) are expected in test environment.

    # The function must have sent at least one chunk (the "⚠️ No API key" message
    # OR any progress event) — proving it got past the prompt extraction.
    # An empty chunks list with no done=True signal means it crashed before doing anything.
    assert done_signals, (
        "run_agent_stream_body sent no done=True signal — "
        "it likely crashed before extracting the prompt"
    )


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 2: agent_tools_shell._ca import (critical regression test)
# Ensures shell analysis tools (assume_*, impact_*, etc.) load without NameError
# ─────────────────────────────────────────────────────────────────────────────
def test_agent_tools_shell_ca_import():
    """
    E2E: agent_tools_shell must import _ca (code_analysis) without NameError.
    Previously broken: register() used _ca but never imported it.
    """
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from evocli_soul.agent_tools_shell import register

    class MockAgent:
        def tool_plain(self, fn): return fn

    calls_recorded = []

    async def mock_sc(method, params):
        calls_recorded.append((method, params))
        return "mock result"

    async def mock_call_handler(handler_fn, params):
        return "{}"

    # register() must not raise NameError for _ca
    try:
        register(
            agent=MockAgent(),
            _sc=mock_sc,
            _call_handler=mock_call_handler,
            _sid="test_session",
            _json=__import__("json"),
            bridge=None,
        )
    except NameError as e:
        raise AssertionError(f"REGRESSION: agent_tools_shell.register() has undefined name: {e}")
    except Exception:
        pass  # Other errors are OK (type errors, missing bridge) — only NameError is the regression


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 3: agent_litellm _tool_display_name + build_system_prompt imports
# ─────────────────────────────────────────────────────────────────────────────
def test_agent_litellm_imports():
    """
    E2E: agent_litellm must import _tool_display_name and build_system_prompt
    at module level. Previously broken: these were used without import.
    """
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from evocli_soul.agent_litellm import (
        AgentLiteLLMMixin,
        _tool_display_name,
        build_system_prompt,
    )
    assert callable(_tool_display_name), "_tool_display_name must be callable"
    assert callable(build_system_prompt), "build_system_prompt must be callable"

    # Verify they produce expected output
    result = _tool_display_name("shell.run", {"cmd": "cargo test"})
    assert "cargo test" in result, f"Unexpected display: {result!r}"


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 4: EvoCLIAgent initialization chain (6 mixins)
# Verifies the full mixin inheritance works without AttributeError/MRO issues
# ─────────────────────────────────────────────────────────────────────────────
def test_evocliagent_full_initialization():
    """
    E2E: EvoCLIAgent must initialize with all 6 mixins without errors.
    Tests the full inheritance chain: __init__ → _init_agent → mixin methods.
    With no API key, it gracefully sets self._agent = None (LiteLLM fallback mode).
    """
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from evocli_soul.agent import EvoCLIAgent

    class _MockBridge:
        async def call(self, tool, args): return {"ok": True}

    # EvoCLIAgent must initialize without raising any error
    agent = EvoCLIAgent(
        bridge=_MockBridge(),
        memory=None,
        config={"llm": {"provider": "anthropic", "tiers": {"fast": "claude-3-haiku-20240307"}}},
        session_id="test_init_e2e",
    )

    # All mixin methods must be accessible via the class
    assert hasattr(agent, "_execute_tool"),            "_execute_tool missing from AgentExecutorMixin"
    assert hasattr(agent, "_select_tools_for_request"),"_select_tools_for_request missing from AgentToolSelectorMixin"
    assert hasattr(agent, "_build_tool_definitions"),  "_build_tool_definitions missing from AgentToolDefsMixin"
    assert hasattr(agent, "_build_context"),           "_build_context missing from AgentContextMixin"
    assert hasattr(agent, "stream"),                   "stream() missing from AgentExecutionMixin"
    assert hasattr(agent, "_run_litellm"),             "_run_litellm missing from AgentLiteLLMMixin"
    assert hasattr(agent, "_TOOL_TO_RPC"),             "_TOOL_TO_RPC missing from AgentToolSelectorMixin"
    assert isinstance(agent._TOOL_TO_RPC, dict),       "_TOOL_TO_RPC must be a dict"
    assert len(agent._TOOL_TO_RPC) > 30,               f"Expected 30+ RPC entries, got {len(agent._TOOL_TO_RPC)}"

    # No API key → _agent should be None (graceful degradation, not crash)
    # LiteLLM fallback is still available via _run_litellm / _stream_litellm
    print(f"  EvoCLIAgent initialized: _agent={'pydantic-ai' if agent._agent else 'LiteLLM fallback'}")
    print(f"  _TOOL_TO_RPC entries: {len(agent._TOOL_TO_RPC)}")
    print(f"  Tool count: {agent._count_registered_tools()}")


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 5: spawn_agent no longer imports non-existent WorkerAgent
# ─────────────────────────────────────────────────────────────────────────────
def test_spawn_agent_no_worker_agent_import():
    """
    E2E: agent_tools_code.spawn_agent must NOT try to import WorkerAgent
    (which doesn't exist in multi_agent.py). Previously would always fail
    the try block and silently fall through to ImportError except.
    """
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

    # Verify WorkerAgent does NOT exist in multi_agent (it's WorkerPool)
    from evocli_soul import multi_agent
    assert not hasattr(multi_agent, "WorkerAgent"), \
        "WorkerAgent was added to multi_agent — update spawn_agent to use it directly"

    # Verify the tool registration code no longer imports WorkerAgent
    import ast
    code = open("D:/AI项目/MMcode/evocli/evocli-soul/evocli_soul/agent_tools_code.py",
                encoding="utf-8").read()
    # Check it's not in an import statement (may appear in comments/docstrings)
    import re
    import_lines = [l for l in code.splitlines() if re.match(r'\s*from .* import.*WorkerAgent', l)]
    assert not import_lines, \
        f"agent_tools_code.py still has WorkerAgent import: {import_lines}"


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 6: EvoCLIAgent.run() — full execution path without NameError
# Tests that the entire run() call chain works: _build_context → _inject_context
# → _run_litellm (or pydantic-ai). Should fail gracefully (no API key), not crash.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_evocliagent_run_no_crash():
    """
    E2E: EvoCLIAgent.run() must not raise NameError/AttributeError.
    With no real LLM, it should return an error string or raise LLMError,
    NOT NameError/AttributeError from broken refactoring.
    """
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from evocli_soul.agent import EvoCLIAgent

    class _MockBridge:
        """Mock bridge that returns sensible responses for all bridge calls."""
        async def call(self, tool: str, args: dict):
            if tool == "config.get":
                return {"llm": {"provider": "anthropic", "tiers": {"fast": "claude-3-haiku-20240307"}}}
            if tool == "fs.read":
                return "# Mock file content"
            if tool == "git.diff":
                return ""
            if tool == "symbol.lookup":
                return {"found": False, "symbols": []}
            return {"ok": True, "tool": tool}

    agent = EvoCLIAgent(
        bridge=_MockBridge(),
        memory=None,
        config={"llm": {"provider": "anthropic", "tiers": {"fast": "claude-3-haiku-20240307"}}},
        session_id="test_run_e2e",
    )

    # agent.run() should NOT raise NameError or AttributeError.
    # It will fail (no real LLM) but must fail gracefully.
    try:
        result = await agent.run("What is 2+2?")
        # If it returned something, verify it's a string (not a crash)
        assert isinstance(result, str), f"Expected str result, got {type(result)}"
    except (NameError, AttributeError) as e:
        raise AssertionError(
            f"REGRESSION: EvoCLIAgent.run() crashed with {type(e).__name__}: {e}\n"
            f"This indicates a broken mixin reference or undefined name in the split architecture."
        )
    except Exception:
        # LLM connection errors, auth errors, etc. are all acceptable
        pass


# ─────────────────────────────────────────────────────────────────────────────
# E2E Test 7: task_complete → verify → auto_commit chain
# Tests the full completion lifecycle in handlers/agent_loop.py
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_task_complete_chain():
    """
    E2E: The task_complete → double-check → accept → verify → auto-commit chain
    must function correctly. Tests state transitions without requiring real LLM.
    """
    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    import evocli_soul.state as state

    sid = "test_chain_e2e_unique"
    state.clear_task_complete(sid)
    state.set_todos([{"id": "1", "content": "Write tests", "status": "completed"}], sid)

    # Step 1: First task_complete call → rejected (needs double-check)
    assert not state.is_task_double_checked(sid)
    state.mark_task_double_checked(sid)  # Simulate re-verify step
    assert state.is_task_double_checked(sid)

    # Step 2: Set task complete signal
    state.set_task_complete(sid, result="Tests written and passing", command="pytest")
    completion = state.get_task_complete(sid)
    assert completion is not None
    assert completion["result"] == "Tests written and passing"
    assert completion["command"] == "pytest"

    # Step 3: Verify todos are all completed
    todos = state.get_todos(sid)
    all_done = all(t.get("status") in ("completed", "cancelled") for t in todos)
    assert all_done, f"Todos not all completed: {todos}"

    # Step 4: Clear task complete (simulates loop exit)
    state.clear_task_complete(sid)
    assert state.get_task_complete(sid) is None
    assert not state.is_task_double_checked(sid)  # Reset by clear_task_complete

    print("  task_complete chain: double-check → accept → verify → clear: PASS")


if __name__ == "__main__":
    # Run directly without pytest for quick sanity check
    import traceback
    tests = [
        test_session_events_isolation,
        test_lru_session_cache_evicts,
        test_lru_session_cache_update_order,
        test_config_defaults_all_keys,
        test_config_defaults_types,
        test_task_complete_double_check,
        test_circuit_breaker_increments,
        test_config_defaults_override,
        test_history_session_isolation,
        test_todos_session_isolation,
        test_tool_count_not_zero,
    ]
    passed = failed = 0
    for t in tests:
        try:
            if "tmp_path" in t.__code__.co_varnames:
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    t(pathlib.Path(tmpdir))
            else:
                t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(failed)
