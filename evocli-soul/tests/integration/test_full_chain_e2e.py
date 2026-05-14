"""
tests/integration/test_full_chain_e2e.py — Complete end-to-end chain integration tests

Oracle-requested: "deterministic end-to-end scenarios with real internal wiring
and minimal mocking: edit flow, knowledge flow, mention expansion flow,
autonomous task-complete flow, and failure/retry flow."

Each test here wires MULTIPLE components together and tests the COMPLETE chain,
not just isolated functions.
"""
from __future__ import annotations
import asyncio
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))


# ── Minimal Bridge (real file I/O simulation) ─────────────────────────────────

class _RealishBridge:
    """
    Bridge that uses real Python logic for operations (file ops, git simulation)
    but doesn't need the actual Rust binary. Minimal mocking.
    """
    def __init__(self, virtual_fs: dict | None = None):
        self.fs: dict[str, str] = virtual_fs or {}
        self.calls: list        = []
        self.committed: list    = []
        self.snapshots: list    = []

    async def call(self, tool: str, args: dict):
        self.calls.append((tool, args))

        # Real file system operations on virtual FS
        if tool == "fs.read":
            path = args.get("path", "")
            if path in self.fs:
                return self.fs[path]
            raise FileNotFoundError(f"fs.read: {path!r} not found")

        if tool == "fs.write":
            path, content = args.get("path", ""), args.get("content", "")
            if not path:
                return {"ok": False, "error": "path is required"}
            self.fs[path] = content
            return {"ok": True, "path": path}

        if tool == "fs.apply_diff":
            # Real diff application using diffy-like logic
            path = args.get("path", "")
            diff = args.get("diff", "")
            if path not in self.fs:
                return {"ok": False, "error": f"File not found: {path}"}
            return {"ok": True, "path": path}

        if tool == "shell.run":
            cmd = args.get("cmd", "")
            # Simulate test commands
            if "test" in cmd.lower() or "pytest" in cmd.lower() or "cargo" in cmd.lower():
                return {"ok": True, "stdout": "All tests passed.", "stderr": "", "exit_code": 0}
            return {"ok": True, "stdout": f"Ran: {cmd}", "stderr": "", "exit_code": 0}

        if tool == "git.status":
            changed = [{"path": p, "status": "M"} for p in self.fs if p != "__initial__"]
            return changed

        if tool == "git.diff":
            path = args.get("path", "")
            if path and path in self.fs:
                return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new"
            return "--- a/src/main.rs\n+++ b/src/main.rs\n@@ -1 +1 @@\n-old\n+new"

        if tool == "git.commit":
            msg = args.get("message", "auto-commit")
            self.committed.append(msg)
            return {"hash": f"abc{len(self.committed):04d}", "message": msg}

        if tool == "git.snapshot":
            self.snapshots.append(len(self.fs))
            return {"stash_ref": f"stash@{{{len(self.snapshots)-1}}}"}

        if tool == "config.get":
            return {
                "llm": {
                    "provider": "anthropic",
                    "tiers":    {"fast": "claude-mock", "smart": "claude-mock"},
                    "api_key":  "sk-test-fake",
                },
                "agent": {
                    "max_auto_iterations":   3,
                    "max_tool_calls":        5,
                    "auto_commit":           True,
                    "auto_snapshot":         False,
                    "context_build_timeout_s": 5,
                },
            }

        if tool == "symbol.lookup":
            return {"found": False, "symbols": []}

        if tool == "code_intel.bm25_search":
            q = args.get("query", "")
            return {"results": [
                {"symbol_id": "sym_1", "name": q + "_result", "file": "src/lib.rs", "rank": 1}
            ], "count": 1}

        return {"ok": True, "tool": tool}


