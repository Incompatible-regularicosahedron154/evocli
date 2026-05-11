---
name: requesting-code-review
description: Use when completing tasks, implementing major features, or before merging to verify work meets requirements
source: https://github.com/obra/superpowers - bundled verbatim
---

# Requesting Code Review

Dispatch a code reviewer subagent to catch issues before they cascade.

**Core principle:** Review early, review often.

## When to Request Review

**Mandatory:**
- After each task in subagent-driven development
- After completing major feature
- Before merge to main

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing complex bug

## How to Request

1. **Get git SHAs:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)  # or origin/main
HEAD_SHA=$(git rev-parse HEAD)
```

2. **Dispatch code reviewer subagent** with:
   - Brief summary of what you built
   - What it should do (requirements/plan excerpt)
   - BASE_SHA and HEAD_SHA

3. **Act on feedback:**
   - Fix Critical issues immediately
   - Fix Important issues before proceeding
   - Note Minor issues for later
   - Push back if reviewer is wrong (with reasoning)

## Example

```
[Just completed Task 2: Add verification function]

BASE_SHA=a7981ec   # Task 1 commit
HEAD_SHA=$(git rev-parse HEAD)

[Dispatch code reviewer subagent]
  Description: Added verifyIndex() and repairIndex() with 4 issue types
  Requirements: Task 2 from docs/superpowers/plans/deployment-plan.md
  BASE_SHA: a7981ec
  HEAD_SHA: 3df7661

[Subagent returns]:
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor: Magic number (100) for reporting interval

[Fix progress indicators]
[Continue to Task 3]
```

## Red Flags

Never:
- Skip review because "it is simple"
- Ignore Critical issues
- Proceed with unfixed Important issues
- Argue with valid technical feedback
