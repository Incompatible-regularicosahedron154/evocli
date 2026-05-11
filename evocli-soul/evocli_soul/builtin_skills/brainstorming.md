---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior."
source: https://github.com/obra/superpowers - bundled verbatim
---

# Brainstorming Ideas Into Designs

Help turn ideas into fully formed designs and specs through natural collaborative dialogue.

<HARD-GATE>
Do NOT invoke any implementation skill, write any code, scaffold any project, or take any implementation action until you have presented a design and the user has approved it. This applies to EVERY project regardless of perceived simplicity.
</HARD-GATE>

## Checklist

You MUST complete these items in order:

1. **Explore project context** - check files, docs, recent commits
2. **Ask clarifying questions** - one at a time, understand purpose/constraints/success criteria
3. **Propose 2-3 approaches** - with trade-offs and your recommendation
4. **Present design** - in sections scaled to complexity, get user approval after each section
5. **Write design doc** - save to docs/superpowers/specs/YYYY-MM-DD-topic-design.md and commit
6. **User reviews written spec** - ask user to review before proceeding
7. **Transition to implementation** - invoke writing-plans skill to create implementation plan

## Process

**Understanding the idea:**
- Check out the current project state first (files, docs, recent commits)
- Ask questions one at a time to refine the idea
- Prefer multiple choice questions when possible
- Focus on: purpose, constraints, success criteria

**Exploring approaches:**
- Propose 2-3 different approaches with trade-offs
- Lead with your recommended option and explain why

**Presenting the design:**
- Once you understand what you are building, present the design
- Scale each section to its complexity
- Ask after each section whether it looks right
- Cover: architecture, components, data flow, error handling, testing

**Key Principles:**
- **One question at a time** - Do not overwhelm with multiple questions
- **Multiple choice preferred** - Easier to answer than open-ended when possible
- **YAGNI ruthlessly** - Remove unnecessary features from all designs
- **Explore alternatives** - Always propose 2-3 approaches before settling
- **Incremental validation** - Present design, get approval before moving on

## After the Design

**Documentation:**
- Write the validated design to docs/superpowers/specs/YYYY-MM-DD-topic-design.md
- Commit the design document to git

**User Review Gate:**
After writing the spec, ask the user to review before proceeding. Wait for approval.

**Implementation:**
- Invoke the writing-plans skill to create a detailed implementation plan
- Do NOT invoke any other skill. writing-plans is the next step.

## Anti-Pattern: "This Is Too Simple To Need A Design"

Every project goes through this process. "Simple" projects are where unexamined assumptions cause the most wasted work. The design can be short, but you MUST present it and get approval.

## Red Flags

- Writing code before design approval
- Skipping clarifying questions
- Proposing only one approach
- Vague success criteria
- Moving to implementation without user approval
