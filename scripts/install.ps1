# install.ps1 — EvoCLI 一键安装脚本 (Windows)
#
# 用法（推荐，PowerShell 直接运行）：
#   irm https://raw.githubusercontent.com/bambooqj/evocli/main/scripts/install.ps1 | iex
#
# 本地运行：
#   .\install.ps1 [-Version v0.1.0] [-InstallDir ~\.evocli\app] [-Yes]
#
# 环境变量：
#   EVOCLI_VERSION        指定版本（默认 latest）
#   EVOCLI_INSTALL_DIR    安装目录（默认 %USERPROFILE%\.evocli\app）
#   EVOCLI_NO_MODIFY_PATH 设为 1 则不修改用户 PATH

param(
    [string]$Version    = $env:EVOCLI_VERSION,
    [string]$InstallDir = $env:EVOCLI_INSTALL_DIR,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$REPO = "bambooqj/evocli"

# ── 默认值 ─────────────────────────────────────────────────────────────
if (-not $Version)    { $Version    = "latest" }
if (-not $InstallDir) { $InstallDir = "$env:USERPROFILE\.evocli\app" }

# ── 横幅 ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━ EvoCLI Installer (Windows) ━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

function ok   { param($msg) Write-Host "  $([char]0x2713)  $msg" -ForegroundColor Green }
function info { param($msg) Write-Host "  ->  $msg" -ForegroundColor Yellow }
function warn { param($msg) Write-Host "  !   $msg" -ForegroundColor Yellow }
function die  { param($msg) Write-Host "`n  X  ERROR: $msg`n" -ForegroundColor Red; exit 1 }

# ── Step 1: 获取版本信息 ────────────────────────────────────────────────
Write-Host "[1/5] Resolving version..." -ForegroundColor Yellow
if ($Version -eq "latest") {
    info "Fetching latest release from GitHub..."
    try {
        $releaseInfo = Invoke-RestMethod "https://api.github.com/repos/$REPO/releases/latest" -ErrorAction Stop
        $Version = $releaseInfo.tag_name
    } catch {
        die "Failed to reach GitHub API: $_`nCheck your network connection."
    }
    if (-not $Version) { die "Could not parse release version from GitHub API." }
}
ok "Version: $Version"

# ── Step 2: 检测平台 ────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/5] Detecting platform..." -ForegroundColor Yellow

# Windows 只支持 x86_64
$Arch = (Get-WmiObject -Class Win32_Processor -Property AddressWidth -ErrorAction SilentlyContinue).AddressWidth
$PLATFORM = "windows-x86_64"
ok "Platform: $PLATFORM"

# ── Step 3: 下载 ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/5] Downloading evocli $Version..." -ForegroundColor Yellow

$VER_NUM   = $Version.TrimStart('v')
$PKG_NAME  = "evocli-v$VER_NUM-$PLATFORM"
$PKG_FILE  = "$PKG_NAME.zip"
$DOWNLOAD_URL = "https://github.com/$REPO/releases/download/$Version/$PKG_FILE"

$TmpDir = [System.IO.Path]::GetTempPath() + "evocli-install-" + [System.IO.Path]::GetRandomFileName()
New-Item -ItemType Directory -Path $TmpDir | Out-Null

try {
    info "URL: $DOWNLOAD_URL"
    Invoke-WebRequest -Uri $DOWNLOAD_URL -OutFile "$TmpDir\$PKG_FILE" -UseBasicParsing
    ok "Downloaded $PKG_FILE"
} catch {
    Remove-Item -LiteralPath $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
    die "Download failed: $_`nCheck the URL or specify -Version manually."
}

# ── Step 4: 解压 & 安装 ─────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/5] Installing..." -ForegroundColor Yellow

Expand-Archive -Path "$TmpDir\$PKG_FILE" -DestinationPath $TmpDir -Force
$Extracted = "$TmpDir\$PKG_NAME"
if (-not (Test-Path $Extracted)) {
    Remove-Item -LiteralPath $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
    die "Unexpected archive structure. Expected folder: $PKG_NAME"
}

# 创建安装目录
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# 拷贝二进制
Copy-Item "$Extracted\evocli.exe" "$InstallDir\evocli.exe" -Force
ok "Binary installed: $InstallDir\evocli.exe"

# 拷贝 Python Soul
$SoulDst = "$InstallDir\evocli-soul"
if (Test-Path $SoulDst) { Remove-Item -LiteralPath $SoulDst -Recurse -Force }
Copy-Item "$Extracted\evocli-soul" $SoulDst -Recurse -Force
ok "Python Soul installed: $SoulDst"

# 拷贝辅助脚本
foreach ($f in @("setup.ps1", "setup_env.py", "download_models.py", "preflight.py")) {
    $src = "$Extracted\$f"
    if (Test-Path $src) { Copy-Item $src "$InstallDir\$f" -Force }
}

# 清理临时文件
Remove-Item -LiteralPath $TmpDir -Recurse -Force -ErrorAction SilentlyContinue

# 运行 Python 环境 setup
info "Setting up Python environment (first run: 2-5 min)..."
try {
    & "$InstallDir\setup.ps1"
    if ($LASTEXITCODE -ne 0) { throw "setup.ps1 exited with code $LASTEXITCODE" }
} catch {
    warn "setup.ps1 encountered an error — run manually: $InstallDir\setup.ps1"
    warn "Error: $_"
}

# ── Step 5: PATH 配置 ───────────────────────────────────────────────────
Write-Host ""
Write-Host "[5/5] Configuring PATH..." -ForegroundColor Yellow

$CurrentPath = [System.Environment]::GetEnvironmentVariable("Path", "User") ?? ""
$PathParts   = $CurrentPath -split ";" | Where-Object { $_ -ne "" }

if ($PathParts -contains $InstallDir) {
    ok "$InstallDir is already in user PATH"
} elseif ($env:EVOCLI_NO_MODIFY_PATH -eq "1") {
    warn "Skipping PATH modification (EVOCLI_NO_MODIFY_PATH=1)"
    warn "Add manually: [Environment]::SetEnvironmentVariable('Path', `$env:Path + ';$InstallDir', 'User')"
} else {
    $NewPath = ($PathParts + $InstallDir) -join ";"
    [System.Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    $env:Path = "$env:Path;$InstallDir"
    ok "Added $InstallDir to user PATH"
    ok "PATH updated for current session"
}

# ── 完成 ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  [OK]  EvoCLI $Version installed!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    evocli init    <- configure LLM provider + API key"
Write-Host "    evocli doctor  <- verify installation"
Write-Host "    evocli         <- start AI coding session"
Write-Host ""
Write-Host "  To uninstall:" -ForegroundColor Gray
Write-Host "    irm https://raw.githubusercontent.com/$REPO/main/scripts/uninstall.ps1 | iex" -ForegroundColor Gray
Write-Host ""
