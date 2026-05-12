# Changelog

All notable changes to EvoCLI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added — Wave 5 (2026-05-12)

**Native web fetching (Rust)**
- `web.fetch` RPC endpoint built in Rust: `reqwest 0.12` (async HTTP, rustls TLS) + `scraper 0.21` (HTML parser, html5ever) + `htmd 0.1` (HTML→Markdown). Replaces Python `web_fetcher.py` dependency on `httpx` + `readability-lxml` + `html2text`
- Content extraction: priority CSS selector chain (`article → main → [role=main] → #content → body`)
- SSL certificate verification disabled by default (`danger_accept_invalid_certs(true)`) — self-signed and proxy certs work out-of-the-box
- Optional `selector` parameter for targeted CSS extraction (e.g. `"article"`, `".content"`)
- `fetch_url` pydantic-ai tool now calls Rust `web.fetch` instead of Python path

**Dynamic tool routing** (`tool_registry.py`, `tool_router.py`)
- `tool_registry.py` — single source of truth for all 66 tools with metadata: `name`, `rpc`, `description`, `tags`, `tier`, `base_score`, `keywords`
- 3-tier system: Tier 1 (Always-On, 3 tools), Tier 2 (Intent-Selected, fills to 12), Tier 3 (On-Demand, never auto-sent)
- 3-stage routing pipeline: keyword gate (0 ms) → tag matching (<1 ms) → embedding similarity fill (5–15 ms)
- `ToolScoreStore`: per-tool memory-weighted scoring. Effective score = `base × success_mult × failure_mult × freq_mult × time_decay`; persisted to `~/.evocli/tool_routing_scores.json`
- `auto_classify_unknown()`: new tools without a ToolSpec are classified at runtime by embedding similarity and injected into the running registry
- `_distill_session()` hook: tool success/failure events update routing scores after each session

**Automatic tool flow learning** (`tool_flow_miner.py`)
- `ToolFlowMiner`: mines repeated tool sequences from session events using PrefixSpan (≥2 occurrences → creates ToolFlow)
- Parameter templating: `"src/agent.py"` → `{{file}}`, symbol names → `{{symbol}}`, errors → `{{error}}`
- `FlowTrigger`: matches user queries to learned flows via intent tags + fastembed embedding similarity
- Thresholds: ≥0.70 similarity = auto-execute; ≥0.45 = suggest
- `FlowExecutor`: chains steps with `step_N.output` context passing; streaming progress via `_progress_cb`
- `/flows` slash command: lists learned flows with confidence and step tools
- Flow storage: `~/.evocli/flows/` (global) + `.evocli/flows/` (project-local)

**64 pydantic-ai tools (was 27)**
- Added 37 tools to pydantic-ai primary path to match LiteLLM fallback coverage:
  - Shell tools: `shell_ls`, `shell_find`, `shell_cat`, `shell_head`, `shell_tail`, `shell_wc`, `shell_mkdir`, `shell_mv`, `shell_cp`, `shell_touch`
  - Code intel: `symbol_variants`, `symbol_usages`, `code_intel_list_symbols`, `code_intel_incoming_calls`, `code_intel_outgoing_calls`
  - Assumption verifiers: `assume_has_tests`, `assume_is_pure`, `assume_caller_count`, `assume_has_side_effects`, `assume_verify`, `assume_is_deprecated`, `assume_is_only_caller`, `assume_types_match`
  - Impact analysis: `impact_check`, `impact_affected_tests`, `impact_batch_check`
  - Verification: `verify_task`, `verify_coverage`, `verify_drift`
  - Equivalence: `equiv_find`, `equiv_find_similar_code`
  - Git safety: `git_snapshot`, `git_restore`
  - System: `approval_request`, `memory_constraints`, `tool_list_user`, `tool_run_user`
- All new tools use `_sc()` safe bridge call — tool errors return `"Error: ..."` string instead of crashing the stream

