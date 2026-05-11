---
name: "EvoCLI Skills"
description: "How to create and use TOML executable skills"
---

# EvoCLI Executable Skills

## Overview
EvoCLI supports executable skills defined in TOML format. These skills automate multi-step workflows, combining shell commands, file operations, and LLM generation.

## Skill Format
Skills are defined in `.toml` files located in `~/.evocli/skills/` (global) or `.evocli/skills/` (project-local).

```toml
[skill]
id = "my-custom-skill"
name = "My Custom Skill"
version = "1.0.0"
status = "verified"

[skill.trigger]
keywords = ["custom", "workflow"]

[[skill.steps]]
id = "step1"
action = "shell.run"
params = { command = "echo 'Hello World'" }

[[skill.steps]]
id = "step2"
action = "llm.generate"
params = { prompt = "Summarize the output", context = "..." }
requires_approval = true
```

## Lifecycle
1. **Load:** Skills are loaded at startup or via the `skill.reload` RPC method.
2. **Trigger:** Skills can be triggered manually or automatically based on keywords.
3. **Execute:** Steps are executed sequentially.
4. **Approval:** If a step has `requires_approval = true`, execution pauses until the user confirms via the TUI.

## Dry-Run Usage
Always use `dry_run = true` when testing a new skill or when you want to see the execution plan without actually running the commands. This is crucial for safety.

## Best Practices
- Keep skills focused on a single, well-defined workflow.
- Use `requires_approval` for destructive actions (e.g., `git push`, `rm -rf`).
- Handle errors gracefully within the skill steps.
- Document the skill's purpose and required parameters in the TOML file.
