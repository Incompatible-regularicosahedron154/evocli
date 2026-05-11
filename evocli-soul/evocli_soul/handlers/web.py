"""
Web handlers — URL 内容抓取 (Aider /web + Continue.dev @url 模式)

研究来源:
- Aider (/web): playwright + BeautifulSoup slimdown + pandoc
- Continue.dev (@url): readability-lxml + html2text (Python 等价实现)

新 RPC 方法:
  web.fetch  — 获取 URL 内容并转为 Markdown，注入 LLM 上下文
"""
from __future__ import annotations
import logging

log = logging.getLogger("evocli.handlers.web")


def register(router) -> None:
    router.add("web.fetch", handle_web_fetch)


async def handle_web_fetch(req_id: str, params: dict, send, state) -> None:
    """
    Fetch a URL and return clean Markdown content for the AI's context.
    Equivalent to Aider's /web command and Continue.dev's @url provider.

    Research: Aider uses playwright + pypandoc for full JS rendering.
    EvoCLI uses httpx + readability-lxml + html2text (lighter, no browser).

    params:
      url:       str  URL to fetch
      max_chars: int  Max characters to return (default 16000 ≈ 4k tokens)
    """
    url       = params.get("url", "")
    max_chars = int(params.get("max_chars", 16_000))
    if not url:
        await send.error(req_id, -32600, "url is required")
        return
    try:
        from evocli_soul.web_fetcher import fetch_url
        result = await fetch_url(url, max_chars=max_chars)
        await send.response(req_id, result)
    except Exception as e:
        log.exception("web.fetch failed")
        await send.error(req_id, -32603, str(e))
