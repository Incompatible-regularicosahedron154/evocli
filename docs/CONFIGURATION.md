# Configuration Reference

All configuration options for EvoCLI. The config file lives at `~/.evocli/config.toml` (global) or `{project}/.evocli/config.toml` (project-specific).

**Priority** (highest to lowest):
1. Environment variables
2. Project config `{project}/.evocli/config.toml`  ← deep-merged over global
3. Global config `~/.evocli/config.toml`
4. Built-in defaults

Both the Rust host and the Python Soul read this merged config, so project-level overrides apply to all LLM calls, routing decisions, and agent parameters.

Run `evocli init` for an interactive setup wizard. See `docs/config.toml.example` for a full annotated example.

---

## `[llm]` — Language Model

EvoCLI uses the OpenAI-compatible protocol for all providers. There is no `provider` field — set `base_url` and `api_key` directly.

```toml
[llm]
# API key — or set via environment variable (see below)
# api_key = "sk-..."

# Base URL for your provider's API endpoint
# OpenAI:    https://api.openai.com/v1
# Anthropic: https://api.anthropic.com      (OpenAI-compat mode)
# DeepSeek:  https://api.deepseek.com/v1
# Ollama:    http://localhost:11434/v1       (no key needed)
# base_url = "https://api.openai.com/v1"

# Default models (used when no task/role override applies)
fast  = "gpt-4o-mini"            # quick tasks — commit messages, Q&A, lint
smart = "gpt-4o"                 # complex work — refactoring, architecture
```

**Environment variable alternatives** (override `api_key`):
```bash
OPENAI_API_KEY="sk-..."
ANTHROPIC_API_KEY="sk-ant-..."
DEEPSEEK_API_KEY="..."
```

---

## `[llm.tasks]` — Task Routing

Route specific task types to a model tier or exact model name. Falls back to the global `fast`/`smart` if not set.

```toml
[llm.tasks]
# Values: "fast" | "smart" | any exact model name
commit  = "fast"     # auto-commit message generation
lint    = "fast"     # lint-fix loop
stream  = "fast"     # streaming chat responses
agent   = "smart"    # agent tool-calling loop
architect = "smart"  # architect step in architect/editor mode
editor  = "fast"     # editor step in architect/editor mode
```

---

## `[llm.params.<task>]` — Per-task Parameters

Override `max_tokens` and `temperature` per task. Inherits global defaults if not set.

```toml
[llm.params.agent]
max_tokens  = 4096
temperature = 0.7

[llm.params.stream]
max_tokens  = 2048
temperature = 0.7

[llm.params.architect]
max_tokens  = 2000
temperature = 0.3   # lower = more deterministic plans

[llm.params.editor]
max_tokens  = 4000
temperature = 0.2   # lower = more precise SEARCH/REPLACE blocks
```

---

## `[llm.roles.<name>]` — Per-role Model Config

Override model, base_url, and api_key for individual agent roles. Highest priority — overrides everything else for that role.

This enables multi-provider setups, e.g. Anthropic for the architect role and DeepSeek for the editor role.

```toml
[llm.roles.architect]
model    = "claude-opus-4-5"
base_url = "https://api.anthropic.com"
api_key  = "sk-ant-..."

[llm.roles.editor]
model    = "deepseek-coder"
base_url = "https://api.deepseek.com/v1"
api_key  = "..."

[llm.roles.commit]
model = "gpt-4o-mini"
# inherits base_url and api_key from [llm] global
```

**Resolution order** (highest wins):
1. `[llm.roles.<task>]` — role-specific provider/model/key
2. `[llm.tasks.<task>]` — task tier routing
3. `[llm.params.<task>]` — task token/temperature
4. `[llm]` global defaults

---

## `[llm.global_params]` — Global LLM Defaults

```toml
[llm.global_params]
max_tokens  = 4096
temperature = 0.7
```

---

## `[agent]` — Agent Behavior

```toml
[agent]
# Max tool calls per request (default: 20)
max_tool_calls = 20

# Max reflection loops for lint/test failures (default: 3)
max_reflections = 3

# Context-build timeout in seconds (default: 20)
context_build_timeout_s = 20

# Streaming LLM call timeout in seconds (default: 30)
stream_timeout_s = 30

# Nudge user to /compress after this many turns (default: 15)
history_compress_turns = 15

# Nudge user to /compress after estimated token count (default: 40000)
history_compress_tokens = 40000
```

