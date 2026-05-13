"""
tests/test_code_chunks_e2e.py — CodeChunkIndex E2E 测试

覆盖 code_chunks.py 中所有公开功能：
  Feature 1:  extract_body          — 函数体提取（显式范围 + 缩进推断）
  Feature 2:  _body_hash            — 去重哈希
  Feature 3:  _get_table            — LanceDB 表初始化与 schema
  Feature 4:  ingest_symbols        — 批量符号向量化入库
  Feature 5:  search                — 语义向量搜索
  Feature 6:  get_body              — 按 chunk_id 精确取体
  Feature 7:  get_body_by_rust_id   — 按 Rust UUID 取体（新功能）
  Feature 8:  get_bodies_for_symbols — 按符号名批量取体
  Feature 9:  stats                 — 索引统计
  Feature 10: generate_community_summaries — 社区摘要生成

运行:
  pytest evocli-soul/tests/test_code_chunks_e2e.py -v
  pytest evocli-soul/tests/test_code_chunks_e2e.py -v -k "extract_body"

测试隔离:
  - LanceDB 全写入 tmp_path（monkeypatch Path.home）
  - Embedder 全 mock（确定性伪向量，无 API 调用）
  - LLM client 使用 AsyncMock
  - lancedb 未安装时 LanceDB 相关用例自动 skip
"""
from __future__ import annotations

import random
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 确保 evocli_soul 可 import ─────────────────────────────────────────────
SOUL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SOUL_DIR))

from evocli_soul.code_chunks import CodeChunkIndex  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# 公共 Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def fake_embed(monkeypatch):
    """
    把 CodeChunkIndex._embed 替换为不需要 API Key 的确定性伪向量。
    相同文本 → 相同 768-dim 向量（保证 search 结果可重现）。
    """
    def _embed(self, text: str) -> list[float]:  # noqa: ANN001
        rng = random.Random(hash(text) & 0xFFFFFFFF)
        return [rng.uniform(-1.0, 1.0) for _ in range(768)]

    monkeypatch.setattr(CodeChunkIndex, "_embed", _embed)


@pytest.fixture()
def lancedb_home(tmp_path, monkeypatch):
    """
    将 Path.home() 重定向到 tmp_path，使 _get_table() 写入临时目录。
    测试结束后自动清理，不污染真实 ~/.evocli。
    """
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def index(lancedb_home, fake_embed):
    """返回一个已初始化、指向 tmp_path 的 CodeChunkIndex 实例。"""
    pytest.importorskip("lancedb")
    return CodeChunkIndex(project_id="test-project")


@pytest.fixture()
def py_file(tmp_path) -> Path:
    """
    写一个包含两个 Python 函数的临时源文件，供 extract_body / ingest 使用。

    文件内容（行号从 1 开始）：
      1: def add(a, b):
      2:     # adds two numbers
      3:     return a + b
      4:
      5: def multiply(x, y):
      6:     result = x * y
      7:     return result
    """
    src = textwrap.dedent("""\
        def add(a, b):
            # adds two numbers
            return a + b

        def multiply(x, y):
            result = x * y
            return result
    """)
    p = tmp_path / "sample.py"
    p.write_text(src, encoding="utf-8")
    return p


@pytest.fixture()
def mock_llm():
    """AsyncMock LLM client，complete_for_task 返回固定摘要字符串。"""
    client = MagicMock()
    client.complete_for_task = AsyncMock(
        return_value="Handles HTTP routing and middleware pipeline."
    )
    return client


