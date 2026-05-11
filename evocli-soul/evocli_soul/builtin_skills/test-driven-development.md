---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code
source: https://github.com/obra/superpowers - bundled verbatim
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you did not watch the test fail, you do not know if it tests the right thing.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over. No exceptions.

## Red-Green-Refactor

### RED - Write Failing Test

Write one minimal test showing what should happen.
- One behavior, clear name, real code (no mocks unless unavoidable)

### Verify RED - Watch It Fail (MANDATORY)

```bash
npm test path/to/test.test.ts   # or pytest, cargo test, etc.
```

Confirm test fails with expected message because feature is missing.

### GREEN - Minimal Code

Write simplest code to pass the test. Do not add features beyond the test.

### Verify GREEN - Watch It Pass (MANDATORY)

All tests must pass. Other tests must not break.

### REFACTOR - Clean Up

After green only: remove duplication, improve names, extract helpers. Keep tests green. Do not add behavior.

### Repeat

Next failing test for next feature.

## Good Tests

| Quality | Good | Bad |
|---------|------|-----|
| **Minimal** | One thing. "and" in name? Split it. | test validates email and domain and whitespace |
| **Clear** | Name describes behavior | test1 |
| **Shows intent** | Demonstrates desired API | Obscures what code should do |

## Common Rationalizations (All Wrong)

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve same goals" | Tests-after = "what does this do?" Tests-first = "what should this do?" |
| "Already manually tested" | Ad-hoc != systematic. No record, cannot re-run. |
| "Deleting X hours is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt. |
| "TDD will slow me down" | TDD faster than debugging. |

## Red Flags - STOP and Start Over

Any of these mean: Delete code. Start over with TDD.

- Code before test
- Test passes immediately
- Tests added "later"
- "I already manually tested it"
- "Tests after achieve the same purpose"
- "TDD is dogmatic, I am being pragmatic"
- "This is different because..."

## Verification Checklist

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass
- [ ] Edge cases and errors covered

## When Stuck

| Problem | Solution |
|---------|----------|
| Cannot figure out how to test | Write wished-for API first. Then write assertion. |
| Test too complicated | Design too complicated. Simplify interface. |
| Must mock everything | Code too coupled. Use dependency injection. |

## Final Rule

```
Production code -> test exists and failed first
Otherwise -> not TDD
```
