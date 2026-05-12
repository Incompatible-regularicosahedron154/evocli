# Changelog

All notable changes to EvoCLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed — Stability / Usability / Functionality (2026-05-12)

**Tool use routing (critical)**
- `_stream_litellm`: was calling `acompletion()` without `tools=`, making `finish_reason="tool_calls"` structurally unreachable. Now passes full tool schemas to streaming call. Provider compat guard retries without `tools=` on keyword-detected rejection errors (`_tools_in_stream` flag prevents dead routing after degradation).
- `tool_call_seen`: stream loop now tracks `delta.tool_calls` in addition to `finish_reason`, so tool routing fires even when a model streams prose before requesting tools.

**History — single-injection guarantee (all paths)**
- History is now embedded in `full_input` via `_build_context` → `_inject_context` exactly once, for all LLM paths (pydantic-ai, `_stream_litellm`, `_run_litellm`).
- Removed `messages.extend(prior_history)` from `_stream_litellm` and `conversation.extend(prior_history)` from `_run_litellm` — both were double-injecting history already present in `full_input`.
- Removed `message_history=prior_history` from pydantic-ai `run_stream()` call — plain `{role, content}` dicts are not typed `ModelMessage` objects; passing both caused potential double-injection.

**Session continuity**
- `handle_agent_run()`: `EvoCLIAgent` now constructed with `session_id` derived from cwd-hash (matching stream path). Previously always used `"default"` session bucket.
- `agent.run()`: loads `get_history(session_id)` from state before `_build_context` so non-streaming path has multi-turn context.
- `agent.run()`: persists `[user, assistant]` turn in both pydantic-ai and LiteLLM paths. Removed duplicate persistence from `handlers/agent.py` (ownership now in `agent.run()` only).

**`/compress` — full fix**
- Compress prompt now uses real `prior_history` (last 20 turns) instead of the literal string `"/compress"` as the summary source.
- `context_engine.py`: `anchored_summary` is now injected unconditionally before the history block, so it survives `clear_history()` after `/compress`. Previously it only injected inside `if history and remaining > 0`, meaning compressed sessions lost their summary on the very next turn.
- Token double-count fixed: `_already_counted` tracks anchor tokens before the history block; `used` is now incremental only.
- `_maybe_compress_history()`: no longer writes `summary_msgs` back into history as `[user, assistant]` pair — summary lives exclusively in `_anchored_summaries` and is injected by `context_engine` unconditionally.

**`/add` command**
- Fixed argument order: `add_file(_add_sid, f)` → `add_file(f, _add_sid)`. Was silently writing files to wrong session bucket, so pinned files were never retrieved.

**Prompt pipeline — DO-NOW rules reach all LLM paths**
- `context_engine.py` system_prompt assembly now uses `build_system_prompt()` as base, so `SYSTEM_WORKFLOW` DO-NOW rules, tool ordering, and failure recovery instructions are present in every LLM call (pydantic-ai and both LiteLLM paths). Previously the LiteLLM paths built their own inline prompt starting with `"你是 EvoCLI..."`, discarding all workflow rules.
- `_build_context()`: passes `read_only=self.read_only` through to `ctx_engine.build()` so read-only mode uses the correct system prompt.

**Stream fallback — user context not lost**
- `handlers/agent.py` LiteLLM fallback now calls `agent._inject_context(prompt, fallback_ctx)` before `_stream_litellm`. Previously passed raw `prompt` without file contents / diff / history from `user_context`.

**Per-role LLM config — hardcoded params removed**
- `_run_litellm`: `max_tokens`/`temperature` now read from `llm.get_task_params("agent")` instead of hardcoded `4096`/`0.7`.
- `_stream_litellm`: reads from `get_task_params("stream")`.
- `run_architect_mode()`: architect and editor now use `complete_for_task("architect"/"editor")` instead of `complete(tier=..., max_tokens=...)`.

