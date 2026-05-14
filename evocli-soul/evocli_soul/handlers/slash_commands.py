"""
handlers/slash_commands.py — Slash command handlers for handle_agent_stream

Extracted from handlers/agent.py to keep the stream handler focused on
the autonomous execution loop and session management.

Single responsibility: handle /help, /add, /compress, /flows, /undo, /plan, /btw.

Each handler returns True if the command was handled (caller should return),
or False / raises if the input was not a slash command.
"""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.handlers.slash")


async def dispatch_slash(
    prompt: str,
    req_id: str,
    params: dict,
    send,
    state,
    derive_session_id,
    emit_event,
) -> bool:
    """
    Dispatch slash commands from handle_agent_stream.

    Returns True if a slash command was matched and handled.
    Returns False if this is a normal prompt (no slash command).

    Args:
        prompt:           The user's raw prompt text
        req_id:           JSON-RPC request ID for stream responses
        params:           Full RPC params dict
        send:             RPC send helper (stream_chunk, response, error)
        state:            evocli_soul.state module reference
        derive_session_id: Callable to get session_id from params
        emit_event:       Callable for soul event emission
    """
    stripped = prompt.strip()
    stripped_lower = stripped.lower()

    # ── /help ─────────────────────────────────────────────────────────────────
    if stripped_lower in ("/help", "/?", "/h"):
        await _handle_help(req_id, send)
        return True

    # ── /add ──────────────────────────────────────────────────────────────────
    if stripped_lower.startswith("/add"):
        await _handle_add(stripped, req_id, params, send, state, derive_session_id)
        return True

    # ── /compress / /compact ──────────────────────────────────────────────────
    if stripped_lower in ("/compress", "/compact"):
        await _handle_compress(req_id, params, send, state, derive_session_id, emit_event)
        return True

    # ── /flows / /flow ────────────────────────────────────────────────────────
    if stripped_lower in ("/flows", "/flow"):
        await _handle_flows(req_id, send)
        return True

    # ── /undo ─────────────────────────────────────────────────────────────────
    if stripped_lower == "/undo":
        await _handle_undo(req_id, params, send, state, derive_session_id)
        return True

    # ── /plan ─────────────────────────────────────────────────────────────────
    if stripped_lower.startswith("/plan"):
        await _handle_plan(stripped, req_id, params, send, state, derive_session_id)
        return True

    # ── /btw ──────────────────────────────────────────────────────────────────
    if stripped_lower.startswith("/btw "):
        await _handle_btw(stripped, req_id, params, send, state, derive_session_id)
        return True

    return False


# ── Individual slash command implementations ──────────────────────────────────

async def _handle_help(req_id: str, send) -> None:
    help_text = """\
**EvoCLI 可用命令**

| 命令 | 说明 |
|---|---|
| `/help` 或 `/?` | 显示此帮助 |
| `/compress` 或 `/compact` | 压缩会话历史，释放上下文空间 |
| `/undo` | 撤销上一轮操作（移除最后一轮历史 + 尝试 git 快照恢复）|
| `/plan <任务>` | 计划模式：只读分析代码库，生成结构化实现计划（不修改文件）|
| `/btw <问题>` | 旁白问题：不写入历史，不污染上下文（适合临时性查询）|
| `/add <文件>` | 将文件固定到每轮上下文中 |
| `/add list` | 查看已固定的文件 |
| `/add clear` | 清除所有固定文件 |

**使用技巧**
- 只读分析操作（搜索、读文件、查符号）会立即执行，无需确认
- 有风险的修改（3+ 文件、API 变更）会先描述计划，等待你确认
- 上下文过长时输入 `/compress` 压缩，可显著提升响应质量
- 使用 `evocli doctor` 诊断配置和连接问题
- 使用 `evocli skill list` 查看可用的自动化技能

**当前状态**
输入任意问题开始对话，或直接描述你想做的代码任务。
"""
    await send.stream_chunk(req_id, help_text.strip(), done=True)


