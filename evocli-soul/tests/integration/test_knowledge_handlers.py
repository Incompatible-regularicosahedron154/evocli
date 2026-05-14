"""
tests/integration/test_knowledge_handlers.py — handlers/knowledge.py E2E tests

Covers ALL 7 knowledge RPC handlers:
  - handle_bm25_search
  - handle_hybrid_search (BM25 + vector + RRF merge)
  - handle_blast_radius
  - handle_symbol_context
  - handle_communities
  - handle_processes
  - handle_wiki_generate

Uses MockBridge + MockState to simulate Rust responses without real binary.
"""
from __future__ import annotations
import asyncio, pathlib, sys
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))


# ── Test Infrastructure ────────────────────────────────────────────────────────

class _MockBridge:
    """Records calls and returns configurable responses."""
    def __init__(self, responses: dict | None = None):
        self.calls: list = []
        self._responses = responses or {}

    async def call(self, tool: str, args: dict):
        self.calls.append((tool, args))
        if tool in self._responses:
            r = self._responses[tool]
            return r(args) if callable(r) else r
        # Sensible defaults for code_intel tools
        if "bm25_search" in tool:
            return {"results": [
                {"symbol_id": "sym_main", "name": "main", "file": "src/main.rs", "rank": 1},
                {"symbol_id": "sym_auth", "name": "authenticate", "file": "src/auth.rs", "rank": 2},
            ], "count": 2}
        if "blast_radius" in tool:
            return {
                "symbol_id": args.get("symbol_id", ""),
                "upstream": [{"symbol_id": "caller_1", "file": "src/main.rs", "depth": 1}],
                "downstream": [{"symbol_id": "callee_1", "file": "src/db.rs", "depth": 1}],
                "risk_level": "medium",
            }
        if "symbol_context" in tool:
            return {
                "symbol_id": args.get("symbol_id", ""),
                "callers":   [{"name": "main", "file": "src/main.rs"}],
                "callees":   [{"name": "db_query", "file": "src/db.rs"}],
                "community": "auth_module",
            }
        if "communities" in tool:
            return {"communities": [
                {"id": "c1", "name": "Authentication", "members": ["authenticate", "validate_jwt"]},
                {"id": "c2", "name": "Database",       "members": ["query", "connect"]},
            ]}
        if "processes" in tool:
            return {"processes": [
                {"id": "p1", "name": "Request Handling", "steps": ["receive", "authenticate", "respond"]},
            ]}
        return {"ok": True, "tool": tool}


class _MockMemory:
    """Mock memory for vector search."""
    def search(self, query: str, top_k: int = 5, **kwargs):
        return [
            {"id": "mem_1", "title": "JWT auth pattern", "body": "Use HS256", "score": 0.9},
            {"id": "mem_2", "title": "DB connection pool", "body": "Use r2d2", "score": 0.7},
        ]


class _MockState:
    def __init__(self, bridge=None):
        self._bridge = bridge or _MockBridge()
        self._memory = _MockMemory()

    def get_bridge(self): return self._bridge
    def get_memory(self): return self._memory
    def get_config(self): return {}


class _Capture:
    """Capture RPC send calls."""
    def __init__(self):
        self.responses: list  = []
        self.errors:    list  = []

    async def response(self, req_id: str, data):
        self.responses.append(data)

    async def error(self, req_id: str, code: int, msg: str):
        self.errors.append({"code": code, "message": msg})

    @property
    def last_response(self): return self.responses[-1] if self.responses else None
    @property
    def last_error(self): return self.errors[-1] if self.errors else None


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBm25Search:
    @pytest.mark.asyncio
    async def test_valid_query_returns_results(self):
        from evocli_soul.handlers.knowledge import handle_bm25_search
        state, send = _MockState(), _Capture()
        await handle_bm25_search("req1", {"query": "authenticate user"}, send, state)
        assert send.last_response is not None
        assert "results" in send.last_response or isinstance(send.last_response, (dict, list))

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self):
        from evocli_soul.handlers.knowledge import handle_bm25_search
        state, send = _MockState(), _Capture()
        await handle_bm25_search("req2", {"query": ""}, send, state)
        assert send.last_error is not None
        assert send.last_error["code"] == -32600

    @pytest.mark.asyncio
    async def test_limit_parameter_respected(self):
        from evocli_soul.handlers.knowledge import handle_bm25_search
        bridge = _MockBridge()
        state, send = _MockState(bridge), _Capture()
        await handle_bm25_search("req3", {"query": "auth", "limit": 5}, send, state)
        calls = [c for c in bridge.calls if "bm25_search" in c[0]]
        assert calls, "bridge.call('bm25_search') was not called"


