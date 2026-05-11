#!/usr/bin/env pwsh
# PyApp 打包验证脚本
# 验证：Python Soul（含 LanceDB 原生扩展）能否被 PyApp 打包为独立二进制

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

function Write-Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-OK($msg)       { Write-Host "    ✅ $msg" -ForegroundColor Green }
function Write-Fail($msg)     { Write-Host "    ❌ $msg" -ForegroundColor Red; exit 1 }

Write-Host "`n📦 PyApp 打包验证" -ForegroundColor Yellow

# ─── 1. 构建 Python Soul wheel ──────────────────────────────
Write-Step "1/4" "构建 Python Soul wheel"
Set-Location "$Root/evocli-soul"
& uv build --wheel 2>&1 | Tee-Object -Variable buildOut
if ($LASTEXITCODE -ne 0) { Write-Fail "wheel 构建失败" }

$wheel = Get-ChildItem dist -Filter "*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wheel) { Write-Fail "找不到生成的 wheel 文件" }
Write-OK "wheel: $($wheel.FullName)  ($([math]::Round($wheel.Length/1MB, 2)) MB)"

# ─── 2. 检查 PyApp ──────────────────────────────────────────
Write-Step "2/4" "检查 PyApp 可用性"
$pyapp = Get-Command pyapp -ErrorAction SilentlyContinue
if (-not $pyapp) {
    Write-Host "    安装 PyApp..." -ForegroundColor DarkYellow
    & cargo install pyapp 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "PyApp 安装失败" }
}
Write-OK "PyApp 可用"

# ─── 3. 设置 PyApp 环境变量并构建 ──────────────────────────
Write-Step "3/4" "PyApp 构建（嵌入 Python + wheel）"

$env:PYAPP_PROJECT_NAME         = "evocli-soul-tracer"
$env:PYAPP_PROJECT_PATH         = $wheel.FullName
$env:PYAPP_PYTHON_VERSION       = "3.12"
$env:PYAPP_DISTRIBUTION_EMBED   = "1"    # ← 关键：嵌入 Python 解释器
$env:PYAPP_UV_ENABLED           = "1"
$env:PYAPP_EXEC_MODULE          = "evocli_soul.main"

Set-Location $Root
& cargo build --release -p pyapp 2>&1 | Tee-Object -Variable pyappBuild
if ($LASTEXITCODE -ne 0) {
    Write-Host $pyappBuild -ForegroundColor Red
    Write-Fail "PyApp 构建失败"
}

$binary = "target/release/pyapp$(if($IsWindows){'.exe'})"
$size   = [math]::Round((Get-Item $binary).Length / 1MB, 1)
Write-OK "构建成功：$binary  ($size MB)"

# ─── 4. 运行验证 ────────────────────────────────────────────
Write-Step "4/4" "运行 PyApp 二进制（验证依赖解析）"

# 启动二进制，发送 tracer.check_deps，检查 lancedb 是否正常
$proc = Start-Process -FilePath $binary `
    -ArgumentList "" `
    -RedirectStandardOutput "tracer_out.txt" `
    -RedirectStandardError  "tracer_err.txt" `
    -PassThru -NoNewWindow

# 发送 JSON-RPC 请求
Start-Sleep -Milliseconds 2000   # 等待启动
$req = '{"id":"t1","method":"tracer.check_deps","params":{}}'
$proc.StandardInput.WriteLine($req)
Start-Sleep -Milliseconds 3000

$proc.Kill()
$out = Get-Content "tracer_out.txt" -Raw 2>/dev/null

Write-Host "    输出：$out"

if ($out -match '"ok":true') {
    Write-OK "lancedb 原生扩展在 PyApp 中正常运行 ✓"
    Write-Host "`n🎉 PyApp 打包验证通过！" -ForegroundColor Green
    Write-Host "   二进制大小：$size MB"
    Write-Host "   原生扩展（lancedb）：可正常打包并运行"
} elseif ($out -match '"ok":false') {
    Write-Host "`n⚠️  PyApp 打包成功但部分依赖缺失（见上方输出）" -ForegroundColor Yellow
    Write-Host "   需要检查：是否有平台特定的预编译 wheel？"
} else {
    Write-Fail "PyApp 二进制启动失败或无响应（见 tracer_err.txt）"
}

# 清理
Remove-Item "tracer_out.txt","tracer_err.txt" -ErrorAction SilentlyContinue
