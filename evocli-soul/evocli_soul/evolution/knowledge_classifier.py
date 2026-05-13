"""
KnowledgeClassifier — 跨项目知识迁移分类器（Section 9.9）

判断一条 Memory 是否可以从项目级（P1）迁移到全局（P3），
实现"工程知识跨项目共享"。
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import IntEnum

log = logging.getLogger("evocli.evolution.knowledge_classifier")


class Transferability(IntEnum):
    PROJECT_ONLY     = 0   # 不可迁移（项目专属）
    LANGUAGE_SCOPED  = 1   # 同语言项目可用
    GLOBAL           = 2   # 全局适用


# 判断为项目专属的信号
PROJECT_SPECIFIC_SIGNALS = [
    "myapp", "this project", "这个项目", "当前项目",
    "specific", "hardcoded", "internal",
]

# 判断为通用知识的信号
TRANSFERABLE_SIGNALS = [
    "rust", "python", "typescript", "golang",
    "cargo", "npm", "pip",
    "pattern", "best practice", "avoid", "always",
    "模式", "最佳实践", "避免", "总是",
]


@dataclass
class ClassificationResult:
    transferability: Transferability
    confidence:      float   # 0.0 - 1.0
    reason:          str


class KnowledgeClassifier:
    """
    判断 Memory 条目的迁移性，实现 P1→P3 自动提升（Section 9.9）。
    """

    def classify(self, memory_item: dict) -> ClassificationResult:
        """判断一条记忆的迁移性。"""
        text = f"{memory_item.get('title','')} {memory_item.get('body','')}".lower()

        project_signals  = sum(1 for s in PROJECT_SPECIFIC_SIGNALS if s in text)
        transfer_signals = sum(1 for s in TRANSFERABLE_SIGNALS if s in text)

        if project_signals >= 2:
            return ClassificationResult(
                transferability=Transferability.PROJECT_ONLY,
                confidence=min(0.9, project_signals * 0.3),
                reason=f"Contains {project_signals} project-specific signals",
            )
        elif transfer_signals >= 2 and project_signals == 0:
            return ClassificationResult(
                transferability=Transferability.GLOBAL,
                confidence=min(0.85, transfer_signals * 0.25),
                reason=f"Contains {transfer_signals} general engineering signals",
            )
        elif transfer_signals >= 1:
            return ClassificationResult(
                transferability=Transferability.LANGUAGE_SCOPED,
                confidence=0.6,
                reason="Language or tool specific",
            )
        else:
            return ClassificationResult(
                transferability=Transferability.PROJECT_ONLY,
                confidence=0.5,
                reason="Insufficient signals",
            )

    async def promote_if_transferable(self, memory_item: dict, bridge) -> dict:
        """如果知识可迁移，将其从 P1 提升到更高范围。"""
        result = self.classify(memory_item)
        if result.transferability == Transferability.PROJECT_ONLY:
            return {"promoted": False, "reason": result.reason}

        target_scope = "global" if result.transferability == Transferability.GLOBAL else "tool"
        try:
            import evocli_soul.state as _kc_state
            import asyncio as _kc_asyncio
            # Use the current project's memory instance (None → normalize to cwd).
            # The entry's project_id field is set by memory_client.add():
            #   "global" if priority == "global" else self.project_id
            # So global-scoped memories get project_id="global" in the store,
            # and are visible from all projects via the vector search filter
            # (project_id = current OR project_id = 'global').
            _kc_mem = _kc_state.get_memory(project_id=None)
            _kc_content = (
                f"[{target_scope.upper()}] {memory_item.get('title','')}\n"
                f"{memory_item.get('body', '')}"
            )
            await _kc_asyncio.to_thread(
                _kc_mem.add,
                _kc_content,
                memory_item.get("memory_type", "episodic"),
                target_scope,
            )
            log.info("Promoted memory to %s: %s", target_scope, memory_item.get("title", "")[:50])
            return {"promoted": True, "to_scope": target_scope, "confidence": result.confidence}
        except Exception as e:
            log.warning("Failed to promote: %s", e)
            return {"promoted": False, "error": str(e)}