**Shell architecture (cross-platform Rust native)**
- All shell convenience tools now use dedicated Rust RPC methods instead of `shell.run` + OS commands:
  - `shell_ls` → `shell.ls` (std::fs::read_dir)
  - `shell_find` → `shell.find` (walkdir)
  - `shell_cat` → `shell.cat` (std::fs::read_to_string)
  - `shell_head` / `shell_tail` → `shell.head` / `shell.tail`
  - `shell_wc` → `shell.wc`
  - `shell_mkdir` → `shell.mkdir` (std::fs::create_dir_all)
  - `shell_mv` / `shell_cp` / `shell_touch` → `shell.mv` / `shell.cp` / `shell.touch`
- `shell.run` Windows executor: bash (Git Bash/WSL) → pwsh (PS7) → powershell (PS5.1) priority chain; shell detection cached per-process in `OnceLock`; PS5.1 fallback rewrites `&&` to `;`

**Security — fully config-driven**
- `SecurityConfig` in `config.rs` now has `allowed_commands`, `blocked_patterns`, `denied_paths` fields with defaults equal to previous hardcoded values. Users can fully replace (not just append) any list
- `tools/src/lib.rs`: removed `ALLOWED_PREFIXES` and `DANGEROUS_PATTERNS` constants; replaced with `init_security(allowed, blocked)` called once from `tool_dispatch.rs` on startup
- `security.rs`: `SecurityController` reads all rules from config, no hardcoded constants except `config.toml` self-protect
- `load_or_default()`: config migration — auto-upgrades old configs with `allow_all_paths=false` and stale deny lists to new permissive defaults

**TUI improvements**
- `Ctrl+Y`: copy last AI message to system clipboard (`arboard` crate)
- `enable_mouse` config option (`[tui] enable_mouse = true/false`): default `false` — native terminal text selection/copy works; `true` — mouse wheel scrolls messages
- Token bar: now shows current context window usage (`in_tok` from last `cost_update`, SET not accumulated) instead of inflated cumulative sum
- `/help` updated with keyboard shortcuts, text selection modes, and config instructions
- `/flows` slash command added

**Progress feedback**
- Immediate `stream_chunk` sent before context building to reset TUI's 60 s first-chunk deadline
- `context_engine.build()` emits `soul_status` events at key phases: `"⚙ 构建上下文…"`, `"🧠 检索项目记忆…"`, `"📊 扫描代码库结构…"`
- `_run_litellm` tool loop emits `soul_status` showing current tool name per call (`"🔧 fs_read_range"`)
- `first_chunk_timeout_s` configurable via `[agent]` section (default 120 s, was hardcoded 60 s)

**Proactive project analysis**
- `SYSTEM_WORKFLOW` prompt now includes explicit "项目分析快速启动" section: when asked to analyze project, AI immediately calls `fs_read(AGENTS.md) → fs_read(README.md) → shell_ls(.)` without asking user for files
- `COMPACT_SYSTEM_PROMPT` updated with same rule

**Agent prompt pipeline**
- `context_engine.py` system_prompt uses `build_system_prompt()` as base — DO-NOW rules, `SYSTEM_WORKFLOW`, tool ordering, and failure recovery reach ALL LLM paths (both pydantic-ai and LiteLLM)

**CI/CD**
- `.github/workflows/ci.yml`: upgraded Rust toolchain from `1.82` to `stable` (resolves `ravif 0.13.0` edition2024 requirement via `fastembed → image → ravif` chain)
- `cargo clippy` changed to `-W warnings + continue-on-error` — style warnings don't block CI on each Rust release
- `.gitattributes`: all `.rs`, `.py`, `.toml`, `.yml` files use LF; prevents `cargo fmt --check` CRLF diffs from Windows dev machines
- `evocli-soul/ruff.toml`: configures ruff to ignore E402 (deferred imports), E741 (ambiguous vars), E501 (line length) in pre-existing code

### Fixed — Wave 4 (2026-05-12)

