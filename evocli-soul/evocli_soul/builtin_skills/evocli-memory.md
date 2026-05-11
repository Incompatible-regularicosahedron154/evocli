---
name: "EvoCLI Memory"
description: "How to use the EvoCLI memory system effectively"
---

# EvoCLI Memory System

## Overview
EvoCLI uses a multi-tiered memory system (LanceDB + jina-embeddings) to persist context across sessions. The memory is categorized by priority levels (P1, P2, P3) and supports time decay and conflict resolution.

## Priority Levels

### P1: Core Directives & Constraints
- **What:** Absolute rules, architectural invariants, user preferences.
- **When to write:** When the user explicitly states a rule ("Always use spaces, never tabs", "We use PostgreSQL, not MySQL").
- **Impact:** Always injected into the context window. Never decays.

### P2: Project Context & State
- **What:** Current architecture, active tasks, recent decisions, known bugs.
- **When to write:** After completing a significant milestone, making an architectural decision, or discovering a complex bug.
- **Impact:** Retrieved based on semantic relevance. Decays slowly.

### P3: Episodic Memory
- **What:** Specific actions taken, command outputs, minor fixes.
- **When to write:** Automatically handled by the system (e.g., memory distillation). You rarely need to write P3 memories manually.
- **Impact:** Used for short-term context. Decays quickly.

## When to Write Memories
- **DO NOT** write a memory for every small change.
- **DO** write a memory when you learn something that will be useful in a future session.
- **DO** write a memory when you establish a new pattern or convention.

## Constraint Rules
When writing P1 constraints, be specific and actionable.
- **Bad:** "Write good code."
- **Good:** "All new API endpoints must include rate limiting and input validation using Zod."

## Memory Distillation
The system automatically distills successful and failed execution paths into L2 semantic memory. You can rely on this for general project knowledge, but explicit architectural decisions should still be manually recorded as P2 memories.
