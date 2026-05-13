"""全局状态懒初始化 — 唯一职责：管理 Soul 内所有单例实例。"""
from __future__ import annotations
import os
import threading
from typing import Optional


def normalize_project_id(project_id: str | None) -> str:
    """Normalize project_id to a consistent absolute path.

    Different callers use ".", "global", None, or an actual path.
    This function maps all these to a single canonical form so memory
    lookups, code-index keying, and context injection always use the same key.

    Mapping rules:
    - None / "" / "." / "global" → os.getcwd() (current project)
    - relative path → os.path.abspath(path)
    - absolute path → as-is (normalized separators)
    """
    if not project_id or project_id in (".", "global", ""):
        return os.path.abspath(os.getcwd())
    return os.path.abspath(project_id)

_bridge: Optional[object]       = None
# _memory 改为字典单例，按 project_id 隔离
# 旧代码中 _memory 是进程级唯一实例，首次绑定后不可更换。
# 多项目并行时（evocli 在项目 A 启动后切换到 B），
# 所有写入都会被标记 A 的 project_id，导致向量索引分类错乱。
_memories: dict[str, object]    = {}   # project_id → EvoCLIMemory
_skill_engine: Optional[object] = None
_llm_client: Optional[object]   = None
_agent: Optional[object]        = None
_orchestrator: Optional[object] = None
_config: Optional[dict]         = None  # Cached config from ~/.evocli/config.toml
_active_subagents: dict[str, object] = {}  # session_id -> SubAgentSession

# GAP-3: Per-session event accumulator for memory distillation.
# Events are appended during tool execution and drained at session end.
# Thread-safe: GIL protects list.append() and list.clear() in CPython.
_session_events: list[dict] = []

# ── Multi-turn conversation history (keyed by session_id) ──────────────────
# Implements Aider/Claude Code pattern: persist history server-side so Rust TUI
# doesn't need to send it back. Each entry: {"role": "user"|"assistant", "content": str}
# Tool messages are NOT stored (they bloat history without adding recall value).
# Key: session_id (str); Value: list of message dicts
_conversation_histories: dict[str, list[dict]] = {}

# ── Session-level context cache (keyed by session_id) ─────────────────────
# Caches expensive computation (RepoMap, memory search results) across turns.
# Invalidated when goal fingerprint OR current file hash changes.
# Keys per session: "goal_fingerprint", "current_file_hash", "repomap_text",
#                   "memory_results", "turn"
_context_caches: dict[str, dict] = {}

# ── Anchored summary store (keyed by session_id) ──────────────────────────
# When history grows too large, it gets compressed to an Anchored Summary.
# The summary is injected at the front of the next LLM conversation.
_anchored_summaries: dict[str, str] = {}

# ── File read tracker (keyed by session_id) ───────────────────────────────
# Cline pattern: if a file is read multiple times in a session, annotate
# subsequent reads with "also read in turn N" to reduce redundant large content.
# Keys: path → turn_number of first read
_files_read: dict[str, dict[str, int]] = {}  # session_id -> {path: turn}

# ── Current turn counter (keyed by session_id) ────────────────────────────
_current_turns: dict[str, int] = {}  # session_id -> turn_number

# ── Explicitly added files (keyed by session_id) ──────────────────────────
# Aider /add pattern: files pinned by user persist for the whole session.
# They're injected into every turn's context automatically.
_added_files: dict[str, list[str]] = {}  # session_id → [path, ...]

_init_lock = threading.Lock()

# ── Added files API ───────────────────────────────────────────────────────

def add_file(path: str, session_id: str = "default") -> None:
    """Pin a file to session context (Aider /add pattern)."""
    if session_id not in _added_files:
        _added_files[session_id] = []
    if path not in _added_files[session_id]:
        _added_files[session_id].append(path)


def get_added_files(session_id: str = "default") -> list[str]:
    """Return all pinned files for a session."""
    return list(_added_files.get(session_id, []))


def remove_added_files(session_id: str, paths: list[str]) -> list[str]:
    """Remove specific files from pinned context. Returns actually removed paths."""
    existing = _added_files.get(session_id, [])
    removed = [p for p in paths if p in existing]
    _added_files[session_id] = [p for p in existing if p not in paths]
    return removed


def clear_added_files(session_id: str = "default") -> None:
    _added_files.pop(session_id, None)

# ── History API ───────────────────────────────────────────────────────────

# History persistence directory: ~/.evocli/history/{session_id}.json
# Written after every append, read lazily on first get_history() call.
_HISTORY_DIR = None  # resolved lazily

