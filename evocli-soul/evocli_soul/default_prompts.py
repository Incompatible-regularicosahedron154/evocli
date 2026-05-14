"""
default_prompts.py — EvoCLI prompt loader

Prompts are loaded from (in priority order):
  1. ~/.evocli/prompts/{name}.md  (user override)
  2. evocli_soul/prompts/{name}.md  (bundled default)

To customize: copy any .md file from evocli_soul/prompts/ to ~/.evocli/prompts/
and edit it. Your changes survive EvoCLI updates.
"""
from __future__ import annotations

import logging
import pathlib
from typing import Any

log = logging.getLogger("evocli.prompts")

_PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"
_USER_PROMPTS_DIR = pathlib.Path.home() / ".evocli" / "prompts"


def load_prompt(name: str) -> str:
    """Load prompt by name. User ~/.evocli/prompts/{name}.md overrides bundled default."""
    for base in (_USER_PROMPTS_DIR, _PROMPTS_DIR):
        p = base / f"{name}.md"
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception as e:
                log.warning("Failed to load prompt %s from %s: %s", name, p, e)
    log.warning("Prompt %s not found in %s or %s", name, _PROMPTS_DIR, _USER_PROMPTS_DIR)
    return ""


def _get(name: str) -> str:
    return load_prompt(name)


SYSTEM_CORE = _get("system_core")
SYSTEM_CORE_MANDATES = _get("system_mandates")
SYSTEM_WORKFLOW = _get("system_workflow")
SYSTEM_TOOL_RULES = _get("system_tool_rules")
SYSTEM_DIFF_FORMAT = _get("system_diff_format")
SYSTEM_GIT_HYGIENE = _get("system_git")
SYSTEM_MEMORY_RULES = _get("system_memory")
SYSTEM_UNCERTAINTY = _get("system_uncertainty")

SYSTEM_CLAUDE_SPECIFIC = _get("model_claude")
SYSTEM_GPT_SPECIFIC = _get("model_gpt")
SYSTEM_GEMINI_SPECIFIC = _get("model_gemini")
SYSTEM_DEEPSEEK_SPECIFIC = _get("model_deepseek")

READ_ONLY_EXTENSION = _get("read_only_extension")
COMPACT_SYSTEM_PROMPT = _get("compact_system")
PROJECT_CONSTRAINTS_TEMPLATE = _get("project_constraints_template")

DEFAULT_SYSTEM_PROMPT = "\n".join(
    part
    for part in [
        SYSTEM_CORE,
        SYSTEM_CORE_MANDATES,
        SYSTEM_WORKFLOW,
        SYSTEM_TOOL_RULES,
        SYSTEM_DIFF_FORMAT,
        SYSTEM_GIT_HYGIENE,
        SYSTEM_MEMORY_RULES,
        SYSTEM_UNCERTAINTY,
    ]
    if part
)


def load_project_constraints(project_dir: str = ".") -> str:
    """
    从项目目录加载约束文件，按优先级合并：
      1. <project_dir>/AGENTS.md      （最高优先级）
      2. <project_dir>/.evocli/rules/*.md
      3. <project_dir>/.cursorrules   （兼容 Cursor）
      4. ~/.evocli/global_rules.md    （全局默认规则）
    """
    from pathlib import Path

    constraints_parts: list[str] = []

    search_paths = [
        (Path(project_dir) / "AGENTS.md", "AGENTS.md"),
        (Path(project_dir) / "CLAUDE.md", "CLAUDE.md"),
        (Path(project_dir) / ".evocli" / "rules", ".evocli/rules/"),
        (Path(project_dir) / ".cursorrules", ".cursorrules"),
        (Path.home() / ".evocli" / "global_rules.md", "~/.evocli/global_rules.md"),
    ]

    for path, label in search_paths:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    constraints_parts.append(f"### [{label}]\n{content}")
                    log.debug("Loaded constraints from %s", path)
            except Exception as e:
                log.warning("Failed to read %s: %s", path, e)
        elif path.is_dir():
            try:
                for md_file in sorted(path.glob("*.md")):
                    content = md_file.read_text(encoding="utf-8").strip()
                    if content:
                        constraints_parts.append(f"### [{label}{md_file.name}]\n{content}")
            except Exception as e:
                log.warning("Failed to read rules dir %s: %s", path, e)

    if not constraints_parts:
        return ""

    combined = "\n\n".join(constraints_parts)
    return PROJECT_CONSTRAINTS_TEMPLATE.format(
        source="AGENTS.md / .evocli/rules/",
        constraints=combined,
    )


def build_env_block(model_id: str = "", provider_id: str = "") -> str:
    """
    Build OpenCode-style environment context block.
    Injected as a separate section so static provider prompt can be prefix-cached.

    Tells the AI: which model it is, where it's running, what OS, today's date.
    This dramatically improves path/command/version accuracy.
    """
    import os
    import platform
    from datetime import datetime

    try:
        from evocli_soul.state import get_session_root
        cwd = get_session_root()
    except Exception:
        cwd = os.getcwd()

    is_git = os.path.exists(os.path.join(cwd, ".git"))
    plat = platform.system().lower()
    today = datetime.now().strftime("%a %b %d %Y")

    lines: list[str] = []
    if model_id:
        pid = f"{provider_id}/{model_id}" if provider_id else model_id
        lines.append(f"You are powered by the model named {model_id}. The exact model ID is {pid}")
    lines += [
        "Here is some useful information about the environment you are running in:",
        "<env>",
        f"  Working directory: {cwd}",
        f"  Is directory a git repo: {'yes' if is_git else 'no'}",
        f"  Platform: {plat}",
        f"  Today's date: {today}",
        "</env>",
    ]
    return "\n".join(lines)


