# pyright: reportImportCycles=false, reportMissingImports=false, reportMissingTypeArgument=false
"""
config_defaults.py — Centralized configuration defaults for EvoCLI Soul

ALL magic numbers live here. Each constant has:
  - A name that explains what it controls
  - A config key showing where to override it in config.toml
  - A docstring explaining the trade-off

Usage pattern (throughout the codebase):
    from evocli_soul.config_defaults import cfg_get, DEFAULTS
    top_k = cfg_get("search.top_k")          # reads from config, falls back to DEFAULTS
    timeout = cfg_get("shell.timeout_s")

This eliminates scattered .get("key", MAGIC_NUMBER) patterns.
"""
from __future__ import annotations
import functools
import logging
from typing import Any

log = logging.getLogger("evocli.config_defaults")

# ── Master defaults table ─────────────────────────────────────────────────────
# Format: "section.key": (default_value, description)
# Override any of these in ~/.evocli/config.toml or {project}/.evocli/config.toml

DEFAULTS: dict[str, tuple[Any, str]] = {

    # ── Shell / Execution ────────────────────────────────────────────────────
    "shell.timeout_s":          (30,    "Default shell command timeout in seconds"),
    "shell.long_timeout_s":     (120,   "Timeout for long-running commands (tests, builds)"),
    "shell.verify_timeout_s":   (60,    "Timeout for task_complete verification commands"),
    "shell.max_results":        (100,   "Max results for shell_grep / shell_find"),

    # ── Agent Loop ───────────────────────────────────────────────────────────
    "agent.max_auto_iterations":        (8,  "Max autonomous loop iterations per request"),
    "agent.max_no_tool_turns":          (2,  "Stop loop after N consecutive text-only turns"),
    "agent.max_tool_calls":             (20, "Max tool calls per _run_litellm turn"),
    "agent.max_reflections":            (3,  "Max auto-reflection retries on lint/test failure"),
    "agent.max_consecutive_failures":   (3,  "Circuit breaker: stop after N consecutive tool errors"),
    "agent.context_build_timeout_s":    (20, "Timeout for _build_context before falling back to empty"),
    "agent.stream_timeout_s":           (30, "Timeout per _stream_litellm chunk batch"),
    "agent.observation_max_chars":      (6000, "Max chars of tool output injected into context"),
    "agent.symbol_context_lines":       (10,   "Lines of context around a symbol for fs_read_symbol"),
    "agent.auto_snapshot":              (True, "Create git snapshot before modifying tasks"),
    "agent.auto_commit":                (True, "Auto-commit after successful task_complete"),

    # ── LLM / Model ─────────────────────────────────────────────────────────
    "llm.max_tokens":               (4096,   "Default max output tokens for LLM calls"),
    "llm.temperature":              (0.7,    "Default generation temperature"),
    "llm.default_context_window":   (32_000, "Fallback context window if model info unavailable"),
    "llm.fallback_context_window":  (8_192,  "Last-resort fallback for completely unknown models"),
    "llm.max_tools_per_call":       (20,     "Max tools passed to LiteLLM (some providers limit this)"),

    # ── Context Engine ───────────────────────────────────────────────────────
    "context.retrieval_top_k":      (15,  "Memory search results to retrieve per turn"),
    "context.summary_window":       (40,  "Max history messages used for summarization"),
    "context.compaction_window":    (20,  "Messages kept verbatim during Head/Tail compaction"),
    "context.summary_max_tokens":   (600, "Max tokens for auto-generated session summaries"),
    "context.repomap_tokens":       (1024, "Max tokens for compact symbol navigation"),
    "context.history_turns":        (3,    "Recent conversation turns to include"),
    "context.auto_compress_threshold": (0.70, "Compress when context exceeds this % of max"),

    # ── History Management ───────────────────────────────────────────────────
    "agent.history_compress_turns":  (10,   "Compress history after this many conversation turns"),
    "agent.history_compress_tokens": (8_000,"Compress history when estimated tokens exceed this"),
    "agent.history_tail_messages":   (10,   "Verbatim messages to keep at tail during compression"),
    "ui.summary_history_window":     (20,   "History window for /compress slash command"),

    # ── Memory ───────────────────────────────────────────────────────────────
    "memory.search_top_k":          (5,  "Default memory search results count"),
    "memory.dedupe_window":         (20, "Recent memories checked for deduplication"),
    "memory.list_limit":            (30, "Max memories shown in memory list commands"),
    "memory.enhance_max_iterations":(2,  "Max iterations for memory enhancement/consolidation"),
    "memory.decay_half_life_days":  (30.0, "Days before infrequently-accessed memory weight halves"),

    # ── Search ───────────────────────────────────────────────────────────────
    "search.top_k":         (5,    "Default semantic search results count"),
    "search.max_results":   (100,  "Max results for code search / grep"),
    "search.rrf_k_factor":  (60.0, "Reciprocal Rank Fusion K parameter (higher=less aggressive merge)"),
    "search.fetch_url_max_chars": (8000, "Max characters fetched from @url mentions"),

    # ── Embeddings ───────────────────────────────────────────────────────────
    "embeddings.text_model": ("jinaai/jina-embeddings-v2-base-zh",
                              "Embedding model for text/memory (Chinese+English)"),
    "embeddings.code_model": ("jinaai/jina-embeddings-v2-base-code",
                              "Embedding model for code search"),

    # ── Scratchpad / Evolution ────────────────────────────────────────────────
    "agent.scratchpad_max_iters":     (5,   "Max iterations kept in Gemini-style scratchpad"),
    "evolution.schedule_interval_s":  (300, "Background evolution scan interval in seconds"),
    "evolution.step_timeout_s":       (30,  "Timeout per tool-flow step execution"),

    # ── Bridge / IPC ─────────────────────────────────────────────────────────
    "system.bridge_timeout_s":   (30.0,  "Default Rust bridge RPC call timeout"),
    "system.bridge_long_timeout":(300.0, "Long bridge call timeout (indexing, builds)"),
    "system.max_sessions":       (100,   "Max concurrent sessions in state.py LRU cache"),
    "mcp.request_timeout_s":     (15.0,  "MCP server request timeout"),

    # ── Multi-Agent ──────────────────────────────────────────────────────────
    "multi_agent.per_agent_budget": (4_000, "Max context tokens per sub-agent"),

    # ── Code Intelligence ─────────────────────────────────────────────────────
    "code_intel.max_depth":    (5, "Max traversal depth for blast radius / impact analysis"),
    "code_intel.watched_extensions": (
        ["rs", "py", "ts", "tsx", "js", "jsx", "go", "java", "cpp", "c", "cs"],
        "File extensions auto-indexed by code intelligence"
    ),

    # ── Project Discovery ─────────────────────────────────────────────────────
    "project.docs_files": (
        ["AGENTS.md", "CLAUDE.md", "README.md", "CONTRIBUTING.md"],
        "Files read during project quick-start analysis"
    ),
}