---

## `[context]` — Token Budget

```toml
[context]
# Total token budget per request (default: 128,000)
max_total = 128000

# Max tokens allocated to code context (symbols, current file)
max_code = 32000
```

**Budget allocation** (approximate):
- P1 constraints: 4,000 tokens
- P2 tool patterns: 2,000 tokens
- P3 global prefs: 1,500 tokens
- Anchored summary (after /compress): up to 2,000 tokens
- Code context: up to `max_code`
- Remaining: conversation history

---

## `[safety]` — Write Approval

```toml
[safety]
# Require user confirmation before AI writes files
# false (default): AI asks before each write
# true:  AI can write without asking (suitable for CI/automation)
auto_approve_writes = false
```

---

## `[security]` — Command Execution

```toml
[security]
# Command execution mode:
# true (default):  blacklist mode — allow all except SHELL_BLOCKED_DANGEROUS
# false:           strict mode — only extra_allowed_commands are permitted
allow_all_commands = true

# Path access mode:
# true:   allow all paths (PATH_DENY_IMMUTABLE still enforced)
# false (default): extra_denied_paths also enforced
allow_all_paths = false

# Permanent dangerous pattern blocking (strongly recommended: true)
block_dangerous_always = true

# Additional commands to allow in strict mode (allow_all_commands = false)
extra_allowed_commands = ["docker", "kubectl", "terraform"]

# Additional patterns to always block (supports glob * wildcard)
extra_blocked_patterns = [
    "curl * | bash",
    "wget * | sh",
    "rm -rf ${HOME}",
]

# Additional paths to deny (substring match, case-insensitive)
extra_denied_paths = [
    "/prod",
    "/etc/nginx",
]
```

**Important**: `~/.evocli/config.toml` itself is in `PATH_DENY_IMMUTABLE` — the AI can never read or modify this file. This prevents the AI from changing its own security rules.

---

## `[memory]` — Memory System

```toml
[memory]
# Maximum episodic memories to retain (default: 1,000)
max_episodes = 1000
```

---

## `[graph]` — Knowledge Graph

Advanced settings for the code intelligence graph. Most users do not need to change these.

```toml
[graph]
# Label Propagation community detection iterations (default: 20)
lpa_max_iter = 20

# Merge communities smaller than this (default: 2)
min_community_size = 2

# Blast radius BFS depth (default: 5)
blast_radius_depth = 5

# Reciprocal Rank Fusion k constant (default: 60.0)
rrf_k = 60.0

# BM25 weight in hybrid search (default: 0.4)
bm25_weight = 0.4

# Vector search weight in hybrid search (default: 0.6)
vector_weight = 0.6
```

---

## Soul Script Path

```toml
# Path to the Python Soul entry point
# Set by `evocli init` or the EVOCLI_SOUL environment variable
soul_script = "/path/to/evocli-soul/evocli_soul/main.py"
```

**Priority for soul script resolution**:
1. `EVOCLI_SOUL` environment variable
2. `soul_script` in `~/.evocli/config.toml`
3. Relative path `evocli-soul/evocli_soul/main.py` from CWD
4. Walking up from the binary location
5. Python module fallback: `evocli_soul.main`

---

## Project-local Config

Create `{project}/.evocli/config.toml` to override settings for a specific project. All sections support partial override — only fields you specify are changed.

```toml
# {project}/.evocli/config.toml
# Safe to check into git (no secrets here — put api_key in global config or env)

[llm]
# Use a different model for this project
fast  = "deepseek-chat"
smart = "deepseek-reasoner"
base_url = "https://api.deepseek.com/v1"

[llm.roles.architect]
# Use Claude for architecture on this project
model    = "claude-opus-4-5"
base_url = "https://api.anthropic.com"

[agent]
# This project's tool loop needs more room
max_tool_calls = 30

[context]
# Large monorepo — increase code budget
max_code = 64000

[security]
# This project needs Docker and kubectl
extra_allowed_commands = ["docker", "docker-compose", "kubectl"]
extra_denied_paths = ["/etc/", "/prod/"]
```

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `EVOCLI_SOUL` | Override path to Python Soul |
| `OPENAI_API_KEY` | OpenAI / OpenAI-compatible API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `HF_ENDPOINT` | Hugging Face mirror URL (e.g., `https://hf-mirror.com`) |
| `EVOCLI_RESUME_SESSION` | Session ID to resume on startup |
