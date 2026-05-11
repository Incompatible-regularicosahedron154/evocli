"""Diff handlers — Python-side diff application using whatthepatch."""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.handlers.diff")


def register(router) -> None:
    router.add("diff.apply",       handle_diff_apply)
    router.add("diff.parse_stats", handle_diff_parse_stats)


async def handle_diff_apply(req_id: str, params: dict, send, state) -> None:
    """
    Python-side diff application via whatthepatch (fallback for Rust fs.apply_diff).
    Research source: pylsp + Aider use whatthepatch for reliable unified-diff application.

    params:
      path:  str   File path to patch
      diff:  str   Unified diff text
    """
    path = params.get("path", "")
    diff_text = params.get("diff", "")
    if not path or not diff_text:
        await send.error(req_id, -32600, "path and diff are required")
        return
    try:
        bridge = state.get_bridge()
        # Architecture fix: use bridge for file IO (consistent with handlers/edit.py pattern)
        content = await bridge.call("fs.read", {"path": path})
        if not isinstance(content, str):
            await send.response(req_id, {"ok": False, "error": f"Could not read: {path}"})
            return
        from evocli_soul.diff_utils import apply_unified_diff
        patched = apply_unified_diff(content, diff_text)
        if patched is None:
            await send.response(req_id, {"ok": False, "path": path, "engine": "failed"})
            return
        await bridge.call("fs.write", {"path": path, "content": patched})
        await send.response(req_id, {"ok": True, "path": path, "engine": "whatthepatch"})
    except Exception as e:
        log.exception("diff.apply failed")
        await send.error(req_id, -32603, str(e))


async def handle_diff_parse_stats(req_id: str, params: dict, send, state) -> None:
    """
    Parse a unified diff and return statistics (files changed, lines added/removed).
    Useful for validating LLM-generated patches before applying.

    params:
      diff: str   Unified diff text
    """
    diff_text = params.get("diff", "")
    if not diff_text:
        await send.error(req_id, -32600, "diff is required")
        return
    try:
        from evocli_soul.diff_utils import parse_diff_stats
        stats = parse_diff_stats(diff_text)
        await send.response(req_id, stats)
    except Exception as e:
        log.exception("diff.parse_stats failed")
        await send.error(req_id, -32603, str(e))