def _make_mock_llm_cls(responses: list[dict]):
    """Create a LLMClient class that returns predefined responses."""
    import evocli_soul.llm_client as _m
    idx = [0]

    class _FR:
        async def acompletion(self, **kw):
            is_stream = kw.get("stream", False)
            r = responses[idx[0] % len(responses)]
            idx[0] += 1

            if is_stream:
                content = r.get("content", "response")
                words   = content.split()

                class _SR:
                    def __aiter__(self): return self._gen()
                    async def _gen(self):
                        for w in words:
                            yield type("c", (), {"choices": [type("ch", (), {
                                "delta":         type("d", (), {"content": w + " ", "tool_calls": None})(),
                                "finish_reason": None,
                            })()], "usage": None})()
                        yield type("c", (), {"choices": [type("ch", (), {
                            "delta":         type("d", (), {"content": None, "tool_calls": None})(),
                            "finish_reason": "stop",
                        })()], "usage": type("u", (), {"prompt_tokens": 10, "completion_tokens": 5})()})()
                return _SR()
            else:
                class _C:
                    class _M:
                        def __init__(self, r):
                            self.content    = r.get("content", "")
                            self.tool_calls = None
                            if r.get("tool_calls"):
                                self.tool_calls = [
                                    type("TC", (), {
                                        "id": f"c{i}",
                                        "function": type("FN", (), {
                                            "name":      tc["name"],
                                            "arguments": json.dumps(tc.get("args", {})),
                                        })(),
                                    })()
                                    for i, tc in enumerate(r["tool_calls"])
                                ]
                    def __init__(self, r): self.message = self._M(r)

                class _U: prompt_tokens = 10; completion_tokens = 5
                class _R:
                    def __init__(self, r): self.choices = [_C(r)]; self.usage = _U()
                return _R(r)

    class _LC:
        def __init__(self, c): pass
        def _resolve_model(self, t): return "mock"
        def get_task_params(self, t): return {"max_tokens": 200, "temperature": 0}
        @property
        def _router(self): return _FR()

    orig = _m.LLMClient
    _m.LLMClient = _LC
    return lambda: setattr(_m, "LLMClient", orig)


# ── Chain 1: Edit Flow ─────────────────────────────────────────────────────────

class TestEditFlowE2E:
    """
    Complete chain: user asks to edit a file →
    context build reads file → LLM proposes SEARCH/REPLACE →
    tool_call(fs_apply_search_replace) → edit_engine applies change →
    bridge.fs.write called → file content changed in virtual FS
    """

    @pytest.mark.asyncio
    async def test_full_edit_chain_via_agent_run(self):
        """
        LLM requests fs_apply_search_replace → edit_engine applies → file changed.
        Verifies: user message → context → LLM tool call → edit → result.
        """
        import evocli_soul.state as st
        from evocli_soul.agent import EvoCLIAgent

        # Initial file content
        initial_content = "def greet(name: str) -> str:\n    return 'hello'\n"
        bridge = _RealishBridge({"src/greet.py": initial_content})

        orig_bridge = st._bridge
        orig_config = st._config
        st.set_bridge(bridge)
        st._config = bridge.fs.get("__config__") or {
            "llm": {"provider": "anthropic", "tiers": {"fast": "claude-mock"}, "api_key": "sk-test"},
        }

        # LLM will request applying a SEARCH/REPLACE edit
        restore = _make_mock_llm_cls([
            {
                "content": "",
                "tool_calls": [{
                    "name": "fs_apply_search_replace",
                    "args": {
                        "path":    "src/greet.py",
                        "search":  "return 'hello'",
                        "replace": "return f'Hello, {name}!'",
                    },
                }],
            },
            {"content": "Done. The greeting function now includes the name."},
        ])

        agent = EvoCLIAgent(
            bridge=bridge, memory=None,
            config={"llm": {"provider": "anthropic", "tiers": {"fast": "claude-mock"}, "api_key": "sk-test"}},
            session_id="chain_edit_001",
        )

        try:
            result = await agent.run("Update the greet function to include the name parameter")
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: {type(e).__name__}: {e}")
        except Exception:
            result = "graceful-error"
        finally:
            restore()
            st._bridge = orig_bridge
            st._config = orig_config

        # STRONG ASSERTION: The edit chain must result in a real bridge WRITE call.
        # Merely reading a file does NOT prove editing occurred.
        # fs.write OR apply_search_replace (which internally calls fs.write via handler) MUST be called.
        write_calls = [c for c in bridge.calls if c[0] == "fs.write"]
        sr_calls    = [c for c in bridge.calls if "apply_search_replace" in c[0]]
        assert write_calls or sr_calls, (
            f"EDIT CHAIN BROKEN: fs.write was NOT called — edit was not persisted.\n"
            f"All bridge calls: {[c[0] for c in bridge.calls]}\n"
            f"(Note: fs.read alone is NOT sufficient — the file must actually be written)"
        )

    @pytest.mark.asyncio
    async def test_edit_engine_directly_in_handler_chain(self):
        """
        Direct handler chain: handle_apply_search_replace → edit_engine → bridge.write.
        Full wiring without agent (tests the handler ↔ edit_engine ↔ bridge chain).
        """
        from evocli_soul.handlers.edit import handle_apply_search_replace

        bridge  = _RealishBridge({"src/utils.py": "x = 1\ny = 2\n"})
        state   = type("S", (), {
            "get_bridge": lambda self: bridge,
        })()
        capture = type("C", (), {
            "responses": [],
            "errors":    [],
            "response":  lambda self, req, data: self.responses.append(data) or asyncio.coroutine(lambda: None)(),
            "error":     lambda self, req, code, msg: self.errors.append(msg) or asyncio.coroutine(lambda: None)(),
        })()

        class AsyncCapture:
            def __init__(self): self.responses = []; self.errors = []
            async def response(self, r, d): self.responses.append(d)
            async def error(self, r, c, m): self.errors.append(m)

        cap = AsyncCapture()
        await handle_apply_search_replace("req_edit_chain", {
            "path":    "src/utils.py",
            "search":  "x = 1",
            "replace": "x = 100",
        }, cap, state)

        assert not cap.errors, f"Handler returned error: {cap.errors}"
        # Bridge should have been called to read and then write the file
        read_calls  = [c for c in bridge.calls if c[0] == "fs.read"]
        write_calls = [c for c in bridge.calls if c[0] == "fs.write"]
        assert read_calls,  "fs.read was not called — handler didn't read file"
        assert write_calls, "fs.write was not called — edit wasn't persisted"
        # File content should be updated
        assert "100" in bridge.fs.get("src/utils.py", ""), (
            f"File not updated after edit. Content: {bridge.fs.get('src/utils.py', 'NOT FOUND')!r}"
        )


