"""
EvoCLI Soul — 入口

唯一职责：启动 JSON-RPC 服务循环并注册所有 handler。
业务逻辑全部在 handlers/ 和各功能模块中。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading

# Windows GBK 修复：强制 stdout/stderr/stdin UTF-8（subprocess pipe 需要显式包装）
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
    # stdin 也需要包装：未包装时 Windows pipe 模式下 readline() 可能等到 EOF 才返回
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8", line_buffering=True)


def _setup_logging() -> None:
    from evocli_soul.soul_logging import setup_logging  # 修复：logging.py 已重命名为 soul_logging.py
    debug = "--debug" in sys.argv
    setup_logging(debug)


def _build_router():
    import evocli_soul.state as state
    from evocli_soul.router import Router
    from evocli_soul.handlers import register_all

    router = Router(state)
    register_all(router)
    return router


async def _serve(router) -> None:
    """主循环：读 stdin → dispatch → 写 stdout。"""
    from evocli_soul.rpc import emit_event

    await emit_event("soul_ready")
    log = logging.getLogger("evocli.soul")
    log.info("EvoCLI Soul ready")

    # 跨平台 stdin 读取（线程 + asyncio.Queue）
    # asyncio.get_running_loop() is the correct API in Python 3.10+.
    # get_event_loop() is deprecated and raises DeprecationWarning in 3.10+,
    # RuntimeError in some 3.12+ contexts when there is no current event loop.
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[str] = asyncio.Queue()

    def _read_stdin() -> None:
        try:
            for line in sys.stdin:
                line = line.strip()
                if line:
                    loop.call_soon_threadsafe(q.put_nowait, line)
        except Exception as e:
            log.warning("stdin closed: %s", e)
        finally:
            # Guard against calling into a closed loop during shutdown.
            if not loop.is_closed():
                loop.call_soon_threadsafe(q.put_nowait, "")  # EOF sentinel

    threading.Thread(target=_read_stdin, daemon=True).start()

    while True:
        line = await q.get()
        if not line:
            log.info("stdin EOF — Soul exiting")
            break
        try:
            msg     = json.loads(line)
            req_id  = msg.get("id", "")
            method  = msg.get("method", "")
            params  = msg.get("params", {})

            # 响应消息（Rust → Soul 的 tool call 响应）
            # result/error 字段存在 = 这是对 bridge.call() 的回复
            if "result" in msg or "error" in msg:
                import evocli_soul.state as state
                bridge = state.get_bridge()
                await bridge.handle_response(msg)
                continue

            # Attach error callback so handler exceptions are logged, not silently swallowed.
            # Without this, a crash in router.dispatch() is only visible as a GC warning.
            task = asyncio.create_task(router.dispatch(req_id, method, params))
            task.add_done_callback(_log_task_exception)
        except json.JSONDecodeError as e:
            log.warning("JSON parse error: %s | %r", e, line[:120])
        except Exception as e:
            log.exception("Main loop error: %s", e)


def _log_task_exception(task: asyncio.Task) -> None:
    """Background task error callback — logs unhandled exceptions."""
    if not task.cancelled() and task.exception():
        log = logging.getLogger("evocli.soul")
        log.error("Background task %s failed: %s", task.get_name(), task.exception())


async def main() -> None:
    _setup_logging()

    # 显式初始化 bridge 单例（在任何 background task 启动前，消除竞态）
    import evocli_soul.state as _state
    from evocli_soul.host_bridge import HostBridge
    _state.set_bridge(HostBridge())

    router = _build_router()

    log = logging.getLogger("evocli.soul")

    # 模型 Context Window 预热（后台，不阻塞启动）
    async def _warmup_model_context():
        """在后台探测模型 context window，解决新模型名称问题。
        通过 bridge.call("config.get") 获取配置，不直接读取 config.toml。
        """
        try:
            import os
            import evocli_soul.state as _state
            bridge = _state.get_bridge()
            cfg = await bridge.call("config.get", {})
            llm = cfg.get("llm", {}) if isinstance(cfg, dict) else {}
            base_url = llm.get("base_url")
            api_key  = llm.get("api_key") or os.environ.get("OPENAI_API_KEY")
            tiers    = llm.get("tiers", {})
            models   = list({tiers.get("fast"), tiers.get("smart")} - {None})
            if models and base_url and api_key:
                from evocli_soul.model_context import warmup
                await warmup(models, base_url, api_key)
        except Exception as e:
            log.debug("Model context warmup skipped: %s", e)

    # P2-3: 启动 Daemon Workers（memory_distill 每5分钟，evolution_scan 每10分钟）
    async def _start_daemons():
        try:
            from evocli_soul.multi_agent import get_daemon_manager
            import evocli_soul.state as state
            mgr = get_daemon_manager(state.get_bridge())
            mgr.start()
            log.info("Daemon workers started (memory_distill/5m, evolution_scan/10m)")
        except Exception as e:
            log.warning("Daemon workers init failed (non-fatal): %s", e)

    # Fix: 启动 Evolution 后台调度器（每10分钟读取真实事件，检测重复模式，生成 Skill 草案）
    # 根因：start_background_scheduler() 从未被调用，Evolution 系统完全处于休眠状态。
    async def _start_evolution_scheduler():
        try:
            import evocli_soul.state as _st
            from evocli_soul.evolution import EvolutionEngine
            engine = EvolutionEngine(_st.get_bridge())
            engine.start_background_scheduler()
            log.info("Evolution background scheduler started (reads events.db every 10m)")
        except Exception as e:
            log.warning("Evolution scheduler init failed (non-fatal): %s", e)

    task1 = asyncio.create_task(_start_daemons())   # 包含 memory_distill(5m) + evolution_scan(10m)
    task1.add_done_callback(_log_task_exception)
    task_evo = asyncio.create_task(_start_evolution_scheduler())   # Fix: Evolution 调度器
    task_evo.add_done_callback(_log_task_exception)
    task2 = asyncio.create_task(_warmup_model_context())  # 后台预热 context window
    task2.add_done_callback(_log_task_exception)

    # 后台预热 memory + fastembed 模型（100MB+，首次加载需要 30–120 秒）
    # 目的：让首次请求不等模型加载，直接用 None 降级跳过 constraints；
    # 预热完成后所有后续请求自动获得完整的向量记忆功能。
    async def _prewarm_memory():
        from evocli_soul.rpc import emit_event as _emit
        import time
        import evocli_soul.state as _st
        loop = asyncio.get_running_loop()

        # If memory is already cached in this process, skip silently — no user-facing
        # messages needed since there's nothing to wait for.
        already_ready = _st.get_memory_if_ready() is not None
        if already_ready:
            log.info("Memory already initialised — skipping pre-warm notification")
            return

        # Announce loading so the user knows something is happening.
        await _emit("soul_status", {
            "status":  "loading",
            "message": "Loading memory & embedding models… "
                       "Responses work now, but memory context will activate shortly.",
        })

        t0 = time.monotonic()
        try:
            await loop.run_in_executor(None, _st.get_memory)
            elapsed = time.monotonic() - t0
            # Always confirm completion — the user saw "⏳ Loading…" and needs to know
            # it finished (or failed).  No elapsed-time gate: even a 0.1s cache hit
            # deserves a "✅ ready" so the loading message doesn't hang unresolved.
            await _emit("soul_status", {
                "status":  "ready",
                "message": f"Memory ready ✓  (loaded in {elapsed:.1f}s)",
            })
            log.info("Memory/embeddings pre-warm complete (%.1fs)", elapsed)
        except Exception as e:
            log.error("Memory pre-warm failed: %s", e, exc_info=True)
            await _emit("soul_status", {
                "status":  "error",
                "message": (
                    f"Memory unavailable: {e}. "
                    "Responses work without memory context. "
                    "Run `evocli doctor` to diagnose."
                ),
            })

    task4 = asyncio.create_task(_prewarm_memory())
    task4.add_done_callback(_log_task_exception)

    # Load MCP tools if any servers are registered
    try:
        from evocli_soul.handlers.mcp_bridge import initialize_mcp_tools
        task3 = asyncio.create_task(initialize_mcp_tools())
        task3.add_done_callback(_log_task_exception)
    except Exception as e:
        log.warning("MCP tools init failed: %s", e)

    await _serve(router)


if __name__ == "__main__":
    asyncio.run(main())
