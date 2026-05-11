"""Session handlers — 会话生命周期管理（Section 26）。"""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.handlers.session")


def register(router) -> None:
    router.add("session.list",   handle_session_list)
    router.add("session.create", handle_session_create)
    router.add("session.resume", handle_session_resume)
    router.add("session.pause",  handle_session_pause)


async def handle_session_list(req_id: str, params: dict, send, state) -> None:
    try:
        from evocli_soul.session import SessionManager
        sm = SessionManager(state.get_bridge())
        await send.response(req_id, sm.list_sessions(params.get("status")))
    except Exception as e:
        log.exception("session.list failed")
        await send.error(req_id, -32603, str(e))


async def handle_session_create(req_id: str, params: dict, send, state) -> None:
    try:
        from evocli_soul.session import SessionManager
        from dataclasses import asdict
        sm   = SessionManager(state.get_bridge())
        meta = sm.create(params.get("project", "."), params.get("goal", ""))
        await send.response(req_id, asdict(meta))
    except Exception as e:
        log.exception("session.create failed")
        await send.error(req_id, -32603, str(e))


async def handle_session_resume(req_id: str, params: dict, send, state) -> None:
    try:
        from evocli_soul.session import SessionManager
        sm  = SessionManager(state.get_bridge())
        sid = params.get("session_id")
        if not sid:
            latest = sm.latest_interrupted()
            sid    = latest.id if latest else None
        if not sid:
            await send.error(req_id, -32600, "No session to resume")
            return
        result = await sm.resume(sid)
        await send.response(req_id, result)
    except Exception as e:
        log.exception("session.resume failed")
        await send.error(req_id, -32603, str(e))


async def handle_session_pause(req_id: str, params: dict, send, state) -> None:
    try:
        from evocli_soul.session import SessionManager
        sm = SessionManager(state.get_bridge())
        sm.mark_paused(params.get("session_id", ""), params.get("snapshot", ""))

        # Session 结束时自动触发 Memory 蒸馏（异步，不阻塞响应）
        import asyncio
        async def _distill():
            try:
                from evocli_soul.memory_distill import MemoryDistiller
                distiller = MemoryDistiller(state.get_bridge())
                await distiller.run({
                    "session_id":     params.get("session_id", ""),
                    "events":         params.get("events", []),
                    "project_id":     params.get("project_id", "."),
                    "priority_scope": "project",
                })
            except Exception as e:
                log.warning("Distillation on pause failed: %s", e)
        asyncio.create_task(_distill())

        await send.response(req_id, {"ok": True})
    except Exception as e:
        log.exception("session.pause failed")
        await send.error(req_id, -32603, str(e))
