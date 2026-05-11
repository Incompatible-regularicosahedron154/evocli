# uninstall.ps1 — EvoCLI 卸载脚本 (Windows)
#
# 用法：
#   .\uninstall.ps1              # 交互确认后卸载（保留用户数据）
#   .\uninstall.ps1 -Purge       # 同时删除所有用户数据
#   .\uninstall.ps1 -Yes         # 跳过确认提示
#
# 远程运行：
#   irm https://raw.githubusercontent.com/bambooqj/evocli/main/scripts/uninstall.ps1 | iex
#
# 本脚本会删除：
#   - evocli.exe 二进制（从 PATH 或默认安装目录）
#   - %USERPROFILE%\.evocli\venv\         Python 虚拟环境
#   - %USERPROFILE%\.evocli\bin\          uv 包管理器
#   - %USERPROFILE%\.evocli\logs\         日志文件
#   - %USERPROFILE%\.evocli\models\       向量模型缓存（~570 MB）
#
# -Purge 额外删除（用户数据，不可恢复）：
#   - %USERPROFILE%\.evocli\config.toml
#   - %USERPROFILE%\.evocli\data\
#   - %USERPROFILE%\.evocli\skills\
#   - %USERPROFILE%\.evocli\sessions\
#   - %USERPROFILE%\.evocli\*.db
#   - %USERPROFILE%\.evocli\   (若已空)

param(
    [switch]$Purge,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$REPO        = "bambooqj/evocli"
$EvoCLIHome  = "$env:USERPROFILE\.evocli"

# ── 横幅 ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━ EvoCLI Uninstaller (Windows) ━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

if ($Purge) {
    Write-Host "  Mode: PURGE — all user data will be permanently deleted!" -ForegroundColor Red
} else {
    Write-Host "  Mode: standard (user data in .evocli\ will be preserved)" -ForegroundColor Yellow
}
Write-Host ""

# ── 辅助函数 ───────────────────────────────────────────────────────────
function ok   { param($msg) Write-Host "  [OK]  $msg" -ForegroundColor Green }
function info { param($msg) Write-Host "   ->   $msg" -ForegroundColor Yellow }
function skip { param($msg) Write-Host "   -    $msg (not found, skipping)" -ForegroundColor Gray }
function die  { param($msg) Write-Host "`n  [ERR] $msg`n" -ForegroundColor Red; exit 1 }

function Remove-EvoCLIDir {
    param([string]$Path, [string]$Label)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
        ok "Removed ${Label}: $Path"
    } else {
        skip $Label
    }
}

function Remove-EvoCLIFile {
    param([string]$Path, [string]$Label)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
        ok "Removed ${Label}: $Path"
    } else {
        skip $Label
    }
}

# ── 确认提示 ───────────────────────────────────────────────────────────
if (-not $Yes) {
    if ($Purge) {
        $confirm = Read-Host "  This will delete EvoCLI AND all your memory/skills/config. Continue? [y/N]"
    } else {
        $confirm = Read-Host "  This will remove EvoCLI binaries and Python environment. Continue? [y/N]"
    }
    if ($confirm -notmatch '^[yY]') {
        Write-Host "  Aborted."
        exit 0
    }
    Write-Host ""
}

# ── Step 1: 删除 evocli.exe 二进制 ────────────────────────────────────
Write-Host "[1/4] Removing evocli binary..." -ForegroundColor Yellow

$BinaryFound = $false

# 从 PATH 中搜索
$PathDirs = ($env:Path -split ";") | Where-Object { $_ -ne "" } | Select-Object -Unique
foreach ($dir in $PathDirs) {
    $bin = Join-Path $dir "evocli.exe"
    if (Test-Path -LiteralPath $bin) {
        Remove-Item -LiteralPath $bin -Force
        ok "Removed binary: $bin"
        # 同级 Soul 和辅助文件
        $soulDir = Join-Path $dir "evocli-soul"
        if (Test-Path -LiteralPath $soulDir) {
            Remove-Item -LiteralPath $soulDir -Recurse -Force
            ok "Removed Soul: $soulDir"
        }
        foreach ($f in @("setup.ps1", "setup_env.py", "download_models.py", "preflight.py")) {
            $fp = Join-Path $dir $f
            if (Test-Path -LiteralPath $fp) { Remove-Item -LiteralPath $fp -Force }
        }
        $BinaryFound = $true
    }
}