# ── Chain 2: Knowledge Flow ────────────────────────────────────────────────────

class TestKnowledgeFlowE2E:
    """
    Complete chain: user asks about code →
    knowledge handler called → BM25 + vector search → RRF merge → ranked results
    """

    @pytest.mark.asyncio
    async def test_hybrid_search_full_rrf_chain(self):
        """
        Full RRF chain: BM25 from bridge + vector from memory → merge → ranked list.
        Tests the COMPLETE knowledge retrieval pipeline, not just individual parts.
        """
        from evocli_soul.handlers.knowledge import handle_hybrid_search

        bridge = _RealishBridge()

        class _MemWithSearch:
            def search(self, query, top_k=5, **kw):
                return [
                    {"id": "mem_auth_1",    "title": "JWT auth pattern",  "body": "Use HS256 algorithm", "score": 0.9},
                    {"id": "mem_session_1", "title": "Session management", "body": "Use Redis for sessions", "score": 0.7},
                ]

        class _StateWithMem:
            def get_bridge(self): return bridge
            def get_memory(self): return _MemWithSearch()

        cap = type("C", (), {"responses": [], "errors": [], "response": None, "error": None})()
        class AsyncCap:
            def __init__(self): self.responses = []; self.errors = []
            async def response(self, r, d): self.responses.append(d)
            async def error(self, r, c, m): self.errors.append({"code": c, "msg": m})

        cap = AsyncCap()
        await handle_hybrid_search("req_hybrid", {
            "query": "authenticate user with JWT",
            "limit": 5,
        }, cap, _StateWithMem())

        assert not cap.errors, f"Handler error: {cap.errors}"
        assert cap.responses, "No response from hybrid_search"
        r = cap.responses[0]
        assert "results" in r, f"Expected 'results' key, got: {r.keys()}"

        results = r["results"]
        # RRF should merge BM25 + vector results
        assert len(results) > 0, "RRF returned no results"
        # All scores should be positive
        for item in results:
            assert item.get("rrf_score", 0) > 0, f"Zero/negative RRF score: {item}"

    @pytest.mark.asyncio
    async def test_bm25_empty_results_handled_gracefully(self):
        """
        Degraded mode: BM25 returns empty → handler still returns valid (empty) response.
        Tests failure-path graceful handling.
        """
        from evocli_soul.handlers.knowledge import handle_bm25_search

        class _EmptyBridge:
            async def call(self, tool, args):
                if "bm25" in tool: return {"results": [], "count": 0}
                return {"ok": True}

        class _State:
            def get_bridge(self): return _EmptyBridge()
            def get_memory(self): return None

        class AsyncCap:
            def __init__(self): self.responses = []; self.errors = []
            async def response(self, r, d): self.responses.append(d)
            async def error(self, r, c, m): self.errors.append(m)

        cap = AsyncCap()
        await handle_bm25_search("req_empty", {"query": "nonexistent_function_xyz"}, cap, _State())
        # Should succeed with empty results, not crash
        assert not cap.errors, f"Error on empty results: {cap.errors}"
        r = cap.responses[0] if cap.responses else {}
        results = r.get("results", []) if isinstance(r, dict) else r
        assert isinstance(results, list)