# ══════════════════════════════════════════════════════════════════════════════
# Feature 1 — extract_body
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractBody:
    """Feature 1: 从磁盘文件按行号范围提取函数体文本。"""

    def test_explicit_range_returns_correct_lines(self, py_file):
        """显式指定 line_end 时，返回 [line_start, line_end] 对应的行。"""
        body = CodeChunkIndex.extract_body(str(py_file), line_start=1, line_end=3)
        assert body is not None
        assert "def add" in body
        assert "return a + b" in body

    def test_explicit_range_line_count(self, py_file):
        """返回行数与 line_end - line_start + 1 一致。"""
        body = CodeChunkIndex.extract_body(str(py_file), line_start=1, line_end=3)
        assert body is not None
        assert len(body.splitlines()) == 3

    def test_indent_heuristic_stops_at_dedent(self, py_file):
        """line_end=None 时，推断在缩进退出外层作用域处截止。"""
        # add() 是第 1 行，其 body 应在第 4 行（空行）或第 5 行（def multiply）前结束
        body = CodeChunkIndex.extract_body(str(py_file), line_start=1, line_end=None)
        assert body is not None
        assert "def add" in body
        # multiply 不应出现在 add 的 body 里
        assert "def multiply" not in body

    def test_second_function_extract(self, py_file):
        """提取第二个函数 multiply（第 5 行）。"""
        body = CodeChunkIndex.extract_body(str(py_file), line_start=5, line_end=7)
        assert body is not None
        assert "def multiply" in body
        assert "return result" in body

    def test_nonexistent_file_returns_none(self, tmp_path):
        """文件不存在时返回 None，不抛异常。"""
        result = CodeChunkIndex.extract_body(
            str(tmp_path / "no_such_file.py"), line_start=1
        )
        assert result is None

    def test_line_start_out_of_bounds_returns_none(self, py_file):
        """line_start 超出文件行数时返回 None。"""
        result = CodeChunkIndex.extract_body(str(py_file), line_start=9999)
        assert result is None

    def test_line_start_zero_returns_none(self, py_file):
        """line_start=0（无效，1-indexed）返回 None。"""
        result = CodeChunkIndex.extract_body(str(py_file), line_start=0)
        assert result is None

    def test_max_lines_cap(self, tmp_path):
        """函数体超过 max_lines 时截断到 max_lines 行。"""
        lines = ["def long_func():\n"] + [f"    x_{i} = {i}\n" for i in range(50)]
        p = tmp_path / "long.py"
        p.write_text("".join(lines), encoding="utf-8")

        body = CodeChunkIndex.extract_body(str(p), line_start=1, max_lines=5)
        assert body is not None
        assert len(body.splitlines()) <= 5

    def test_single_line_function(self, tmp_path):
        """单行函数也能被提取（MIN_BODY_LINES=1）。"""
        p = tmp_path / "oneliner.py"
        p.write_text("def f(): return 42\n", encoding="utf-8")
        body = CodeChunkIndex.extract_body(str(p), line_start=1, line_end=1)
        assert body is not None
        assert "def f" in body

    def test_returns_string_not_list(self, py_file):
        """返回值是字符串，不是列表。"""
        body = CodeChunkIndex.extract_body(str(py_file), line_start=1, line_end=3)
        assert isinstance(body, str)


# ══════════════════════════════════════════════════════════════════════════════
# Feature 2 — _body_hash
# ══════════════════════════════════════════════════════════════════════════════

class TestBodyHash:
    """Feature 2: 函数体 MD5 截断哈希，用于增量索引去重。"""

    def test_returns_16_hex_chars(self):
        """返回值固定为 16 个十六进制字符。"""
        h = CodeChunkIndex._body_hash("def foo(): pass")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        """相同输入两次调用结果相同。"""
        body = "def bar(x):\n    return x * 2"
        assert CodeChunkIndex._body_hash(body) == CodeChunkIndex._body_hash(body)

    def test_different_bodies_different_hashes(self):
        """不同函数体产生不同哈希值。"""
        h1 = CodeChunkIndex._body_hash("def foo(): pass")
        h2 = CodeChunkIndex._body_hash("def bar(): pass")
        assert h1 != h2

    def test_empty_string(self):
        """空字符串也能正常哈希，不抛异常。"""
        h = CodeChunkIndex._body_hash("")
        assert len(h) == 16

    def test_unicode_body(self):
        """包含中文的函数体正常哈希。"""
        h = CodeChunkIndex._body_hash("def 函数(): return '你好'")
        assert len(h) == 16


# ══════════════════════════════════════════════════════════════════════════════
# Feature 3 — _get_table (LanceDB 表初始化)
# ══════════════════════════════════════════════════════════════════════════════