# 检查默认安装目录
$DefaultDirs = @(
    "$env:USERPROFILE\.evocli\app",
    "$env:USERPROFILE\.local\bin",
    "C:\Program Files\evocli"
)
foreach ($dir in $DefaultDirs) {
    $bin = "$dir\evocli.exe"
    if ((Test-Path -LiteralPath $bin) -and (-not $BinaryFound)) {
        Remove-Item -LiteralPath $bin -Force
        ok "Removed binary: $bin"
        $soulDir = "$dir\evocli-soul"
        if (Test-Path -LiteralPath $soulDir) {
            Remove-Item -LiteralPath $soulDir -Recurse -Force
            ok "Removed Soul: $soulDir"
        }
        $BinaryFound = $true
    }
}

if (-not $BinaryFound) { skip "evocli.exe (not found in PATH or default locations)" }

# ── Step 2: 删除 Python 环境 ───────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Removing Python environment..." -ForegroundColor Yellow
Remove-EvoCLIDir "$EvoCLIHome\venv" "Python venv"
Remove-EvoCLIDir "$EvoCLIHome\bin"  "uv package manager"

# ── Step 3: 删除运行时缓存 ─────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Removing runtime cache..." -ForegroundColor Yellow
Remove-EvoCLIDir  "$EvoCLIHome\logs"   "log files"
Remove-EvoCLIDir  "$EvoCLIHome\models" "embedding model cache"

# ── Step 4: （可选）删除用户数据 ───────────────────────────────────────
Write-Host ""
Write-Host "[4/4] User data..." -ForegroundColor Yellow

if ($Purge) {
    Remove-EvoCLIFile "$EvoCLIHome\config.toml"       "config"
    Remove-EvoCLIDir  "$EvoCLIHome\data"              "memory data"
    Remove-EvoCLIDir  "$EvoCLIHome\skills"            "global skills"
    Remove-EvoCLIDir  "$EvoCLIHome\sessions"          "session history"
    Remove-EvoCLIFile "$EvoCLIHome\events.db"         "events database"
    Remove-EvoCLIFile "$EvoCLIHome\jobs.db"           "job queue database"
    Remove-EvoCLIFile "$EvoCLIHome\contracts.db"      "contracts database"
    Remove-EvoCLIFile "$EvoCLIHome\skill_stats.json"  "skill stats"
    Remove-EvoCLIFile "$EvoCLIHome\mcp_servers.json"  "MCP server config"
    Remove-EvoCLIFile "$EvoCLIHome\user_tools.toml"   "user tools"

    # 若目录已空则删除整个 .evocli\
    if (Test-Path -LiteralPath $EvoCLIHome) {
        $remaining = @(Get-ChildItem -LiteralPath $EvoCLIHome -ErrorAction SilentlyContinue)
        if ($remaining.Count -eq 0) {
            Remove-Item -LiteralPath $EvoCLIHome -Force
            ok "Removed $EvoCLIHome\ (now empty)"
        } else {
            info "$EvoCLIHome\ still has $($remaining.Count) item(s) — leaving in place"
        }
    }
} else {
    skip "user data (use -Purge to also remove config/memory/skills)"
    if (Test-Path -LiteralPath $EvoCLIHome) {
        Write-Host ""
        Write-Host "  Preserved: $EvoCLIHome\" -ForegroundColor Gray
        Write-Host "    config.toml, data\, skills\, sessions\ remain untouched." -ForegroundColor Gray
        Write-Host "    To remove everything: .\uninstall.ps1 -Purge" -ForegroundColor Gray
    }
}

# ── 从用户 PATH 移除安装目录 ───────────────────────────────────────────
try {
    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User") ?? ""
    $CleanPath = ($UserPath -split ";" | Where-Object { $_ -notmatch "evocli" -and $_ -ne "" }) -join ";"
    if ($CleanPath -ne $UserPath) {
        [System.Environment]::SetEnvironmentVariable("Path", $CleanPath, "User")
        ok "Removed evocli entries from user PATH"
    }
} catch {
    info "Could not modify user PATH: $_"
}

# ── 完成 ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  [OK]  EvoCLI uninstalled." -ForegroundColor Green
Write-Host ""
if (-not $Purge) {
    Write-Host "  Your config and memory are preserved in $EvoCLIHome\"
    Write-Host "  Reinstall anytime:"
    Write-Host "    irm https://raw.githubusercontent.com/$REPO/main/scripts/install.ps1 | iex" -ForegroundColor Gray
}
Write-Host ""