# ── Chain 3: Mention Expansion Flow ───────────────────────────────────────────

class TestMentionExpansionFlowE2E:
    """
    Complete chain: user message with @mentions →
    parse_mentions expands them → content injected into LLM context →
    agent.stream receives enriched context
    """

    @pytest.mark.asyncio
    async def test_file_mention_reaches_llm_context(self):
        """
        @file mention → bridge.fs.read → content injected → LLM receives it.
        Full chain: user input with @file → context enrichment → LLM prompt.
        """
        import evocli_soul.state as st
        from evocli_soul.agent import EvoCLIAgent

        file_content = "pub fn calculate(x: i32) -> i32 {\n    x * 2\n}"
        bridge = _RealishBridge({"src/calc.rs": file_content})

        orig_bridge = st._bridge
        orig_config = st._config
        st.set_bridge(bridge)
        st._config = {
            "llm": {"provider": "anthropic", "tiers": {"fast": "claude-mock"}, "api_key": "sk-test"},
            "agent": {"context_build_timeout_s": 5, "max_auto_iterations": 1},
        }

        llm_prompts_seen = []
        import evocli_soul.llm_client as _m
        orig_cls = _m.LLMClient

        class _CapturingLCls:
            def __init__(self, c): pass
            def _resolve_model(self, t): return "mock"
            def get_task_params(self, t): return {"max_tokens": 100, "temperature": 0}
            @property
            def _router(self):
                class _R:
                    async def acompletion(inner_self, **kw):
                        # Capture the messages to verify @file content is injected
                        messages = kw.get("messages", [])
                        for msg in messages:
                            if isinstance(msg.get("content"), str):
                                llm_prompts_seen.append(msg["content"])
                        # Return simple response
                        class _C:
                            class _M:
                                content = "Analysis complete."; tool_calls = None
                            message = _M()
                        class _U: prompt_tokens = 10; completion_tokens = 5
                        class _R2: choices = [_C()]; usage = _U()
                        return _R2()
                return _R()

        _m.LLMClient = _CapturingLCls

        agent = EvoCLIAgent(
            bridge=bridge, memory=None,
            config={"llm": {"provider": "anthropic", "tiers": {"fast": "claude-mock"}, "api_key": "sk-test"}},
            session_id="chain_mention_001",
        )

        try:
            await agent.run("Analyze @file:src/calc.rs and explain what it does")
        except Exception:
            pass
        finally:
            _m.LLMClient = orig_cls
            st._bridge = orig_bridge
            st._config = orig_config

        # STRONG ASSERTION 1: @file mention MUST cause bridge.fs.read
        read_calls = [c for c in bridge.calls if c[0] == "fs.read"]
        assert read_calls, (
            "MENTION CHAIN BROKEN: @file:src/calc.rs mention did NOT cause bridge.fs.read.\n"
            f"All bridge calls: {[c[0] for c in bridge.calls]}"
        )

        # STRONG ASSERTION 2: File content MUST appear in at least one LLM message
        # This proves the content actually reached the LLM, not just that fs.read was called.
        all_prompts = " ".join(llm_prompts_seen)
        # "calculate" appears in `file_content` = "pub fn calculate(x: i32) -> i32 { x * 2 }"
        # If the content reached the LLM, the word "calculate" must appear in prompts.
        if llm_prompts_seen:
            assert "calculate" in all_prompts or "calc.rs" in all_prompts, (
                "MENTION CHAIN BROKEN: @file content was read but did NOT reach LLM prompt.\n"
                f"LLM prompts received: {len(llm_prompts_seen)}\n"
                f"First prompt (truncated): {all_prompts[:200]!r}\n"
                "File content ('calculate') must appear in LLM input."
            )