**Tool use routing (critical)**
- `_stream_litellm`: was calling `acompletion()` without `tools=`, making `finish_reason="tool_calls"` structurally unreachable. Now passes full tool schemas to streaming call
- `tool_call_seen`: stream loop now tracks `delta.tool_calls` in addition to `finish_reason`

**History — single-injection guarantee**
- History embedded exactly once via `_build_context` → `_inject_context`; removed duplicate injections from `_stream_litellm`, `_run_litellm`, and pydantic-ai `message_history`

**Session continuity**
- `handle_agent_run()`: `EvoCLIAgent` uses `session_id` from cwd-hash; previously always used `"default"`
- `agent.run()`: loads history from state, persists turn; removed duplicate persistence from handler

**`/compress` — full fix**
- Compress prompt uses real `prior_history`; `anchored_summary` injected unconditionally; token double-count fixed; `_maybe_compress_history()` no longer writes summary back to history

**`/add` command**
- Fixed argument order: `add_file(_add_sid, f)` → `add_file(f, _add_sid)`

**Per-role LLM config**
- `_run_litellm`, `_stream_litellm`, architect/editor paths read params from `get_task_params()` instead of hardcoded values

**Python config project-local merge**
- `llm_client` and `state.get_config()` both deep-merge project-local over global config

**Tool errors no longer crash pydantic-ai stream**
- All `@agent.tool_plain` functions use `_sc()` safe bridge call — JSON-RPC errors return `"Error: ..."` string, preventing stream failures

**Token bar accuracy**
- `finish_streaming()`: no longer adds chunk count to `tokens_output` (was double-counting with `cost_update`)
- `tokens_input` / `tokens_output` field semantics clarified; bar shows current context occupancy

**Progress during long operations**
- Immediate `stream_chunk` prevents 60 s TUI timeout during context building
- `context_engine.build()` emits phase-level `soul_status` events

**[E202] path deny**
- Default security changed to `allow_all_paths = true`, `denied_paths = []` — AI can read all project files by default; users opt-in to path restrictions via config

## [0.1.0] — 2026-05-12

### Added

**Core Runtime**
- Rust Host + Python Soul dual-engine architecture with JSON-RPC IPC
- 62 Rust-side tools (fs, git, shell, code_intel, memory, approval, prompt.choice)
- 55+ Python LLM-visible tools via Pydantic AI + LiteLLM router

**TUI**
- Full-screen ratatui terminal UI with Catppuccin × Tokyo Night color theme
- Streaming AI responses with live cursor animation
- Token usage progress bar with context-window fill indicator
- Thinking animation, word-wrap, virtual scrolling, notification bar, debug overlay
- `prompt.choice` interactive modal
- Responsive layout (Wide ≥120 / Normal 60–119 / Compact 40–59 / Tiny <40)

**Memory System**
- LanceDB vector memory with `jinaai/jina-embeddings-v2-base-zh` (768-dim, bilingual)
- SQLite FTS fallback, background pre-warm, memory distillation on session pause

**Code Intelligence**
- tree-sitter AST indexing (Rust, Python, JS, TS)
- BM25 full-text search (Tantivy embedded), PageRank-weighted ranking
- Hybrid BM25 + vector search (RRF fusion), LSP call chains

**Skill System**
- TOML-defined executable skills with multi-step pipelines
- Built-in skills: TDD, brainstorming, debugging, code review, git workflow

**Security**
- Blacklist security model; user-configurable via `config.toml`
- MCP server and client (`evocli mcp serve/connect/tools`)
- Auto Python environment setup via `uv`

**CLI Commands**
- `evocli` (TUI), `evocli init`, `evocli doctor`, `evocli index`
- `evocli skill`, `evocli git`, `evocli session`, `evocli mcp`
- `evocli stats`, `evocli tool register/list`

---

[Unreleased]: https://github.com/bambooqj/evocli/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bambooqj/evocli/releases/tag/v0.1.0

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
