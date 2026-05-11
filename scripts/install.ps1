# install.ps1 — EvoCLI 一键安装脚本
param([string]$InstallDir = "$env:USERPROFILE\.local\bin")

$ErrorActionPreference = "Stop"
$BaseUrl = "https://github.com/evocli/releases/latest"

Write-Host "🚀 Installing EvoCLI..." -ForegroundColor Yellow

# Create install directory
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# Download latest binary (placeholder — replace with actual release URL)
Write-Host "Downloading evocli binary..."
# Invoke-WebRequest "$BaseUrl/evocli.exe" -OutFile "$InstallDir\evocli.exe"

Write-Host "Note: For now, build from source:" -ForegroundColor Yellow
Write-Host "  cd evocli && cargo build --release && copy target\release\evocli.exe $InstallDir"
Write-Host ""
Write-Host "Then install Python Soul:"
Write-Host "  pip install evocli-soul"
Write-Host "  evocli init"
