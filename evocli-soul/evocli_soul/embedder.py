"""
embedder.py — 统一嵌入模型配置中心

设计原则：
  所有嵌入模型引用集中在这里，各模块只 import 这里的函数/常量。
  换模型只需改这一个文件。

当前模型选型（CPU-only，无需 GPU，ONNX int8 量化）：

  CODE_MODEL  = jina-embeddings-v2-base-code
    专为代码设计，支持 30+ 编程语言 + 8192 token 上下文。
    中文 query → 英文代码 跨语言检索效果最佳。
    fastembed ONNX int8 量化后约 160MB。

  TEXT_MODEL  = jina-embeddings-v2-base-zh
    中英双语，已在用户机器上（memory_client 已用）。
    覆盖：工具路由意图分类 + 项目记忆检索 + MemRouter 分类器。
    fastembed ONNX int8 量化后约 137MB。

  两模型都是 768 维，同 jina-v2 架构系列，LanceDB 表 schema 兼容。
  合计新增下载量：~160MB（jina-zh 已有，code 首次下载）。

配置说明（可在 config.toml 覆盖）：
  [embedder]
  code_model = "jinaai/jina-embeddings-v2-base-code"
  text_model = "jinaai/jina-embeddings-v2-base-zh"
  # 可换成其他 fastembed 支持的模型：
  # code_model = "BAAI/bge-base-en-v1.5"     # 更小 (109MB)，但不专注代码
  # text_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # 384-dim，更小
"""
from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

log = logging.getLogger("evocli.embedder")

# ── 模型配置 ─────────────────────────────────────────────────────────────────
# 可通过 config.toml [embedder] 节覆盖
CODE_MODEL_DEFAULT = "jinaai/jina-embeddings-v2-base-code"  # 768-dim, 代码专用
TEXT_MODEL_DEFAULT = "jinaai/jina-embeddings-v2-base-zh"    # 768-dim, 中英双语

EMBED_DIM_CODE = 768   # jina-v2-base-code 输出维度
EMBED_DIM_TEXT = 768   # jina-v2-base-zh  输出维度

# ── 模型缓存目录 ──────────────────────────────────────────────────────────────
_CACHE_DIR = str(Path.home() / ".evocli" / "models")

# ── 进程级模型缓存 ────────────────────────────────────────────────────────────
_code_embedder: Any = None
_text_embedder: Any = None


def _load_config() -> dict:
    """从 config.toml 读取 [embedder] 节覆盖值。"""
    try:
        from pathlib import Path as _Path
        import tomllib
        cfg_path = _Path.home() / ".evocli" / "config.toml"
        if cfg_path.exists():
            with open(cfg_path, "rb") as f:
                cfg = tomllib.load(f)
            return cfg.get("embedder", {})
    except Exception:
        pass
    return {}


def _get_model_name(key: str, default: str) -> str:
    cfg = _load_config()
    return cfg.get(key, default)


def get_code_embedder():
    """
    获取代码语义搜索嵌入器（进程级单例）。

    模型：jina-embeddings-v2-base-code（或 config.toml 覆盖值）
    用于：code_chunks 代码块向量化 + 语义搜索
    """
    global _code_embedder
    if _code_embedder is not None:
        return _code_embedder

    model_name = _get_model_name("code_model", CODE_MODEL_DEFAULT)
    try:
        from fastembed import TextEmbedding
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            _code_embedder = TextEmbedding(
                model_name=model_name,
                cache_dir=_CACHE_DIR,
            )
        log.info("Code embedder loaded: %s (%d-dim)", model_name, EMBED_DIM_CODE)
        return _code_embedder
    except Exception as e:
        log.warning("Code embedder failed to load (%s): %s — falling back to text embedder", model_name, e)
        return get_text_embedder()  # graceful fallback


def get_text_embedder():
    """
    获取通用文本嵌入器（进程级单例）。

    模型：jina-embeddings-v2-base-zh（或 config.toml 覆盖值）
    用于：
      - 项目记忆检索 (memory_client.py)
      - 工具路由意图分类 (local_classifier.py)
      - MemRouter 分类器 (metrics.py)
      - Agent 意图识别 (orchestrator.py)
    """
    global _text_embedder
    if _text_embedder is not None:
        return _text_embedder

    model_name = _get_model_name("text_model", TEXT_MODEL_DEFAULT)
    try:
        from fastembed import TextEmbedding
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            _text_embedder = TextEmbedding(
                model_name=model_name,
                cache_dir=_CACHE_DIR,
            )
        log.info("Text embedder loaded: %s (%d-dim)", model_name, EMBED_DIM_TEXT)
        return _text_embedder
    except Exception as e:
        log.warning("Text embedder failed to load (%s): %s", model_name, e)
        return None


def embed_code(text: str) -> list[float] | None:
    """代码内容嵌入（单条）。"""
    emb = get_code_embedder()
    if emb is None:
        return None
    try:
        vecs = list(emb.embed([text]))
        return list(vecs[0]) if vecs else None
    except Exception as e:
        log.debug("embed_code failed: %s", e)
        return None


def embed_text(text: str) -> list[float] | None:
    """通用文本嵌入（单条）。"""
    emb = get_text_embedder()
    if emb is None:
        return None
    try:
        vecs = list(emb.embed([text]))
        return list(vecs[0]) if vecs else None
    except Exception as e:
        log.debug("embed_text failed: %s", e)
        return None


def embed_texts(texts: list[str], use_code_model: bool = False) -> list[list[float]]:
    """批量嵌入，返回向量列表（空列表表示失败）。"""
    emb = get_code_embedder() if use_code_model else get_text_embedder()
    if emb is None:
        return []
    try:
        return [list(v) for v in emb.embed(texts)]
    except Exception as e:
        log.debug("embed_texts failed: %s", e)
        return []


def normalize_vector(vec: list[float], target_dim: int) -> list[float]:
    """将向量填充或截断到目标维度（用于 LanceDB schema 兼容）。"""
    if len(vec) > target_dim:
        return vec[:target_dim]
    elif len(vec) < target_dim:
        return vec + [0.0] * (target_dim - len(vec))
    return vec


def prefetch_models() -> None:
    """
    预加载两个嵌入模型（在后台 warm-up 时调用）。
    如果模型未下载，触发自动下载（约 300MB，仅首次）。
    """
    log.info("Pre-loading embedding models...")
    get_text_embedder()   # 先加载 text（已有，快）
    get_code_embedder()   # 再加载 code（首次需下载 ~160MB）
    log.info("Embedding models ready.")


def model_info() -> dict:
    """返回当前配置的模型信息（用于 doctor/stats 命令）。"""
    return {
        "code_model": _get_model_name("code_model", CODE_MODEL_DEFAULT),
        "text_model": _get_model_name("text_model", TEXT_MODEL_DEFAULT),
        "embed_dim_code": EMBED_DIM_CODE,
        "embed_dim_text": EMBED_DIM_TEXT,
        "cache_dir": _CACHE_DIR,
    }
