"""JSON-RPC 原语层 — 唯一职责：读写 stdout/stdin JSON 消息。"""
from __future__ import annotations
import json
import sys
import threading

# Global lock ensuring atomic (non-interleaved) writes to stdout.
# Without this, concurrent async tasks emitting events while the agent streams
# a response could produce interleaved JSON fragments, corrupting the RPC stream.
_stdout_lock = threading.Lock()


def _send(msg: dict) -> None:
    """写一行 JSON 到 stdout（Rust Host 读取）。
    
    线程安全：使用 _stdout_lock 保证每条消息的 write+flush 是原子操作，
    防止并发 emit_event / stream_chunk 调用产生 JSON 行混叠。
    """
    line = json.dumps(msg, ensure_ascii=False) + "\n"
    try:
        with _stdout_lock:
            sys.stdout.write(line)
            sys.stdout.flush()
    except BrokenPipeError:
        # Rust Host closed the pipe (process is shutting down). Ignore silently.
        pass
    except Exception:
        # Other I/O errors (e.g., disk full) — nothing we can do at this layer.
        pass


async def send_response(req_id: str, result) -> None:
    _send({"id": req_id, "result": result, "error": None})


async def send_error(req_id: str, code: int, message: str) -> None:
    _send({"id": req_id, "result": None, "error": {"code": code, "message": message}})


async def send_stream_chunk(req_id: str, text: str, done: bool) -> None:
    _send({"method": "stream.chunk", "params": {"id": req_id, "text": text, "done": done}})


async def emit_event(event_type: str, data: dict | None = None) -> None:
    _send({"method": "event.emit", "params": {"type": event_type, **(data or {})}})