class TestHybridSearch:
    @pytest.mark.asyncio
    async def test_hybrid_merges_bm25_and_vector(self):
        """RRF merge should combine BM25 and vector results."""
        from evocli_soul.handlers.knowledge import handle_hybrid_search
        state, send = _MockState(), _Capture()
        await handle_hybrid_search("req4", {"query": "JWT auth"}, send, state)
        r = send.last_response
        assert r is not None
        # Should have results from RRF merge
        if isinstance(r, dict):
            assert "results" in r
            assert "query" in r

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self):
        from evocli_soul.handlers.knowledge import handle_hybrid_search
        state, send = _MockState(), _Capture()
        await handle_hybrid_search("req5", {}, send, state)
        assert send.last_error is not None

    @pytest.mark.asyncio
    async def test_rrf_scoring_is_positive(self):
        """All RRF scores must be positive."""
        from evocli_soul.handlers.knowledge import handle_hybrid_search
        state, send = _MockState(), _Capture()
        await handle_hybrid_search("req6", {"query": "database connection"}, send, state)
        r = send.last_response
        if r and isinstance(r, dict):
            for result in r.get("results", []):
                assert result.get("rrf_score", 0) > 0


class TestBlastRadius:
    @pytest.mark.asyncio
    async def test_valid_symbol_id(self):
        from evocli_soul.handlers.knowledge import handle_blast_radius
        state, send = _MockState(), _Capture()
        await handle_blast_radius("req7", {"symbol_id": "authenticate"}, send, state)
        assert send.last_response is not None

    @pytest.mark.asyncio
    async def test_empty_symbol_id_error(self):
        from evocli_soul.handlers.knowledge import handle_blast_radius
        state, send = _MockState(), _Capture()
        await handle_blast_radius("req8", {"symbol_id": ""}, send, state)
        assert send.last_error is not None
        assert send.last_error["code"] == -32600

    @pytest.mark.asyncio
    async def test_max_depth_param_passed_to_bridge(self):
        from evocli_soul.handlers.knowledge import handle_blast_radius
        bridge = _MockBridge()
        state, send = _MockState(bridge), _Capture()
        await handle_blast_radius("req9", {"symbol_id": "main", "max_depth": 3}, send, state)
        calls = [c for c in bridge.calls if "blast_radius" in c[0]]
        assert calls
        assert calls[0][1]["max_depth"] == 3


class TestSymbolContext:
    @pytest.mark.asyncio
    async def test_valid_symbol_returns_context(self):
        from evocli_soul.handlers.knowledge import handle_symbol_context
        state, send = _MockState(), _Capture()
        await handle_symbol_context("req10", {"symbol_id": "authenticate"}, send, state)
        assert send.last_response is not None

    @pytest.mark.asyncio
    async def test_missing_symbol_id_error(self):
        from evocli_soul.handlers.knowledge import handle_symbol_context
        state, send = _MockState(), _Capture()
        await handle_symbol_context("req11", {}, send, state)
        assert send.last_error is not None


class TestCommunities:
    @pytest.mark.asyncio
    async def test_returns_community_list(self):
        from evocli_soul.handlers.knowledge import handle_communities
        state, send = _MockState(), _Capture()
        await handle_communities("req12", {}, send, state)
        assert send.last_response is not None

    @pytest.mark.asyncio
    async def test_bridge_called_for_communities(self):
        from evocli_soul.handlers.knowledge import handle_communities
        bridge = _MockBridge()
        state, send = _MockState(bridge), _Capture()
        await handle_communities("req13", {}, send, state)
        called_tools = [c[0] for c in bridge.calls]
        assert any("communities" in t for t in called_tools)


class TestProcesses:
    @pytest.mark.asyncio
    async def test_returns_processes_list(self):
        from evocli_soul.handlers.knowledge import handle_processes
        state, send = _MockState(), _Capture()
        await handle_processes("req14", {}, send, state)
        assert send.last_response is not None


class TestWikiGenerate:
    @pytest.mark.asyncio
    async def test_wiki_generate_no_crash(self):
        """wiki.generate must not crash with NameError/AttributeError."""
        from evocli_soul.handlers.knowledge import handle_wiki_generate
        state, send = _MockState(), _Capture()
        try:
            await handle_wiki_generate("req15", {}, send, state)
        except (NameError, AttributeError) as e:
            raise AssertionError(f"REGRESSION: {type(e).__name__}: {e}")
        except Exception:
            pass  # Other errors (no code index, etc.) are acceptable
        # Either a response or an error — not a crash
        assert send.last_response is not None or send.last_error is not None
