---
name: evocli-skills-workflow
description: "Use when creating executable automation workflows (Skills) for an EvoCLI project. Covers TOML skill format, dry-run verification, lifecycle management."
---
# Creating and Running EvoCLI Skills

Skills are the primary way to automate complex tasks in EvoCLI. A skill is a collection of tool calls with logic, validation, and metadata, defined in a TOML file.

## Skill Structure (TOML)

A typical skill file (`.evocli/skills/my-skill.toml`) looks like this:

```toml
[metadata]
name = "setup-feature"
description = "Creates a new feature branch with boilerplate"
version = "1.0.0"
author = "EvoCLI"

[[steps]]
name = "create-branch"
tool = "git.create_branch"
args = { name = "$BRANCH_NAME" }

[[steps]]
name = "add-boilerplate"
tool = "fs.write"
args = { path = "src/features/$FEATURE_NAME/index.ts", content = "export {}" }

[validation]
required_vars = ["BRANCH_NAME", "FEATURE_NAME"]
```

## The Skill Lifecycle

1. **Draft**: Created via `evocli skill draft` or manually. Drafts are stored in `.evocli/skills/drafts/`. They require explicit confirmation for every step.
2. **Verified**: A skill becomes "Verified" after it successfully passes a Level 3 dry-run. Verified skills can run with a single "Approve All" prompt.
3. **Trusted**: Trusted skills are those that have been manually approved by the user for background execution. They run without any prompts.

## Dry-Run Verification

Before a skill can be promoted, it must pass verification:

- **Level 1 (Syntax)**: Checks the TOML for errors and ensures all referenced tools exist.
- **Level 2 (Simulation)**: The Rust Host simulates the execution. It checks if files exist, if git branches are valid, etc., without actually making changes.
- **Level 3 (Sandbox)**: The skill is executed in a temporary, isolated directory. The final state is compared against the expected outcome.

## Running Skills

Invoke a skill using the `skill.run` tool:
```json
{
  "name": "setup-feature",
  "args": {
    "BRANCH_NAME": "feat-login",
    "FEATURE_NAME": "login"
  }
}
```

## Skill Evolution

EvoCLI monitors your manual tool usage. If it detects a sequence of tools being used together frequently (e.g., `fs.read` -> `fs.edit` -> `git.add` -> `git.commit`), it will automatically generate a Skill Draft and present it to you for review.

## Best Practices for Skill Authors

- **Use Variables**: Never hardcode paths or names. Use `$VARIABLE` syntax.
- **Add Validation**: Define `required_vars` to prevent runtime errors.
- **Keep Steps Atomic**: Each step should perform one logical action.
- **Include Descriptions**: Good descriptions help the LLM choose the right skill for the job.
- **Error Handling**: Use the `on_failure` attribute in steps to define rollback procedures.