def _history_path(session_id: str):
    """Return the on-disk path for a session's conversation history.

    session_id is sanitized to prevent path traversal attacks AND file-name collisions:
    - Only alphanumeric chars, hyphens, underscores, and dots are kept as-is
    - Characters outside the safe set are replaced with '_' in the readable prefix
    - A short SHA-256 suffix is appended to avoid collisions between session IDs
      that differ only in unsafe chars (e.g. "a/b" vs "a?b" both sanitize to "a_b")
    - Total filename length capped at 140 chars + ".json"
    """
    from pathlib import Path
    import re
    import hashlib
    sid_str = str(session_id)
    # Readable prefix (safe chars only)
    safe_prefix = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', sid_str)[:80]
    # Collision-resistant suffix: first 12 hex chars of SHA-256
    suffix = hashlib.sha256(sid_str.encode()).hexdigest()[:12]
    safe_name = f"{safe_prefix}_{suffix}" if safe_prefix else suffix
    return Path.home() / ".evocli" / "history" / f"{safe_name}.json"


def _load_history_from_disk(session_id: str) -> list[dict]:
    """Load history from disk. Returns [] on any error (safe degradation)."""
    import json
    try:
        path = _history_path(session_id)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_history_to_disk(session_id: str, history: list[dict]) -> None:
    """Persist history to disk (best-effort — never raises)."""
    import json
    try:
        path = _history_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_history(session_id: str = "default") -> list[dict]:
    """Return conversation history for a session (safe copy).
    
    Loads from disk on first access so history persists across process restarts.
    This enables true session resume: user restarts evocli and picks up where they left off.
    """
    if session_id not in _conversation_histories:
        # First access: try to load from disk (cross-restart continuity)
        loaded = _load_history_from_disk(session_id)
        if loaded:
            _conversation_histories[session_id] = loaded
    return list(_conversation_histories.get(session_id, []))


def append_history(messages: list[dict], session_id: str = "default") -> None:
    """Append user+assistant messages to session history.

    Only call with user/assistant role messages — not tool messages.

    Large content (e.g. assistant replies with embedded code blocks) is
    automatically summarised to keep history lean:
    - user messages    > TOOL_RESULT_PRUNE_CHARS: truncated to first 400 chars
    - assistant messages > TOOL_RESULT_PRUNE_CHARS: kept but tail truncated
    This prevents multi-turn history from ballooning with prior file reads
    that the model has already processed (Cline deduplication pattern).
    """
    _TOOL_RESULT_PRUNE_CHARS = 2000  # ~500 tokens — above this we summarise
    if session_id not in _conversation_histories:
        _conversation_histories[session_id] = []

    pruned: list[dict] = []
    for msg in messages:
        role    = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > _TOOL_RESULT_PRUNE_CHARS:
            if role == "user":
                # User messages that are too long are usually context-injected file reads.
                # Keep the first 400 chars (the actual user question) + a note.
                truncated = content[:400].rstrip()
                note = f"\n\n[Note: message truncated from {len(content)} chars — original content visible to AI in that turn only]"
                pruned.append({**msg, "content": truncated + note})
            elif role == "assistant":
                # Assistant replies with large code generation: keep first + last sections
                head = content[:600]
                tail = content[-300:]
                note = f"\n[... {len(content) - 900} chars omitted from history ...]\n"
                pruned.append({**msg, "content": head + note + tail})
            else:
                pruned.append(msg)
        else:
            pruned.append(msg)

    _conversation_histories[session_id].extend(pruned)
    # Persist to disk for cross-restart continuity (best-effort)
    _save_history_to_disk(session_id, _conversation_histories[session_id])


def set_history(messages: list[dict], session_id: str = "default") -> None:
    """Replace entire conversation history for a session (used by /undo)."""
    _conversation_histories[session_id] = list(messages)
    # Persist to disk for cross-restart continuity (best-effort)
    _save_history_to_disk(session_id, _conversation_histories[session_id])


