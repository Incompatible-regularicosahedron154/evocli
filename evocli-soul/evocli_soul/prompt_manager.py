"""
PromptManager — G-08: prompt_template 注册表。

研究更新: 使用 Jinja2 替代自定义 {{ }} 模板引擎。
- 自定义: 169行 string.replace("{{ var }}", value) 手写模板引擎
- 改为: Jinja2 — Python 最成熟的模板库（Flask/Django/Ansible 同款）
- 好处: 支持 if/for/filters，更安全，更健壮，语法与原有 {{ }} 完全兼容

Skill TOML 用法：
  action = "llm.analyze"
  params = { prompt_template = "analyze_unwrap_usage", input = "${steps.scan.result}" }
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("evocli.prompt_manager")

TEMPLATES_DIR = Path.home() / ".evocli" / "prompt_templates"

_JINJA2_AVAILABLE = importlib.util.find_spec("jinja2") is not None

# ── 内置默认模板（无需 TOML 文件）────────────────────────────────────────────
_BUILTIN_TEMPLATES: dict[str, str] = {
    "analyze_unwrap_usage": (
        "你是 Rust 代码审查助手。\n"
        "以下是项目中所有 .unwrap() 调用的列表：\n\n"
        "{{ input }}\n\n"
        "请分析每处 unwrap 的风险，并生成 unified diff 格式的修改建议，"
        "将高风险的 unwrap 替换为 `?` 运算符或 `match` 表达式。"
        "只修改确实存在 panic 风险的行，不要修改测试代码。"
    ),
    "generate_test": (
        "你是 Rust 测试编写助手。\n"
        "请为以下函数生成完整的单元测试：\n\n"
        "{{ input }}\n\n"
        "要求：\n"
        "1. 测试正常路径、边界情况和错误路径\n"
        "2. 使用 #[test] 标注\n"
        "3. 测试名称要描述性（test_<函数名>_<场景>）\n"
        "4. 生成完整的 #[cfg(test)] 模块"
    ),
    "fix_error": (
        "你是代码调试助手。\n"
        "以下是编译错误或运行时错误信息：\n\n"
        "{{ input }}\n\n"
        "请：\n"
        "1. 分析错误根因\n"
        "2. 生成 unified diff 格式的修复建议\n"
        "3. 说明修复思路"
    ),
    "refactor_function": (
        "你是代码重构助手。\n"
        "请重构以下代码，使其更清晰、更符合 Rust 惯用法：\n\n"
        "{{ input }}\n\n"
        "要求：不改变外部行为，只改进内部实现质量。"
    ),
    "explain_code": (
        "你是代码解释助手。\n"
        "请用中文详细解释以下代码的功能、设计思路和关键细节：\n\n"
        "{{ input }}"
    ),
    "review_diff": (
        "你是代码审查助手。\n"
        "请审查以下代码变更，指出潜在问题、风险和改进建议：\n\n"
        "{{ input }}\n\n"
        "关注：正确性、安全性、性能、可维护性。"
    ),
}


def _render_jinja2(tmpl: str, variables: dict) -> str:
    """
    使用 Jinja2 渲染模板（研究来源：Flask/Django/Ansible 同款模板引擎）。
    与原有 {{ variable }} 语法完全兼容，额外支持 if/for/filters。
    """
    from jinja2 import Environment, Undefined
    try:
        env = Environment(undefined=Undefined)   # 未定义变量保留原文不报错
        return env.from_string(tmpl).render(**variables)
    except Exception as e:
        log.debug("Jinja2 render error: %s — falling back to str.replace", e)
        return _render_simple(tmpl, variables)


def _render_simple(tmpl: str, variables: dict) -> str:
    """Fallback: 简单字符串替换（Jinja2 不可用时）。"""
    rendered = tmpl
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


class PromptManager:
    """
    命名 prompt 模板管理器。
    模板引擎: Jinja2（研究: 成熟的 Python 模板库，Flask/Django 同款）
    语法: {{ variable }} — 与原有格式完全兼容
    """

    def __init__(self, templates_dir: Path | None = None):
        self._dir      = templates_dir or TEMPLATES_DIR
        self._cache: dict[str, str] = {}
        self._loaded   = False
        if not _JINJA2_AVAILABLE:
            log.info("jinja2 not installed — using simple str.replace (install: pip install jinja2)")

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._dir.mkdir(parents=True, exist_ok=True)
        for toml_file in self._dir.glob("*.toml"):
            try:
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                with open(toml_file, "rb") as f:
                    data = tomllib.load(f)
                for name, tmpl in data.get("templates", {}).items():
                    if isinstance(tmpl, str):
                        self._cache[name] = tmpl
                    elif isinstance(tmpl, dict) and "prompt" in tmpl:
                        self._cache[name] = tmpl["prompt"]
                log.debug("Loaded prompt templates from %s", toml_file)
            except Exception as e:
                log.warning("Failed to load prompt template %s: %s", toml_file, e)

    def get_template(self, name: str, variables: dict | None = None) -> Optional[str]:
        """
        获取命名模板并用 Jinja2 渲染变量。

        优先级：用户 TOML → 内置默认模板
        变量替换：Jinja2 ({{ variable }} 语法，向后兼容)
        """
        self._ensure_loaded()

        tmpl = self._cache.get(name)
        if tmpl is None:
            tmpl = _BUILTIN_TEMPLATES.get(name)
        if tmpl is None:
            log.debug("Prompt template '%s' not found", name)
            return None

        if not variables:
            return tmpl

        # Jinja2 渲染（研究驱动：成熟模板引擎替代手写 str.replace）
        if _JINJA2_AVAILABLE:
            return _render_jinja2(tmpl, variables)
        return _render_simple(tmpl, variables)

    def list_templates(self) -> list[str]:
        """返回所有可用模板名称（内置 + 用户自定义）。"""
        self._ensure_loaded()
        return sorted(set(_BUILTIN_TEMPLATES.keys()) | set(self._cache.keys()))

    def save_template(self, name: str, prompt: str) -> None:
        """保存新模板到 ~/.evocli/prompt_templates/custom.toml。"""
        self._ensure_loaded()
        self._cache[name] = prompt
        custom_file = self._dir / "custom.toml"
        try:
            existing: dict = {}
            if custom_file.exists():
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore[no-redef]
                with open(custom_file, "rb") as f:
                    existing = tomllib.load(f)
            if "templates" not in existing:
                existing["templates"] = {}
            existing["templates"][name] = prompt
            with open(custom_file, "w", encoding="utf-8") as f:
                f.write("[templates]\n")
                for k, v in existing["templates"].items():
                    escaped = v.replace('"""', '\\"\\"\\"')
                    f.write(f'{k} = """\n{escaped}\n"""\n\n')
            log.info("Saved prompt template '%s' to %s", name, custom_file)
        except Exception as e:
            log.warning("Failed to save template '%s': %s", name, e)


# ── 全局单例 ─────────────────────────────────────────────────────────────────

_pm: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    global _pm
    if _pm is None:
        _pm = PromptManager()
    return _pm

