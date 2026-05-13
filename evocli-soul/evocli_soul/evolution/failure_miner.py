"""
FailureMiner — 失败知识挖掘（Section 9.6）

从失败事件中提取可学习的工程知识，写入 L2 Memory。
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("evocli.evolution.failure_miner")

FAILURE_TYPES = {
    "compilation":   ["build_failed", "type_error", "compile_error"],
    "test_failure":  ["test_failed", "assertion_err", "pytest_failed"],
    "tool_error":    ["tool_timeout", "tool_crash", "bridge_error"],
    "logic_bug":     ["wrong_output", "e2e_fail"],
    "permission":    ["access_denied", "sandbox_trip"],
}

@dataclass
class FailurePattern:
    failure_type: str
    error_msg:    str
    frequency:    int = 1
    last_seen:    str = ""

class FailureMiner:
    """从失败事件中提取工程教训并存入 Memory（Section 9.6）。"""

    def __init__(self, bridge):
        self.bridge = bridge

    async def mine(self, events: list[dict], project_id: str = ".") -> dict:
        """
        分析事件流，提取失败模式，写入 L2 记忆。
        """
        failure_events = [e for e in events if e.get("type", "") in ("tool_error", "skill_failed", "test_failed", "error")]
        if not failure_events:
            return {"mined": 0, "patterns": []}

        patterns = self._classify(failure_events)
        written  = 0

        for p in patterns:
            try:
                import evocli_soul.state as _fm_state
                import asyncio as _fm_asyncio
                _fm_mem = _fm_state.get_memory(project_id=project_id)
                _fm_content = (
                    f"失败模式：{p.failure_type}\n"
                    f"错误类型：{p.failure_type}\n"
                    f"错误信息：{p.error_msg[:200]}\n"
                    f"出现次数：{p.frequency}\n"
                    f"最后出现：{p.last_seen}"
                )
                await _fm_asyncio.to_thread(
                    _fm_mem.add,
                    _fm_content,
                    "episodic",
                    "project",
                )
                written += 1
            except Exception as e:
                log.debug("Failed to write failure pattern: %s", e)

        log.info("FailureMiner: mined %d patterns from %d events", written, len(failure_events))
        return {"mined": written, "patterns": [{"type": p.failure_type, "count": p.frequency} for p in patterns]}

    def _classify(self, events: list[dict]) -> list[FailurePattern]:
        """将失败事件分类为已知模式。"""
        counts: dict[str, FailurePattern] = {}
        for ev in events:
            ev_type = ev.get("type", "")
            err_msg = ev.get("error", ev.get("message", "unknown"))
            
            # 匹配失败类型
            matched = "unknown"
            for ftype, triggers in FAILURE_TYPES.items():
                if any(t in ev_type for t in triggers):
                    matched = ftype
                    break
            
            if matched in counts:
                counts[matched].frequency += 1
                counts[matched].last_seen  = datetime.now().isoformat()
            else:
                counts[matched] = FailurePattern(
                    failure_type = matched,
                    error_msg    = str(err_msg)[:200],
                    last_seen    = datetime.now().isoformat(),
                )
        return list(counts.values())