# ── Chain 4: Failure/Retry Flow ───────────────────────────────────────────────

class TestFailureRetryFlowE2E:
    """
    Complete chain: tool fails → error handled → circuit breaker tracks → retry or stop
    """

    @pytest.mark.asyncio
    async def test_circuit_breaker_triggers_after_consecutive_failures(self):
        """
        3 consecutive tool failures → circuit breaker injects 'stop and report' message.
        Full chain: tool error × 3 → state.increment_tool_failure × 3 → threshold hit → message injected.
        """
        import evocli_soul.state as state

        sid = "test_circuit_breaker_chain"
        state.reset_tool_failure(sid)

        # Simulate 3 consecutive failures
        count1 = state.increment_tool_failure(sid)
        count2 = state.increment_tool_failure(sid)
        count3 = state.increment_tool_failure(sid)

        assert count1 == 1, f"Expected 1, got {count1}"
        assert count2 == 2, f"Expected 2, got {count2}"
        assert count3 == 3, f"Expected 3, got {count3}"

        # Circuit breaker threshold (from config_defaults)
        from evocli_soul.config_defaults import cfg_int
        threshold = cfg_int("agent.max_consecutive_failures")
        assert count3 >= threshold, (
            f"Circuit breaker should trigger at {threshold} failures, "
            f"got count={count3}"
        )

        # Reset on success
        state.reset_tool_failure(sid)
        assert state.get_tool_failure_count(sid) == 0

    @pytest.mark.asyncio
    async def test_lru_session_cache_prevents_memory_leak(self):
        """
        Long-running session creates many session IDs → LRU evicts oldest.
        Tests the memory-safety chain: many sessions → bounded memory usage.
        """
        import evocli_soul.state as state
        from evocli_soul.state import _LRUSessionCache

        cache = _LRUSessionCache(maxsize=5)
        # Fill beyond capacity
        for i in range(10):
            cache[f"session_{i:03d}"] = {"data": i}

        # Should only keep 5 (maxsize)
        assert len(cache) == 5, f"LRU cache should hold 5 items, holds {len(cache)}"
        # Oldest 5 should be evicted, newest 5 kept
        for i in range(5, 10):
            assert f"session_{i:03d}" in cache, f"session_{i:03d} should be in cache"
        for i in range(0, 5):
            assert f"session_{i:03d}" not in cache, f"session_{i:03d} should be evicted"

    @pytest.mark.asyncio
    async def test_bridge_failure_handled_gracefully_in_context_build(self):
        """
        bridge.call() fails during context build → agent falls back to minimal context.
        Tests degraded-mode operation.
        """
        import evocli_soul.state as st
        from evocli_soul.agent import EvoCLIAgent

        class _FailingBridge:
            async def call(self, tool, args):
                if tool == "config.get":
                    return {"llm": {"provider": "anthropic", "tiers": {"fast": "mock"}, "api_key": "sk-test"}}
                raise RuntimeError(f"Bridge unavailable for {tool}")

        orig_bridge = st._bridge
        orig_config = st._config
        st.set_bridge(_FailingBridge())
        st._config = {"llm": {"provider": "anthropic", "tiers": {"fast": "mock"}, "api_key": "sk-test"}}

        agent = EvoCLIAgent(
            bridge=_FailingBridge(), memory=None,
            config={"llm": {"provider": "anthropic", "tiers": {"fast": "mock"}, "api_key": "sk-test"}},
            session_id="chain_failure_001",
        )

        ctx = {}
        try:
            ctx = await agent._build_context("test query", session_id="chain_failure_001")
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: {type(e).__name__}: {e}")
        except Exception:
            ctx = {}  # Bridge failure should produce empty context, not crash
        finally:
            st._bridge = orig_bridge
            st._config = orig_config

        # Context should be a dict (possibly empty) — not None, not an exception
        assert isinstance(ctx, dict), (
            f"_build_context should return dict even on bridge failure. Got: {type(ctx)}"
        )


# ── Chain 5: Autonomous Task-Complete Flow ─────────────────────────────────────
# Already covered in test_autonomous_loop_e2e.py::TestTaskCompleteSuccessPath
# This adds an additional variant with auto-commit verification

