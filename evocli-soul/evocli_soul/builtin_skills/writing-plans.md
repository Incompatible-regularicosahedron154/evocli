---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
source: https://github.com/obra/superpowers - bundled verbatim
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for the codebase and questionable taste. Document everything they need to know: which files to touch for each task, code, testing, docs they might need to check, how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

**Announce at start:** "I am using the writing-plans skill to create the implementation plan."

**Save plans to:** docs/superpowers/plans/YYYY-MM-DD-feature-name.md

## Plan Document Header

Every plan MUST start with this header:

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]
**Architecture:** [2-3 sentences about approach]
**Tech Stack:** [Key technologies/libraries]
```

## Bite-Sized Task Granularity

Each step is one action (2-5 minutes):
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Task Structure

```markdown
### Task N: [Component Name]

**Files:**
- Create: exact/path/to/file.py
- Modify: exact/path/to/existing.py:123-145
- Test: tests/exact/path/to/test.py

- [ ] Step 1: Write the failing test
- [ ] Step 2: Run test to verify it fails (Expected: FAIL)
- [ ] Step 3: Write minimal implementation
- [ ] Step 4: Run test to verify it passes (Expected: PASS)
- [ ] Step 5: Commit
```

## No Placeholders

Every step must contain actual content. These are plan failures:
- "TBD", "TODO", "implement later"
- "Add appropriate error handling"
- "Write tests for the above" (without actual test code)
- Steps that describe what to do without showing how

## File Structure

Before defining tasks, map out which files will be created or modified. Design units with clear boundaries. Each file should have one clear responsibility.

## Self-Review

After writing the complete plan:
1. **Spec coverage:** Does every spec requirement map to a task?
2. **Placeholder scan:** Any TBD, TODO, incomplete sections?
3. **Type consistency:** Do types/method signatures match across tasks?

## Execution Handoff

After saving the plan, offer:

1. Subagent-Driven (recommended) - fresh subagent per task, review between tasks
2. Inline Execution - execute tasks in this session with checkpoints
