---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from current workspace or before executing implementation plans
source: https://github.com/obra/superpowers - bundled verbatim
---

# Using Git Worktrees

## Overview

Ensure work happens in an isolated workspace. Prefer your platform native worktree tools. Fall back to manual git worktrees only when no native tool is available.

**Core principle:** Detect existing isolation first. Use native tools. Fall back to git. Never fight the harness.

**Announce at start:** "I am using the using-git-worktrees skill to set up an isolated workspace."

## Step 0: Detect Existing Isolation

Before creating anything, check if you are already in an isolated workspace:

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

If GIT_DIR != GIT_COMMON (and not in a submodule): You are already in a linked worktree. Skip to Step 3.

## Step 1: Create Isolated Workspace

### 1a. Native Worktree Tools (preferred)

If you have a native worktree tool (EnterWorktree, WorktreeCreate, /worktree command), use it. Skip to Step 3.

### 1b. Git Worktree Fallback

Only if Step 1a does not apply:

```bash
# Safety: verify directory is ignored before creating
git check-ignore -q .worktrees 2>/dev/null || echo "MUST add to .gitignore first"

# Create worktree
git worktree add .worktrees/$BRANCH_NAME -b $BRANCH_NAME
cd .worktrees/$BRANCH_NAME
```

## Step 3: Project Setup

Auto-detect and run appropriate setup:

```bash
if [ -f package.json ]; then npm install; fi
if [ -f Cargo.toml ]; then cargo build; fi
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then pip install -e .; fi
```

## Step 4: Verify Clean Baseline

```bash
npm test / cargo test / pytest / go test ./...
```

If tests fail: Report failures, ask whether to proceed.
If tests pass: Report ready.

## Quick Reference

| Situation | Action |
|-----------|--------|
| Already in linked worktree | Skip creation (Step 0) |
| Native worktree tool available | Use it (Step 1a) |
| No native tool | Git worktree fallback (Step 1b) |
| Directory not ignored | Add to .gitignore + commit |
| Tests fail during baseline | Report failures + ask |

## Red Flags

Never:
- Create a worktree when Step 0 detects existing isolation
- Use git worktree add when you have a native worktree tool
- Skip safety verification for project-local directories
- Proceed with failing tests without asking
