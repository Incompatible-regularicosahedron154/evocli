"""
protocols.py — Protocol First: Single Source of Truth for all EvoCLI data schemas

Rule 3 (AI Programming Bible 3.0):
  Define Types/Schemas first. Use them as the absolute Source of Truth.
  All modules import from here — never define schemas inline.

This file is the contract between:
  - Rust Host ↔ Python Soul (RPC messages)
  - Agent ↔ Tools (tool call inputs/outputs)
  - Session state (what a session contains)
  - Memory system (what a memory entry looks like)
  - Config validation (what valid config looks like)

Rule: Keep this file < 300 lines. If it grows, split into protocols_*.py
"""
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ── RPC Protocol (Rust Host ↔ Python Soul) ────────────────────────────────────

class RpcRequest(BaseModel):
    """JSON-RPC request from Rust Host to Python Soul."""
    id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class RpcResponse(BaseModel):
    """JSON-RPC response from Python Soul to Rust Host."""
    id: str
    result: Optional[Any] = None
    error: Optional[dict[str, Any]] = None


class StreamChunk(BaseModel):
    """Streaming chunk from Soul to TUI."""
    id: str
    text: str
    done: bool


class SoulEvent(BaseModel):
    """Event emitted from Soul to TUI (soul_status, tool_call_*, etc.)."""
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Tool Call Protocol ─────────────────────────────────────────────────────────

class ToolCallResult(BaseModel):
    """Standard tool call result envelope."""
    ok: bool
    output: str = ""
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, output: str, **meta: Any) -> "ToolCallResult":
        return cls(ok=True, output=output, metadata=meta)

    @classmethod
    def failure(cls, error: str, **meta: Any) -> "ToolCallResult":
        return cls(ok=False, error=error, metadata=meta)


# ── Core Tool Input Schemas (Protocol First for major tools) ──────────────────

class FileReadArgs(BaseModel):
    """Protocol for fs_read tool input."""
    path: str = Field(..., description="Absolute or project-relative file path")

    @field_validator("path")
    @classmethod
    def no_traversal(cls, v: str) -> str:
        if ".." in v.replace("\\", "/").split("/"):
            raise ValueError(f"Path traversal detected: {v!r}")
        return v


class FileWriteArgs(BaseModel):
    """Protocol for fs_write tool input."""
    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write")

    @field_validator("path")
    @classmethod
    def no_traversal(cls, v: str) -> str:
        if ".." in v.replace("\\", "/").split("/"):
            raise ValueError(f"Path traversal detected: {v!r}")
        return v


class ShellRunArgs(BaseModel):
    """Protocol for shell_run tool input."""
    cmd: str = Field(..., min_length=1, description="Command to execute")
    cwd: str = Field(default="", description="Working directory (empty = project root)")
    timeout_s: int = Field(default=0, ge=0, le=600, description="Timeout (0 = config default)")


class MemoryRecallArgs(BaseModel):
    """Protocol for memory_recall tool input."""
    query: str = Field(..., min_length=1, description="Semantic search query")
    top_k: int = Field(default=0, ge=0, le=50, description="Results count (0 = config default)")


# ── Session Protocol ───────────────────────────────────────────────────────────

class SessionMeta(BaseModel):
    """Metadata about an active agent session."""
    session_id: str
    project_root: str
    turn: int = 0
    model_id: str = ""
    provider_id: str = ""
    created_at: float = Field(default_factory=lambda: __import__("time").time())


class TaskItem(BaseModel):
    """A single todo item in the AI's task plan."""
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"
    priority: Literal["high", "medium", "low"] = "medium"


class TaskPlan(BaseModel):
    """The AI's structured task plan (todo_write output)."""
    todos: list[TaskItem] = Field(default_factory=list)
    session_id: str = ""

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.todos if t.status in ("pending", "in_progress"))

    @property
    def is_complete(self) -> bool:
        return all(t.status in ("completed", "cancelled") for t in self.todos)


# ── Memory Protocol ────────────────────────────────────────────────────────────

class MemoryEntry(BaseModel):
    """A single memory entry stored in LanceDB."""
    id: str = ""
    title: str
    body: str = ""
    memory_type: Literal["constraint", "episode", "skill", "global"] = "episode"
    priority: Literal["project", "tool", "global"] = "project"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    project_id: str = ""
    created_at: float = Field(default_factory=lambda: __import__("time").time())


# ── Task Complete Protocol ─────────────────────────────────────────────────────

class TaskCompleteSignal(BaseModel):
    """Stored when AI calls task_complete tool."""
    result: str = Field(..., min_length=1)
    command: str = ""
    ts: float = Field(default_factory=lambda: __import__("time").time())


# ── Config Validation ──────────────────────────────────────────────────────────

class AgentRuntimeConfig(BaseModel):
    """Validated runtime configuration for a single agent session."""
    max_auto_iterations: int = Field(default=8, ge=1, le=50)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    max_reflections: int = Field(default=3, ge=0, le=10)
    observation_max_chars: int = Field(default=6000, ge=500, le=50000)
    context_build_timeout_s: float = Field(default=20.0, ge=1.0, le=120.0)
    auto_commit: bool = True
    auto_snapshot: bool = True

    @classmethod
    def from_config(cls, cfg: dict) -> "AgentRuntimeConfig":
        """Parse from config dict with graceful fallback to defaults."""
        agent_cfg = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
        try:
            return cls(**{k: v for k, v in agent_cfg.items() if k in cls.model_fields})
        except Exception:
            return cls()
