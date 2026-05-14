"""
context_summary.py — Anchored Summary Compaction (OpenCode Recursive Summary pattern)

Extracted from context_engine.py to keep context_engine.py focused on
token budgeting and context assembly.

Single responsibility: compact long conversation histories into structured
Markdown summaries that preserve Goal / Constraints / Progress / Decisions.
"""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.context.summary")

# ── Anchored Summary Template (OpenCode pattern) ──────────────────────────────
# Structured Markdown template used by both the /compress command and the
# automatic background summarization (every 8 turns). Preserves:
#   - Goal: what the user is trying to accomplish
#   - Constraints: project rules the AI must not forget after compaction
#   - Progress: done / in-progress / blocked
#   - Key Decisions: architectural choices made
#   - Next Steps: priority order for continuation

_ANCHORED_SUMMARY_TEMPLATE = """
You are summarizing an AI coding assistant's session to preserve key context.
Output EXACTLY this Markdown structure (no extra text):

## Goal
[One paragraph: what was the user trying to accomplish?]

## Constraints
[Bullet list: any rules, limitations, or "never do X" statements from the conversation]

## Progress
### Done
[Bullet list of completed steps]
### In Progress
[What was being worked on when context was compacted]
### Blocked
[Any blockers or unresolved issues]

## Key Decisions
[Bullet list of architectural/design decisions made]

## Next Steps
[Bullet list of what should happen next, in priority order]

## Critical Context
[Any facts the agent MUST remember: file paths changed, errors seen, commands run]

## Relevant Files
[Bullet list of files that were read or edited: path — what was done]
""".strip()


async def compact_session_to_anchor(
    history: list[dict],
    llm_client,
    existing_summary: str = "",
) -> str:
    """
    Compact a long history into an Anchored Summary using a weak/fast LLM.

    Research source: OpenCode's "Recursive Anchored Summary" algorithm.
    - Uses a Markdown template to preserve: Goal, Constraints, Progress, Key Decisions
    - When called recursively, feeds the old summary + new messages → updates in place
    - Preserves the "Constraints" section to keep user rules alive after compaction
    - The agent can "re-read" its goal even after a full context reset

    Returns: compact Markdown summary (typically 500-1500 tokens).
    """
    history_text = "\n".join(
        f"[{m.get('role','?')}]: {str(m.get('content',''))[:500]}"
        for m in history[-40:]
    )

    if existing_summary:
        # Recursive update: feed old summary + new messages
        prompt = (
            f"Below is the existing summary of this coding session:\n\n"
            f"```\n{existing_summary}\n```\n\n"
            f"New messages since that summary:\n\n{history_text}\n\n"
            f"Update the anchored summary to reflect the new progress. "
            f"Keep all sections. Mark completed items as done."
        )
    else:
        prompt = (
            f"Here is a coding session conversation:\n\n{history_text}\n\n"
            f"Create an anchored summary following the template."
        )

    system = _ANCHORED_SUMMARY_TEMPLATE
    try:
        summary = await llm_client.complete_for_task(
            "summarize",
            prompt,
            system=system,
        )
        log.info("Context compacted: %d history msgs → anchored summary (%d chars)",
                 len(history), len(summary))
        return summary
    except Exception as e:
        log.warning("Anchored summary compaction failed (%s), using simple truncation", e)
        return "\n".join(
            f"[{m.get('role','?')}]: {str(m.get('content',''))[:200]}"
            for m in history[-5:]
        )
