#!/usr/bin/env python3
"""
EvoCLI Environment Pre-flight Verification

Tests every critical dependency and returns exit code 0 if everything is healthy,
or 1 with a detailed report of what failed and how to fix it.

Used by:
  - setup.ps1 / setup.sh  (after install, verifies environment before "Setup complete")
  - evocli doctor         (runtime health check)
  - Manual run            python preflight.py
"""
from __future__ import annotations

import io
import sys

# Force UTF-8 output on Windows GBK terminals.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SEP = "-" * 60


# ── Individual check functions (must be defined before CHECKS list) ──────────

def _check_model_cached() -> None:
    import pathlib
    cache = pathlib.Path.home() / ".evocli" / "models"
    # Check for both required models
    onnx_files = list(cache.rglob("*.onnx"))
    if not onnx_files:
        raise FileNotFoundError(
            f"Embedding models not cached in {cache}. "
            "Run: python download_models.py"
        )
    # Warn if code model specifically is missing (text model may exist from older installs)
    model_dirs = [p.parent.name for p in onnx_files]
    has_code_model = any("code" in d for d in model_dirs)
    if not has_code_model:
        raise FileNotFoundError(
            f"Code embedding model (jina-v2-base-code) not found in {cache}. "
            "Run: python download_models.py  (adds ~160MB for code search)"
        )

def _check_scipy() -> None:
    import scipy
    from scipy.sparse import csr_matrix
    csr_matrix((3, 3))   # exercises the C extension module

def _check_numpy() -> None:
    import numpy
    numpy.array([1.0])

def _check_fastembed() -> None:
    from fastembed import TextEmbedding  # noqa: F401


# ── Check registry ────────────────────────────────────────────────────────────

ALIYUN = "https://mirrors.aliyun.com/pypi/simple/"

CHECKS = [
    # (label, check, fix_hint)
    ("litellm",      "import litellm",                    "uv pip install 'litellm>=1.83'"),
    ("pydantic-ai",  "import pydantic_ai",                "uv pip install 'pydantic-ai>=0.0.46'"),
    ("langgraph",    "import langgraph",                  "uv pip install 'langgraph>=0.3'"),
    ("numpy",        _check_numpy,
                     f"uv pip install --force-reinstall --index-url {ALIYUN} 'numpy>=1.26,<3'"),
    ("scipy",        _check_scipy,
                     f"uv pip install --force-reinstall --index-url {ALIYUN} 'scipy>=1.11,<2'"),
    ("onnxruntime",  "import onnxruntime",                "uv pip install 'onnxruntime>=1.19,<2'"),
    ("fastembed",    _check_fastembed,                    "uv pip install 'fastembed>=0.4,<0.9'"),
    ("lancedb",      "import lancedb",                    "uv pip install 'lancedb>=0.5,<0.35'"),
    ("networkx",     "import networkx; networkx.Graph()", "uv pip install 'networkx>=3.0'"),
    ("jedi",         "import jedi",                       "uv pip install 'jedi>=0.19'"),
    ("embed_model",  _check_model_cached,                 "python download_models.py"),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def _run_check(check) -> tuple[bool, str]:
    try:
        if callable(check):
            check()
        else:
            exec(check, {})  # noqa: S102
        return True, ""
    except Exception as exc:
        return False, str(exc).split("\n")[0][:120]


def main() -> int:
    print()
    print("=== EvoCLI Environment Preflight ===")
    print(SEP)

    failures: list[tuple[str, str, str]] = []

    for label, check, fix_hint in CHECKS:
        ok, err = _run_check(check)
        if ok:
            print(f"  [OK]   {label}")
        else:
            print(f"  [FAIL] {label}  --  {err}")
            failures.append((label, err, fix_hint))

    print(SEP)

    if not failures:
        print("  All checks passed -- environment is healthy.")
        print()
        return 0

    print(f"  {len(failures)} check(s) failed:")
    print()
    for label, err, fix_hint in failures:
        print(f"  [{label}]")
        print(f"    Error : {err}")
        print(f"    Fix   : {fix_hint}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
