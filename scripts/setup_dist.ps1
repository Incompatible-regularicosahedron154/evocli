# setup.ps1 — EvoCLI Windows one-click environment setup
# Features: uv -> Python 3.11 venv -> evocli-soul dependencies
# All installed under ~/.evocli/ — no system Python pollution
#
# Usage:
#   .\setup.ps1            normal install (reuses existing venv)
#   .\setup.ps1 -Clean     clean venv and reinstall (preserves config/memory/skills)
#   .\setup.ps1 -Force     force reinstall all Python packages (fixes conflicts)

param(
    [switch]$Clean,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path $MyInvocation.MyCommand.Path -Parent
$SoulDir   = Join-Path $ScriptDir "evocli-soul"
$UvBin     = "$env:USERPROFILE\.evocli\bin\uv.exe"
$VenvDir   = "$env:USERPROFILE\.evocli\venv"

Write-Host ""
Write-Host "━━━ EvoCLI Environment Setup (Windows) ━━━━━━━━━━━━━━" -ForegroundColor Cyan
if ($Clean) { Write-Host "  Mode: CLEAN (rebuilding venv, user data preserved)" -ForegroundColor Yellow }
if ($Force) { Write-Host "  Mode: FORCE (reinstalling all packages)" -ForegroundColor Yellow }
Write-Host ""

# ── -Clean: remove venv only ──────────────────────────────────────────────────
# Preserved: ~/.evocli/config.toml, data/, memory/, skills/, sessions/
# Removed:   ~/.evocli/venv/ (Python environment — fully rebuildable)
if ($Clean -and (Test-Path $VenvDir)) {
    Write-Host "  Removing old venv (user data preserved)..." -ForegroundColor Yellow
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
    Write-Host "  ✓  Old venv removed" -ForegroundColor Green
    Write-Host ""
}

# ── Step 1: uv ────────────────────────────────────────────────────────────────
Write-Host "[1/5] Setting up uv (Rust-based Python manager)..." -ForegroundColor Yellow
$uvPath = (Get-Command uv -ErrorAction SilentlyContinue)?.Source
if ($uvPath) {
    Write-Host "  ✓  uv already in PATH: $uvPath" -ForegroundColor Green
} elseif (Test-Path $UvBin) {
    $uvPath = $UvBin
    Write-Host "  ✓  uv found at $uvPath" -ForegroundColor Green
} else {
    Write-Host "  → Downloading uv from GitHub releases..."
    New-Item -ItemType Directory -Force -Path (Split-Path $UvBin) | Out-Null
    $zipUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    $zipTmp = "$env:TEMP\uv-latest.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipTmp -UseBasicParsing
    Expand-Archive -Path $zipTmp -DestinationPath (Split-Path $UvBin) -Force
    Remove-Item $zipTmp -ErrorAction SilentlyContinue
    if (-not (Test-Path $UvBin)) {
        Write-Error "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    }
    $uvPath = $UvBin
    Write-Host "  ✓  uv installed: $uvPath" -ForegroundColor Green
}

# ── Step 2: Python 3.11 venv ──────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/5] Setting up Python 3.11 isolated environment..." -ForegroundColor Yellow
if (Test-Path "$VenvDir\Scripts\python.exe") {
    Write-Host "  ✓  venv exists: $VenvDir" -ForegroundColor Green
} else {
    Write-Host "  → Creating venv (uv will download Python 3.11 if needed)..."
    & $uvPath venv $VenvDir --python 3.11 --seed
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create venv" }
    Write-Host "  ✓  venv created: $VenvDir" -ForegroundColor Green
}

# ── Step 3: Install evocli-soul dependencies ──────────────────────────────────
Write-Host ""
Write-Host "[3/5] Installing evocli-soul[full] dependencies..." -ForegroundColor Yellow
Write-Host "  Source: $SoulDir" -ForegroundColor Gray
Write-Host "  Includes: litellm, pydantic-ai, lancedb, fastembed, scikit-learn" -ForegroundColor Gray

$installArgs = @("-e", "$SoulDir[full]", "--python", "$VenvDir\Scripts\python.exe")
if ($Force) {
    $installArgs += "--reinstall"
    Write-Host "  (Force reinstall — resolves package conflicts)" -ForegroundColor Gray
}

& $uvPath pip install @installArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  [full] install failed, trying core only..." -ForegroundColor Yellow
    & $uvPath pip install "-e" "$SoulDir" "--python" "$VenvDir\Scripts\python.exe"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Core installation failed. Try: .\setup.ps1 -Clean -Force"
    }
    Write-Host "  ✓  Core installed (some features may be limited)" -ForegroundColor Yellow
} else {
    Write-Host "  ✓  evocli-soul[full] installed" -ForegroundColor Green
}

