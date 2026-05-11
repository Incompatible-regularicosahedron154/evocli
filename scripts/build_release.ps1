#!/usr/bin/env pwsh
# build_release.ps1 — EvoCLI release build pipeline
# Usage: .\scripts\build_release.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  EvoCLI Release Build" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: cargo check ──────────────────────────────────────────
Write-Host "[1/3] cargo check..." -ForegroundColor Yellow
Push-Location $Root
try {
    cargo check 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: cargo check failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK" -ForegroundColor Green
} finally {
    Pop-Location
}

# ── Step 2: cargo test ───────────────────────────────────────────
Write-Host ""
Write-Host "[2/3] cargo test..." -ForegroundColor Yellow
Push-Location $Root
try {
    cargo test --workspace 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: cargo test failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK" -ForegroundColor Green
} finally {
    Pop-Location
}

# ── Step 3: cargo build --release ────────────────────────────────
Write-Host ""
Write-Host "[3/3] cargo build --release..." -ForegroundColor Yellow
Push-Location $Root
try {
    cargo build --release 2>&1 | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: cargo build --release failed" -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK" -ForegroundColor Green
} finally {
    Pop-Location
}

# ── Summary ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Build Complete!" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan

$BinPath = Join-Path $Root "target\release\evocli.exe"
if (Test-Path $BinPath) {
    $Size = (Get-Item $BinPath).Length
    $SizeMB = [math]::Round($Size / 1MB, 2)
    Write-Host ""
    Write-Host "  Binary: $BinPath" -ForegroundColor White
    Write-Host "  Size:   $SizeMB MB" -ForegroundColor White
} else {
    # Unix
    $BinPath = Join-Path $Root "target/release/evocli"
    if (Test-Path $BinPath) {
        $Size = (Get-Item $BinPath).Length
        $SizeMB = [math]::Round($Size / 1MB, 2)
        Write-Host ""
        Write-Host "  Binary: $BinPath" -ForegroundColor White
        Write-Host "  Size:   $SizeMB MB" -ForegroundColor White
    }
}

Write-Host ""
