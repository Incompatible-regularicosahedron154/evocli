"""
tree_sitter_analyzer.py — tree-sitter 代码分析模块（Section 16 Layer 1）

替代 Rust 侧 regex 的精确符号提取。
使用 tree-sitter 进行 AST 解析，支持 Python/Rust/TypeScript/Go。
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("evocli.code_intel.tree_sitter")

# 支持的语言映射
LANGUAGE_MAP = {
    ".py":  ("python",     "tree_sitter_python"),
    ".rs":  ("rust",       "tree_sitter_rust"),
    ".ts":  ("typescript", "tree_sitter_typescript"),
    ".tsx": ("typescript", "tree_sitter_typescript"),
    ".js":  ("javascript", "tree_sitter_javascript"),
    ".go":  ("go",         "tree_sitter_go"),
}

# 每种语言查找函数/类/方法的 AST 节点类型
SYMBOL_NODE_TYPES = {
    "python":     ["function_definition", "class_definition", "decorated_definition"],
    "rust":       ["function_item", "struct_item", "impl_item", "fn_item"],
    "typescript": ["function_declaration", "class_declaration", "method_definition", "arrow_function"],
    "javascript": ["function_declaration", "class_declaration", "method_definition"],
    "go":         ["function_declaration", "method_declaration", "type_declaration"],
}


class TreeSitterAnalyzer:
    """使用 tree-sitter 精确提取代码符号（比 regex 更准确）。"""

    def __init__(self):
        self._parsers: dict = {}
        self._languages: dict = {}
        self._available = self._check_available()

    def _check_available(self) -> bool:
        """检查 tree-sitter 是否可用。"""
        return (importlib.util.find_spec("tree_sitter") is not None)

    def _get_parser(self, ext: str):
        """懒加载对应语言的 parser。"""
        if ext in self._parsers:
            return self._parsers[ext], self._languages.get(ext)

        if not self._available:
            return None, None

        lang_info = LANGUAGE_MAP.get(ext)
        if not lang_info:
            return None, None

        lang_name, module_name = lang_info

        if not importlib.util.find_spec(module_name):
            log.debug("tree-sitter language module not found: %s", module_name)
            return None, None

        try:
            from tree_sitter import Language, Parser
            lang_module = importlib.import_module(module_name)
            language    = Language(lang_module.language())
            parser      = Parser(language)
            self._parsers[ext]   = parser
            self._languages[ext] = language
            return parser, language
        except Exception as e:
            log.debug("Failed to init tree-sitter parser for %s: %s", ext, e)
            return None, None

    def extract_symbols(self, file_path: Path, content: str) -> list[dict]:
        """
        使用 tree-sitter 从文件中提取符号（函数/类/方法）。
        返回 [{"name": str, "kind": str, "line": int, "signature": str}]
        如果 tree-sitter 不可用，返回空列表（让 Rust regex 处理）。
        """
        ext = file_path.suffix.lower()
        parser, language = self._get_parser(ext)
        if parser is None:
            return []

        try:
            tree    = parser.parse(content.encode())
            symbols = []
            lang_name = LANGUAGE_MAP[ext][0]
            self._traverse(tree.root_node, content, lang_name, symbols)
            return symbols
        except Exception as e:
            log.debug("tree-sitter parse failed for %s: %s", file_path, e)
            return []

    def _traverse(self, node, content: str, lang: str, results: list) -> None:
        """递归遍历 AST，提取符号定义。"""
        node_types = SYMBOL_NODE_TYPES.get(lang, [])

        if node.type in node_types:
            name, kind = self._extract_name_and_kind(node, lang)
            if name:
                line_start = node.start_point[0]
                # 提取签名（函数定义行）
                lines = content.split("\n")
                signature = lines[line_start].strip() if line_start < len(lines) else ""
                results.append({
                    "name":      name,
                    "kind":      kind,
                    "line":      line_start + 1,
                    "signature": signature[:200],  # 最多 200 字符
                })

        for child in node.children:
            self._traverse(child, content, lang, results)

    def _extract_name_and_kind(self, node, lang: str) -> tuple[str, str]:
        """从节点提取名称和类型。"""
        kind_map = {
            "function_definition":    "function",
            "function_declaration":   "function",
            "function_item":          "function",
            "fn_item":                "function",
            "method_definition":      "method",
            "method_declaration":     "method",
            "class_definition":       "class",
            "class_declaration":      "class",
            "struct_item":            "struct",
            "impl_item":              "impl",
            "type_declaration":       "type",
            "go_function_declaration":"function",
            "decorated_definition":   "function",
        }
        kind = kind_map.get(node.type, "symbol")

        # 获取 identifier 子节点作为名称
        for child in node.children:
            if child.type in ("identifier", "type_identifier", "field_identifier"):
                return child.text.decode(), kind
            # Go/Rust 的特殊情况
            if child.type == "name":
                return child.text.decode(), kind

        return "", kind

    def extract_calls(self, file_path: Path, content: str, known_symbols: list[str]) -> list[dict]:
        """
        提取函数调用关系（调用了哪些已知符号）。
        返回 [{"caller": str, "callee": str, "line": int}]
        """
        ext = file_path.suffix.lower()
        parser, language = self._get_parser(ext)
        if parser is None:
            return []

        try:
            tree  = parser.parse(content.encode())
            calls: list[dict] = []
            known_set = set(known_symbols)
            self._find_calls(tree.root_node, content, known_set, "", calls)
            return calls
        except Exception as e:
            log.debug("Call extraction failed for %s: %s", file_path, e)
            return []

    def _find_calls(self, node, content: str, known_symbols: set, current_func: str, results: list) -> None:
        """找函数调用。"""
        # 跟踪当前函数上下文
        if node.type in ("function_definition", "function_item", "function_declaration", "method_definition"):
            for child in node.children:
                if child.type in ("identifier", "name"):
                    current_func = child.text.decode()
                    break

        # 检测函数调用
        if node.type == "call":
            func_node = node.child_by_field_name("function") or (node.children[0] if node.children else None)
            if func_node:
                callee = func_node.text.decode().split(".")[-1]  # 取最后部分
                if callee in known_symbols and current_func:
                    results.append({
                        "caller": current_func,
                        "callee": callee,
                        "line":   node.start_point[0] + 1,
                    })

        for child in node.children:
            self._find_calls(child, content, known_symbols, current_func, results)


# 全局单例
_analyzer: Optional[TreeSitterAnalyzer] = None


def get_analyzer() -> TreeSitterAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = TreeSitterAnalyzer()
    return _analyzer


def analyze_file(file_path: str, content: str) -> dict:
    """
    分析文件，返回符号列表（tree-sitter 精确版）。
    供 Python Soul 调用，用于增强 Rust 侧 regex 分析。
    """
    analyzer = get_analyzer()
    path     = Path(file_path)
    symbols  = analyzer.extract_symbols(path, content)

    return {
        "file":    file_path,
        "symbols": symbols,
        "engine":  "tree-sitter" if symbols else "fallback-regex",
        "count":   len(symbols),
    }
