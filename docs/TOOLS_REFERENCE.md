# Tool Reference

All tools available in EvoCLI.

**Architecture:**
- **Rust tools** (`shell.*`, `fs.*`, `git.*`, etc.): called via `bridge.call(tool, params)` from Python. Pure Rust implementations — cross-platform, no system shell required.
- **Python pydantic-ai tools** (64 total): registered via `@agent.tool_plain`, visible to the LLM for tool calling. All shell convenience tools use the Rust RPC methods above.
- **`shell.run`**: for external programs (cargo, git, npm, python, etc.) that require a real process.

**Tool routing**: `tool_router.py` dynamically selects ≤12 tools per request based on intent (keyword gate → tag matching → embedding similarity). Tool schemas not sent to the LLM save ~55% context tokens.

---

## Rust-Native Shell Tools (cross-platform, no system shell)

These are pure Rust implementations using `std::fs` and `walkdir` — identical behavior on Windows, Linux, macOS.

### `shell.ls`
List directory contents.
```json
params: { "path": "src/", "long": false }
returns: { "path": "src/", "entries": ["main.rs", "lib.rs"], "count": 2 }
// long=true: entries = [{"name": "main.rs", "is_dir": false, "size": 1234}]
```

### `shell.find`
Find files by name pattern (walkdir, no glob shell needed).
```json
params: { "name": "*.rs", "path": "src/" }
returns: { "files": ["src/main.rs", "src/lib.rs"], "count": 2 }
```

### `shell.grep`
Regex search across files (Rust regex, no grep binary needed).
```json
params: { "pattern": "fn main", "path": "src/" }
returns: { "matches": [{"file": "src/main.rs", "line": 5, "content": "fn main() {"}], "count": 1 }
```

### `shell.cat`
Read file contents.
```json
params: { "file": "src/main.rs" }
returns: { "file": "src/main.rs", "content": "..." }
```

### `shell.head` / `shell.tail`
Read first/last N lines.
```json
params: { "file": "src/main.rs", "n": 20 }
returns: { "file": "src/main.rs", "n": 20, "content": "..." }
```

### `shell.wc`
Count lines, words, characters.
```json
params: { "file": "src/main.rs" }
returns: { "file": "src/main.rs", "lines": 142, "words": 890, "chars": 4521 }
```

### `shell.mkdir`
Create directory recursively.
```json
params: { "path": "src/new/module" }
returns: { "created": "src/new/module" }
```

### `shell.mv` / `shell.cp`
Move or copy files.
```json
params: { "src": "old.rs", "dst": "new.rs" }
returns: { "moved": {"from": "old.rs", "to": "new.rs"} }
```

### `shell.rm`
Remove file or directory.
```json
params: { "path": "tmp/", "recursive": true }
returns: { "removed": "tmp/" }
```

### `shell.touch`
Create empty file or update timestamp.
```json
params: { "file": "src/new.rs" }
returns: { "touched": "src/new.rs" }
```

### `shell.run`
Execute any whitelisted external program. Uses `sh -c` on Linux/macOS; bash → pwsh → powershell fallback on Windows.
```json
params: { "cmd": "cargo build --release", "cwd": ".", "timeout_s": 60, "dry_run": false }
returns: { "exit_code": 0, "stdout": "...", "stderr": "..." }
```

---

## Rust Tools (62 total)

### File System — `fs.*`

#### `fs.read`
Read file contents.
```json
params: { "path": "src/main.rs" }
returns: string (file contents)
```

#### `fs.write`
Write or overwrite a file.
```json
params: { "path": "src/main.rs", "content": "..." }
returns: { "written": true }
```

#### `fs.diff`
Generate unified diff between two strings.
```json
params: { "old": "...", "new": "...", "path": "hint for header" }
returns: string (unified diff)
```

#### `fs.apply_diff`
Apply a unified diff to a file.
```json
params: { "path": "src/main.rs", "diff": "--- ...\n+++ ...\n@@..." }
returns: { "applied": true }
```

---

### Git — `git.*`

#### `git.status`
Get working tree status.
```json
params: {}
returns: string (git status output)
```

#### `git.commit`
Commit staged changes.
```json
params: { "message": "feat: add feature", "files": ["src/main.rs"] }
returns: { "sha": "abc123" }
```

#### `git.diff`
Show diff for a file or entire working tree.
```json
params: { "path": "src/main.rs" }  // optional
returns: string (diff output)
```

