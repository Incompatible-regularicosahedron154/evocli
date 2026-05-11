---
name: finishing-a-development-branch
description: Use when implementation is complete, all tests pass, and you need to decide how to integrate the work
source: https://github.com/obra/superpowers - bundled verbatim
---

# Finishing a Development Branch

## Overview

Guide completion of development work by presenting clear options and handling chosen workflow.

**Core principle:** Verify tests -> Detect environment -> Present options -> Execute choice -> Clean up.

**Announce at start:** "I am using the finishing-a-development-branch skill to complete this work."

## The Process

### Step 1: Verify Tests

Run project test suite. If tests fail, stop and fix before presenting options.

### Step 2: Detect Environment

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

### Step 4: Present Options

**Normal repo and named-branch worktree - present exactly these 4 options:**

```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Push and create a Pull Request
3. Keep the branch as-is (I will handle it later)
4. Discard this work

Which option?
```

### Step 5: Execute Choice

**Option 1: Merge Locally**
```bash
cd $MAIN_ROOT
git checkout <base-branch>
git pull
git merge <feature-branch>
# Verify tests on merged result
git branch -d <feature-branch>
```

**Option 2: Push and Create PR**
```bash
git push -u origin <feature-branch>
gh pr create --title "<title>" --body "Summary of changes"
```
Do NOT clean up worktree for Option 2.

**Option 3: Keep As-Is**
Report: "Keeping branch. Worktree preserved." Do not cleanup.

**Option 4: Discard**
Require typed "discard" confirmation. Then clean up worktree and force-delete branch.

### Step 6: Cleanup Workspace

Only for Options 1 and 4. Only clean up worktrees you created (under .worktrees/, worktrees/, or ~/.config/superpowers/worktrees/).

```bash
cd $MAIN_ROOT
git worktree remove $WORKTREE_PATH
git worktree prune
```

## Quick Reference

| Option | Merge | Push | Keep Worktree | Cleanup Branch |
|--------|-------|------|---------------|----------------|
| 1. Merge locally | yes | - | no | yes |
| 2. Create PR | - | yes | yes | - |
| 3. Keep as-is | - | - | yes | - |
| 4. Discard | - | - | no | yes (force) |

## Red Flags

Never:
- Proceed with failing tests
- Merge without verifying tests on result
- Delete work without typed confirmation
- Clean up worktrees you did not create
- Run git worktree remove from inside the worktree