async def _handle_add(
    stripped: str,
    req_id: str,
    params: dict,
    send,
    state,
    derive_session_id,
) -> None:
    import os as _os_add
    import evocli_soul.state as _st_add
    _add_sid = derive_session_id(params)
    _add_args = stripped.split()[1:]

    if not _add_args or _add_args[0].lower() == "list":
        files = _st_add.get_added_files(_add_sid)
        if files:
            file_list = "\n".join(f"  • {f}" for f in files)
            await send.stream_chunk(req_id,
                f"**Files in context ({len(files)}):**\n{file_list}\n\n"
                f"Use `/add clear` to remove all, or `/add <file>` to add more.",
                done=True)
        else:
            await send.stream_chunk(req_id,
                "No files explicitly added to context.\n"
                "Use `/add <path>` to pin files across all turns.",
                done=True)
        return

    if _add_args[0].lower() == "clear":
        _st_add.clear_added_files(_add_sid)
        await send.stream_chunk(req_id, "✓ Cleared all added files from context.", done=True)
        return

    if _add_args[0].lower() == "remove" and len(_add_args) > 1:
        removed = _st_add.remove_added_files(_add_sid, _add_args[1:])
        await send.stream_chunk(req_id, f"✓ Removed {len(removed)} file(s) from context.", done=True)
        return

    added, missing = [], []
    for f in _add_args:
        if _os_add.path.exists(f):
            _st_add.add_file(f, _add_sid)
            added.append(f)
        else:
            missing.append(f)

    all_files = _st_add.get_added_files(_add_sid)
    msg = ""
    if added:
        msg += f"✓ Added to context: {', '.join(added)}\n"
    if missing:
        msg += f"⚠ Not found: {', '.join(missing)}\n"
    msg += f"\n**Context files ({len(all_files)}):** {', '.join(all_files)}\n"
    msg += "These files will be injected into every turn automatically."
    await send.stream_chunk(req_id, msg, done=True)


async def _handle_compress(
    req_id: str,
    params: dict,
    send,
    state,
    derive_session_id,
    emit_event,
) -> None:
    import evocli_soul.state as _st_compress
    session_id = derive_session_id(params)
    try:
        await send.stream_chunk(req_id, "⏳ Compressing session context…\n\n", done=False)
        events = list(_st_compress._session_events)
        llm = state.get_llm_client()

        history_for_summary = _st_compress.get_history(session_id)
        history_summary = ""
        if history_for_summary:
            history_lines = []
            for m in history_for_summary[-20:]:
                role    = m.get("role", "?")
                content = str(m.get("content", ""))[:300]
                history_lines.append(f"[{role}]: {content}")
            history_summary = "\n".join(history_lines)

        event_summary = ""
        if events:
            tool_names = [e.get("method", e.get("type", "?")) for e in events[-20:]]
            event_summary = f"Recent tool calls: {', '.join(tool_names)}"

        compress_prompt = (
            f"Summarize the following AI coding session as an Anchored Summary.\n"
            f"Format:\n"
            f"## Goal\n[what the user is trying to accomplish]\n"
            f"## Progress\n[what has been done, what's in progress]\n"
            f"## Key Decisions\n[important choices made]\n"
            f"## Next Steps\n[what should happen next]\n\n"
            f"Conversation history (most recent 20 turns):\n{history_summary}\n\n"
            f"{event_summary}\n\n"
            f"Be concise. Focus on engineering decisions and state."
        )
        summary = await llm.complete(compress_prompt, tier="fast", max_tokens=600)

        _st_compress.set_anchored_summary(summary, session_id)
        await send.stream_chunk(req_id,
            f"**Session compressed.**\n\n{summary}\n\n"
            f"*Context anchored. Continue working — history preserved.*",
            done=True)
        await emit_event("session_compacted", {
            "summary":              summary,
            "chars":                len(summary),
            "original_event_count": len(events),
        })
        _st_compress.clear_history(session_id)
    except Exception as e:
        log.warning("/compress failed: %s", e)
        await send.stream_chunk(req_id, f"Compression failed: {e}", done=True)


async def _handle_flows(req_id: str, send) -> None:
    try:
        from evocli_soul.tool_flow_miner import list_flows
        flows = list_flows()
        if not flows:
            await send.stream_chunk(req_id,
                "📭 还没有学到工具流。\n\n"
                "工具流会在你重复使用相同工具序列（≥2次）后自动学习。\n"
                "继续使用 EvoCLI，系统会自动发现你的工作模式。",
                done=True)
            return
        lines = ["## 已学习的工具流\n"]
        for f in flows:
            steps_str = " → ".join(f["step_tools"][:5])
            if len(f["step_tools"]) > 5:
                steps_str += f" (+{len(f['step_tools'])-5})"
            lines.append(
                f"**{f['name']}**\n"
                f"  步骤: {steps_str}\n"
                f"  置信度: {f['confidence']:.0%}  成功率: {f['success_rate']:.0%}\n"
            )
        lines.append("\n💡 触发：在对话中描述相关任务，系统会自动建议或执行匹配的工具流。")
        await send.stream_chunk(req_id, "\n".join(lines), done=True)
    except Exception as e:
        await send.stream_chunk(req_id, f"获取工具流失败: {e}", done=True)