**Python config — project-local merge**
- `llm_client._load_config_from_disk()`: deep-merges `{cwd}/.evocli/config.toml` over `~/.evocli/config.toml`. Mirrors Rust host `config.rs` merge logic.
- `state.get_config()`: same deep-merge so all handlers and agents see effective per-project configuration.

**Auto-continue — disabled (protocol incompatibility)**
- Auto-continue fired after `done=True` was already sent to the TUI. Rust TUI breaks its stream loop on `done=True` (lib.rs:218), so all followup chunks were silently dropped. Disabled with `if False` guard and TODO comment for proper re-implementation that defers `done=True` until the full turn completes.

**Tool whitelist**
- Added `cd`, `rust-analyzer`, `pnpm`, `yarn`, `gofmt`, `gopls`, and 25+ other common dev tools to `ALLOWED_PREFIXES` in `crates/tools/src/lib.rs`.

**New tools**
- `fs_read_range`: read a specific line range from a file (avoids loading large files for small edits).
- `/help` and `/?` slash commands in TUI chat.

## [0.1.0] — 2026-05-12

### Added

**Core Runtime**
- Rust Host + Python Soul dual-engine architecture with JSON-RPC IPC
- 62 Rust-side tools (fs, git, shell, code_intel, memory, approval, prompt.choice)
- 55+ Python LLM-visible tools via Pydantic AI + LiteLLM router

**TUI**
- Full-screen ratatui terminal UI with Catppuccin × Tokyo Night color theme
- Streaming AI responses with live cursor animation
- Token usage progress bar with context-window fill indicator (`[████░░] 12%  15k/128k`)
- Thinking animation (`◆ model  ⠸`) in chat area while AI processes
- Word-wrap and virtual scrolling for all message types
- Notification bar (transient 6-second alerts between chat and input)
- Debug log overlay (F12) with auto-scroll
- `prompt.choice` interactive modal — AI presents numbered options, user picks or types custom answer
- Responsive layout (Wide ≥120 / Normal 60–119 / Compact 40–59 / Tiny <40)

**Memory System**
- LanceDB vector memory with `jinaai/jina-embeddings-v2-base-zh` (768-dim, bilingual)
- SQLite FTS fallback when LanceDB unavailable
- Background pre-warm so first response isn't blocked by model loading
- Memory distillation on session pause

**Code Intelligence**
- tree-sitter AST indexing (Rust, Python, JS, TS)
- BM25 full-text search (Tantivy embedded)
- PageRank-weighted symbol ranking
- Hybrid BM25 + vector search (RRF fusion)
- LSP client for incoming/outgoing call chains

**Skill System**
- TOML-defined executable skills with multi-step pipelines
- Built-in skills: TDD, brainstorming, debugging, code review, git workflow
- `/chain <symbol>` call-chain visualization in TUI

**Security**
- Blacklist security model (allow all, block known-dangerous)
- `PATH_DENY_IMMUTABLE`: AI cannot read/write `config.toml` or SSH keys
- `SHELL_BLOCKED_DANGEROUS`: 22 hardcoded patterns (rm -rf /, dd, mkfs, etc.)
- User-configurable `extra_blocked_patterns` in `config.toml`

**Providers & Integrations**
- OpenAI, Anthropic, DeepSeek, Ollama via LiteLLM router
- MCP server and client (`evocli mcp serve/connect/tools`)
- Auto Python environment setup via `uv` (zero manual pip)

**CLI Commands**
- `evocli` — launch TUI
- `evocli init` — interactive setup wizard
- `evocli doctor` — 10-point health check
- `evocli index` — code symbol indexing
- `evocli skill list/run/export/import`
- `evocli git status/commit/snapshot/restore`
- `evocli session list/resume/pause`
- `evocli mcp serve/connect/list/tools`
- `evocli stats` — flywheel metrics dashboard
- `evocli tool register/list` — user-defined tool registration

---

[Unreleased]: https://github.com/bambooqj/evocli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bambooqj/evocli/releases/tag/v0.1.0
