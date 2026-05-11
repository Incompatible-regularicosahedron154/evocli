---
name: evocli-memory
description: "Use when you need to store or retrieve long-term information in an EvoCLI project. Covers constraint, episodic, semantic, and procedural memory types."
---
# EvoCLI Memory System

The EvoCLI memory system provides a persistent, tiered storage mechanism for project knowledge. It allows AI agents to maintain context across different sessions and even different users.

## Memory Tiers

Knowledge is categorized by its scope and importance:

- **P1 (Project)**: Stored in the `.evocli/memory/project/` directory. This contains information specific to the current repository. It is always loaded first.
- **P2 (Tool)**: Stored in `~/.evocli/memory/tools/`. This contains learned patterns for specific tools (e.g., "The best way to run tests in this framework is...").
- **P3 (Global)**: Stored in `~/.evocli/memory/global/`. This contains your general preferences and cross-project knowledge.

## Memory Types

### 1. Constraint Memory
Constraints are the "laws" of the project. They are used to enforce coding standards, security policies, and architectural decisions.
- **Example**: "Never use `any` in TypeScript files."
- **Usage**: Checked automatically before any code modification.

### 2. Episodic Memory
Episodic memory records "episodes" or events. It answers the question "What happened?".
- **Example**: "Fixed the race condition in the auth module by adding a mutex."
- **Usage**: Useful for generating changelogs or debugging recurring issues.

### 3. Semantic Memory
Semantic memory stores facts and relationships. It answers the question "What is this?".
- **Example**: "The `DataStore` class is a singleton that manages the local SQLite connection."
- **Usage**: Helps the AI understand the codebase structure without re-reading every file.

### 4. Procedural Memory
Procedural memory stores "how-to" guides.
- **Example**: "To deploy to staging: 1. Run build, 2. Run smoke tests, 3. Push to staging branch."
- **Usage**: Provides step-by-step instructions for complex, multi-stage tasks.

## Interacting with Memory

### Adding Memory
Use the `memory.add` tool. You must specify the type and priority.
```json
{
  "content": "Use Tailwind for all new components.",
  "type": "constraint",
  "priority": "P1"
}
```

### Recalling Memory
Use `memory.query`. This performs a hybrid search (vector + keyword) across all tiers.
```json
{
  "query": "How do we handle authentication?"
}
```

### Forgetting/Updating
Memory is not static. Use `memory.update` to refine existing knowledge or `memory.archive` to remove outdated information.

## Evolution of Memory
EvoCLI's "Soul" periodically reviews episodic memories to identify patterns. If a certain fix is applied multiple times, it may be promoted to a Constraint or a Procedural memory.
