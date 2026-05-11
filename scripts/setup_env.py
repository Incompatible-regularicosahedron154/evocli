#!/usr/bin/env python3
"""
EvoCLI Environment Setup  —  cross-platform, mirror-aware, self-healing.

Handles everything in one pass:
  1. Probe PyPI mirrors → pick fastest reachable
  2. Install all dependencies via uv
  3. Probe HuggingFace mirrors → pick fastest reachable
  4. Download embedding model
  5. Run preflight checks — auto-repair if any fail

Usage:
  python setup_env.py                   # full setup
  python setup_env.py --verify-only     # skip install/download, only verify
  python setup_env.py --skip-model      # skip model download step

Compatible with: Windows 10+, macOS 12+, Linux (glibc 2.17+)
"""
from __future__ import annotations

import argparse
import io
import os
import pathlib
import platform
import shutil
import socket
import subprocess
import sys
import time
from typing import Optional

# ── UTF-8 output (Windows GBK fix) ───────────────────────────────────────────
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

IS_WIN   = platform.system() == "Windows"
SEP      = "=" * 62
THIN_SEP = "-" * 62

# ── Mirror lists (ordered by expected priority) ───────────────────────────────

PYPI_MIRRORS = [
    ("PyPI (official)",     "pypi.org",                                        "https://pypi.org/simple/"),
    ("Aliyun",              "mirrors.aliyun.com",                              "https://mirrors.aliyun.com/pypi/simple/"),
    ("Tsinghua TUNA",       "pypi.tuna.tsinghua.edu.cn",                       "https://pypi.tuna.tsinghua.edu.cn/simple/"),
    ("Huawei Cloud",        "mirrors.huaweicloud.com",                         "https://mirrors.huaweicloud.com/repository/pypi/simple/"),
    ("USTC",                "pypi.mirrors.ustc.edu.cn",                        "https://pypi.mirrors.ustc.edu.cn/simple/"),
]

HF_MIRRORS = [
    ("HuggingFace (official)", "huggingface.co",  "https://huggingface.co"),
    ("hf-mirror.com",          "hf-mirror.com",   "https://hf-mirror.com"),
]

# ── TCP latency probe ─────────────────────────────────────────────────────────

def _tcp_latency(host: str, port: int = 443, timeout: float = 3.0) -> Optional[float]:
    """Return TCP round-trip time in seconds, or None if unreachable."""
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return time.monotonic() - t0
    except Exception:
        return None


def pick_fastest(mirrors: list[tuple[str, str, str]], label: str) -> str:
    """Probe all mirrors in parallel-ish order, return URL of fastest reachable one."""
    print(f"\n  Probing {label} mirrors...")
    best_url   = mirrors[0][2]   # fallback
    best_ms    = float("inf")

    for name, host, url in mirrors:
        ms = _tcp_latency(host)
        if ms is None:
            print(f"    {name:<28} unreachable")
        else:
            tag = " (selected)" if ms < best_ms else ""
            print(f"    {name:<28} {ms*1000:>6.0f} ms{tag}")
            if ms < best_ms:
                best_ms  = ms
                best_url = url

    selected = next(n for n, h, u in mirrors if u == best_url)
    print(f"  -> Using: {selected}  ({best_url})")
    return best_url


# ── uv location ──────────────────────────────────────────────────────────────

def _find_or_install_uv() -> str:
    """Return path to uv, installing it into ~/.evocli/bin if not found."""
    # 1. Already in PATH?
    uv = shutil.which("uv")
    if uv:
        return uv

    # 2. In our managed bin dir?
    home = pathlib.Path.home()
    bin_dir = home / ".evocli" / "bin"
    managed = bin_dir / ("uv.exe" if IS_WIN else "uv")
    if managed.exists():
        return str(managed)

    # 3. Install via official installer
    print("\n  uv not found — installing via official installer...")
    bin_dir.mkdir(parents=True, exist_ok=True)

    if IS_WIN:
        # PowerShell one-liner
        ps_cmd = (
            f'$env:UV_INSTALL_DIR="{bin_dir}"; '
            "irm https://astral.sh/uv/install.ps1 | iex"
        )
        subprocess.run(["powershell", "-Command", ps_cmd], check=True)
    else:
        curl_cmd = (
            f'UV_INSTALL_DIR="{bin_dir}" '
            "curl -fsSL https://astral.sh/uv/install.sh | sh"
        )
        subprocess.run(["sh", "-c", curl_cmd], check=True)

    if not managed.exists():
        raise RuntimeError(
            "uv installation failed. Please install manually: "
            "https://docs.astral.sh/uv/getting-started/installation/"
        )
    print(f"  uv installed: {managed}")
    return str(managed)


# ── Python / venv ─────────────────────────────────────────────────────────────

