"""
tests/unit/test_auto_commit.py — auto_commit.py generate_commit_message tests

Covers: Conventional Commit message generation with mock LLM,
        fallback behavior on LLM failure, message format validation.
"""
from __future__ import annotations
import asyncio, pathlib, sys, pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from evocli_soul.auto_commit import generate_commit_message, AI_COMMIT_PREFIX


class MockLLMClient:
    """Mock LLM client for testing commit message generation."""

    def __init__(self, response: str = "", should_fail: bool = False):
        self._response  = response
        self._fail      = should_fail
        self.calls: list = []

    async def complete_for_task(self, task: str, prompt: str, **kw) -> str:
        self.calls.append({"task": task, "prompt": prompt})  # store full prompt, not truncated
        if self._fail:
            raise RuntimeError("LLM connection failed")
        return self._response


class TestGenerateCommitMessage:

    @pytest.mark.asyncio
    async def test_basic_commit_message_generated(self):
        """Generate a valid Conventional Commit message from a diff."""
        diff = """--- a/src/auth.rs\n+++ b/src/auth.rs\n@@ -1,5 +1,10 @@\n+pub fn validate_jwt(token: &str) -> bool {\n+    // JWT validation logic\n+    true\n+}\n"""
        llm = MockLLMClient(response="feat(auth): add JWT token validation")
        msg = await generate_commit_message(diff, llm, goal="Add JWT auth")
        assert isinstance(msg, str)
        assert len(msg) > 0
        assert len(msg) <= 100  # Git subject line limit

    @pytest.mark.asyncio
    async def test_conventional_commit_prefix_preserved(self):
        """If LLM returns a message with correct prefix, it's kept."""
        llm = MockLLMClient(response="fix(memory): resolve session isolation bug")
        msg = await generate_commit_message("--- a/state.py\n+++ b/state.py\n", llm)
        assert msg.startswith("fix(") or msg.startswith("feat(") or msg.startswith("ai:")

    @pytest.mark.asyncio
    async def test_non_conventional_message_gets_prefix(self):
        """If LLM returns message without conventional prefix, AI_COMMIT_PREFIX is added."""
        llm = MockLLMClient(response="added some improvements")
        msg = await generate_commit_message("diff content", llm)
        # Should have a conventional prefix OR fallback prefix
        has_prefix = any(msg.startswith(p) for p in
                         ["feat", "fix", "refactor", "docs", "test", "chore",
                          "build", "ci", "style", "perf", AI_COMMIT_PREFIX])
        assert has_prefix, f"Expected conventional prefix, got: {msg!r}"

    @pytest.mark.asyncio
    async def test_llm_failure_returns_fallback(self):
        """If LLM fails, a reasonable fallback message is returned."""
        llm = MockLLMClient(should_fail=True)
        msg = await generate_commit_message("some diff", llm, goal="fix bug")
        assert isinstance(msg, str)
        assert len(msg) > 0  # Never empty
        assert not msg.startswith("Error")  # Should be a commit msg, not error

    @pytest.mark.asyncio
    async def test_empty_diff_returns_minor_message(self):
        """Empty diff produces a short fallback message."""
        llm = MockLLMClient(response="")
        msg = await generate_commit_message("", llm)
        assert isinstance(msg, str)
        assert len(msg) > 0

    @pytest.mark.asyncio
    async def test_message_under_100_chars(self):
        """Generated message must not exceed 100 characters (Git limit)."""
        # LLM returns a very long message
        long_msg = "feat(authentication): " + "x" * 200
        llm = MockLLMClient(response=long_msg)
        msg = await generate_commit_message("diff", llm)
        assert len(msg) <= 100

    @pytest.mark.asyncio
    async def test_goal_context_included_in_prompt(self):
        """The goal is passed to the LLM as context."""
        llm = MockLLMClient(response="feat: add feature")
        await generate_commit_message("diff content", llm, goal="Implement OAuth2 login")
        assert len(llm.calls) > 0
        # Goal should appear in the prompt
        prompt = llm.calls[0]["prompt"]
        assert "OAuth2" in prompt or "login" in prompt.lower()

    @pytest.mark.asyncio
    async def test_ai_commit_prefix_constant(self):
        """AI_COMMIT_PREFIX is defined and non-empty."""
        assert isinstance(AI_COMMIT_PREFIX, str)
        assert len(AI_COMMIT_PREFIX) > 0