def clear_history(session_id: str = "default") -> None:
    """Clear raw message history for a session while PRESERVING the anchored summary.

    The anchored summary is the whole point of /compress — it must survive the clear.
    Only the raw message list is cleared; the summary acts as the new compact "memory"
    of what happened before.

    Also removes (or truncates) the on-disk history file so cleared history cannot
    accidentally resurrect after a process restart (e.g., `evocli session resume`).
    """
    _conversation_histories.pop(session_id, None)
    _context_caches.pop(session_id, None)
    # _anchored_summaries intentionally NOT cleared — survives /compress
    # The summary IS the session context after compression.
    _files_read.pop(session_id, None)
    _current_turns.pop(session_id, None)
    # Note: _added_files intentionally NOT cleared — user's /add persists across /compress

    # Remove on-disk history so cleared state survives restarts.
    # Anchored summary is NOT persisted here — it's only needed within a running session.
    # When a session resumes after /compress: the raw history is [] (disk deleted),
    # and the model starts fresh. The summary is gone after restart by design — users
    # must /compress again in the new session if they want a compact history.
    try:
        path = _history_path(session_id)
        if path.exists():
            path.unlink(missing_ok=True)
    except Exception:
        pass


def get_history_token_estimate(session_id: str = "default") -> int:
    """Rough token count of stored history (char // 4 heuristic, no ML needed)."""
    history = _conversation_histories.get(session_id, [])
    return sum(len(str(m.get("content", ""))) for m in history) // 4


# ── Context cache API ─────────────────────────────────────────────────────

def get_context_cache(session_id: str = "default") -> dict:
    """Return the session context cache dict (mutable reference)."""
    if session_id not in _context_caches:
        _context_caches[session_id] = {}
    return _context_caches[session_id]


def update_context_cache(updates: dict, session_id: str = "default") -> None:
    """Merge updates into the session context cache."""
    if session_id not in _context_caches:
        _context_caches[session_id] = {}
    _context_caches[session_id].update(updates)


# ── Anchored summary API ──────────────────────────────────────────────────

def get_anchored_summary(session_id: str = "default") -> str:
    return _anchored_summaries.get(session_id, "")


def set_anchored_summary(text: str, session_id: str = "default") -> None:
    _anchored_summaries[session_id] = text


# ── File read tracker API ─────────────────────────────────────────────────

def record_file_read(path: str, session_id: str = "default") -> int:
    """Record that a file was read. Returns 1 (first read) or 2+ (repeat read).
    
    Cline pattern: caller can annotate repeat reads so history doesn't re-bloat.
    """
    turn = get_current_turn(session_id)
    if session_id not in _files_read:
        _files_read[session_id] = {}
    if path not in _files_read[session_id]:
        _files_read[session_id][path] = turn
        return 1
    return 2  # already read in a prior turn


def get_file_first_read_turn(path: str, session_id: str = "default") -> Optional[int]:
    """Return the turn number when path was first read, or None."""
    return _files_read.get(session_id, {}).get(path)


# ── Turn counter API ──────────────────────────────────────────────────────

def increment_turn(session_id: str = "default") -> int:
    """Increment and return the current turn number for a session."""
    _current_turns[session_id] = _current_turns.get(session_id, 0) + 1
    return _current_turns[session_id]


def get_current_turn(session_id: str = "default") -> int:
    return _current_turns.get(session_id, 0)


# ── Session event buffer (GAP-3: memory distillation) ─────────────────────

def append_session_event(event: dict) -> None:
    """Append a tool/action event to the current session's event buffer.

    Called from _execute_tool() and Python-native tool closures in agent.py.
    The accumulated events are consumed by MemoryDistiller at session end (GAP-3).
    """
    _session_events.append(event)


def drain_session_events() -> list[dict]:
    """Return all accumulated session events and clear the buffer.

    Called once per session end by _distill_session() in handlers/agent.py.
    """
    events = list(_session_events)
    _session_events.clear()
    return events


def get_config() -> dict:
    """
    Load and cache config.toml with project-local override.

    Merge order (highest priority wins):
      1. {cwd}/.evocli/config.toml  — project-local overrides
      2. ~/.evocli/config.toml      — global defaults

    Mirrors Rust host config.rs merge logic so Python handlers see the same
    effective configuration as the host.
    Falls back to empty dict if neither file is found or readable.
    """
    global _config
    if _config is None:
        with _init_lock:
            if _config is None:
                try:
                    try:
                        import tomllib
                    except ImportError:
                        import tomli as tomllib  # type: ignore[no-redef]
                    from pathlib import Path

                    def _read(p: Path) -> dict:
                        if p.exists():
                            try:
                                with open(p, "rb") as f:
                                    return tomllib.load(f)
                            except Exception:
                                pass
                        return {}

                    global_cfg  = _read(Path.home() / ".evocli" / "config.toml")
                    project_cfg = _read(Path.cwd() / ".evocli" / "config.toml")

                    def _deep_merge(base: dict, override: dict) -> dict:
                        result = dict(base)
                        for k, v in override.items():
                            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                                result[k] = _deep_merge(result[k], v)
                            else:
                                result[k] = v
                        return result

                    _config = _deep_merge(global_cfg, project_cfg)
                except Exception as e:
                    import logging
                    logging.getLogger("evocli.state").debug("Config load failed: %s", e)
                    _config = {}
    return _config
    return _config


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        with _init_lock:
            if _orchestrator is None:  # double-check after acquiring lock
                try:
                    from evocli_soul.orchestrator import Orchestrator
                    _orchestrator = Orchestrator(get_bridge(), get_memory())
                except Exception as e:
                    import logging
                    logging.getLogger("evocli.state").debug("Orchestrator init failed: %s", e)
    return _orchestrator


