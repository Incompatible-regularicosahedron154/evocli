"""
tests/unit/test_protocols.py — Pydantic protocol model validation tests

Covers: FileReadArgs, FileWriteArgs, ShellRunArgs, MemoryRecallArgs,
        TaskItem, TaskPlan, ToolCallResult, SessionMeta, MemoryEntry,
        TaskCompleteSignal, AgentRuntimeConfig
"""
from __future__ import annotations
import pathlib, sys, pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from evocli_soul.protocols import (
    FileReadArgs, FileWriteArgs, ShellRunArgs, MemoryRecallArgs,
    TaskItem, TaskPlan, ToolCallResult, SessionMeta, MemoryEntry,
    TaskCompleteSignal, AgentRuntimeConfig,
)
from pydantic import ValidationError


class TestFileReadArgs:
    def test_valid_path(self):
        args = FileReadArgs(path="src/main.rs")
        assert args.path == "src/main.rs"

    def test_absolute_path(self):
        args = FileReadArgs(path="/home/user/project/src/main.rs")
        assert args.path.startswith("/")

    def test_path_traversal_blocked(self):
        with pytest.raises(ValidationError):
            FileReadArgs(path="../../../etc/passwd")

    def test_deep_traversal_blocked(self):
        with pytest.raises(ValidationError):
            FileReadArgs(path="src/../../../secret")

    def test_no_path_raises(self):
        with pytest.raises(ValidationError):
            FileReadArgs()


class TestFileWriteArgs:
    def test_valid(self):
        args = FileWriteArgs(path="src/new_file.py", content="print('hello')")
        assert args.content == "print('hello')"

    def test_traversal_blocked(self):
        with pytest.raises(ValidationError):
            FileWriteArgs(path="../outside/file.txt", content="data")

    def test_empty_content_allowed(self):
        args = FileWriteArgs(path="empty.txt", content="")
        assert args.content == ""


class TestShellRunArgs:
    def test_valid_cmd(self):
        args = ShellRunArgs(cmd="cargo test")
        assert args.cmd == "cargo test"
        assert args.timeout_s == 0  # default (use config)

    def test_with_timeout(self):
        args = ShellRunArgs(cmd="npm build", timeout_s=60)
        assert args.timeout_s == 60

    def test_timeout_max(self):
        with pytest.raises(ValidationError):
            ShellRunArgs(cmd="sleep 9999", timeout_s=601)  # exceeds max

    def test_negative_timeout_blocked(self):
        with pytest.raises(ValidationError):
            ShellRunArgs(cmd="ls", timeout_s=-1)

    def test_empty_cmd_blocked(self):
        with pytest.raises(ValidationError):
            ShellRunArgs(cmd="")


class TestMemoryRecallArgs:
    def test_valid_query(self):
        args = MemoryRecallArgs(query="JWT authentication pattern")
        assert args.query == "JWT authentication pattern"
        assert args.top_k == 0  # default (use config)

    def test_empty_query_blocked(self):
        with pytest.raises(ValidationError):
            MemoryRecallArgs(query="")

    def test_top_k_range(self):
        args = MemoryRecallArgs(query="test", top_k=10)
        assert args.top_k == 10

    def test_top_k_too_high_blocked(self):
        with pytest.raises(ValidationError):
            MemoryRecallArgs(query="test", top_k=51)


class TestTaskPlan:
    def test_empty_plan(self):
        plan = TaskPlan()
        assert plan.todos == []
        assert plan.is_complete is True  # empty = complete

    def test_with_items(self):
        plan = TaskPlan(todos=[
            TaskItem(id="1", content="Read auth.rs", status="completed"),
            TaskItem(id="2", content="Write tests", status="pending"),
        ])
        assert plan.pending_count == 1
        assert not plan.is_complete

    def test_all_completed(self):
        plan = TaskPlan(todos=[
            TaskItem(id="1", content="Done", status="completed"),
            TaskItem(id="2", content="Cancelled", status="cancelled"),
        ])
        assert plan.is_complete
        assert plan.pending_count == 0

    def test_invalid_status_blocked(self):
        with pytest.raises(ValidationError):
            TaskItem(id="1", content="Task", status="unknown_status")

    def test_invalid_priority_blocked(self):
        with pytest.raises(ValidationError):
            TaskItem(id="1", content="Task", priority="critical")  # only high/medium/low


class TestToolCallResult:
    def test_success_factory(self):
        r = ToolCallResult.success("file content here", tokens=100)
        assert r.ok is True
        assert r.output == "file content here"
        assert r.metadata["tokens"] == 100  # stored as-is (int)

    def test_failure_factory(self):
        r = ToolCallResult.failure("File not found: src/auth.rs")
        assert r.ok is False
        assert r.error == "File not found: src/auth.rs"
        assert r.output == ""

    def test_direct_construction(self):
        r = ToolCallResult(ok=True, output="result", error=None)
        assert r.ok


class TestAgentRuntimeConfig:
    def test_defaults(self):
        cfg = AgentRuntimeConfig()
        assert cfg.max_auto_iterations == 8
        assert cfg.max_tool_calls == 20
        assert cfg.auto_commit is True

    def test_from_config_dict(self):
        cfg = AgentRuntimeConfig.from_config({"agent": {"max_auto_iterations": 3}})
        assert cfg.max_auto_iterations == 3

    def test_from_config_empty_dict(self):
        cfg = AgentRuntimeConfig.from_config({})
        assert cfg.max_auto_iterations == 8  # default

    def test_max_iterations_range(self):
        with pytest.raises(ValidationError):
            AgentRuntimeConfig(max_auto_iterations=0)  # ge=1

    def test_context_timeout_range(self):
        with pytest.raises(ValidationError):
            AgentRuntimeConfig(context_build_timeout_s=0.5)  # ge=1.0


class TestMemoryEntry:
    def test_valid_entry(self):
        e = MemoryEntry(title="Auth pattern", body="Use JWT with 24h expiry")
        assert e.title == "Auth pattern"
        assert e.importance == 0.5  # default

    def test_importance_range(self):
        with pytest.raises(ValidationError):
            MemoryEntry(title="test", importance=1.5)  # exceeds 1.0

    def test_negative_importance_blocked(self):
        with pytest.raises(ValidationError):
            MemoryEntry(title="test", importance=-0.1)

    def test_invalid_memory_type_blocked(self):
        with pytest.raises(ValidationError):
            MemoryEntry(title="test", memory_type="unknown")


class TestTaskCompleteSignal:
    def test_valid_signal(self):
        sig = TaskCompleteSignal(result="Fixed the auth bug", command="cargo test")
        assert sig.result == "Fixed the auth bug"
        assert sig.command == "cargo test"
        assert sig.ts > 0

    def test_empty_result_blocked(self):
        with pytest.raises(ValidationError):
            TaskCompleteSignal(result="")

    def test_no_command_ok(self):
        sig = TaskCompleteSignal(result="Done")
        assert sig.command == ""