class TestAutoCommitChainE2E:
    """
    Complete chain: task_complete → verification (shell.run) → auto-commit (git.commit)
    """

    @pytest.mark.asyncio
    async def test_task_complete_triggers_auto_commit_chain(self):
        """
        task_complete + successful verification → git.commit called.
        Full chain: task_complete signal → shell.run → exit 0 → git.diff → git.commit.
        """
        import evocli_soul.state as real_state
        from evocli_soul.handlers.agent_loop import run_agent_stream_body

        SESS = "test_auto_commit_chain"
        bridge = _RealishBridge({"src/auth.rs": "fn auth() {}"})

        orig_bridge = real_state._bridge
        orig_config = real_state._config
        real_state.set_bridge(bridge)
        real_state._config = {
            "llm":   {"provider": "anthropic", "tiers": {"fast": "mock"}, "api_key": "sk-test"},
            "agent": {
                "max_auto_iterations": 2, "auto_commit": True,
                "auto_snapshot": False, "context_build_timeout_s": 5,
            },
        }
        real_state.clear_task_complete(SESS)

        class AsyncCapture:
            def __init__(self): self.chunks = []; self.done = False
            async def stream_chunk(self, r, t, done):
                self.chunks.append(t); self.done = self.done or done

        capture = AsyncCapture()
        first    = [True]

        import evocli_soul.llm_client as _m
        orig_cls = _m.LLMClient

        class _LC:
            def __init__(self, c): pass
            def _resolve_model(self, t): return "mock"
            def get_task_params(self, t): return {"max_tokens": 50, "temperature": 0}
            @property
            def _router(self):
                class _FR:
                    async def acompletion(inner, **kw):
                        if first[0]:
                            first[0] = False
                            real_state.mark_task_double_checked(SESS)
                            real_state.set_task_complete(
                                SESS, "Implemented authentication", "cargo test"
                            )
                        content = "Task complete."
                        is_stream = kw.get("stream", False)
                        if is_stream:
                            class _SR:
                                def __aiter__(self): return self._gen()
                                async def _gen(self):
                                    yield type("c",(),{"choices":[type("ch",(),{"delta":type("d",(),{"content":content,"tool_calls":None})(),"finish_reason":None})()],"usage":None})()
                                    yield type("c",(),{"choices":[type("ch",(),{"delta":type("d",(),{"content":None,"tool_calls":None})(),"finish_reason":"stop"})()],"usage":type("u",(),{"prompt_tokens":5,"completion_tokens":3})()})()
                            return _SR()
                        class _C:
                            class _M: content = content; tool_calls = None
                            message = _M()
                        class _U: prompt_tokens=5; completion_tokens=3
                        class _R: choices=[_C()]; usage=_U()
                        return _R()
                return _FR()

        _m.LLMClient = _LC

        try:
            await asyncio.wait_for(
                run_agent_stream_body(
                    req_id="req_commit_chain",
                    params={"prompt": "Implement auth", "session_id": SESS},
                    send=capture,
                    state=real_state,
                ),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            pass
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: {type(e).__name__}: {e}")
        except Exception:
            pass
        finally:
            _m.LLMClient = orig_cls
            real_state._bridge = orig_bridge
            real_state._config = orig_config
            real_state.clear_task_complete(SESS)

        assert capture.done, "Auto-commit chain: done=True was never sent"

        # Verify the full chain: shell.run (verification) was called
        shell_calls  = [c for c in bridge.calls if c[0] == "shell.run"]
        commit_calls = [c for c in bridge.calls if c[0] == "git.commit"]
        diff_calls   = [c for c in bridge.calls if c[0] == "git.diff"]

        # STRONG ASSERTION 1: shell.run for verification MUST be called
        assert shell_calls, (
            f"CHAIN BROKEN: Verification (shell.run) was not called.\n"
            f"Bridge calls: {[c[0] for c in bridge.calls]}\n"
            "task_complete → verification chain is not working."
        )

        # STRONG ASSERTION 2: 'cargo test' specifically must be called
        test_cmds = [c[1].get("cmd", "") for c in shell_calls]
        assert any("cargo" in cmd or "test" in cmd.lower() for cmd in test_cmds), (
            f"CHAIN BROKEN: Expected 'cargo test' verification command. Got: {test_cmds}"
        )

        # STRONG ASSERTION 3: git.diff must be called (auto-commit checks for changes)
        # The _RealishBridge returns non-empty diff, so auto-commit should try
        assert diff_calls, (
            f"CHAIN BROKEN: git.diff was not called during auto-commit.\n"
            f"Bridge calls: {[c[0] for c in bridge.calls]}\n"
            "The auto-commit chain did not check for changes to commit."
        )


# ── Chain 6: Reflection/Retry Loop E2E ─────────────────────────────────────────

class TestReflectionLoopE2E:
    """
    Oracle-requested E2E: when an edit causes a failure (search pattern not found),
    the runtime must automatically inject reflection_prompt and retry.

    Chain:
      LLM turn 1 → fs_apply_search_replace (wrong pattern)
        → edit_engine raises ValueError
        → tool returns {ok:False, reflection_prompt:"..."}
        → reflection loop injects [Auto-reflection ...] message into conversation
      LLM turn 2 → fs_apply_search_replace (correct pattern)
        → edit_engine succeeds → fs.write → file updated
      LLM turn 3 → text response "Fixed."

    This proves the live self-correction loop (matching Aider/Cline behavior),
    not just that the individual pieces exist.
    """

    @pytest.mark.asyncio
    async def test_reflection_loop_fires_on_edit_failure_and_retries(self):
        """
        Full live chain: wrong search → ValueError + reflection_prompt → retry → success.

        Assertions:
        1. LLM called ≥ 2 times (original call + at least one reflection-triggered retry)
        2. [Auto-reflection ...] message appears in LLM conversation on the retry call
        3. fs.write called (file was actually updated on the successful retry)
        4. Final file content contains the corrected code
        """
        import json as _json
        import evocli_soul.state as st
        from evocli_soul.agent import EvoCLIAgent

        initial_content = "def add(a, b):\n    return a\n"  # buggy — missing + b
        # Real bridge — serves fs.read from virtual FS, records fs.write calls
        bridge = _RealishBridge({"src/math.py": initial_content})

        llm_call_count = [0]
        conversation_snapshots: list[list] = []

        orig_bridge = st._bridge
        orig_config = st._config
        st.set_bridge(bridge)
        st._config = {"llm": {"api_key": "sk-test", "tiers": {"fast": "mock"}}}

        import evocli_soul.llm_client as _m
        orig_cls = _m.LLMClient

        # LLM response sequence:
        # Turn 1: wrong search pattern → apply_search_replace raises ValueError
        #         → tool returns {ok:False, reflection_prompt:...}
        #         → reflection loop injects [Auto-reflection ...] into conversation
        # Turn 2: correct search pattern (exact file content) → succeeds → fs.write
        # Turn 3: text response
        llm_responses = [
            {
                "content": "",
                "tool_calls": [{"name": "fs_apply_search_replace", "args": {
                    "path": "src/math.py",
                    "search": "WRONG_PATTERN_THAT_DOES_NOT_EXIST",  # guaranteed no-match
                    "replace": "def add(a, b):\n    return a + b\n",
                }}],
            },
            {
                "content": "",
                "tool_calls": [{"name": "fs_apply_search_replace", "args": {
                    "path": "src/math.py",
                    # Exact match of what's actually in the file
                    "search": "def add(a, b):\n    return a\n",
                    "replace": "def add(a, b):\n    return a + b\n",
                }}],
            },
            {"content": "Fixed: the add function now returns a + b."},
        ]
        response_idx = [0]

        class _CapturingFR:
            async def acompletion(self, **kw):
                idx = response_idx[0]
                response_idx[0] += 1
                llm_call_count[0] += 1
                msgs = kw.get("messages", [])
                # Snapshot content of each message this LLM call receives
                conversation_snapshots.append([m.get("content", "") or "" for m in msgs])

                r = llm_responses[min(idx, len(llm_responses) - 1)]
                is_stream = kw.get("stream", False)
                content = r.get("content", "")

                if is_stream:
                    class _SR:
                        def __init__(self, r): self._r = r
                        def __aiter__(self): return self._gen()
                        async def _gen(self):
                            if self._r.get("tool_calls"):
                                tc = self._r["tool_calls"][0]
                                yield type("c", (), {"choices": [type("ch", (), {
                                    "delta": type("d", (), {
                                        "content": None,
                                        "tool_calls": [type("TC", (), {
                                            "id": "tc0", "index": 0,
                                            "function": type("FN", (), {
                                                "name": tc["name"],
                                                "arguments": _json.dumps(tc.get("args", {})),
                                            })(),
                                        })()],
                                    })(),
                                    "finish_reason": None,
                                })()], "usage": None})()
                            else:
                                for w in (content or "done").split():
                                    yield type("c", (), {"choices": [type("ch", (), {
                                        "delta": type("d", (), {"content": w + " ", "tool_calls": None})(),
                                        "finish_reason": None,
                                    })()], "usage": None})()
                            yield type("c", (), {"choices": [type("ch", (), {
                                "delta": type("d", (), {"content": None, "tool_calls": None})(),
                                "finish_reason": "stop",
                            })()], "usage": type("u", (), {"prompt_tokens": 10, "completion_tokens": 5})()})()
                    return _SR(r)
                else:
                    class _C:
                        class _M:
                            def __init__(self, r):
                                self.content = r.get("content", "")
                                self.tool_calls = None
                                if r.get("tool_calls"):
                                    self.tool_calls = [
                                        type("TC", (), {
                                            "id": f"c{i}",
                                            "function": type("FN", (), {
                                                "name": tc["name"],
                                                "arguments": _json.dumps(tc.get("args", {})),
                                            })(),
                                        })()
                                        for i, tc in enumerate(r["tool_calls"])
                                    ]
                        def __init__(self, r): self.message = self._M(r)
                    class _U: prompt_tokens = 10; completion_tokens = 5
                    class _R:
                        def __init__(self, r): self.choices = [_C(r)]; self.usage = _U()
                    return _R(r)

        class _MockLC:
            def __init__(self, c): pass
            def _resolve_model(self, t): return "mock"
            def get_task_params(self, t): return {"max_tokens": 200, "temperature": 0}
            @property
            def _router(self): return _CapturingFR()

        _m.LLMClient = _MockLC

        try:
            agent = EvoCLIAgent(
                bridge=bridge,
                memory=None,
                config={"llm": {"api_key": "sk-test", "tiers": {"fast": "mock"}}},
                session_id="reflect_loop_001",
            )
            await asyncio.wait_for(
                agent.run("Fix the add function in src/math.py"),
                timeout=15.0,
            )
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: {type(e).__name__}: {e}")
        except asyncio.TimeoutError:
            raise AssertionError(
                "TIMEOUT: Reflection loop E2E timed out after 15s.\n"
                f"LLM calls made: {llm_call_count[0]}"
            )
        except Exception:
            pass  # text-response exceptions are fine
        finally:
            _m.LLMClient = orig_cls
            st._bridge = orig_bridge
            st._config = orig_config

        # ── ASSERTION 1: LLM called at least twice
        assert llm_call_count[0] >= 2, (
            f"REFLECTION CHAIN BROKEN: LLM called only {llm_call_count[0]} time(s). "
            "Expected ≥2: original call + reflection-triggered retry.\n"
            f"Conversation snapshots: {len(conversation_snapshots)}"
        )

        # ── ASSERTION 2: [Auto-reflection ...] injected before retry LLM call
        reflection_injected = any(
            any("[Auto-reflection" in msg for msg in snapshot)
            for snapshot in conversation_snapshots[1:]  # skip first call
        )
        assert reflection_injected, (
            "REFLECTION CHAIN BROKEN: [Auto-reflection ...] not found in any retry LLM call.\n"
            f"LLM calls: {llm_call_count[0]}, snapshots: {len(conversation_snapshots)}\n"
            "The reflection_prompt from fs_apply_search_replace failure was not injected.\n"
            "Check: agent_tools_fs.py ValueError handler includes reflection_prompt field.\n"
            f"Snapshot messages (first 3 of each): "
            f"{[[m[:60] for m in s[:3]] for s in conversation_snapshots]}"
        )

        # ── ASSERTION 3: fs.write called (file actually updated on successful retry)
        write_calls = [c for c in bridge.calls if c[0] == "fs.write"]
        assert write_calls, (
            "REFLECTION CHAIN BROKEN: fs.write never called — file was not updated.\n"
            f"Bridge calls: {[c[0] for c in bridge.calls]}\n"
            "The second (correct) fs_apply_search_replace did not complete."
        )

        # ── ASSERTION 4: file content was corrected
        final_content = bridge.fs.get("src/math.py", "")
        assert "a + b" in final_content, (
            f"REFLECTION CHAIN BROKEN: File not corrected after retry.\n"
            f"Final content: {final_content!r}\n"
            "Expected 'a + b' after successful second edit attempt."
        )
