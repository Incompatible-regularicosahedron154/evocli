---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
source: https://github.com/obra/superpowers - bundled verbatim
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you have not completed Phase 1, you cannot propose fixes.

## The Four Phases

You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

BEFORE attempting ANY fix:

1. **Read Error Messages Carefully** - read completely including stack traces
2. **Reproduce Consistently** - can you trigger it reliably?
3. **Check Recent Changes** - git diff, recent commits, new dependencies
4. **Gather Evidence in Multi-Component Systems** - add instrumentation at each component boundary before proposing fixes
5. **Trace Data Flow** - where does bad value originate? Keep tracing up until source.

### Phase 2: Pattern Analysis

1. **Find Working Examples** - locate similar working code in same codebase
2. **Compare Against References** - read reference implementation COMPLETELY
3. **Identify Differences** - list every difference, however small
4. **Understand Dependencies** - what settings, config, environment does this need?

### Phase 3: Hypothesis and Testing

1. **Form Single Hypothesis** - "I think X is the root cause because Y"
2. **Test Minimally** - the SMALLEST possible change to test hypothesis
3. **Verify Before Continuing** - Did it work? Yes -> Phase 4. No -> form NEW hypothesis
4. **When You Do Not Know** - say "I do not understand X". Do not pretend to know.

### Phase 4: Implementation

1. **Create Failing Test Case** - simplest possible reproduction. MUST have before fixing.
2. **Implement Single Fix** - address root cause. ONE change at a time.
3. **Verify Fix** - test passes? No other tests broken?
4. **If Fix Does Not Work** - STOP. Count fixes tried. If 3+: question the architecture.

### 3+ Fixes Failed: Question Architecture

Pattern indicating architectural problem:
- Each fix reveals new shared state / coupling / problem in different place
- Fixes require massive refactoring

STOP and question fundamentals:
- Is this pattern fundamentally sound?
- Should we refactor architecture vs. continue fixing symptoms?
- Discuss with your human partner before attempting more fixes.

## Red Flags - STOP and Follow Process

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- Adding multiple changes at once
- Proposing solutions before tracing data flow
- "One more fix attempt" (when already tried 2+)

**ALL of these mean: STOP. Return to Phase 1.**

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, do not need process" | Simple issues have root causes too. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check. |
| "Reference too long, I will adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question pattern. |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Form theory, test minimally | Confirmed or new hypothesis |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |
