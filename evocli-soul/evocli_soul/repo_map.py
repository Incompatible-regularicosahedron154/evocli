"""
EvoCLI RepoMap — Aider-style Personalized PageRank Repository Map

研究来源：Aider (github.com/Aider-AI/aider) RepoMap 算法
作者 Paul Gauthier 在博客中描述："We run a personalized PageRank on the tags graph
to identify the most important symbols in the repository relative to the chat context."

算法步骤：
1. 使用 tree-sitter 提取全仓库的符号定义 + 引用（tags）
2. 构建有向图：每条边 = 文件 A 引用了文件 B 中定义的符号
3. 运行 Personalized PageRank（当前编辑/提到的文件权重 50x）
4. 使用 grep-ast "skeleton" 渲染最重要的符号签名
5. 二分搜索找到在 token 预算内的最大符号集合

对比纯向量 RAG：PageRank 考虑结构性重要性（谁调用了谁），
向量相似度无法捕捉"核心依赖文件"这一维度。

需要：pip install "evocli-soul[code]"（包含 networkx, grep-ast, tree-sitter-language-pack）
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("evocli.repo_map")

_NETWORKX_AVAILABLE = importlib.util.find_spec("networkx") is not None
_GREP_AST_AVAILABLE = importlib.util.find_spec("grep_ast") is not None
_DISKCACHE_AVAILABLE = importlib.util.find_spec("diskcache") is not None
_PATHSPEC_AVAILABLE = importlib.util.find_spec("pathspec") is not None
_GITPYTHON_AVAILABLE = importlib.util.find_spec("git") is not None

# 与 Aider 相同的 token 预算默认值
DEFAULT_MAP_TOKENS = 1024
CHAT_FILE_WEIGHT   = 50.0    # 当前编辑文件的边权重倍数（Aider: 50x）


class RepoMap:
    """
    Aider-style Repository Map。

    使用 tree-sitter + networkx PageRank 为 LLM 提供最相关的代码上下文，
    而非简单地截断文件内容。
    """

    def __init__(
        self,
        root: str | Path = ".",
        map_tokens: int = DEFAULT_MAP_TOKENS,
        cache_dir: Optional[str] = None,
    ):
        self.root       = Path(root).resolve()
        self.map_tokens = map_tokens
        self._cache     = self._init_cache(cache_dir)
        self._tags_cache: dict[str, list[dict]] = {}  # in-memory: path → tags

    def _init_cache(self, cache_dir: Optional[str]):
        """diskcache 持久化缓存（Aider 同款：避免每次重新解析）。"""
        if not _DISKCACHE_AVAILABLE:
            log.debug("diskcache not available — tree-sitter results won't be persisted")
            return None
        try:
            import diskcache
            cd = cache_dir or str(Path.home() / ".evocli" / "cache" / "repo_map")
            cache = diskcache.Cache(cd)
            log.debug("RepoMap cache: %s", cd)
            return cache
        except Exception as e:
            log.debug("diskcache init failed: %s", e)
            return None

    # ── Tag extraction ────────────────────────────────────────────

    def _get_tags(self, file_path: Path) -> list[dict]:
        """
        Extract symbol tags from a file using tree-sitter + grep-ast.
        Returns list of: {name, kind, file, line, is_def}
        
        Uses diskcache keyed on (path, mtime) — same pattern as Aider.
        """
        key = f"{file_path}:{file_path.stat().st_mtime_ns}" if file_path.exists() else None

        # Check cache
        if key and self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        tags = self._extract_tags(file_path)

        # Store in cache
        if key and self._cache is not None:
            self._cache.set(key, tags)

        return tags

    def _extract_tags(self, file_path: Path) -> list[dict]:
        """
        Parse file and extract definition + reference tags using tree-sitter.
        Uses the same LANGUAGE_MAP as tree_sitter_analyzer.py.
        """
        # Language mapping: extension → (lang_name, module_name)
        LANGUAGE_MAP = {
            ".py":  "tree_sitter_python",
            ".rs":  "tree_sitter_rust",
            ".ts":  "tree_sitter_typescript",
            ".tsx": "tree_sitter_typescript",
            ".js":  "tree_sitter_javascript",
            ".go":  "tree_sitter_go",
        }
        suffix = file_path.suffix
        module_name = LANGUAGE_MAP.get(suffix)
        if not module_name or not importlib.util.find_spec(module_name):
            return self._extract_tags_fallback(file_path)

        try:
            from tree_sitter import Language, Parser
            lang_mod = importlib.import_module(module_name)
            language = Language(lang_mod.language())
            parser   = Parser(language)

            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree    = parser.parse(bytes(content, "utf-8"))

            tags: list[dict] = []
            self._walk_tree_for_tags(tree.root_node, bytes(content, "utf-8"), str(file_path), tags)
            return tags

        except Exception as e:
            log.debug("tree-sitter tag extraction failed for %s: %s", file_path, e)
            return self._extract_tags_fallback(file_path)

    def _walk_tree_for_tags(self, node, content: bytes, file_path: str, tags: list[dict],
                            _inside_def_name: bool = False) -> None:
        """
        Walk tree-sitter AST and collect BOTH definitions and call references.

        Oracle bug fix: original code never emitted ref tags, making PageRank edges empty.
        This version collects call sites as references (file A calls function B → edge A→B file).
        """
        DEF_NODES = {
            "function_definition", "function_declaration", "function_item",
            "class_definition", "class_declaration", "struct_item", "impl_item",
            "method_definition", "method_declaration",
            "type_alias_declaration", "interface_declaration",
        }

        if node.type in DEF_NODES:
            # Extract the definition name (first identifier child)
            for child in node.children:
                if child.type == "identifier":
                    def_name = content[child.start_byte:child.end_byte].decode("utf-8", "replace")
                    if def_name:
                        tags.append({
                            "name": def_name,
                            "kind": "def",
                            "file": file_path,
                            "line": node.start_point[0] + 1,
                            "type": node.type,
                        })
                    break
            # Recurse into children, not marking as inside-def-name
            for child in node.children:
                self._walk_tree_for_tags(child, content, file_path, tags)
            return

        # Call expression: extract the function name being called
        # This gives us cross-file edges: "file A calls Foo.bar → file with def bar"
        if node.type == "call":
            func_node = node.children[0] if node.children else None
            if func_node is not None:
                call_name = None
                if func_node.type == "identifier":
                    call_name = content[func_node.start_byte:func_node.end_byte].decode("utf-8", "replace")
                elif func_node.type == "attribute":
                    # method call like obj.method() → extract method name
                    for child in func_node.children:
                        if child.type == "identifier":
                            call_name = content[child.start_byte:child.end_byte].decode("utf-8", "replace")
                if call_name and len(call_name) >= 2:
                    _SKIP_NAMES = {"self", "cls", "super", "print", "len", "str", "int", "list", "dict"}
                    if call_name not in _SKIP_NAMES:
                        tags.append({
                            "name": call_name,
                            "kind": "ref",
                            "file": file_path,
                            "line": node.start_point[0] + 1,
                            "type": "call",
                        })

        # Recurse into all children
        for child in node.children:
            self._walk_tree_for_tags(child, content, file_path, tags)

    def _extract_tags_fallback(self, file_path: Path) -> list[dict]:
        """
        Regex-based fallback when tree-sitter is unavailable.
        Emits definition tags only. Reference edges are added in get_repo_map()
        via cross-file name matching (simpler and more reliable for regex mode).
        """
        import re
        patterns = [
            (r"(?m)^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", "function_item"),
            (r"(?m)^\s*(?:async\s+)?def\s+(\w+)", "function_definition"),
            (r"(?m)^\s*class\s+(\w+)", "class_definition"),
            (r"(?m)^\s*(?:export\s+)?(?:function|class)\s+(\w+)", "function_declaration"),
            (r"(?m)^\s*(?:pub\s+)?struct\s+(\w+)", "struct_item"),
        ]
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tags = []
            for pattern, node_type in patterns:
                for m in re.finditer(pattern, content):
                    line = content[:m.start()].count("\n") + 1
                    tags.append({"name": m.group(1), "kind": "def",
                                 "file": str(file_path), "line": line, "type": node_type})
            return tags
        except Exception:
            return []

    # ── Graph construction + PageRank ─────────────────────────────

    def get_repo_map(
        self,
        chat_files: list[str] | None = None,
        mentioned_symbols: list[str] | None = None,
        max_tokens: int | None = None,
        pre_ranked_symbols: list[dict] | None = None,
    ) -> str:
        """
        Build a Personalized PageRank repo map.

        chat_files:        Files currently in the conversation (50x weight boost)
        mentioned_symbols: Symbol names mentioned in the user's prompt
        max_tokens:        Override default token budget

        Returns a "skeleton" of the most important symbols, formatted for LLM context.
        """
        if not _NETWORKX_AVAILABLE:
            log.info("networkx not available — RepoMap disabled (install evocli-soul[code])")
            return ""

        budget   = max_tokens or self.map_tokens
        chat_set = set(chat_files or [])

        # ── Fast path: use pre-computed Rust code_intel rankings ──────────────
        # When ranked_symbols from code_intel.ranked_context are provided,
        # skip full tree-sitter re-scan (O(all_files)) and use the existing index.
        # This eliminates redundant parsing since Rust already indexed everything.
        if pre_ranked_symbols:
            try:
                file_scores: dict[str, float] = {}
                for sym in pre_ranked_symbols:
                    f = sym.get("file", "")
                    if f:
                        file_scores[f] = file_scores.get(f, 0) + float(sym.get("score", 1.0))
                # Boost chat files (same 50x weight as full path)
                for f in chat_set:
                    file_scores[f] = file_scores.get(f, 0) + CHAT_FILE_WEIGHT

                if file_scores:
                    sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
                    top_files = [f for f, _ in sorted_files[:30]]
                    result = self._render_skeleton(top_files, budget)
                    if result:
                        log.debug("RepoMap fast-path (pre-ranked): %d files, %d chars",
                                  len(top_files), len(result))
                        return result
                    # Skeleton empty → fall through to full tree-sitter path
            except Exception as e:
                log.debug("RepoMap fast-path failed, falling back to tree-sitter: %s", e)
        # ── Slow path: full tree-sitter scan (fallback when Rust index unavailable) ──

        mention_set  = set(mentioned_symbols or [])

        try:
            import networkx as nx

            # 1. Collect tags from all source files
            all_tags: list[dict] = []
            for path in self._iter_source_files():
                tags = self._get_tags(path)
                all_tags.extend(tags)

            if not all_tags:
                return ""

            # 2. Build directed graph: file → file via symbol references
            G = nx.MultiDiGraph()
            defs: dict[str, list[dict]] = {}  # symbol_name → [def_tags]

            for tag in all_tags:
                if tag["kind"] == "def":
                    defs.setdefault(tag["name"], []).append(tag)
                G.add_node(tag["file"])

            # Edges from tree-sitter ref tags (when grep-ast is available)
            for tag in all_tags:
                if tag["kind"] == "ref":
                    for def_tag in defs.get(tag["name"], []):
                        if def_tag["file"] != tag["file"]:
                            weight = CHAT_FILE_WEIGHT if tag["file"] in chat_set else 1.0
                            G.add_edge(tag["file"], def_tag["file"], weight=weight)

            # Fallback edge generation: if no ref tags (regex mode), do cross-file grep
            # This is the "two-pass" approach: find def names appearing in other files' content
            if not any(t["kind"] == "ref" for t in all_tags) and defs:
                self._add_fallback_ref_edges(G, defs, chat_set)

            # 3. Personalized PageRank
            personalization: dict[str, float] = {}
            for node in G.nodes():
                score = 1.0
                if node in chat_set:
                    score = CHAT_FILE_WEIGHT
                elif any(sym in Path(node).stem for sym in mention_set):
                    score = 10.0
                personalization[node] = score

            if not G.nodes():
                return ""

            ranked = nx.pagerank(G, weight="weight", personalization=personalization)

            # 4. Sort by PageRank score, fill token budget via binary search
            sorted_files = sorted(ranked.items(), key=lambda x: x[1], reverse=True)
            top_files = [f for f, _ in sorted_files[:50]]  # Cap at 50 files max

            return self._render_skeleton(top_files, budget)

        except Exception as e:
            log.warning("RepoMap failed: %s", e)
            return ""

    def _add_fallback_ref_edges(
        self,
        G,
        defs: dict[str, list[dict]],
        chat_set: set[str],
    ) -> None:
        """
        Fallback edge generation for regex mode (no tree-sitter ref tags).
        For each file, grep its content for occurrences of definition names from OTHER files.
        This is O(files × def_names) but accurate enough for projects < 200 files.
        """
        import re
        # Build a regex that matches any known def name (word boundary)
        # Cap at 500 most common names to keep regex manageable
        all_def_names = list(defs.keys())[:500]
        if not all_def_names:
            return
        pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in all_def_names) + r")\b")

        for node in list(G.nodes()):
            path = Path(node)
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                for m in pattern.finditer(content):
                    name = m.group(1)
                    for def_tag in defs.get(name, []):
                        if def_tag["file"] != node:
                            weight = CHAT_FILE_WEIGHT if node in chat_set else 1.0
                            G.add_edge(node, def_tag["file"], weight=weight)
            except Exception as e:
                # Log which files are skipped during graph construction so users can diagnose
                # permission or encoding issues that cause files to be absent from the Repo Map.
                log.debug("repo_map: skipping %s in ref-edge building: %s", node, e)
                continue

    def _render_skeleton(self, files: list[str], budget: int) -> str:
        """
        Render a "skeleton" of the top files (signatures only, no bodies).
        Binary search to fit within token budget.
        Uses char/4 approximation for token counting (fast, no network call).
        Aider also uses sampling-based estimation for speed.
        """
        def approx_tokens(text: str) -> int:
            """Approximate token count (len // 4). Fast, no tiktoken download needed."""
            return max(1, len(text) // 4)

        # Binary search: find maximum K files fitting in budget
        lo, hi, best = 0, len(files), ""
        while lo < hi:
            mid = (lo + hi + 1) // 2
            output = self._render_n_files(files[:mid])
            if approx_tokens(output) <= budget:
                best = output
                lo = mid
            else:
                hi = mid - 1

        return best

    def _render_n_files(self, files: list[str]) -> str:
        """Render function/class signatures for a list of files."""
        lines = []
        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                continue
            try:
                rel = path.relative_to(self.root)
            except ValueError:
                rel = path
            lines.append(f"\n{rel}:")
            # Collect def tags for this file
            file_tags = [t for t in self._get_tags(path) if t["kind"] == "def"]
            for tag in sorted(file_tags, key=lambda t: t["line"])[:20]:
                lines.append(f"  {tag.get('type', 'def')} {tag['name']} (line {tag['line']})")
        return "\n".join(lines)

    # ── File discovery ───────────────────────────────────────────

    def _iter_source_files(self):
        """
        Walk repo for source files with full .gitignore support.

        Strategy (Oracle fix: root-only .gitignore misses nested rules):
        1. gitpython `git ls-files` — lists only git-tracked files (handles ALL gitignore rules,
           nested .gitignore, .git/info/exclude, global gitignore). Used by Aider.
        2. pathspec with root .gitignore — partial but common.
        3. Simple os.walk with hardcoded skip list — always available.
        """
        if _GITPYTHON_AVAILABLE:
            result = list(self._iter_with_gitpython())
            if result:
                yield from result
                return
        # Fall back to pathspec or simple walk
        if _PATHSPEC_AVAILABLE:
            yield from self._iter_with_pathspec()
        else:
            yield from self._iter_simple()

    def _iter_with_gitpython(self):
        """
        Use gitpython to list tracked + staged source files.
        Equivalent to `git ls-files` — includes staged but not committed files,
        which matches Aider's behavior (Oracle: `repo.tree().traverse()` only shows HEAD).

        Research source: Aider uses `git ls-files` for file discovery in RepoMap.
        """
        import git as gitmodule

        CODE_EXTENSIONS = {
            ".py", ".rs", ".ts", ".tsx", ".js", ".jsx",
            ".go", ".java", ".cpp", ".c", ".h", ".cs",
            ".rb", ".php", ".swift", ".kt",
        }
        try:
            repo = gitmodule.Repo(str(self.root), search_parent_directories=True)
            # git ls-files: lists tracked files (respects .gitignore, includes staged)
            tracked = repo.git.ls_files().splitlines()
            for rel_path in tracked:
                full = Path(repo.working_dir) / rel_path
                if full.suffix in CODE_EXTENSIONS and full.exists():
                    yield full
        except Exception as e:
            log.debug("gitpython ls-files failed (%s), falling back", e)

    def _iter_with_pathspec(self):
        """pathspec-based .gitignore-aware file iteration."""
        import pathspec

        CODE_EXTENSIONS = {
            ".py", ".rs", ".ts", ".tsx", ".js", ".jsx",
            ".go", ".java", ".cpp", ".c", ".h", ".cs",
            ".rb", ".php", ".swift", ".kt",
        }

        # Load .gitignore rules
        gitignore_path = self.root / ".gitignore"
        spec = None
        if gitignore_path.exists():
            try:
                with open(gitignore_path) as f:
                    spec = pathspec.PathSpec.from_lines("gitwildmatch", f.readlines())
            except Exception:
                pass

        for dirpath, dirnames, filenames in os.walk(self.root):
            # Remove hidden and common non-source dirs
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in {"target", "node_modules", "__pycache__", "dist", "build"}
            ]
            for filename in filenames:
                full = Path(dirpath) / filename
                if full.suffix not in CODE_EXTENSIONS:
                    continue
                # Check .gitignore
                if spec:
                    rel = full.relative_to(self.root)
                    if spec.match_file(str(rel)):
                        continue
                yield full

    def _iter_simple(self):
        """Simple fallback without pathspec."""
        CODE_EXTENSIONS = {".py", ".rs", ".ts", ".js", ".go", ".java", ".cpp", ".c", ".h"}
        SKIP_DIRS = {"target", "node_modules", "__pycache__", "dist", "build", ".git", ".venv"}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
            for f in filenames:
                path = Path(dirpath) / f
                if path.suffix in CODE_EXTENSIONS:
                    yield path
