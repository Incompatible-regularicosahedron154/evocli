#!/usr/bin/env python3
"""
EvoCLI — Embedding Model Pre-download Script

Downloads two embedding models optimized for CPU inference (ONNX int8 quantized):

  1. jinaai/jina-embeddings-v2-base-zh  (~137MB)
     用于：项目记忆检索 / 工具路由意图分类 / Agent 意图识别
     中英双语，已在 memory_client 使用

  2. jinaai/jina-embeddings-v2-base-code  (~160MB)
     用于：代码语义搜索（code_semantic_search 工具）
     专为代码设计，支持 30+ 编程语言，8192 token 上下文

总下载量：约 300MB（仅首次，之后直接从缓存加载）

运行方式：
    python download_models.py

中国用户：设置 HF_ENDPOINT=https://hf-mirror.com 加速下载（脚本自动设置）
"""
from __future__ import annotations

import io
import os
import sys
import pathlib
import importlib.util
import time

# Force UTF-8 stdout
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ── HuggingFace mirror（国内加速）────────────────────────────────────────────
_DEFAULT_MIRROR = "https://hf-mirror.com"
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = _DEFAULT_MIRROR
    _using_mirror = True
else:
    _using_mirror = False

CACHE_DIR = str(pathlib.Path.home() / ".evocli" / "models")

# 两个需要下载的模型
MODELS = [
    {
        "name":  "jinaai/jina-embeddings-v2-base-zh",
        "size":  "~137MB",
        "desc":  "文本记忆 + 工具路由（中英双语）",
        "smoke": "今天天气不错",
    },
    {
        "name":  "jinaai/jina-embeddings-v2-base-code",
        "size":  "~160MB",
        "desc":  "代码语义搜索（30+ 编程语言，8192 token）",
        "smoke": "def authenticate(token: str) -> bool:",
    },
]


def _check_deps() -> bool:
    for pkg in ("fastembed", "lancedb"):
        if importlib.util.find_spec(pkg) is None:
            print(f"  [FAIL]  {pkg} not installed — run setup.ps1 / setup.sh first")
            return False
    return True


def _model_is_cached(model_name: str) -> bool:
    """Check if a specific model has ONNX files in cache."""
    cache = pathlib.Path(CACHE_DIR)
    if not cache.exists():
        return False
    # fastembed stores models in subdirectories named after the model
    model_tag = model_name.replace("/", "_").replace("-", "_").lower()
    for p in cache.rglob("*.onnx"):
        if model_tag in str(p).lower() or any(
            part in str(p).lower() for part in model_name.lower().split("/")
        ):
            return True
    return False


def _download_model(model_info: dict) -> bool:
    name  = model_info["name"]
    size  = model_info["size"]
    desc  = model_info["desc"]
    smoke = model_info["smoke"]

    cached = _model_is_cached(name)
    if cached:
        print(f"  [CACHED] {name}")
    else:
        print(f"  Downloading {name}  ({size}) — {desc}")

    try:
        from fastembed import TextEmbedding
        model = TextEmbedding(name, cache_dir=CACHE_DIR)
        _ = list(model.embed([smoke]))  # smoke test
        if not cached:
            print(f"  [OK]    {name} ready")
        return True
    except KeyboardInterrupt:
        print(f"\n  Download of {name} interrupted. Run again to resume.")
        raise
    except Exception as exc:
        print(f"  [FAIL]  {name}: {exc}")
        return False


def main() -> int:
    print()
    print("=" * 60)
    print("  EvoCLI Embedding Models Download")
    print("=" * 60)
    print(f"  Cache : {CACHE_DIR}")
    print(f"  Mirror: {os.environ['HF_ENDPOINT']}" +
          (" (auto, for China)" if _using_mirror else ""))
    print()

    if not _check_deps():
        return 1

    total_models = len(MODELS)
    success = 0
    t0 = time.monotonic()

    for i, model_info in enumerate(MODELS, 1):
        print(f"  [{i}/{total_models}] {model_info['desc']}")
        try:
            if _download_model(model_info):
                success += 1
        except KeyboardInterrupt:
            print("\n  Interrupted. Run again to resume (partial downloads are cached).")
            return 1
        print()

    elapsed = time.monotonic() - t0
    print(f"  Completed: {success}/{total_models} models ready  ({elapsed:.0f}s)")
    print()

    if success < total_models:
        print("  Troubleshooting:")
        print("    China users: export HF_ENDPOINT=https://hf-mirror.com")
        print("    Offline:     copy model files to " + CACHE_DIR)
        print("    Partial:     EvoCLI works without code model (text search only)")
        return 1

    print("  All models ready. EvoCLI can now:")
    print("    - Search code semantically (code_semantic_search tool)")
    print("    - Recall project memory in Chinese and English")
    print("    - Route tool selections by natural language intent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
