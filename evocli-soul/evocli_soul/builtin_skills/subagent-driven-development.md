---
name: subagent-driven-development
description: Use when executing implementation plans with independent tasks in the current session
source: https://github.com/obra/superpowers - bundled verbatim
---

# Subagent-Driven Development

Execute plan by dispatching fresh subagent per task, with two-stage review after each: spec compliance review first, then code quality review.

**Core principle:** Fresh subagent per task + two-stage review (spec then quality) = high quality, fast iteration

**Continuous execution:** Do not pause to check in with your human partner between tasks. Execute all tasks from the plan without stopping. Only stop for: BLOCKED status, genuine ambiguity preventing progress, or all tasks complete.

## When to Use

Use when:
- You have an implementation plan
- Tasks are mostly independent
- You want to stay in the current session

## The Process

1. **Read plan, extract all tasks with full text, create todo list**
2. **Per task:**
   - Dispatch implementer subagent with full task text + context
   - If subagent asks questions, answer clearly and completely
   - Subagent implements, tests, commits, self-reviews
   - Dispatch spec compliance reviewer
   - If spec reviewer finds issues: implementer fixes, then re-review
   - Dispatch code quality reviewer
   - If code quality reviewer finds issues: implementer fixes, then re-review
   - Mark task complete
3. **After all tasks:** Dispatch final code reviewer for entire implementation
4. **Use finishing-a-development-branch skill**

## Model Selection

- Mechanical implementation tasks (1-2 files, clear specs): cheap/fast model
- Integration and judgment tasks (multi-file): standard model
- Architecture, design, review: most capable model

## Handling Implementer Status

- **DONE:** Proceed to spec compliance review
- **DONE_WITH_CONCERNS:** Read concerns before proceeding
- **NEEDS_CONTEXT:** Provide missing info and re-dispatch
- **BLOCKED:** Assess blocker and either provide context, use more capable model, or break into smaller pieces

## Red Flags

Never:
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed issues
- Start code quality review before spec compliance passes
- Move to next task while review has open issues
- Accept "close enough" on spec compliance

Always:
- Answer subagent questions before letting them proceed
- Re-review after implementer fixes issues
- Run spec review before code quality review