# ── Step 4: Pre-download embedding model ──────────────────────────────────────
$VenvPython = "$VenvDir\Scripts\python.exe"
Write-Host ""
Write-Host "[4/5] Pre-downloading embedding model (~570 MB, one-time)..." -ForegroundColor Yellow
Write-Host "  Model  : jinaai/jina-embeddings-v2-base-zh (bilingual vector search)" -ForegroundColor Gray
Write-Host "  Mirror : hf-mirror.com (auto, better connectivity)" -ForegroundColor Gray
Write-Host "  Skip   : Ctrl+C to skip — EvoCLI works with text search" -ForegroundColor Gray
& $VenvPython "$ScriptDir\download_models.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ⚠  Model download failed — EvoCLI works with text search." -ForegroundColor Yellow
    Write-Host "     Retry: $VenvPython $ScriptDir\download_models.py" -ForegroundColor Gray
} else {
    Write-Host "  ✓  Embedding model cached — vector memory ready" -ForegroundColor Green
}

# ── Step 5: Verify ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Verifying environment..." -ForegroundColor Yellow
& $VenvPython "$ScriptDir\preflight.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  Auto-repairing broken packages..." -ForegroundColor Yellow
    & $uvPath pip install --reinstall `
        "scipy>=1.11,<2" "numpy>=1.26,<3" "onnxruntime>=1.19,<2" `
        "lancedb>=0.5,<0.35" "fastembed>=0.4,<0.9" `
        --python "$VenvDir\Scripts\python.exe"
    & $VenvPython "$ScriptDir\preflight.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN] Some checks still failing." -ForegroundColor Red
        Write-Host "         Try: .\setup.ps1 -Clean -Force" -ForegroundColor Gray
    } else {
        Write-Host "  [OK]  All checks passed after repair." -ForegroundColor Green
    }
} else {
    Write-Host "  [OK]  All dependencies verified." -ForegroundColor Green
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  ✅  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    .\evocli.exe init    <- select LLM provider + API key"
Write-Host "    .\evocli.exe doctor  <- verify all checks pass"
Write-Host "    .\evocli.exe         <- start AI coding session"
Write-Host ""
Write-Host "  Troubleshooting:"
Write-Host "    .\setup.ps1 -Clean        <- clean venv (keeps config/memory/skills)"
Write-Host "    .\setup.ps1 -Force        <- force reinstall all packages"
Write-Host "    .\setup.ps1 -Clean -Force <- full clean reinstall"
Write-Host ""
$uvPath = (Get-Command uv -ErrorAction SilentlyContinue)?.Source
if ($uvPath) {
    Write-Host "  ✓  uv already in PATH: $uvPath" -ForegroundColor Green
} elseif (Test-Path $UvBin) {
    $uvPath = $UvBin
    Write-Host "  ✓  uv found at $uvPath" -ForegroundColor Green
} else {
    Write-Host "  → Downloading uv from GitHub releases..."
    New-Item -ItemType Directory -Force -Path (Split-Path $UvBin) | Out-Null
    $zipUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    $zipTmp = "$env:TEMP\uv-latest.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipTmp -UseBasicParsing
    Expand-Archive -Path $zipTmp -DestinationPath (Split-Path $UvBin) -Force
    Remove-Item $zipTmp -ErrorAction SilentlyContinue
    if (-not (Test-Path $UvBin)) {
        Write-Error "uv installation failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    }
    $uvPath = $UvBin
    Write-Host "  ✓  uv installed: $uvPath" -ForegroundColor Green
}

# Step 2: Python 3.11 venv
Write-Host ""
Write-Host "[2/3] Setting up Python 3.11 isolated environment..." -ForegroundColor Yellow
if (Test-Path "$VenvDir\Scripts\python.exe") {
    Write-Host "  ✓  venv exists: $VenvDir" -ForegroundColor Green
} else {
    Write-Host "  → Creating venv (uv will download Python 3.11 if needed)..."
    & $uvPath venv $VenvDir --python 3.11 --seed
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create venv" }
    Write-Host "  ✓  venv created: $VenvDir" -ForegroundColor Green
}

# Step 3: Install evocli-soul[full] — 所有功能一次性安装
Write-Host ""
Write-Host "[3/4] Installing evocli-soul[full] (all features included)..." -ForegroundColor Yellow
Write-Host "  First run: may take 3-5 minutes (downloading ML models etc.)" -ForegroundColor Gray
Write-Host "  Includes: vector memory, code intelligence, skills, evolution" -ForegroundColor Gray
& $uvPath pip install -e "$SoulDir[full]" --python "$VenvDir\Scripts\python.exe"
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to install evocli-soul[full]" }
Write-Host "  ✓  evocli-soul[full] installed — all features ready" -ForegroundColor Green

# Step 4: Pre-download embedding model (jina-zh, ~570 MB, one-time)
# Uses hf-mirror.com automatically when HF_ENDPOINT is not set.
# If the download fails (no network / firewall), EvoCLI still starts with
# text-search fallback — the model can be downloaded later by re-running this step.
Write-Host ""
Write-Host "[4/4] Pre-downloading embedding model (~570 MB, one-time)..." -ForegroundColor Yellow
Write-Host "  Model  : jinaai/jina-embeddings-v2-base-zh (中英双语向量搜索)" -ForegroundColor Gray
Write-Host "  Mirror : hf-mirror.com  (auto-enabled for better connectivity)" -ForegroundColor Gray
Write-Host "  Re-run : .\download_models.py   to retry if interrupted" -ForegroundColor Gray
$VenvPython = "$VenvDir\Scripts\python.exe"
& $VenvPython "$ScriptDir\download_models.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host "" 
    Write-Host "  ⚠  Model download failed or skipped." -ForegroundColor Yellow
    Write-Host "     EvoCLI works now (text search). Re-run later:" -ForegroundColor Yellow
    Write-Host "     $VenvPython $ScriptDir\download_models.py" -ForegroundColor Gray
} else {
    Write-Host "  ✓  Embedding model cached — vector memory ready" -ForegroundColor Green
}

# Step 5: Verify environment — every critical import must succeed.
# On failure: auto-reinstall broken packages and re-verify.
Write-Host ""
Write-Host "[5/5] Verifying environment (all dependencies must pass)..." -ForegroundColor Yellow
& $VenvPython "$ScriptDir\preflight.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  Auto-repairing broken packages..." -ForegroundColor Yellow
    & $uvPath pip install --force-reinstall `
        "scipy>=1.11,<2" "numpy>=1.26,<3" "onnxruntime>=1.19,<2" `
        "lancedb>=0.5,<0.35" "fastembed>=0.4,<0.9" `
        --python "$VenvDir\Scripts\python.exe"
    & $VenvPython "$ScriptDir\preflight.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [WARN] Some checks still failing — see output above." -ForegroundColor Red
        Write-Host "         Run: .\preflight.py  to diagnose." -ForegroundColor Gray
    } else {
        Write-Host "  [OK]  All checks passed after repair." -ForegroundColor Green
    }
} else {
    Write-Host "  [OK]  All dependencies verified — environment is healthy." -ForegroundColor Green
}

# Done
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  ✅  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    .\evocli.exe init    <- select LLM provider + API key"
Write-Host "    .\evocli.exe doctor  <- verify all checks pass"
Write-Host "    .\evocli.exe         <- start AI coding session"
Write-Host ""
Write-Host "  Optional: add this folder to PATH for global access"
Write-Host ""
