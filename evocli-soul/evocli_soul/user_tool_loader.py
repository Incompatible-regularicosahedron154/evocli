"""
user_tool_loader.py — Dynamic user-defined tool loading from ~/.evocli/tools/*.py

Allows users to add custom tools without modifying EvoCLI source code.
Each file in ~/.evocli/tools/ can define one or more tools using the
standard @agent.tool_plain decorator pattern.

Usage: create ~/.evocli/tools/my_tools.py:

    def register(agent, _sc, _call_handler, _sid, _json, bridge=None, config=None, memory=None):
        \"\"\"Register custom tools. Called automatically on startup.\"\"\"

        @agent.tool_plain
        async def my_custom_tool(query: str) -> str:
            \"\"\"My custom tool description shown to the AI.\"\"\"
            result = await bridge.call("shell.run", {"cmd": f"my-command {query}", "cwd": "."})
            return str(result)

        @agent.tool_plain
        async def another_tool(path: str) -> str:
            \"\"\"Another custom tool.\"\"\"
            return await _sc("fs.read", {"path": path})

Then restart evocli — your tools are automatically discovered and registered.

The register() function signature MUST match:
    def register(agent, _sc, _call_handler, _sid, _json, bridge=None, config=None, memory=None)
"""
from __future__ import annotations
import importlib.util
import logging
from pathlib import Path

log = logging.getLogger("evocli.user_tool_loader")

_TOOLS_DIRS = [
    Path.home() / ".evocli" / "tools",  # global user tools
    # project-local tools added at session init via load_project_tools()
]


def discover_tool_files(project_dir: str | None = None) -> list[Path]:
    """Return all *.py tool files from ~/.evocli/tools/ and optionally {project}/.evocli/tools/."""
    files: list[Path] = []
    dirs = list(_TOOLS_DIRS)
    if project_dir:
        dirs.insert(0, Path(project_dir) / ".evocli" / "tools")  # project tools take priority

    for d in dirs:
        if d.is_dir():
            py_files = sorted(d.glob("*.py"))
            files.extend(f for f in py_files if not f.name.startswith("_"))

    return files


def load_user_tools(
    agent,
    bridge,
    sid: str,
    sc_fn,
    call_handler_fn,
    config=None,
    memory=None,
    project_dir: str | None = None,
) -> int:
    """
    Discover and register all user-defined tools.

    Returns the number of tool files successfully loaded.
    Errors in individual files are logged as warnings and skipped.

    Called from EvoCLIAgent._register_pydantic_tools() after built-in tools.
    """
    import json as _json

    _sc           = sc_fn
    _call_handler = call_handler_fn
    _sid          = sid

    files = discover_tool_files(project_dir)
    if not files:
        return 0

    loaded = 0
    for tool_file in files:
        try:
            spec = importlib.util.spec_from_file_location(
                f"evocli_user_tools_{tool_file.stem}", str(tool_file)
            )
            if spec is None or spec.loader is None:
                log.warning("user_tool_loader: cannot load spec for %s — skipped", tool_file)
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            if not hasattr(module, "register"):
                log.warning(
                    "user_tool_loader: %s has no register() function — skipped. "
                    "Add: def register(agent, _sc, _call_handler, _sid, _json, bridge=None, ...): ...",
                    tool_file.name,
                )
                continue

            module.register(
                agent,
                _sc,
                _call_handler,
                _sid,
                _json,
                bridge=bridge,
                config=config,
                memory=memory,
            )
            log.info("user_tool_loader: loaded %s", tool_file.name)
            loaded += 1

        except Exception as e:
            log.warning(
                "user_tool_loader: failed to load %s: %s (tool file skipped)",
                tool_file.name, e,
            )

    if loaded:
        log.info("user_tool_loader: %d custom tool file(s) loaded", loaded)
    return loaded
