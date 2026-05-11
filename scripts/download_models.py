#!/usr/bin/env python3
"""
EvoCLI — Embedding Model Pre-download Script

Pre-caches jinaai/jina-embeddings-v2-base-zh so EvoCLI starts instantly.
Run this script once after installation:

    python download_models.py

Chinese users: set HF_ENDPOINT=https://hf-mirror.com for faster download.
The script sets this mirror automatically if HF_ENDPOINT is not already set.
"""
from __future__ import annotations

import io
import os
import sys
import pathlib
import importlib.util
import time

# Force UTF-8 stdout so checkmarks / Chinese text render correctly on Windows GBK terminals.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# ── HuggingFace mirror（国内加速，未设置时自动使用）──────────────────────
_DEFAULT_MIRROR = "https://hf-mirror.com"
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = _DEFAULT_MIRROR
    _using_mirror = True
else:
    _using_mirror = False

MODEL_NAME = "jinaai/jina-embeddings-v2-base-zh"
CACHE_DIR  = str(pathlib.Path.home() / ".evocli" / "models")
SIZE_HINT  = "~570 MB"

def _check_deps() -> bool:
    for pkg in ("fastembed", "lancedb"):
        if importlib.util.find_spec(pkg) is None:
            print(f"  [FAIL]  {pkg} not installed — run setup.ps1 / setup.sh first")
            return False
    return True

def _is_cached() -> bool:
    """Quick heuristic: check if any ONNX file exists under cache dir."""
    cache = pathlib.Path(CACHE_DIR)
    return any(cache.rglob("*.onnx")) if cache.exists() else False

def main() -> int:
    print()
    print("=== EvoCLI Embedding Model Download ===")
    print(f"  Model : {MODEL_NAME}")
    print(f"  Cache : {CACHE_DIR}")
    print(f"  Mirror: {os.environ['HF_ENDPOINT']}"
          + (" (auto, for China)" if _using_mirror else ""))
    print()

    if not _check_deps():
        return 1

    if _is_cached():
        print("  Model already cached — verifying...")
    else:
        print(f"  Downloading {SIZE_HINT}... (this is a one-time operation)")
        if _using_mirror:
            print("  Tip: if download is slow, set  HF_ENDPOINT=https://hf-mirror.com")

    t0 = time.monotonic()
    try:
        from fastembed import TextEmbedding   # noqa: PLC0415

        # Instantiating TextEmbedding downloads + caches the model automatically.
        model = TextEmbedding(MODEL_NAME, cache_dir=CACHE_DIR)

        # Quick smoke-test: embed one sentence to confirm the model works.
        _ = list(model.embed(["hello world"]))

        elapsed = time.monotonic() - t0
        print(f"  [OK]  Model ready ({elapsed:.0f}s)")
        print()
        return 0

    except KeyboardInterrupt:
        print("\n  Download interrupted. Run this script again to resume.")
        return 1
    except Exception as exc:
        print(f"  [FAIL]  Download failed: {exc}")
        print()
        print("  Troubleshooting:")
        print("    China users:  set env HF_ENDPOINT=https://hf-mirror.com")
        print("    Offline:      copy model files to " + CACHE_DIR)
        print("    Skip:         EvoCLI works without vector memory (text search only)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
