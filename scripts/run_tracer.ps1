#!/usr/bin/env pwsh
# EvoCLI Tracer Bullet 运行脚本
# 用途：快速验证 Rust ↔ Python 通信链路，不需要完整构建

param(
    [string]$ApiKey  = $env:OPENAI_API_KEY,
    [string]$Model   = "gpt-4o-mini"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

function Write-Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-OK($msg)       { Write-Host "    ✅ $msg" -ForegroundColor Green }
function Write-Fail($msg)     { Write-Host "    ❌ $msg" -ForegroundColor Red; exit 1 }

Write-Host "`n🚀 EvoCLI Tracer Bullet (Dev Mode)" -ForegroundColor Yellow
Write-Host "   Root: $Root"
Write-Host "   Model: $Model"
if ($ApiKey) { Write-Host "   API Key: $($ApiKey.Substring(0,8))..." } 
else         { Write-Host "   API Key: (none — mock mode)" -ForegroundColor DarkYellow }

# ─── 1. Python 环境检查 ──────────────────────────────────────
Write-Step "1/4" "检查 Python 环境"

$python = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) { Write-Fail "找不到 Python，请安装 Python 3.10+" }
Write-OK "Python: $($python.Source)"

$pyver = & $python.Source --version 2>&1
Write-OK "版本: $pyver"

# ─── 2. 安装 Python 依赖 ────────────────────────────────────
Write-Step "2/4" "安装 Python Soul 依赖（uv）"

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "    安装 uv..." -ForegroundColor DarkYellow
    & pip install uv -q
}

$soulDir = Join-Path $Root "evocli-soul"
Write-Host "    uv pip install -e $soulDir ..."

# 仅安装核心验证依赖（不安装所有大型包）
$tracer_deps = @(
    "litellm",
    "lancedb",     # ← 关键：原生扩展测试
    "pydantic>=2.10"
)
foreach ($dep in $tracer_deps) {
    Write-Host "    安装 $dep ..." -NoNewline
    & uv pip install $dep -q 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host " ✓" -ForegroundColor Green }
    else                      { Write-Host " ❌" -ForegroundColor Red; Write-Fail "安装 $dep 失败" }
}

# 安装 mem0 / smolagents / langgraph 等（可选，失败不阻断）
$optional_deps = @("mem0", "smolagents", "langgraph", "pydantic-ai", "sentence-transformers")
foreach ($dep in $optional_deps) {
    Write-Host "    安装 $dep (可选) ..." -NoNewline
    & uv pip install $dep -q 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host " ✓" -ForegroundColor Green }
    else                      { Write-Host " 跳过" -ForegroundColor DarkYellow }
}

# ─── 3. 编译 Rust Host ──────────────────────────────────────
Write-Step "3/4" "编译 Rust Host（dev 模式）"

Set-Location $Root

# 为 Tracer Bullet 临时简化 Cargo.toml（跳过尚未实现的 crate）
$buildResult = & cargo build -p evocli 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $buildResult -ForegroundColor Red
    Write-Fail "Rust 编译失败（见上方错误）"
}
Write-OK "编译成功：target/debug/evocli"

# ─── 4. 运行 Tracer Bullet ─────────────────────────────────
Write-Step "4/4" "运行端到端 Tracer Bullet"
Write-Host ""

$env:EVOCLI_SOUL  = Join-Path $Root "evocli-soul/evocli_soul/main.py"
$env:EVOCLI_MODEL = $Model
if ($ApiKey) { $env:OPENAI_API_KEY = $ApiKey }

& "$Root/target/debug/evocli"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n🎉 Tracer Bullet 全部通过！" -ForegroundColor Green
    Write-Host "   下一步：运行 scripts/test_pyapp.ps1 验证 PyApp 打包" -ForegroundColor Cyan
} else {
    Write-Fail "Tracer Bullet 失败，请查看上方错误"
}