def get_model_addendum(model_id: str) -> str:
    """
    Return model-specific prompt additions (OpenCode per-model specialization).
    Different LLMs need different behavioral nudges for optimal tool use.
    """
    m = model_id.lower()
    if "claude" in m:
        return SYSTEM_CLAUDE_SPECIFIC
    if any(x in m for x in ("gpt-4", "gpt4", "o1", "o3", "o4")):
        return SYSTEM_GPT_SPECIFIC
    if "gemini" in m:
        return SYSTEM_GEMINI_SPECIFIC
    if "deepseek" in m:
        return SYSTEM_DEEPSEEK_SPECIFIC
    if "gpt" in m:
        return SYSTEM_GPT_SPECIFIC
    return ""


def build_system_prompt(
    constraints: str = "",
    goal: str = "",
    project_dir: str = ".",
    read_only: bool = False,
    compact: bool = False,
    model_id: str = "",
    provider_id: str = "",
    inject_skills: bool = True,
) -> str:
    """
    Assemble the full system prompt.

    Layering order (mirrors OpenCode hierarchy):
      1. Core identity + workflow
      2. Tool rules + diff format + git hygiene
      3. EvoCLI-specific capabilities (memory, RepoMap, Evolution)
      4. Per-model behavioral addendum
      5. Environment block (model ID, CWD, platform, date)
      6. Project constraints (AGENTS.md / L1 memory)
      7. Available skills list
      8. Current goal
      9. MCP tools (if any)
      10. Read-only extension (if applicable)

    Args:
        constraints:    L1 memory project constraints
        goal:           Current task description
        project_dir:    Project directory for AGENTS.md loading
        read_only:      Activate read-only analysis mode
        compact:        Use token-efficient compact version
        model_id:       LLM model ID for per-model specialization
        provider_id:    LLM provider ID for environment block
        inject_skills:  Inject available skills list into prompt
    """
    base = COMPACT_SYSTEM_PROMPT if compact and COMPACT_SYSTEM_PROMPT else DEFAULT_SYSTEM_PROMPT
    parts = [base] if base else []

    if model_id:
        addendum = get_model_addendum(model_id)
        if addendum:
            parts.append(addendum)

    env_block = build_env_block(model_id=model_id, provider_id=provider_id)
    if env_block:
        parts.append(env_block)

    file_constraints = load_project_constraints(project_dir)
    all_constraints = []
    if constraints:
        all_constraints.append(constraints)
    if file_constraints:
        all_constraints.append(file_constraints)

    if all_constraints:
        parts.append("\n## 项目约束（必须遵守）\n" + "\n".join(all_constraints))

    if inject_skills:
        try:
            import evocli_soul.state as _st
            if _st._skill_engine is not None:
                engine = _st.get_skill_engine()
                list_skills = getattr(engine, "list_skills", None)
                skills_result = list_skills() if callable(list_skills) else []
                skills_list: list[Any] = skills_result if isinstance(skills_result, list) else []
                if skills_list:
                    skill_lines = ["\n## 可用技能 (Skills)"]
                    skill_lines.append(
                        "以下技能提供专业指令和工作流。当用户任务匹配时，主动建议或调用对应技能："
                    )
                    for s in skills_list[:15]:
                        name = getattr(s, "name", str(s))
                        desc = getattr(s, "description", "")[:80]
                        skill_lines.append(f"- **{name}**: {desc}")
                    parts.append("\n".join(skill_lines))
        except Exception:
            pass

    if goal:
        parts.append(f"\n## 当前任务\n{goal}")

    try:
        from evocli_soul.handlers.mcp_bridge import _mcp_tools, load_mcp_config
        servers = load_mcp_config()
        if servers and _mcp_tools:
            mcp_lines = ["\n## 外部 MCP 工具（通过 mcp_call 调用）"]
            mcp_lines.append("已注册 MCP server 的工具列表（使用 mcp_call(tool_name=..., arguments_json=...) 调用）：")
            for key, info in list(_mcp_tools.items())[:20]:
                mcp_lines.append(f"- {key}: {info['description'][:80]}")
            if len(_mcp_tools) > 20:
                mcp_lines.append(f"  ... 及 {len(_mcp_tools) - 20} 个更多工具（调用 mcp_list_tools() 查看完整列表）")
            parts.append("\n".join(mcp_lines))
        elif servers:
            parts.append(f"\n## MCP 工具\n已注册 {len(servers)} 个 MCP server，工具仍在加载中。调用 mcp_list_tools() 查看可用工具。")
    except Exception:
        pass

    if read_only and READ_ONLY_EXTENSION:
        parts.append(READ_ONLY_EXTENSION)

    return "\n".join(parts)
