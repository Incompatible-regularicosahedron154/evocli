"""
tests/integration/test_context_and_repo.py — context_mentions + repo_map smoke tests

Covers:
  - context_mentions.parse_mentions (@file, @url, @terminal, @diff, @problems)
  - context_summary.compact_session_to_anchor (session compression)
  - repo_map.RepoMap smoke (does not crash, returns string)
  - handlers/edit.py handle_apply_search_replace + handle_lint_file
"""
from __future__ import annotations
import asyncio, pathlib, sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))


# ── context_mentions tests ────────────────────────────────────────────────────

class _MockBridgeForMentions:
    def __init__(self):
        self.calls: list = []

    async def call(self, tool: str, args: dict):
        self.calls.append((tool, args))
        if tool == "fs.read":
            return f"# Content of {args.get('path', 'file')}\ncode here"
        if tool == "web.fetch":
            return "Mock web page content"
        if tool == "git.diff":
            return "--- a/file.rs\n+++ b/file.rs\n@@ -1 +1 @@\n-old\n+new"
        return {"ok": True}


class TestParseMentions:
    @pytest.mark.asyncio
    async def test_file_mention_injects_content(self):
        from evocli_soul.context_mentions import parse_mentions
        bridge = _MockBridgeForMentions()
        cleaned, injected = await parse_mentions(bridge, "Read @file:src/main.rs please")
        assert "@file:src/main.rs" not in cleaned  # removed from prompt
        assert len(injected) > 0
        key = list(injected.keys())[0]
        assert "main.rs" in key

    @pytest.mark.asyncio
    async def test_file_mention_calls_bridge(self):
        from evocli_soul.context_mentions import parse_mentions
        bridge = _MockBridgeForMentions()
        await parse_mentions(bridge, "Look at @file:auth.rs")
        read_calls = [c for c in bridge.calls if c[0] == "fs.read"]
        assert read_calls, "fs.read was not called for @file mention"

    @pytest.mark.asyncio
    async def test_terminal_mention_handled(self):
        from evocli_soul.context_mentions import parse_mentions
        import evocli_soul.state as st
        st.set_terminal_output("$ cargo test\nrunning 5 tests\ntest result: ok")
        bridge = _MockBridgeForMentions()
        cleaned, injected = await parse_mentions(bridge, "Check @terminal output")
        assert "@terminal" not in cleaned
        # terminal context should be in injected OR cleaned
        has_terminal = "terminal" in str(injected).lower() or "terminal" in cleaned.lower()
        assert has_terminal

    @pytest.mark.asyncio
    async def test_diff_mention_calls_git_diff(self):
        from evocli_soul.context_mentions import parse_mentions
        bridge = _MockBridgeForMentions()
        cleaned, injected = await parse_mentions(bridge, "Review @diff changes")
        assert "@diff" not in cleaned
        diff_calls = [c for c in bridge.calls if c[0] == "git.diff"]
        assert diff_calls

    @pytest.mark.asyncio
    async def test_problems_mention_handled(self):
        from evocli_soul.context_mentions import parse_mentions
        bridge = _MockBridgeForMentions()
        cleaned, injected = await parse_mentions(bridge, "Fix the @problems")
        assert "@problems" not in cleaned
        assert "problems" in str(injected).lower() or len(injected) > 0

    @pytest.mark.asyncio
    async def test_no_mentions_returns_original(self):
        from evocli_soul.context_mentions import parse_mentions
        bridge = _MockBridgeForMentions()
        original = "Just a normal message with no mentions"
        cleaned, injected = await parse_mentions(bridge, original)
        assert cleaned == original
        assert injected == {}

    @pytest.mark.asyncio
    async def test_multiple_file_mentions(self):
        from evocli_soul.context_mentions import parse_mentions
        bridge = _MockBridgeForMentions()
        cleaned, injected = await parse_mentions(bridge,
            "Compare @file:src/auth.rs and @file:src/user.rs")
        assert "@file:" not in cleaned
        assert len(injected) == 2  # both files injected


# ── context_summary tests ─────────────────────────────────────────────────────

