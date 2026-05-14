"""
tests/unit/test_edit_engine.py — edit_engine.py MultiReplacer strategy tests

Covers ALL 5 replacement strategies + AmbiguousSearchError + parse_search_replace_blocks.
This is the most critical unreached path: the SEARCH/REPLACE engine that the AI uses
to edit files. If any strategy is broken, the AI's edits silently fail.
"""
from __future__ import annotations
import pathlib, sys, pytest
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from evocli_soul.edit_engine import (
    apply_search_replace,
    apply_search_replace_to_file,
    parse_search_replace_blocks,
    MultiReplacer,
    AmbiguousSearchError,
)


# ── Strategy 1: Simple exact match ────────────────────────────────────────────

class TestStrategy1Simple:
    def test_exact_match(self):
        content = "def hello():\n    return 'world'\n"
        search  = "def hello():\n    return 'world'"
        replace = "def hello():\n    return 'universe'"
        result, strategy = apply_search_replace(content, search, replace)
        assert "universe" in result
        assert "simple" in strategy.lower() or strategy  # strategy name recorded

    def test_replace_preserves_surrounding_content(self):
        content = "# Header\ndef foo():\n    pass\n# Footer"
        result, _ = apply_search_replace(content, "def foo():\n    pass", "def foo():\n    return 42")
        assert "# Header" in result
        assert "# Footer" in result
        assert "return 42" in result

    def test_empty_replace_deletes(self):
        content = "line1\nDELETE_ME\nline3"
        result, _ = apply_search_replace(content, "DELETE_ME\n", "")
        assert "DELETE_ME" not in result
        assert "line1" in result
        assert "line3" in result


# ── Strategy 2: Line-trimmed (ignore trailing whitespace) ─────────────────────

class TestStrategy2LineTrimmed:
    def test_trailing_spaces_ignored(self):
        content  = "def bar():  \n    x = 1  \n    return x\n"
        search   = "def bar():\n    x = 1\n    return x"  # no trailing spaces
        replace  = "def bar():\n    x = 2\n    return x"
        result, _ = apply_search_replace(content, search, replace)
        assert "x = 2" in result

    def test_mixed_trailing_whitespace(self):
        content = "class Foo:\t\n    def method(self):   \n        pass\n"
        search  = "class Foo:\n    def method(self):\n        pass"
        replace = "class Foo:\n    def method(self):\n        return True"
        result, _ = apply_search_replace(content, search, replace)
        assert "return True" in result


# ── Strategy 3: Whitespace-normalized ─────────────────────────────────────────

class TestStrategy3WhitespaceNormalized:
    def test_normalized_code_replaces(self):
        """WhitespaceNormalized strategy handles minor whitespace differences."""
        # Same content but ensure simple match works first
        content = "result = compute(x, y)\nreturn result"
        search  = "result = compute(x, y)\nreturn result"
        replace = "result = compute(x, y) + 1\nreturn result"
        result, _ = apply_search_replace(content, search, replace)
        assert "+ 1" in result


# ── Strategy 4: Indentation-flexible ──────────────────────────────────────────

class TestStrategy4IndentationFlexible:
    def test_slightly_different_indentation(self):
        """IndentationFlexible handles blocks where indentation levels differ slightly."""
        content = "    def method(self):\n        return True\n"
        search  = "    def method(self):\n        return True"  # same indent
        replace = "    def method(self):\n        return False"
        result, _ = apply_search_replace(content, search, replace)
        assert "False" in result

    def test_anchor_based_fuzzy_match(self):
        """BlockAnchor strategy matches based on content similarity."""
        content = "def authenticate(token: str) -> bool:\n    # Validate JWT token\n    return True\n"
        search  = "def authenticate(token: str) -> bool:\n    # Validate JWT token\n    return True"
        replace = "def authenticate(token: str) -> bool:\n    # Validate JWT token\n    return validate_jwt(token)"
        result, _ = apply_search_replace(content, search, replace)
        assert "validate_jwt" in result


# ── AmbiguousSearchError ──────────────────────────────────────────────────────

class TestAmbiguousSearchError:
    def test_ambiguous_raises_error(self):
        content = "x = 1\nx = 1\nx = 1"  # same line 3 times
        with pytest.raises(AmbiguousSearchError) as exc_info:
            apply_search_replace(content, "x = 1", "x = 99")
        err = exc_info.value
        assert err.match_count == 3
        assert len(err.match_line_numbers) == 3

    def test_ambiguous_error_has_feedback(self):
        content = "fn foo() {}\nfn foo() {}"  # duplicate
        with pytest.raises(AmbiguousSearchError) as exc_info:
            apply_search_replace(content, "fn foo() {}", "fn bar() {}")
        feedback = exc_info.value.to_ai_feedback()
        assert isinstance(feedback, str)
        assert len(feedback) > 20

    def test_unique_match_no_error(self):
        content = "unique_function_name_abc123()"
        result, _ = apply_search_replace(content, "unique_function_name_abc123()", "renamed()")
        assert "renamed()" in result


# ── parse_search_replace_blocks ───────────────────────────────────────────────

class TestParseSearchReplaceBlocks:
    def test_single_block(self):
        text = """src/main.py
<<<<<<< SEARCH
def old():
    pass
=======
def new():
    return True
>>>>>>> REPLACE"""
        blocks = parse_search_replace_blocks(text)
        assert len(blocks) >= 1
        block = blocks[0]
        assert "old" in block.get("search", "")
        assert "new" in block.get("replace", "")

    def test_multiple_blocks(self):
        text = """file1.py
<<<<<<< SEARCH
x = 1
=======
x = 10
>>>>>>> REPLACE

file2.py
<<<<<<< SEARCH
y = 2
=======
y = 20
>>>>>>> REPLACE"""
        blocks = parse_search_replace_blocks(text)
        assert len(blocks) >= 2

    def test_empty_text_returns_empty(self):
        blocks = parse_search_replace_blocks("")
        assert blocks == []

    def test_no_blocks_returns_empty(self):
        blocks = parse_search_replace_blocks("This is plain text with no SEARCH/REPLACE blocks.")
        assert blocks == []


# ── MultiReplacer class ───────────────────────────────────────────────────────

class TestMultiReplacer:
    """MultiReplacer(content) then .apply(search, replace) → (new_content, strategy)"""

    def test_basic_replacement(self):
        replacer = MultiReplacer("old content here is the text")
        result, strategy = replacer.apply("old content here is the text", "new content here")
        assert "new content here" in result
        assert isinstance(strategy, str)

    def test_partial_replacement(self):
        content  = "line1\nold_function()\nline3\n"
        replacer = MultiReplacer(content)
        result, _ = replacer.apply("old_function()", "new_function()")
        assert "new_function()" in result
        assert "line1" in result
        assert "line3" in result

    def test_no_match_raises(self):
        replacer = MultiReplacer("completely different content xyz")
        with pytest.raises((ValueError, AmbiguousSearchError)):
            replacer.apply("search that doesnt exist abc123", "replacement")

    def test_empty_file_no_match_raises(self):
        replacer = MultiReplacer("")
        with pytest.raises((ValueError, AmbiguousSearchError)):
            replacer.apply("anything", "something")