def register_subagent(session_id: str, agent_info: dict) -> None:
    _active_subagents[session_id] = agent_info


def get_active_subagents() -> dict:
    return dict(_active_subagents)


def unregister_subagent(session_id: str) -> None:
    _active_subagents.pop(session_id, None)


def get_bridge():
    global _bridge
    if _bridge is None:
        with _init_lock:
            if _bridge is None:  # double-check after acquiring lock
                from evocli_soul.host_bridge import HostBridge
                _bridge = HostBridge()
    return _bridge


def set_bridge(bridge) -> None:
    global _bridge
    _bridge = bridge


def get_memory(project_id: str | None = None):
    """获取（或创建）指定项目的 EvoCLIMemory 实例。

    project_id 默认为当前工作目录路径（cwd），保证每个项目写入各自的
    LanceDB 行，不再出现多项目 project_id 标签混淆问题。

    向后兼容：所有无参数的 get_memory() 调用自动使用 cwd，
    行为与之前相同（每次从同一目录运行 evocli），
    但现在支持同进程内切换项目。
    """
    global _memories
    pid = normalize_project_id(project_id)  # canonical key: always absolute path
    if pid not in _memories:
        with _init_lock:
            if pid not in _memories:
                from evocli_soul.memory_client import EvoCLIMemory
                _memories[pid] = EvoCLIMemory(project_id=pid)
    return _memories[pid]


def get_memory_if_ready(project_id: str | None = None):
    """Return the memory singleton **without blocking**.

    Returns the already-initialised EvoCLIMemory instance if it's ready,
    or ``None`` if initialisation hasn't finished yet (e.g. still loading
    the fastembed model in the background pre-warm task).

    Reading a module-level reference is atomic under the GIL, so no lock
    is needed for this check-only path.
    """
    pid = normalize_project_id(project_id)  # same canonical key as get_memory()
    return _memories.get(pid)


def get_skill_engine():
    global _skill_engine
    if _skill_engine is None:
        with _init_lock:
            if _skill_engine is None:  # double-check after acquiring lock
                from evocli_soul.skill_engine import SkillEngine
                _skill_engine = SkillEngine(get_bridge())
    return _skill_engine


def get_llm_client(config: dict | None = None):
    global _llm_client
    if _llm_client is None:
        with _init_lock:
            if _llm_client is None:  # double-check after acquiring lock
                from evocli_soul.llm_client import LLMClient
                _llm_client = LLMClient(config or {})
    return _llm_client


def get_agent(config: dict | None = None):
    global _agent
    if _agent is None:
        with _init_lock:
            if _agent is None:  # double-check after acquiring lock
                from evocli_soul.agent import EvoCLIAgent
                # Use actual config from disk if not provided.
                # Previously defaulted to {} which caused pydantic-ai to fail
                # (defaulted to provider="anthropic" for openai endpoint).
                effective_config = config or get_config()
                _agent = EvoCLIAgent(get_bridge(), get_memory(), effective_config)
    return _agent


def reset_all() -> None:
    """测试用：重置所有单例。"""
    global _bridge, _memory, _skill_engine, _llm_client, _agent, _orchestrator, _config, _active_subagents
    # Reset old-style single-instance vars (kept for backwards compat with any lingering refs)
    _bridge = _memory = _skill_engine = _llm_client = _agent = _orchestrator = _config = None
    # Reset new-style per-project memory dict (the actual store since H1 unification)
    _memories.clear()
    _active_subagents.clear()
    _session_events.clear()
    _conversation_histories.clear()
    _context_caches.clear()
    _anchored_summaries.clear()
    _files_read.clear()
    _current_turns.clear()
    _added_files.clear()