class TestCompactSessionToAnchor:
    @pytest.mark.asyncio
    async def test_compact_empty_history(self):
        from evocli_soul.context_summary import compact_session_to_anchor

        class _MockLLM:
            async def complete_for_task(self, task, prompt, **kw):
                return f"## Goal\nTest session\n## Progress\n### Done\n- Nothing\n"

        result = await compact_session_to_anchor([], _MockLLM())
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_compact_with_history(self):
        from evocli_soul.context_summary import compact_session_to_anchor

        class _MockLLM:
            async def complete_for_task(self, task, prompt, system=None, **kw):
                return "## Goal\nFix auth bug\n## Progress\n### Done\n- Fixed JWT\n"

        history = [
            {"role": "user",      "content": "Fix the JWT bug"},
            {"role": "assistant", "content": "I'll analyze the auth code"},
            {"role": "user",      "content": "Now write the fix"},
            {"role": "assistant", "content": "Done, here's the fix: ..."},
        ]
        result = await compact_session_to_anchor(history, _MockLLM())
        assert "Goal" in result or len(result) > 0

    @pytest.mark.asyncio
    async def test_compact_with_existing_summary_updates_it(self):
        from evocli_soul.context_summary import compact_session_to_anchor

        prompts_received = []
        class _MockLLM:
            async def complete_for_task(self, task, prompt, system=None, **kw):
                prompts_received.append(prompt)
                return "## Goal\nUpdated goal\n"

        existing = "## Goal\nOld goal\n"
        history  = [{"role": "user", "content": "New work done"}]
        await compact_session_to_anchor(history, _MockLLM(), existing_summary=existing)
        assert prompts_received, "LLM was not called"
        # Should mention the existing summary in the prompt
        assert "Old goal" in prompts_received[0] or "existing" in prompts_received[0].lower()

    @pytest.mark.asyncio
    async def test_compact_llm_failure_returns_fallback(self):
        from evocli_soul.context_summary import compact_session_to_anchor

        class _FailingLLM:
            async def complete_for_task(self, *a, **kw):
                raise RuntimeError("LLM unavailable")

        history = [{"role": "user", "content": "msg1"}, {"role": "assistant", "content": "resp1"}]
        result  = await compact_session_to_anchor(history, _FailingLLM())
        assert isinstance(result, str)
        assert len(result) > 0  # fallback returns last messages as plain text


# ── repo_map smoke test ───────────────────────────────────────────────────────

class TestRepoMapSmoke:
    def test_repo_map_no_crash_empty_files(self):
        """RepoMap must not crash when given empty file lists."""
        try:
            from evocli_soul.repo_map import RepoMap
            rm = RepoMap(root=".", map_tokens=500)
            result = rm.get_repo_map(chat_files=[], mentioned_symbols=[])
            # Should return None or empty string (no code to map)
            assert result is None or isinstance(result, str)
        except (ImportError, Exception) as e:
            if "networkx" in str(e).lower() or "tree_sitter" in str(e).lower():
                pytest.skip(f"RepoMap requires optional deps: {e}")
            raise

    def test_repo_map_instantiation(self):
        """RepoMap class must be importable and instantiable."""
        try:
            from evocli_soul.repo_map import RepoMap
            rm = RepoMap(root=".", map_tokens=1000)
            assert hasattr(rm, "get_repo_map")
        except ImportError as e:
            pytest.skip(f"RepoMap requires optional deps: {e}")


# ── handlers/edit.py tests ────────────────────────────────────────────────────

class _MockStateForEdit:
    def __init__(self):
        self._bridge = _MockBridgeForEdit()

    def get_bridge(self): return self._bridge


class _MockBridgeForEdit:
    def __init__(self):
        self._content = {
            "src/auth.rs": "pub fn authenticate(token: &str) -> bool {\n    true\n}\n"
        }
        self.calls: list = []

    async def call(self, tool: str, args: dict):
        self.calls.append((tool, args))
        if tool == "fs.read":
            path = args.get("path", "")
            return self._content.get(path, "")
        if tool == "fs.write":
            path    = args.get("path", "")
            content = args.get("content", "")
            self._content[path] = content
            return {"ok": True, "path": path}
        if tool == "shell.run":
            return {"ok": True, "stdout": "No errors", "stderr": "", "exit_code": 0}
        return {"ok": True}


class _EditCapture:
    def __init__(self):
        self.responses: list = []
        self.errors:    list = []

    async def response(self, req_id: str, data): self.responses.append(data)
    async def error(self, req_id: str, code: int, msg: str):
        self.errors.append({"code": code, "message": msg})


class TestHandleApplySearchReplace:
    @pytest.mark.asyncio
    async def test_valid_replacement(self):
        from evocli_soul.handlers.edit import handle_apply_search_replace
        state = _MockStateForEdit()
        send  = _EditCapture()
        await handle_apply_search_replace("req_sr1", {
            "path":    "src/auth.rs",
            "search":  "    true\n",
            "replace": "    validate(token)\n",
        }, send, state)
        # Should succeed (no error)
        assert not send.errors, f"Unexpected error: {send.errors}"

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self):
        from evocli_soul.handlers.edit import handle_apply_search_replace
        state = _MockStateForEdit()
        send  = _EditCapture()
        await handle_apply_search_replace("req_sr2", {
            "search":  "something",
            "replace": "other",
        }, send, state)
        assert send.errors, "Expected error for missing path"
        assert send.errors[0]["code"] == -32600

    @pytest.mark.asyncio
    async def test_lint_file_handler(self):
        from evocli_soul.handlers.edit import handle_lint_file
        state = _MockStateForEdit()
        send  = _EditCapture()
        await handle_lint_file("req_lint1", {
            "path": "src/auth.rs",
        }, send, state)
        # Should either succeed or fail gracefully (no crash)
        assert send.responses or send.errors

    @pytest.mark.asyncio
    async def test_lint_missing_path_error(self):
        from evocli_soul.handlers.edit import handle_lint_file
        state = _MockStateForEdit()
        send  = _EditCapture()
        await handle_lint_file("req_lint2", {}, send, state)
        assert send.errors, "Expected error for missing path"