#### `git.restore`
Restore file to last commit.
```json
params: { "path": "src/main.rs" }
returns: { "restored": true }
```

#### `git.snapshot`
Create a stash snapshot for rollback safety.
```json
params: { "message": "before refactor" }
returns: { "ref": "stash@{0}" }
```

#### `git.shadow_snapshot` / `git.shadow_restore`
Shadow-git side-car snapshots (don't touch project `.git`).
```json
params: { "label": "checkpoint-1" }
```

---

### Shell — `shell.*`

All shell commands are checked against the security blacklist before execution.

#### `shell.run`
Execute a shell command.
```json
params: { "cmd": "cargo check", "cwd": "/path", "timeout_s": 30 }
returns: { "stdout": "...", "stderr": "...", "exit_code": 0 }
```

#### `shell.grep`
Grep file contents.
```json
params: { "pattern": "fn main", "path": "src/", "recursive": true }
returns: [{ "file": "...", "line": 1, "text": "..." }]
```

#### `shell.find`
Find files by name pattern.
```json
params: { "pattern": "*.rs", "path": "src/" }
returns: ["src/main.rs", ...]
```

#### `shell.ls`
List directory contents.
```json
params: { "path": "src/" }
returns: [{ "name": "main.rs", "is_dir": false, "size": 1234 }]
```

#### `shell.cat` / `shell.head` / `shell.tail`
Read file with limits.
```json
params: { "path": "file.txt", "lines": 50 }
returns: string
```

#### `shell.mkdir` / `shell.touch` / `shell.mv` / `shell.cp` / `shell.rm`
Standard file operations.
```json
// mkdir
params: { "path": "src/new_dir" }
// mv / cp
params: { "src": "a.txt", "dst": "b.txt" }
// rm
params: { "path": "a.txt" }
```

#### `shell.wc`
Word/line/byte count.
```json
params: { "path": "src/main.rs" }
returns: { "lines": 42, "words": 200, "bytes": 1500 }
```

#### `shell.sed` / `shell.awk` / `shell.sort` / `shell.uniq` / `shell.cut` / `shell.tr`
Text processing utilities.
```json
params: { "cmd": "..." }   // full command string passed to shell
```

---

### Search — `search.*`

#### `search.code`
Search codebase for a pattern using hybrid BM25+vector search.
```json
params: { "query": "authentication token", "path": "src/" }
returns: [{ "file": "...", "line": 5, "score": 0.9, "text": "..." }]
```

---

### Code Intelligence — `code_intel.*`

#### `code_intel.find_symbol`
Find a symbol by name.
```json
params: { "name": "validate_token", "kind": "function" }
returns: { "file": "...", "line": 42, "signature": "fn validate_token(...)" }
```

#### `code_intel.list_symbols`
List all symbols in a file or directory.
```json
params: { "path": "src/auth.rs" }
returns: [{ "name": "...", "kind": "...", "line": 1 }]
```

#### `code_intel.incoming_calls`
Functions that call a given symbol.
```json
params: { "symbol_id": "auth::validate_token" }
returns: [{ "name": "handle_request", "file": "...", "line": 10 }]
```

#### `code_intel.outgoing_calls`
Functions called by a given symbol.
```json
params: { "symbol_id": "auth::validate_token" }
returns: [{ "name": "verify_signature", "file": "...", "line": 5 }]
```

#### `code_intel.full_chain`
Full upstream call chain (all callers recursively).
```json
params: { "symbol_id": "auth::validate_token", "depth": 5 }
returns: { "tree": { "name": "...", "callers": [...] } }
```

#### `code_intel.full_downstream_chain`
Full downstream call chain (all callees recursively).

#### `code_intel.impact_radius`
Which symbols would be affected by changing a given symbol.
```json
params: { "symbol_id": "auth::validate_token" }
returns: { "affected": [...], "risk": "HIGH" }
```

#### `code_intel.index_status`
Check indexing status and coverage.
```json
params: {}
returns: { "indexed_files": 42, "total_symbols": 1200, "last_updated": "..." }
```

#### `code_intel.ingest_tree_sitter`
Force re-index a file or directory.
```json
params: { "path": "src/" }
```

#### `code_intel.ranked_context`
Get PageRank-weighted relevant symbols for a given context.
```json
params: { "modified_file": "src/auth.rs", "mentioned": ["validate_token"], "limit": 20 }
returns: [{ "symbol_id": "...", "score": 0.9, "snippet": "..." }]
```

---

### Symbol Analysis — `symbol.*`

#### `symbol.lookup`
Precise symbol lookup (id + file + line).
```json
params: { "name": "validate_token" }
returns: { "found": true, "symbols": [{ "id": "auth::validate_token", "file": "...", "line": 42 }] }
```

#### `symbol.variants`
All variants/implementations of an enum or trait.
```json
params: { "type_name": "AppState" }
returns: [{ "variant": "Idle" }, { "variant": "Streaming" }]
```

#### `symbol.usages`
All places a symbol is used.
```json
params: { "symbol_id": "auth::validate_token", "limit": 50 }
returns: [{ "file": "...", "line": 10, "context": "..." }]
```

#### `symbol.lifecycle`
How a symbol is created, used, and destroyed across its lifetime.
```json
params: { "symbol_id": "auth::Token" }
returns: { "created": [...], "used": [...], "dropped": [...] }
```

---

### Assumption Verifier — `assume.*`

Tools for verifying code assumptions before making changes.

#### `assume.verify`
Verify a natural-language assumption about code.
```json
params: { "assumption": "validate_token has exactly 1 caller", "subject": "auth::validate_token" }
returns: { "verified": false, "actual": "3 callers found", "evidence": [...] }
```

#### `assume.is_pure`
Check if a function has no side effects.
```json
params: { "symbol": "auth::hash_password" }
returns: { "is_pure": true, "confidence": 0.9 }
```

#### `assume.caller_count`
Count callers of a symbol.
```json
params: { "symbol": "auth::validate_token" }
returns: { "count": 3 }
```

#### `assume.has_tests`
Check if a symbol has test coverage.
```json
params: { "symbol": "auth::validate_token" }
returns: { "has_tests": true, "test_names": ["test_valid_token", ...] }
```

#### `assume.has_side_effects`
Check what side effects a function has.
```json
params: { "symbol": "auth::login" }
returns: { "effects": ["writes_db", "sends_email"] }
```

#### `assume.is_only_caller`
Check if the AI's current context is the only caller.
```json
params: { "symbol": "auth::internal_hash" }
returns: { "is_only_caller": false }
```

#### `assume.is_deprecated`
Check if a symbol is deprecated.
```json
params: { "symbol": "auth::old_login" }
returns: { "is_deprecated": true, "replacement": "auth::login_v2" }
```

#### `assume.types_match`
Verify that two types are compatible.
```json
params: { "type_a": "Token", "type_b": "AuthToken" }
returns: { "match": false, "reason": "different structs" }
```

---

### Impact Analysis — `impact.*`

#### `impact.check`
Check risk level of modifying a symbol.
```json
params: { "symbol": "auth::validate_token", "change_type": "signature" }
returns: { "risk": "CRITICAL", "affected_count": 15, "callers": [...] }
```
`change_type`: `"behavior"` | `"signature"` | `"delete"`

#### `impact.affected_tests`
Which tests would break if a symbol changed.
```json
params: { "symbol": "auth::validate_token" }
returns: [{ "test": "test_login", "file": "tests/auth_test.rs", "line": 10 }]
```

#### `impact.batch_check`
Check impact for multiple symbols at once.
```json
params: { "symbols": ["auth::validate_token", "auth::login"] }
returns: [{ "symbol": "...", "risk": "HIGH", "affected": 5 }]
```

---

### Equivalence Analysis — `equiv.*`

#### `equiv.find`
Find semantically equivalent code patterns.
```json
params: { "pattern": "token.is_expired()", "scope": "src/" }
returns: [{ "file": "...", "line": 5, "code": "...", "similarity": 0.95 }]
```

#### `equiv.check_deps`
Check if two code paths have equivalent dependencies.
```json
params: { "path_a": "src/auth.rs:42", "path_b": "src/auth_v2.rs:10" }
returns: { "equivalent": false, "differences": [...] }
```

#### `equiv.find_similar_code`
Find code similar to a given snippet.
```json
params: { "code": "fn validate(token: &str) -> bool {", "threshold": 0.8 }
returns: [{ "file": "...", "line": 5, "similarity": 0.92 }]
```

---

### Memory — `memory.*`

#### `memory.recall`
Search memory for relevant context.
```json
params: { "query": "authentication design decisions", "top_k": 10 }
returns: [{ "id": "...", "title": "...", "body": "...", "score": 0.9 }]
```

#### `memory.write`
Write a note to memory.
```json
params: { "title": "Auth uses JWT", "body": "...", "tags": ["auth", "security"] }
returns: { "id": "mem_abc123" }
```

#### `memory.constraints`
Get all active project constraints.
```json
params: {}
returns: [{ "rule": "No direct DB access from handlers", "added": "2026-01-01" }]
```

---

### Verification — `verify.*`

#### `verify.task`
Verify that a task has been completed correctly.
```json
params: { "task": "Add token expiry check", "criteria": ["test passes", "no regressions"] }
returns: { "passed": true, "checks": [...] }
```

#### `verify.coverage`
Check test coverage for a file or function.
```json
params: { "path": "src/auth.rs" }
returns: { "coverage_pct": 78, "uncovered_lines": [42, 55] }
```

#### `verify.drift`
Check if implementation has drifted from spec/constraints.
```json
params: { "path": "src/auth.rs" }
returns: { "drifted": false, "violations": [] }
```

---

### Approval & Interaction — `approval.*` / `prompt.*`

#### `approval.request`
Ask the user to approve an action before proceeding.
```json
params: { "message": "About to delete 3 files. Continue?", "action": "rm src/old_auth.rs" }
returns: { "approved": true }
```

#### `prompt.choice`
Present the user with a list of options.
```json
params: {
  "title": "How should I fix the type error?",
  "options": [
    { "id": "change_type", "label": "Change the type to String" },
    { "id": "add_cast",    "label": "Add .to_string() call" },
    { "id": "skip",        "label": "Skip for now" }
  ],
  "allow_custom": true
}
returns:
  { "type": "selected", "id": "change_type" }
  { "type": "custom",   "text": "user typed something" }
  { "type": "cancelled" }
```

---

### User Tools — `tool.*`

#### `tool.list_user`
List user-registered custom tools.
```json
params: {}
returns: [{ "name": "my_lint", "cmd": "./tools/lint.sh", "description": "Run linter" }]
```

#### `tool.run_user`
Execute a user-registered tool.
```json
params: { "name": "my_lint", "args": ["src/"] }
returns: { "stdout": "...", "exit_code": 0 }
```

---

## Python Tools (LLM-visible, 64 total)

These are registered in `agent.py` via `@agent.tool_plain` and appear in the LLM's function-calling schema. The **tool router** (`tool_router.py`) selects ≤12 relevant tools per request based on intent — the LLM only sees those tools, not all 64.

All tool errors are caught by `_sc()` (safe bridge call) — failures return `"Error: ..."` string rather than crashing the stream.

### File System
| Tool | Rust RPC | Description |
|---|---|---|
| `fs_read` | `fs.read` | Read full file contents |
| `fs_read_range` | `fs.read_range` | Read line range (preferred for large files) |
| `fs_read_symbol` | `fs.read_range` | Read source code of a named symbol |
| `fs_write` | `fs.write` | Write/overwrite a file |
| `fs_apply_search_replace` | python-native | Apply SEARCH/REPLACE block (Aider pattern) |
| `fs_apply_diff` | `fs.apply_diff` | Apply unified diff patch |
| `fs_apply_batch` | python-native | Apply SEARCH/REPLACE to multiple files |
| `fs_lint_file` | `shell.run` | Run linter (py_compile or cargo check) |
| `diff_parse_stats` | python-native | Parse diff: files_changed, lines_added/removed |

### Shell (all Rust-native, cross-platform)
| Tool | Rust RPC | Description |
|---|---|---|
| `shell_run` | `shell.run` | Run external program (cargo, git, npm, etc.) |
| `shell_grep` | `shell.grep` | Regex search across files |
| `shell_ls` | `shell.ls` | List directory contents |
| `shell_find` | `shell.find` | Find files by name pattern |
| `shell_cat` | `shell.cat` | Read file contents |
| `shell_head` | `shell.head` | Read first N lines |
| `shell_tail` | `shell.tail` | Read last N lines |
| `shell_wc` | `shell.wc` | Count lines/words/chars |
| `shell_mkdir` | `shell.mkdir` | Create directory recursively |
| `shell_mv` | `shell.mv` | Move/rename file or directory |
| `shell_cp` | `shell.cp` | Copy file or directory |
| `shell_touch` | `shell.touch` | Create empty file |
| `run_and_capture` | `shell.run` | Run command, return stdout/stderr/exit_code |
| `test_and_capture` | `shell.run` | Run tests, return output only on failure |

### Code Search & Intelligence
| Tool | Rust RPC | Description |
|---|---|---|
| `search_code` | `search.code` | Semantic/regex search across codebase |
| `code_hybrid_search` | python-native | Hybrid BM25 + vector search (RRF fusion) |
| `symbol_lookup` | `symbol.lookup` | Find symbol definition, file, and line |
| `symbol_variants` | `symbol.variants` | Find all variants/implementations of a type |
| `symbol_usages` | `symbol.usages` | Find all call sites of a symbol |
| `code_intel_list_symbols` | `code_intel.list_symbols` | List all symbols in a file |
| `code_intel_incoming_calls` | `code_intel.incoming_calls` | Direct callers of a symbol |
| `code_intel_outgoing_calls` | `code_intel.outgoing_calls` | Functions called by a symbol |
| `code_blast_radius` | `code_intel.blast_radius` | Full impact analysis with risk level |
| `code_symbol_context` | `code_intel.symbol_context` | 360° context: callers, callees, communities |
| `code_communities` | `code_intel.communities` | Functional code communities (graph detection) |

### Assumption Verifiers (run BEFORE modifying shared code)
| Tool | Rust RPC | Description |
|---|---|---|
| `assume_has_tests` | `assume.has_tests` | Check if symbol has test coverage |
| `assume_is_pure` | `assume.is_pure` | Check if function is pure (no side effects) |
| `assume_caller_count` | `assume.caller_count` | Count call sites (change risk assessment) |
| `assume_has_side_effects` | `assume.has_side_effects` | Check for I/O, mutation side effects |
| `assume_verify` | `assume.verify` | Verify a natural language assumption |
| `assume_is_deprecated` | `assume.is_deprecated` | Check for deprecation markers |
| `assume_is_only_caller` | `assume.is_only_caller` | Check if current context is the sole caller |
| `assume_types_match` | `assume.types_match` | Check type signature compatibility |

### Impact Analysis
| Tool | Rust RPC | Description |
|---|---|---|
| `impact_check` | `impact.check` | Full impact radius of modifying a symbol |
| `impact_affected_tests` | `impact.affected_tests` | Tests affected by a change |
| `impact_batch_check` | `impact.batch_check` | Batch impact check for multiple symbols |

### Git
| Tool | Rust RPC | Description |
|---|---|---|
| `git_status` | `git.status` | Working tree status |
| `git_diff` | `git.diff` | Staged and unstaged diff |
| `git_commit` | `git.commit` | Create a commit |
| `git_snapshot` | `git.snapshot` | Create rollback snapshot (before risky edits) |
| `git_restore` | `git.restore` | Restore from snapshot |

### Verification
| Tool | Rust RPC | Description |
|---|---|---|
| `verify_task` | `verify.task` | Verify task contract completion |
| `verify_coverage` | `verify.coverage` | Verify test coverage threshold |
| `verify_drift` | `verify.drift` | Check implementation vs spec drift |

### Equivalence Search
| Tool | Rust RPC | Description |
|---|---|---|
| `equiv_find` | `equiv.find` | Find existing implementations matching an intent |
| `equiv_find_similar_code` | `equiv.find_similar_code` | Find semantically similar code blocks |

### Memory
| Tool | Rust RPC | Description |
|---|---|---|
| `memory_recall` | python-native (LanceDB) | Search project memory |
| `memory_write` | python-native (LanceDB) | Save decision/lesson to memory |
| `memory_constraints` | python-native (LanceDB) | Retrieve all active project constraints |

### Web
| Tool | Rust RPC | Description |
|---|---|---|
| `fetch_url` | `web.fetch` | Fetch URL as clean Markdown (Rust: reqwest + scraper + htmd, SSL not verified by default) |

### System
| Tool | Rust RPC | Description |
|---|---|---|
| `approval_request` | `approval.request` | Request user confirmation (TUI modal) |
| `tool_list_user` | `tool.list_user` | List user-registered custom tools |
| `tool_run_user` | `tool.run_user` | Run a user-registered custom tool |

### MCP (External plugins)
| Tool | Rust RPC | Description |
|---|---|---|
| `mcp_call` | python-native | Call an external MCP tool |
| `mcp_list_tools` | python-native | List available MCP tools from connected servers |
