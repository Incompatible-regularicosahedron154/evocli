---
name: using-evocli
description: "Use this skill when working in an EvoCLI-powered project to leverage its unique capabilities: long-term memory, skills, workflow automation, and code intelligence."
---
# Using EvoCLI Effectively

EvoCLI transforms a standard repository into an intelligent, self-documenting workspace. By using EvoCLI tools instead of raw shell commands, you ensure that your actions are recorded, analyzed, and optimized over time.

## The EvoCLI Workflow

When you enter an EvoCLI project, your first step should always be context retrieval.

1. **Recall Context**: Use `memory.query` to see what has been done recently and what constraints are in place.
2. **Check Skills**: Run `skill.list` to see if there are existing automations for your current task.
3. **Execute with Tools**: Use the specialized `fs.*`, `git.*`, and `code_intel.*` tools. These tools are faster than shell equivalents and provide structured feedback to the LLM.
4. **Contribute to Memory**: When you make a decision or discover a pattern, use `memory.add` to store it for future sessions.

## Memory Integration

EvoCLI's memory system is its greatest asset. It prevents "context drift" where the AI forgets project rules over long sessions.

- **Constraint Memories**: Use these for architectural rules (e.g., "Always use functional components").
- **Episodic Memories**: These are automatic logs of what you did. You can query them to find "how did I fix that bug last week?".
- **Semantic Memories**: These store the "why" behind the code.

## Skill Execution

Skills are more than just scripts; they are verified workflows.

- **Drafting**: If you find yourself performing a complex sequence of steps, use `skill.draft`.
- **Verification**: Always run `skill.verify` before trusting a new skill. This runs a multi-level dry-run to ensure safety.
- **Trusted Skills**: Once a skill is trusted, it can be invoked as a single command, drastically reducing token usage and execution time.

## Code Intelligence

EvoCLI's `code_intel` tools use the Rust Host to parse your codebase.

- **Symbol Search**: Find definitions and references across the entire project instantly.
- **Dependency Mapping**: Understand how a change in one file affects the rest of the system.
- **AST Grep**: Perform structural searches that are more accurate than regex.

## Best Practices

- **Prefer Tools over Shell**: `fs.read` is better than `cat` because it handles large files gracefully and provides line numbers.
- **Be Explicit in Memory**: When adding to memory, use clear, concise language.
- **Leverage the TUI**: The `evocli tui` provides a rich environment for debugging complex tool chains.
- **Evolution is Key**: Pay attention to EvoCLI's suggestions for new skills. The system learns from your specific coding style.

## Security and Safety

EvoCLI operates on a "Safety First" principle.
- All shell commands are checked against a whitelist.
- Destructive operations (like `git.reset --hard`) require user confirmation unless the skill is explicitly "Trusted".
- The Python environment is isolated, preventing prompt injection from accessing your system directly.