# ── Runtime config reader ─────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _load_config_toml() -> dict:
    """Load merged config (project > global > built-in defaults). Cached once per process."""
    from pathlib import Path
    merged: dict = {}
    paths = [
        Path.home() / ".evocli" / "config.toml",
    ]
    # Project-level config (highest priority)
    try:
        from evocli_soul.state import get_session_root
        proj_cfg = Path(get_session_root()) / ".evocli" / "config.toml"
        paths.insert(0, proj_cfg)
    except Exception:
        pass

    for p in reversed(paths):  # global first, project overrides
        if p.exists():
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                with open(p, "rb") as f:
                    merged.update(_flatten(tomllib.load(f)))
                log.debug("config_defaults: loaded %s", p)
            except Exception as e:
                log.debug("config_defaults: could not load %s: %s", p, e)
    return merged


def _flatten(d: dict, prefix: str = "") -> dict:
    """Flatten nested TOML dict to dot-notation: {'agent': {'timeout': 30}} → {'agent.timeout': 30}"""
    result = {}
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten(v, full_key))
        else:
            result[full_key] = v
    return result


def cfg_get(key: str, override: Any = None) -> Any:
    """
    Get a configuration value with the following priority:
      1. `override` parameter (if not None) — allows per-call overrides
      2. Project config.toml value
      3. Global ~/.evocli/config.toml value
      4. DEFAULTS table value

    Args:
        key:      Dot-notation config key, e.g. "agent.max_auto_iterations"
        override: Direct value override (bypasses config lookup)

    Example:
        timeout = cfg_get("shell.timeout_s")            # reads from config
        timeout = cfg_get("shell.timeout_s", 60)        # 60 overrides everything
    """
    if override is not None:
        return override
    try:
        loaded = _load_config_toml()
        if key in loaded:
            return loaded[key]
    except Exception as e:
        log.debug("cfg_get(%s) config lookup failed: %s", key, e)
    # Fall back to built-in default
    if key in DEFAULTS:
        return DEFAULTS[key][0]
    log.warning("cfg_get: unknown key '%s' — no default defined", key)
    return None


def cfg_int(key: str, override: int | None = None) -> int:
    """cfg_get with int cast."""
    return int(cfg_get(key, override))


def cfg_float(key: str, override: float | None = None) -> float:
    """cfg_get with float cast."""
    return float(cfg_get(key, override))


def cfg_bool(key: str, override: bool | None = None) -> bool:
    """cfg_get with bool cast."""
    v = cfg_get(key, override)
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")


def cfg_list(key: str, override: list | None = None) -> list:
    """cfg_get returning a list."""
    v = cfg_get(key, override)
    if isinstance(v, list):
        return v
    return [v] if v is not None else []


def invalidate_cache() -> None:
    """Call after config.toml changes (e.g., evocli config set ...)."""
    _load_config_toml.cache_clear()