class TestGetTable:
    """Feature 3: LanceDB 表创建与 schema 验证。"""

    def test_returns_table_object(self, index):
        """_get_table() 返回非 None 的表对象。"""
        tbl = index._get_table()
        assert tbl is not None

    def test_schema_contains_rust_sym_id(self, index, py_file):
        """
        schema 包含 rust_sym_id 字段（新增字段，支持 Rust UUID 反查）。
        通过插入一行后读取列名来验证。
        """
        tbl = index._get_table()
        assert tbl is not None
        # LanceDB 列名可从 schema 取
        col_names = [field.name for field in tbl.schema]
        assert "rust_sym_id" in col_names, (
            f"Schema missing 'rust_sym_id'. Found: {col_names}"
        )

    def test_schema_contains_required_fields(self, index):
        """schema 包含所有必填字段。"""
        tbl = index._get_table()
        assert tbl is not None
        col_names = [field.name for field in tbl.schema]
        required = {"id", "symbol", "file", "language", "kind",
                    "body", "signature", "project_id", "body_hash", "vector"}
        missing = required - set(col_names)
        assert not missing, f"Schema missing fields: {missing}"

    def test_idempotent_returns_same_table(self, index):
        """连续两次调用返回同一个缓存对象。"""
        tbl1 = index._get_table()
        tbl2 = index._get_table()
        assert tbl1 is tbl2

    def test_lancedb_unavailable_returns_none(self, tmp_path, monkeypatch):
        """LanceDB import 或连接失败时返回 None，不抛异常。"""
        pytest.importorskip("lancedb")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        idx = CodeChunkIndex(project_id="test")
        with patch("lancedb.connect", side_effect=RuntimeError("DB unavailable")):
            # 清除缓存
            idx._tbl = None
            idx._db = None
            result = idx._get_table()
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Feature 4 — ingest_symbols
# ══════════════════════════════════════════════════════════════════════════════