async def _handle_undo(
    req_id: str,
    params: dict,
    send,
    state,
    derive_session_id,
) -> None:
    import evocli_soul.state as _st_undo
    _undo_sid = derive_session_id(params)
    try:
        history = _st_undo.get_history(_undo_sid)
        popped = False
        if len(history) >= 2:
            last_user = history[-2] if history[-2].get("role") == "user" else None
            last_asst = history[-1] if history[-1].get("role") == "assistant" else None
            if last_user and last_asst:
                _st_undo.set_history(history[:-2], _undo_sid)
                popped = True
        elif len(history) == 1:
            _st_undo.set_history([], _undo_sid)
            popped = True

        git_msg = ""
        try:
            bridge = state.get_bridge()
            snap_result = await bridge.call("git.snapshot_list", {})
            snapshots = snap_result if isinstance(snap_result, list) else []
            if snapshots:
                latest = snapshots[0]
                snap_id = latest.get("hash") or latest.get("id") or latest.get("ref", "")
                if snap_id:
                    await bridge.call("git.snapshot_restore", {"ref": snap_id})
                    git_msg = f"\n✓ Git snapshot restored: `{snap_id}`"
                else:
                    git_msg = "\n⚠ Snapshot found but no ref to restore."
            else:
                git_msg = "\n⚠ No git snapshots found. Run `evocli git snapshot` to create one."
        except Exception as ge:
            git_msg = f"\n⚠ Git restore skipped: {ge}"

        if popped:
            msg = f"↩ **Undone**: Last conversation turn removed from history.{git_msg}\n\nYou can now rephrase and retry."
        else:
            msg = f"↩ Nothing to undo — history is empty.{git_msg}"
        await send.stream_chunk(req_id, msg, done=True)
    except Exception as e:
        await send.stream_chunk(req_id, f"Undo failed: {e}", done=True)


async def _handle_plan(
    stripped: str,
    req_id: str,
    params: dict,
    send,
    state,
    derive_session_id,
) -> None:
    _plan_args = stripped[5:].strip()
    if not _plan_args:
        await send.stream_chunk(req_id,
            "**Usage**: `/plan <task description>`\n\n"
            "Example: `/plan add rate limiting to the API endpoints`\n\n"
            "Plan Mode analyzes the codebase in read-only mode and produces a structured implementation plan.",
            done=True)
        return
    try:
        from evocli_soul.agent import EvoCLIAgent
        _plan_sid = derive_session_id(params)
        cfg = state.get_config()
        memory_obj = state.get_memory() if hasattr(state, "get_memory") else None
        plan_agent = EvoCLIAgent(state.get_bridge(), memory_obj, cfg,
                                 read_only=True, session_id=_plan_sid)
        plan_prompt = (
            f"You are in PLAN MODE — analysis only, no file writes.\n\n"
            f"Task: {_plan_args}\n\n"
            f"Produce a structured implementation plan in this format:\n\n"
            f"## Goal\n[what we're trying to achieve]\n\n"
            f"## Current State\n[relevant code/dependencies you found]\n\n"
            f"## Approach\n[step-by-step implementation strategy]\n\n"
            f"## Files to Modify\n[explicit list of files and what changes]\n\n"
            f"## Risks & Questions\n[potential blockers, unclear requirements]\n\n"
            f"Analyze the codebase thoroughly before proposing the plan. "
            f"DO NOT make any file edits — plan only."
        )
        await send.stream_chunk(req_id, "📋 **Plan Mode** — analyzing codebase (read-only)…\n\n", done=False)
        plan_chunks: list[str] = []
        async for chunk in plan_agent.stream(plan_prompt, session_id=_plan_sid):
            if chunk:
                await send.stream_chunk(req_id, chunk, done=False)
                plan_chunks.append(chunk)
        await send.stream_chunk(req_id, "", done=True)
        if plan_chunks:
            import evocli_soul.state as _st_plan
            _st_plan.append_history([
                {"role": "user",      "content": f"/plan {_plan_args}"},
                {"role": "assistant", "content": "".join(plan_chunks)},
            ], _plan_sid)
    except Exception as e:
        await send.stream_chunk(req_id, f"Plan mode failed: {e}", done=True)


async def _handle_btw(
    stripped: str,
    req_id: str,
    params: dict,
    send,
    state,
    derive_session_id,
) -> None:
    _btw_question = stripped[5:].strip()
    if not _btw_question:
        await send.stream_chunk(req_id,
            "**Usage**: `/btw <question>`\n\nAsks a side question without adding it to conversation history.",
            done=True)
        return
    try:
        from evocli_soul.agent import EvoCLIAgent
        _btw_sid = derive_session_id(params)
        cfg = state.get_config()
        memory_obj = state.get_memory() if hasattr(state, "get_memory") else None
        btw_agent = EvoCLIAgent(state.get_bridge(), memory_obj, cfg, session_id=_btw_sid)
        await send.stream_chunk(req_id, "*[aside — not saved to history]*\n\n", done=False)
        async for chunk in btw_agent.stream(_btw_question, session_id=_btw_sid):
            if chunk:
                await send.stream_chunk(req_id, chunk, done=False)
        await send.stream_chunk(req_id, "", done=True)
    except Exception as e:
        await send.stream_chunk(req_id, f"/btw failed: {e}", done=True)
