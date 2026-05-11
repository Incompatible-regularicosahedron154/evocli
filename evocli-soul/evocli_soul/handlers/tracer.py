"""Tracer handlers — 健康检查、依赖验证、LLM 流式测试。"""
from __future__ import annotations
import importlib.util
import logging
import os

log = logging.getLogger("evocli.handlers.tracer")


def register(router) -> None:
    router.add("tracer.ping",       handle_ping)
    router.add("tracer.check_deps", handle_check_deps)
    router.add("tracer.llm_stream", handle_llm_stream)


async def handle_ping(req_id: str, params: dict, send, _state) -> None:
    await send.response(req_id, "pong")


async def handle_check_deps(req_id: str, params: dict, send, _state) -> None:
    packages, errors = [], []
    # Required: 必须安装才能运行核心功能
    required = [
        ("litellm",     "litellm"),
        ("pydantic_ai", "pydantic_ai"),
        ("langgraph",   "langgraph"),
        ("instructor",  "instructor"),
    ]
    # Optional [full]: evocli-soul[full] 安装后可用
    optional = [
        ("lancedb",               "lancedb"),          # 向量记忆
        ("fastembed",             "fastembed"),         # 本地嵌入
        ("jedi",                  "jedi"),              # Python 代码智能
        ("grep_ast",              "grep_ast"),          # 上下文代码搜索
        ("smolagents",            "smolagents"),        # Skill 执行
        ("prefixspan",            "prefixspan"),        # Evolution 模式检测
        ("sentence_transformers", "sentence_transformers"),  # 语义相似度
    ]
    # M2 FIX: mem0 已移除，不再检查
    for display, module in required:
        if importlib.util.find_spec(module):
            packages.append(f"{display} [OK]")
        else:
            errors.append(f"{display}: not installed — run: pip install 'evocli-soul'")
    for display, module in optional:
        tag = "[OK]" if importlib.util.find_spec(module) else "[not installed — install evocli-soul[full]]"
        packages.append(f"{display} {tag}")

    if errors:
        await send.response(req_id, {"ok": False, "error": "; ".join(errors), "packages": packages})
    else:
        await send.response(req_id, {"ok": True, "packages": packages})


async def handle_llm_stream(req_id: str, params: dict, send, _state) -> None:
    prompt  = params.get("prompt", "")
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        mock = "Rust 是一门注重内存安全、并发性和高性能的系统编程语言。"
        import asyncio
        for char in mock:
            await send.stream_chunk(req_id, char, done=False)
            await asyncio.sleep(0.015)
        await send.stream_chunk(req_id, "", done=True)
        return

    try:
        import litellm
        model = os.environ.get("EVOCLI_MODEL", "gpt-4o-mini")
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=True, max_tokens=80,
        )
        async for chunk in response:
            text = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if text:
                await send.stream_chunk(req_id, text, done=False)
        await send.stream_chunk(req_id, "", done=True)
    except Exception as e:
        log.exception("LLM stream failed: %s", e)
        await send.stream_chunk(req_id, f"ERROR: {e}", done=True)