class TestIngestSymbols:
    """Feature 4: 批量符号 → extract_body → embed → LanceDB 入库。"""

    def _symbols(self, py_file: Path) -> list[dict]:
        """构造两个有效符号（对应 py_file 里的 add 和 multiply）。"""
        return [
            {
                "id":        "uuid-add-001",
                "name":      "add",
                "kind":      "function",
                "file":      str(py_file),
                "line":      1,
                "line_end":  3,
                "signature": "def add(a, b)",
                "language":  "python",
            },
            {
                "id":        "uuid-mul-002",
                "name":      "multiply",
                "kind":      "function",
                "file":      str(py_file),
                "line":      5,
                "line_end":  7,
                "signature": "def multiply(x, y)",
                "language":  "python",
            },
        ]

    @pytest.mark.asyncio
    async def test_normal_ingest_returns_correct_counts(self, index, py_file):
        """正常 ingest 2 个函数，ingested=2, errors=0。"""
        result = await index.ingest_symbols(self._symbols(py_file))
        assert result["ingested"] == 2
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_kind_filter_skips_non_functions(self, index, py_file):
        """constant / type_alias 类型的符号应被过滤，不入库。"""
        symbols = [
            {
                "id": "uuid-const-001",
                "name": "MAX_SIZE",
                "kind": "constant",          # 不在白名单
                "file": str(py_file),
                "line": 1,
                "signature": "MAX_SIZE = 100",
                "language": "python",
            },
            {
                "id": "uuid-type-002",
                "name": "MyType",
                "kind": "type_alias",         # 不在白名单
                "file": str(py_file),
                "line": 1,
                "signature": "MyType = str",
                "language": "python",
            },
        ]
        result = await index.ingest_symbols(symbols)
        assert result["ingested"] == 0

    @pytest.mark.asyncio
    async def test_incremental_second_ingest_skips_unchanged(self, index, py_file):
        """相同符号 ingest 两次，第二次全部 skipped（body_hash 匹配）。"""
        syms = self._symbols(py_file)
        await index.ingest_symbols(syms)
        result2 = await index.ingest_symbols(syms)
        assert result2["skipped"] == 2
        assert result2["ingested"] == 0

    @pytest.mark.asyncio
    async def test_force_true_reingests_unchanged(self, index, py_file):
        """force=True 强制重新 embed，即使 body_hash 未变。"""
        syms = self._symbols(py_file)
        await index.ingest_symbols(syms)
        result2 = await index.ingest_symbols(syms, force=True)
        assert result2["ingested"] == 2
        assert result2["skipped"] == 0

    @pytest.mark.asyncio
    async def test_rust_sym_id_stored_correctly(self, index, py_file):
        """ingest 后，LanceDB 行的 rust_sym_id 等于传入的 id 字段。"""
        syms = self._symbols(py_file)
        await index.ingest_symbols(syms)

        tbl = index._get_table()
        rows = tbl.search().where("symbol = 'add'").select(["rust_sym_id"]).to_list()
        assert rows, "Symbol 'add' not found after ingest"
        assert rows[0]["rust_sym_id"] == "uuid-add-001"

    @pytest.mark.asyncio
    async def test_nonexistent_file_not_ingested(self, index, tmp_path):
        """符号指向不存在的文件时，extract_body 返回 None，不入库。"""
        symbols = [{
            "id":        "uuid-ghost-001",
            "name":      "ghost_fn",
            "kind":      "function",
            "file":      str(tmp_path / "does_not_exist.py"),
            "line":      1,
            "signature": "def ghost_fn()",
            "language":  "python",
        }]
        result = await index.ingest_symbols(symbols)
        assert result["ingested"] == 0

    @pytest.mark.asyncio
    async def test_lancedb_unavailable_returns_error_dict(self, lancedb_home, fake_embed, py_file):
        """LanceDB 不可用时返回含 error 键的 dict，不抛异常。"""
        pytest.importorskip("lancedb")
        idx = CodeChunkIndex(project_id="test")
        with patch("lancedb.connect", side_effect=RuntimeError("no db")):
            result = await idx.ingest_symbols(self._symbols(py_file))
        assert "error" in result
        assert result["ingested"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Feature 5 — search
# ══════════════════════════════════════════════════════════════════════════════

class TestSearch:
    """Feature 5: 向量语义搜索代码块。"""

    @pytest.fixture()
    async def populated_index(self, index, py_file):
        """预先 ingest 两个 Python 函数 + 一个 Rust 函数。"""
        # Python
        await index.ingest_symbols([
            {
                "id": "uuid-add", "name": "add", "kind": "function",
                "file": str(py_file), "line": 1, "line_end": 3,
                "signature": "def add(a, b)", "language": "python",
            },
            {
                "id": "uuid-mul", "name": "multiply", "kind": "class",
                "file": str(py_file), "line": 5, "line_end": 7,
                "signature": "def multiply(x, y)", "language": "python",
            },
        ])
        # Rust（写一个临时 .rs 文件）
        rs = py_file.parent / "lib.rs"
        rs.write_text("fn greet() {\n    println!(\"hello\");\n}\n", encoding="utf-8")
        await index.ingest_symbols([{
            "id": "uuid-greet", "name": "greet", "kind": "function",
            "file": str(rs), "line": 1, "line_end": 3,
            "signature": "fn greet()", "language": "rust",
        }])
        return index

    @pytest.mark.asyncio
    async def test_search_returns_results(self, populated_index):
        """有索引时 search 返回非空列表。"""
        results = populated_index.search("add two numbers", top_k=5)
        assert isinstance(results, list)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, populated_index):
        """top_k=1 最多返回 1 条。"""
        results = populated_index.search("function", top_k=1)
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_language_filter(self, populated_index):
        """language='rust' 只返回 rust 条目。"""
        results = populated_index.search("function", top_k=10, language="rust")
        for r in results:
            assert r.get("language") == "rust", f"Non-rust result: {r}"

    @pytest.mark.asyncio
    async def test_kind_filter(self, populated_index):
        """kind='class' 只返回 kind==class 的条目。"""
        results = populated_index.search("multiply", top_k=10, kind="class")
        for r in results:
            assert r.get("kind") == "class"

    @pytest.mark.asyncio
    async def test_file_filter(self, populated_index, py_file):
        """file_filter 按文件路径子串过滤。"""
        results = populated_index.search("function", top_k=10,
                                         file_filter="lib.rs")
        for r in results:
            assert "lib.rs" in r.get("file", "")

    def test_empty_index_returns_empty_list(self, index):
        """未 ingest 时 search 返回 []。"""
        results = index.search("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self, populated_index):
        """每条搜索结果包含必要字段。"""
        results = populated_index.search("add", top_k=3)
        if results:
            required = {"id", "symbol", "file", "body"}
            for r in results:
                missing = required - set(r.keys())
                assert not missing, f"Result missing fields {missing}: {r}"


# ══════════════════════════════════════════════════════════════════════════════
# Feature 6 — get_body
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBody:
    """Feature 6: 按 chunk_id（file:line）精确取函数体。"""

    @pytest.mark.asyncio
    async def test_hit_returns_body_string(self, index, py_file):
        """ingest 后用正确 chunk_id 能取到 body 字符串。"""
        await index.ingest_symbols([{
            "id": "uuid-001", "name": "add", "kind": "function",
            "file": str(py_file), "line": 1, "line_end": 3,
            "signature": "def add(a, b)", "language": "python",
        }])
        chunk_id = f"{str(py_file)}:1"
        body = index.get_body(chunk_id)
        assert body is not None
        assert isinstance(body, str)
        assert len(body) > 0

    def test_miss_returns_none(self, index):
        """不存在的 chunk_id 返回 None。"""
        result = index.get_body("nonexistent/path.py:999")
        assert result is None

    def test_empty_index_returns_none(self, index):
        """空索引调用 get_body 返回 None，不抛异常。"""
        result = index.get_body("any/path.py:1")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Feature 7 — get_body_by_rust_id（新功能）
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBodyByRustId:
    """Feature 7: 按 Rust symbol UUID 取函数体（blast_radius 反查链路）。"""

    @pytest.mark.asyncio
    async def test_hit_by_rust_uuid(self, index, py_file):
        """ingest 时传入 id='uuid-abc'，之后能用该 UUID 取到 body。"""
        rust_uuid = "rust-sym-uuid-abc-123"
        await index.ingest_symbols([{
            "id":        rust_uuid,
            "name":      "add",
            "kind":      "function",
            "file":      str(py_file),
            "line":      1,
            "line_end":  3,
            "signature": "def add(a, b)",
            "language":  "python",
        }])
        body = index.get_body_by_rust_id(rust_uuid)
        assert body is not None
        assert "def add" in body

    def test_miss_returns_none(self, index):
        """不存在的 UUID 返回 None。"""
        result = index.get_body_by_rust_id("non-existent-uuid-xyz")
        assert result is None

    def test_old_index_without_column_returns_none(self, index):
        """
        旧版索引（无 rust_sym_id 列）调用时静默返回 None，不崩溃。
        通过 mock 表的 where() 抛出异常来模拟旧 schema。
        """
        mock_tbl = MagicMock()
        mock_tbl.search.return_value.where.side_effect = Exception(
            "Column 'rust_sym_id' not found"
        )
        index._tbl = mock_tbl

        result = index.get_body_by_rust_id("some-uuid")
        assert result is None  # 不崩溃，返回 None

    @pytest.mark.asyncio
    async def test_different_symbols_different_uuids(self, index, py_file):
        """两个不同 UUID 各自取到各自的函数体，不混淆。"""
        uuid_add = "uuid-for-add"
        uuid_mul = "uuid-for-multiply"

        await index.ingest_symbols([
            {
                "id": uuid_add, "name": "add", "kind": "function",
                "file": str(py_file), "line": 1, "line_end": 3,
                "signature": "def add(a, b)", "language": "python",
            },
            {
                "id": uuid_mul, "name": "multiply", "kind": "function",
                "file": str(py_file), "line": 5, "line_end": 7,
                "signature": "def multiply(x, y)", "language": "python",
            },
        ])

        body_add = index.get_body_by_rust_id(uuid_add)
        body_mul = index.get_body_by_rust_id(uuid_mul)

        assert body_add is not None and "add" in body_add
        assert body_mul is not None and "multiply" in body_mul
        assert body_add != body_mul


# ══════════════════════════════════════════════════════════════════════════════
# Feature 8 — get_bodies_for_symbols
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBodiesForSymbols:
    """Feature 8: 按符号名批量取代码体（community_summaries 的 prompt 数据源）。"""

    @pytest.mark.asyncio
    async def test_returns_matching_symbols(self, index, py_file):
        """ingest 2 个符号后按名查询，返回 2 条。"""
        await index.ingest_symbols([
            {
                "id": "u1", "name": "add", "kind": "function",
                "file": str(py_file), "line": 1, "line_end": 3,
                "signature": "def add(a, b)", "language": "python",
            },
            {
                "id": "u2", "name": "multiply", "kind": "function",
                "file": str(py_file), "line": 5, "line_end": 7,
                "signature": "def multiply(x, y)", "language": "python",
            },
        ])
        results = index.get_bodies_for_symbols(["add", "multiply"])
        assert len(results) == 2
        names = {r["symbol"] for r in results}
        assert names == {"add", "multiply"}

    def test_empty_input_returns_empty_list(self, index):
        """空列表输入直接返回 []，不查 DB。"""
        result = index.get_bodies_for_symbols([])
        assert result == []

    @pytest.mark.asyncio
    async def test_partial_match(self, index, py_file):
        """只有部分符号已入库时，返回已入库的条目。"""
        await index.ingest_symbols([{
            "id": "u1", "name": "add", "kind": "function",
            "file": str(py_file), "line": 1, "line_end": 3,
            "signature": "def add(a, b)", "language": "python",
        }])
        results = index.get_bodies_for_symbols(["add", "not_exist_fn"])
        assert len(results) == 1
        assert results[0]["symbol"] == "add"

    @pytest.mark.asyncio
    async def test_result_has_body_field(self, index, py_file):
        """返回结果包含 body 字段且非空。"""
        await index.ingest_symbols([{
            "id": "u1", "name": "add", "kind": "function",
            "file": str(py_file), "line": 1, "line_end": 3,
            "signature": "def add(a, b)", "language": "python",
        }])
        results = index.get_bodies_for_symbols(["add"])
        assert results[0].get("body"), "body field should not be empty"


# ══════════════════════════════════════════════════════════════════════════════
# Feature 9 — stats
# ══════════════════════════════════════════════════════════════════════════════

class TestStats:
    """Feature 9: 返回索引统计信息。"""

    def test_empty_index_returns_zero_total(self, index):
        """未 ingest 时 total == 0。"""
        result = index.stats()
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_ingest(self, index, py_file):
        """ingest 2 python + 1 rust 后，total=3，by_language 正确。"""
        rs = py_file.parent / "lib.rs"
        rs.write_text("fn greet() {\n    println!(\"hi\");\n}\n", encoding="utf-8")

        await index.ingest_symbols([
            {
                "id": "u1", "name": "add", "kind": "function",
                "file": str(py_file), "line": 1, "line_end": 3,
                "signature": "def add(a, b)", "language": "python",
            },
            {
                "id": "u2", "name": "multiply", "kind": "function",
                "file": str(py_file), "line": 5, "line_end": 7,
                "signature": "def multiply(x, y)", "language": "python",
            },
            {
                "id": "u3", "name": "greet", "kind": "function",
                "file": str(rs), "line": 1, "line_end": 3,
                "signature": "fn greet()", "language": "rust",
            },
        ])

        stats = index.stats()
        assert stats["total"] == 3
        assert stats["by_language"].get("python") == 2
        assert stats["by_language"].get("rust") == 1

    def test_lancedb_unavailable_returns_error_key(self, lancedb_home, fake_embed):
        """LanceDB 不可用时返回含 error 键的 dict。"""
        pytest.importorskip("lancedb")
        idx = CodeChunkIndex(project_id="test")
        with patch("lancedb.connect", side_effect=RuntimeError("no db")):
            result = idx.stats()
        assert "error" in result or result["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Feature 10 — generate_community_summaries
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerateCommunitySummaries:
    """Feature 10: 社区摘要生成（LLM + 代码体 prompt 组装）。"""

    @pytest.fixture()
    async def populated(self, index, py_file):
        """预先 ingest add 和 multiply，供社区摘要测试使用。"""
        await index.ingest_symbols([
            {
                "id": "u1", "name": "add", "kind": "function",
                "file": str(py_file), "line": 1, "line_end": 3,
                "signature": "def add(a, b)", "language": "python",
            },
            {
                "id": "u2", "name": "multiply", "kind": "function",
                "file": str(py_file), "line": 5, "line_end": 7,
                "signature": "def multiply(x, y)", "language": "python",
            },
        ])
        return index, py_file

    @pytest.mark.asyncio
    async def test_normal_summary_returns_one_result(self, populated, mock_llm):
        """1 个有代码体的社区 → 返回 1 条摘要，含必要字段。"""
        idx, _ = populated
        communities = [{
            "id": "comm-1",
            "label": "math_ops",
            "symbols": ["add", "multiply"],
        }]
        results = await idx.generate_community_summaries(communities, mock_llm)
        assert len(results) == 1
        r = results[0]
        assert r["label"] == "math_ops"
        assert r["community_id"] == "comm-1"
        assert "summary" in r and r["summary"]
        assert "symbols" in r

    @pytest.mark.asyncio
    async def test_prompt_contains_symbol_name_in_file(self, populated, mock_llm):
        """
        生成 prompt 时包含 'sym_name in file' 格式的 snippet header。
        验证新修复：之前只有 '// file'，现在是 '// sym_name in file'。
        """
        idx, _ = populated

        captured_prompts: list[str] = []

        async def capture_prompt(task, prompt):
            captured_prompts.append(prompt)
            return "Test summary."

        mock_llm.complete_for_task = capture_prompt

        communities = [{
            "id": "comm-1",
            "label": "math_ops",
            "symbols": ["add", "multiply"],
        }]
        await idx.generate_community_summaries(communities, mock_llm)

        assert captured_prompts, "LLM should have been called"
        prompt = captured_prompts[0]
        # prompt 中应含 'symbol_name in file_path' 格式
        assert " in " in prompt, (
            f"Prompt should contain 'sym_name in file' header.\nPrompt:\n{prompt[:500]}"
        )

    @pytest.mark.asyncio
    async def test_communities_sorted_by_size_desc(self, populated, mock_llm):
        """大社区优先处理（按 symbols 数量降序）。"""
        idx, _ = populated

        call_order: list[str] = []

        async def record_order(task, prompt):
            # 从 prompt 里提取 community label
            for line in prompt.splitlines():
                if "community '" in line:
                    label = line.split("community '")[1].split("'")[0]
                    call_order.append(label)
                    break
            return "summary"

        mock_llm.complete_for_task = record_order

        communities = [
            {"id": "small", "label": "small_comm",  "symbols": ["add"]},
            {"id": "large", "label": "large_comm",  "symbols": ["add", "multiply"]},
        ]
        await idx.generate_community_summaries(communities, mock_llm)

        assert call_order[0] == "large_comm", (
            f"Larger community should be processed first. Order: {call_order}"
        )

    @pytest.mark.asyncio
    async def test_max_communities_limit(self, populated, mock_llm):
        """max_communities=1 时只处理 1 个社区。"""
        idx, _ = populated
        communities = [
            {"id": f"c{i}", "label": f"comm_{i}", "symbols": ["add"]}
            for i in range(5)
        ]
        results = await idx.generate_community_summaries(
            communities, mock_llm, max_communities=1
        )
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_llm_error_skips_community_no_crash(self, populated, mock_llm):
        """LLM 抛异常时跳过该社区，不崩溃，返回空列表。"""
        idx, _ = populated
        mock_llm.complete_for_task = AsyncMock(side_effect=RuntimeError("LLM down"))

        communities = [{"id": "c1", "label": "comm_1", "symbols": ["add"]}]
        results = await idx.generate_community_summaries(communities, mock_llm)
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_symbols_community_skipped(self, populated, mock_llm):
        """symbols=[] 的社区直接跳过。"""
        idx, _ = populated
        communities = [{"id": "empty", "label": "empty_comm", "symbols": []}]
        results = await idx.generate_community_summaries(communities, mock_llm)
        assert results == []

    @pytest.mark.asyncio
    async def test_community_with_no_indexed_bodies_skipped(self, index, mock_llm):
        """社区的符号未被 ingest（无代码体）时，社区被跳过。"""
        communities = [{
            "id": "c1",
            "label": "unknown_comm",
            "symbols": ["ghost_func_xyz", "phantom_fn"],
        }]
        results = await index.generate_community_summaries(communities, mock_llm)
        assert results == []
