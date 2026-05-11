"""
请求路由器 — 唯一职责：将 JSON-RPC method 分发到对应 handler。

handler 签名：
    async def handler(req_id, params, send, state) -> None
"""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

log = logging.getLogger("evocli.router")

# 流式方法集合 — 这些方法通过 call_stream() 调用，响应必须用 stream.chunk 格式
# 若用 send.error() 响应，Rust bridge 找不到 stream ID，TUI 会永远卡在 Streaming... 状态
_STREAMING_METHODS = frozenset({
    "agent.stream",
})


class SendProxy:
    """包装 rpc，让 handler 无需直接 import rpc。"""
    def __init__(self, method: str = ""):
        self._method = method  # 记录当前方法名，用于选择错误响应格式

    async def response(self, req_id: str, result) -> None:
        from evocli_soul import rpc; await rpc.send_response(req_id, result)

    async def error(self, req_id: str, code: int, message: str) -> None:
        from evocli_soul import rpc
        # 流式方法必须用 stream_chunk(done=True) 响应错误，否则 Rust bridge 的
        # stream channel 永远不关闭，TUI 卡在 "Streaming..." 状态
        if self._method in _STREAMING_METHODS:
            await rpc.send_stream_chunk(req_id, f"ERROR [{code}]: {message}", done=True)
        else:
            await rpc.send_error(req_id, code, message)

    async def stream_chunk(self, req_id: str, text: str, done: bool) -> None:
        from evocli_soul import rpc; await rpc.send_stream_chunk(req_id, text, done)


HandlerFn = Callable[[str, dict, SendProxy, object], Awaitable[None]]


class Router:
    def __init__(self, state):
        self._state    = state
        self._handlers: dict[str, HandlerFn] = {}
        self._send_override: SendProxy | None = None  # test hook

    def add(self, method: str, handler: HandlerFn) -> None:
        self._handlers[method] = handler

    async def dispatch(self, req_id: str, method: str, params: dict) -> None:
        # Use override (for tests) or create a fresh method-aware SendProxy
        send = self._send_override if self._send_override is not None else SendProxy(method)
        # If override is set, update its method awareness
        if self._send_override is not None:
            self._send_override._method = method

        handler = self._handlers.get(method)
        if handler is None:
            log.warning("Unknown method: %s", method)
            await send.error(req_id, -32601, f"Method not found: {method}")
            return
        try:
            await handler(req_id, params, send, self._state)
        except Exception as e:
            log.exception("Handler %s raised: %s", method, e)
            await send.error(req_id, -32603, str(e))

    # Backward-compat property for tests that do `router._send = CaptureSend()`
    @property
    def _send(self):
        return self._send_override

    @_send.setter
    def _send(self, value):
        self._send_override = value
