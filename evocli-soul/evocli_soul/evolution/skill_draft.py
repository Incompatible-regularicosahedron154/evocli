"""Skill 草案生成 — 唯一职责：将重复模式转换为 Skill 草案。"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Optional

from evocli_soul.evolution.pattern_detector import Pattern


@dataclass
class SkillDraft:
    id:               str
    name:             str
    trigger_keywords: list[str]
    steps:            list[dict]


def generate(pattern: Pattern) -> Optional[SkillDraft]:
    if len(pattern.sequence) < 2:
        return None
    steps = [
        {
            "id":                f"step_{i+1}",
            "action":            action,
            "params":            {},
            "requires_approval": action in ("fs.apply_diff", "git.commit", "shell.run"),
        }
        for i, action in enumerate(pattern.sequence)
    ]
    return SkillDraft(
        id=f"auto_{uuid.uuid4().hex[:8]}",
        name=f"自动: {' → '.join(pattern.sequence)}",
        trigger_keywords=pattern.sequence[:2],
        steps=steps,
    )
