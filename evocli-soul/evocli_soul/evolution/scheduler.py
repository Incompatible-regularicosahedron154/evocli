"""进化调度器 — 唯一职责：定时触发后台进化任务。

修复 C1: 移除 Rocketry 线程模式。
  原因: Rocketry 在独立线程中调用 bridge.call() → sys.stdout.write()，
  与主 asyncio 线程形成无锁并发写，破坏 JSON-RPC 协议。
  最优方案: 统一使用 asyncio，所有 stdout 写入在同一事件循环内串行完成。
"""
from __future__ import annotations
import asyncio
import logging

log = logging.getLogger("evocli.evolution.scheduler")


def start(observe_fn) -> None:
    """启动后台进化调度（纯 asyncio，无跨线程风险）。"""
    asyncio.create_task(_asyncio_loop(observe_fn))
    log.info("Evolution scheduler started (asyncio mode)")


async def _asyncio_loop(observe_fn) -> None:
    while True:
        await asyncio.sleep(600)  # 每 10 分钟
        try:
            await observe_fn({"events": [], "project_id": "current"})
        except Exception as e:
            log.debug("Evolution scan error: %s", e)
