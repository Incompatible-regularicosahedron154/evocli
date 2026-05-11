"""Evolution 门面 — 组合子模块，对外提供统一接口。"""
from __future__ import annotations
import logging

from evocli_soul.evolution.pattern_detector import (
    Pattern, extract_sequences, detect_patterns, PATTERN_THRESHOLD
)
from evocli_soul.evolution.skill_draft      import SkillDraft, generate as generate_draft
from evocli_soul.evolution.failure_miner    import FailureMiner
from evocli_soul.evolution.knowledge_classifier import KnowledgeClassifier, Transferability
from evocli_soul.evolution import decay_detector
from evocli_soul.evolution import scheduler as _scheduler
from evocli_soul.evolution.circuit_breaker  import get_circuit_breaker

log = logging.getLogger("evocli.evolution")

__all__ = ["EvolutionEngine"]


class EvolutionEngine:
    """门面：协调所有 evolution 子模块（Section 9）。"""

    def __init__(self, bridge, skill_engine=None):
        self.bridge             = bridge
        self.skill_engine       = skill_engine
        self._failure_miner     = FailureMiner(bridge)
        self._knowledge_clf     = KnowledgeClassifier()

    async def observe(self, params: dict) -> dict:
        """主观察入口：模式检测 + 失败挖掘。"""
        events = params.get("events", [])

        result: dict = {"patterns": [], "drafts": [], "failures_mined": 0}

        # Section 9.5：模式检测
        if len(events) >= PATTERN_THRESHOLD:
            sequences   = extract_sequences(events)
            patterns    = detect_patterns(sequences)
            significant = [p for p in patterns if p.frequency >= PATTERN_THRESHOLD]
            drafts      = [d for p in significant[:3] if (d := generate_draft(p))]
            result["patterns"] = [{"sequence": p.sequence, "frequency": p.frequency} for p in significant]
            result["drafts"]   = [{"id": d.id, "name": d.name, "trigger_keywords": d.trigger_keywords, "steps": d.steps} for d in drafts]

        # Section 9.6：失败知识挖掘
        if events:
            project = params.get("project_id", ".")
            mine_result = await self._failure_miner.mine(events, project)
            result["failures_mined"] = mine_result.get("mined", 0)

        log.info("Evolution scan: %d patterns, %d drafts, %d failures",
                 len(result["patterns"]), len(result["drafts"]), result["failures_mined"])
        return result

    async def check_skill_decay(self, skill_id: str, project: str) -> dict:
        """Section 9.7：Skill 腐化检测。"""
        return await decay_detector.check(skill_id, project, self.bridge)

    async def promote_knowledge(self, memory_item: dict) -> dict:
        """Section 9.9：跨项目知识迁移——将 P1 知识提升到 P2/P3。"""
        return await self._knowledge_clf.promote_if_transferable(memory_item, self.bridge)

    def start_background_scheduler(self) -> None:
        """Section 9.5：启动进化飞轮后台调度。"""
        _scheduler.start(self.observe)
