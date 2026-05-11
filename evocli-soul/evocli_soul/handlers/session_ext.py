"""
Session handlers — auto-commit, run+capture, session compaction.

研究来源:
- Aider (repo.py): auto_commit 每 turn 提交，weak model 生成消息
- Aider (commands.py /run): 执行命令，可选将输出加入上下文
- Aider (commands.py /test): 只有失败时才加入上下文 (节省 tokens)
- OpenCode: Anchored Summary compaction (Goal/Constraints/Progress)
- Claude Code: /rewind checkpoint 恢复

新 RPC 方法:
  session.auto_commit       — AI 修改后自动提交 (Aider 模式)
  session.run_and_capture   — /run: 执行命令，返回输出
  session.test_and_capture  — /test: 执行测试，只在失败时返回详情
  session.compact           — 触发 Anchored Summary 压缩当前会话
"""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.handlers.session_ext")


def register(router) -> None:
    router.add("session.auto_commit",      handle_auto_commit)
    router.add("session.run_and_capture",  handle_run_and_capture)
    router.add("session.test_and_capture", handle_test_and_capture)
    router.add("session.compact",          handle_session_compact)


async def handle_auto_commit(req_id: str, params: dict, send, state) -> None:
    """
    Auto-commit after AI edits with LLM-generated commit message.

    Research: Aider commits after every successful turn.
    Uses a fast/cheap "weak model" to generate Conventional Commit messages.
    Sets GIT_AUTHOR_NAME attribution to indicate AI involvement.

    params:
      goal:     str   What the AI was doing (used for commit message context)
      message:  str   Optional manual commit message override
    """
    goal    = params.get("goal", "")
    message = params.get("message", "")
    try:
        bridge = state.get_bridge()
        # Get current diff to generate message from
        if not message:
            try:
                diff_result = await bridge.call("git.diff", {})
                diff_text   = diff_result if isinstance(diff_result, str) else ""
                if diff_text.strip():
                    from evocli_soul.auto_commit import generate_commit_message
                    llm = state.get_llm_client()
                    message = await generate_commit_message(diff_text, llm, goal)
                else:
                    await send.response(req_id, {"ok": True, "committed": False,
                                                  "reason": "nothing to commit"})
                    return
            except Exception as e:
                log.debug("auto_commit: diff failed: %s", e)
                from evocli_soul.auto_commit import AI_COMMIT_PREFIX
                message = f"{AI_COMMIT_PREFIX}{goal[:60]}" if goal else f"{AI_COMMIT_PREFIX}applied AI edits"

        # Commit
        result = await bridge.call("git.commit", {"message": message, "files": []})
        await send.response(req_id, {"ok": True, "committed": True,
                                     "message": message, "result": result})
    except Exception as e:
        log.exception("session.auto_commit failed")
        await send.error(req_id, -32603, str(e))


async def handle_run_and_capture(req_id: str, params: dict, send, state) -> None:
    """
    Run a shell command and return output for the AI to analyze.
    Equivalent to Aider's /run command.

    Research: Aider's `/run` asks "Add N tokens of output to chat?" 
    EvoCLI returns the output directly for the agent to decide.

    params:
      cmd:           str   Command to run
      cwd:           str   Working directory
      add_to_context: bool  If True, include full output (default: True)
      max_lines:     int   Cap output at N lines (default: 100)
    """
    cmd        = params.get("cmd", "")
    cwd        = params.get("cwd", ".")
    max_lines  = params.get("max_lines", 100)
    if not cmd:
        await send.error(req_id, -32600, "cmd is required")
        return
    try:
        bridge = state.get_bridge()
        result = await bridge.call("shell.run", {
            "cmd": cmd, "cwd": cwd, "timeout_s": 60, "dry_run": False,
        })
        output    = ""
        exit_code = 0
        if isinstance(result, dict):
            stdout    = result.get("stdout", "")
            stderr    = result.get("stderr", "")
            exit_code = result.get("exit_code", 0)
            output    = (stdout + ("\n" + stderr if stderr else "")).strip()
        else:
            output = str(result)

        # Cap output (Aider shows token count and asks permission for large outputs)
        lines = output.splitlines()
        if len(lines) > max_lines:
            output = "\n".join(lines[:max_lines]) + f"\n...[{len(lines)-max_lines} lines truncated]"

        await send.response(req_id, {
            "ok":       True,
            "output":   output,
            "exit_code": exit_code,
            "cmd":      cmd,
        })
    except Exception as e:
        log.exception("session.run_and_capture failed")
        await send.error(req_id, -32603, str(e))


async def handle_test_and_capture(req_id: str, params: dict, send, state) -> None:
    """
    Run a test command and return output ONLY if tests fail.
    Equivalent to Aider's /test command.

    Research: Aider's `/test` only adds output to context if exit code != 0.
    This saves tokens when tests pass — the agent only needs to see failures.

    params:
      cmd:  str   Test command (e.g., "cargo test", "pytest", "npm test")
      cwd:  str   Working directory
    """
    cmd = params.get("cmd", "")
    cwd = params.get("cwd", ".")
    if not cmd:
        await send.error(req_id, -32600, "cmd is required")
        return
    try:
        bridge = state.get_bridge()
        result = await bridge.call("shell.run", {
            "cmd": cmd, "cwd": cwd, "timeout_s": 120, "dry_run": False,
        })
        stdout    = result.get("stdout", "") if isinstance(result, dict) else str(result)
        stderr    = result.get("stderr", "") if isinstance(result, dict) else ""
        exit_code = result.get("exit_code", 0) if isinstance(result, dict) else 0
        passed    = (exit_code == 0)

        if passed:
            await send.response(req_id, {
                "ok": True, "passed": True,
                "output": "✓ All tests passed.",
                "cmd": cmd,
            })
        else:
            output = (stdout + "\n" + stderr).strip()
            lines  = output.splitlines()
            if len(lines) > 80:
                output = "\n".join(lines[:80]) + f"\n...[{len(lines)-80} lines truncated]"
            await send.response(req_id, {
                "ok":       False,
                "passed":   False,
                "output":   output,
                "exit_code": exit_code,
                "cmd":      cmd,
                # Ready-to-use reflection prompt (Aider pattern)
                "reflection_prompt": (
                    f"Tests failed with exit code {exit_code}:\n\n```\n{output[:800]}\n```\n\n"
                    "Please analyze the failures and fix the code."
                ),
            })
    except Exception as e:
        log.exception("session.test_and_capture failed")
        await send.error(req_id, -32603, str(e))


async def handle_session_compact(req_id: str, params: dict, send, state) -> None:
    """
    Compact the current session using Anchored Summary (OpenCode pattern).
    Returns a structured Markdown summary with Goal/Progress/Constraints.

    params:
      history:          list  Conversation history to compact
      existing_summary: str   Previous anchor to update (for recursive compaction)
      goal:             str   Current session goal
    """
    history          = params.get("history", [])
    existing_summary = params.get("existing_summary", "")
    if not history:
        await send.error(req_id, -32600, "history is required")
        return
    try:
        from evocli_soul.context_engine import compact_session_to_anchor
        llm     = state.get_llm_client()
        summary = await compact_session_to_anchor(history, llm, existing_summary)
        await send.response(req_id, {
            "ok":      True,
            "summary": summary,
            "chars":   len(summary),
        })
    except Exception as e:
        log.exception("session.compact failed")
        await send.error(req_id, -32603, str(e))
