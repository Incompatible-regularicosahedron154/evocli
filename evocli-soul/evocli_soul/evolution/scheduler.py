"""进化调度器 — 定时触发后台进化任务和记忆自动蒸馏。

修复 C1: 移除 Rocketry 线程模式。
  原因: Rocketry 在独立线程中调用 bridge.call() → sys.stdout.write()，
  与主 asyncio 线程形成无锁并发写，破坏 JSON-RPC 协议。
  最优方案: 统一使用 asyncio，所有 stdout 写入在同一事件循环内串行完成。

修复 C2: 传递真实事件（从 events.db 读取）。
  原因: 原版传递 events=[] 空列表，导致模式检测永远找不到任何模式，
  Evolution 系统虽然在运行但对用户行为毫无感知。

修复 C3: 集成 Memory 自动蒸馏（不依赖 session.pause）。
  原因: MemoryDistiller 原本只在用户显式 session.pause 时触发，
  若用户不暂停则积累的工具调用经验永远不会写入长期记忆。
  现在每 5 分钟自动从 events.db 读取事件并蒸馏。
"""
from __future__ import annotations
import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import Callable, Awaitable, Optional

log = logging.getLogger("evocli.evolution.scheduler")

# 蒸馏所需最少事件数（避免为极少量事件浪费 LLM 调用）
MIN_EVENTS_FOR_DISTILL = 5


def start(
    observe_fn: Callable[[dict], Awaitable[dict]],
    distill_fn: Optional[Callable[[dict], Awaitable[dict]]] = None,
) -> None:
    """启动后台调度（纯 asyncio，无跨线程风险）。

    Args:
        observe_fn:  EvolutionEngine.observe — 每 10 分钟运行
        distill_fn:  MemoryDistiller.run    — 每 5 分钟运行（可选）
    """
    asyncio.create_task(_asyncio_loop(observe_fn, distill_fn))
    features = "evolution scan (10m)"
    if distill_fn is not None:
        features += " + memory auto-distillation (5m)"
    log.info("Background scheduler started: %s", features)


def _load_recent_events(limit: int = 200) -> list[dict]:
    """从 Rust EventBus 的 events.db 读取最近的工具调用事件。

    只读操作，不走 bridge（避免 JSON-RPC 死锁）。
    """
    events: list[dict] = []
    try:
        db_path = Path.home() / ".evocli" / "events.db"
        if not db_path.exists():
            log.debug("events.db not found — skipping scan")
            return events
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            rows = conn.execute(
                "SELECT session_id, event_type, data "
                "FROM events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for sid, etype, data_str in rows:
                entry: dict = {"session_id": sid, "type": etype}
                if data_str:
                    try:
                        entry["data"] = json.loads(data_str)
                    except Exception:
                        entry["data"] = data_str
                events.append(entry)
            log.debug("Scheduler: loaded %d events from events.db", len(events))
        finally:
            conn.close()
    except Exception as e:
        log.debug("Scheduler: failed to read events.db: %s", e)
    return events


async def _asyncio_loop(
    observe_fn: Callable[[dict], Awaitable[dict]],
    distill_fn: Optional[Callable[[dict], Awaitable[dict]]],
) -> None:
    """主调度循环：每 5 分钟触发，交替运行蒸馏和进化扫描。

    时间轴：
      t=5m  → distill only
      t=10m → evolution scan + distill
      t=15m → distill only
      t=20m → evolution scan + distill
    """
    cycle = 0
    while True:
        await asyncio.sleep(300)  # 每 5 分钟
        cycle += 1

        events = _load_recent_events(limit=200)

        # ── Memory 自动蒸馏（每 5 分钟）──────────────────────────────
        if distill_fn is not None and len(events) >= MIN_EVENTS_FOR_DISTILL:
            try:
                distill_result = await distill_fn({
                    "events":     events,
                    "project_id": "current",
                    "session_id": "daemon",
                })
                n = distill_result.get("distilled", 0) if isinstance(distill_result, dict) else 0
                if n:
                    log.info("Auto-distillation: wrote %d memory item(s) from daemon", n)
            except Exception as e:
                log.debug("Auto-distillation error: %s", e)

        # ── Evolution scan（每 10 分钟 = 每隔两个 5m 周期）──────────
        if cycle % 2 == 0:
            try:
                result = await observe_fn({"events": events, "project_id": "current"})
                drafts_saved = result.get("drafts_saved", 0)
                if drafts_saved:
                    log.info(
                        "Evolution scan: %d pattern(s), %d new skill draft(s) saved",
                        len(result.get("patterns", [])),
                        drafts_saved,
                    )
            except Exception as e:
                log.debug("Evolution scan error: %s", e)