def _venv_python() -> str:
    home    = pathlib.Path.home()
    venv    = home / ".evocli" / "venv"
    python  = venv / ("Scripts/python.exe" if IS_WIN else "bin/python3")
    return str(python)


def ensure_venv(uv: str) -> str:
    python = _venv_python()
    venv   = pathlib.Path(python).parent.parent
    if pathlib.Path(python).exists():
        print(f"  venv already exists: {venv}")
        return python
    print(f"  Creating Python 3.11 venv at {venv}...")
    subprocess.run(
        [uv, "venv", str(venv), "--python", "3.11", "--seed"],
        check=True,
    )
    print(f"  venv created: {python}")
    return python


# ── Package installation ──────────────────────────────────────────────────────

def install_packages(uv: str, python: str, pypi_url: str, soul_dir: pathlib.Path) -> None:
    print(f"\n  Installing evocli-soul (all features)...")
    print(f"  Source: {pypi_url}")
    cmd = [
        uv, "pip", "install",
        "--python", python,
        "--index-url", pypi_url,
        "-e", str(soul_dir),
    ]
    subprocess.run(cmd, check=True)
    print("  Packages installed.")


# ── Model download ────────────────────────────────────────────────────────────

def download_model(python: str, hf_url: str, script_dir: pathlib.Path) -> None:
    dl_script = script_dir / "download_models.py"
    if not dl_script.exists():
        print("  download_models.py not found — skipping.")
        return

    env = os.environ.copy()
    env["HF_ENDPOINT"] = hf_url
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run([python, str(dl_script)], env=env)
    if result.returncode != 0:
        print("  [WARN] Model download failed. Re-run: python download_models.py")


# ── Preflight verification ────────────────────────────────────────────────────

def verify(python: str, script_dir: pathlib.Path, auto_repair: bool, pypi_url: str, uv: str) -> bool:
    pf = script_dir / "preflight.py"
    if not pf.exists():
        print("  preflight.py not found — skipping verification.")
        return True

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([python, str(pf)], env=env)

    if result.returncode == 0:
        return True

    if not auto_repair:
        return False

    print("\n  Auto-repairing broken packages...")
    repair_pkgs = [
        "scipy>=1.11", "numpy>=1.26", "onnxruntime>=1.19",
        "lancedb>=0.5", "fastembed>=0.4",
    ]
    subprocess.run(
        [uv, "pip", "install", "--force-reinstall",
         "--python", python,
         "--index-url", pypi_url]
        + repair_pkgs,
    )
    result2 = subprocess.run([python, str(pf)], env=env)
    return result2.returncode == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="EvoCLI environment setup")
    ap.add_argument("--verify-only",  action="store_true", help="Only run preflight, skip install/download")
    ap.add_argument("--skip-model",   action="store_true", help="Skip embedding model download")
    ap.add_argument("--no-repair",    action="store_true", help="Don't auto-repair on verify failure")
    args = ap.parse_args()

    script_dir = pathlib.Path(__file__).parent.resolve()
    soul_dir   = script_dir.parent / "evocli-soul"   # dev checkout layout
    if not soul_dir.exists():
        soul_dir = script_dir.parent                  # dist layout: pyproject.toml is sibling

    print()
    print(SEP)
    print("  EvoCLI Environment Setup")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Python   : {sys.version.split()[0]}")
    print(SEP)

    if args.verify_only:
        python = _venv_python()
        ok = verify(python, script_dir, not args.no_repair, PYPI_MIRRORS[0][2], "uv")
        return 0 if ok else 1

    # ── Step 1: Mirror selection ───────────────────────────────────────────
    print("\n[1/4] Selecting fastest mirrors...")
    pypi_url = pick_fastest(PYPI_MIRRORS, "PyPI")
    hf_url   = pick_fastest(HF_MIRRORS,   "HuggingFace")

    # ── Step 2: uv + venv + packages ──────────────────────────────────────
    print("\n[2/4] Setting up Python environment...")
    uv     = _find_or_install_uv()
    python = ensure_venv(uv)
    install_packages(uv, python, pypi_url, soul_dir)

    # ── Step 3: Embedding model ────────────────────────────────────────────
    if not args.skip_model:
        print("\n[3/4] Pre-downloading embedding model...")
        download_model(python, hf_url, script_dir)
    else:
        print("\n[3/4] Skipping model download (--skip-model).")

    # ── Step 4: Verify ────────────────────────────────────────────────────
    print("\n[4/4] Verifying environment...")
    ok = verify(python, script_dir, not args.no_repair, pypi_url, uv)

    print()
    print(SEP)
    if ok:
        print("  Setup complete — environment is healthy.")
        print()
        print("  Next steps:")
        print("    evocli init    <- configure LLM provider + API key")
        print("    evocli doctor  <- full health check")
        print("    evocli         <- start AI coding session")
    else:
        print("  Setup finished with warnings. Run: python preflight.py")
    print(SEP)
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
