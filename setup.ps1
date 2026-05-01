# =============================================================================
# zen2api Windows 一键安装脚本
# 用法: irm https://raw.githubusercontent.com/ymymssss/zen2api-re/main/setup.ps1 | iex
# 或者: .\setup.ps1
# 要求: Windows 10+, PowerShell 5.1+
# =============================================================================
$ErrorActionPreference = "Stop"

# ── 颜色 ──────────────────────────────────────────────────────────────────────
function info  { Write-Host "[✓] $args" -ForegroundColor Green }
function warn  { Write-Host "[!] $args" -ForegroundColor Yellow }
function err   { Write-Host "[✗] $args" -ForegroundColor Red }
function step  { Write-Host ""; Write-Host "═══ $args ═══" -ForegroundColor Cyan }
function detail { Write-Host "    $args" }

# ── 管理员检查 ────────────────────────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    warn "未以管理员运行 — 安装到用户目录 (不需要管理员权限)"
}

# ── 环境检测 ──────────────────────────────────────────────────────────────────
step "检测运行环境"

$ARCH = $env:PROCESSOR_ARCHITECTURE
detail "CPU 架构: $ARCH"
switch -Wildcard ($ARCH) {
    "AMD64"   { $GOARCH = "amd64"; $RELEASE_ARCH = "windows-amd64" }
    "ARM64"   { $GOARCH = "arm64"; $RELEASE_ARCH = "windows-arm64" }
    default   {
        err "不支持的 CPU 架构: $ARCH (支持 AMD64, ARM64)"
        exit 1
    }
}
detail "目标架构: $GOARCH"

# ── 确定安装目录 ──────────────────────────────────────────────────────────────
$INSTALL_DIR = Join-Path $env:USERPROFILE "zen2api"
$BIN_DIR = Join-Path $env:USERPROFILE "zen2api\bin"
$REPO_URL = "https://github.com/ymymssss/zen2api-re.git"
$RELEASES_URL = "https://github.com/ymymssss/zen2api-re/releases/latest/download/zen2api-$RELEASE_ARCH.exe"

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $BIN_DIR | Out-Null

# ── 获取/编译 zen2api ───────────────────────────────────────────────────────
step "获取 zen2api"

# Stop running instance to avoid "Text file busy" / file lock errors
$running = Get-Process zen2api -ErrorAction SilentlyContinue
if ($running) {
    detail "停止正在运行的 zen2api..."
    $running | Stop-Process -Force
    Start-Sleep -Seconds 1
}

$goCmd = Get-Command go -ErrorAction SilentlyContinue

if ($goCmd) {
    # 有 Go — 源码编译
    $goVer = (& go version) -replace '.*go(\d+\.\d+).*', '$1'
    detail "检测到 Go $goVer"

    $requiredGo = "1.22"
    if ([version]$goVer -lt [version]$requiredGo) {
        warn "Go 版本过低 (需要 >= $requiredGo，当前 $goVer)，尝试继续编译"
    }

    # 克隆仓库
    $repoDir = Join-Path $INSTALL_DIR "src"
    if (Test-Path (Join-Path $repoDir ".git")) {
        info "仓库已存在，拉取最新代码..."
        Push-Location $repoDir
        git pull --ff-only origin main 2>$null
        if ($LASTEXITCODE -ne 0) { warn "拉取失败，使用现有代码" }
        Pop-Location
    } else {
        if (Test-Path $repoDir) {
            warn "$repoDir 已存在，备份后重新克隆"
            Move-Item $repoDir "$repoDir.bak.$(Get-Date -Format 'yyyyMMddHHmmss')"
        }
        detail "克隆仓库..."
        git clone --depth 1 $REPO_URL $repoDir
        if ($LASTEXITCODE -ne 0) {
            err "克隆失败！请检查网络"
            exit 1
        }
    }

    Push-Location $repoDir
    $env:CGO_ENABLED = "0"
    $env:GOOS = "windows"
    $env:GOARCH = $GOARCH

    detail "编译中 (GOOS=windows GOARCH=$GOARCH)..."
    go build -ldflags="-s -w" -o (Join-Path $BIN_DIR "zen2api.exe") .
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        err "编译失败！"
        err "常见原因: Go 版本过低或网络问题"
        exit 1
    }
    Pop-Location
    info "编译成功"
} else {
    # 无 Go — 下载预编译二进制
    detail "未检测到 Go，尝试下载预编译二进制..."

    $exePath = Join-Path $BIN_DIR "zen2api.exe"
    try {
        Invoke-WebRequest -Uri $RELEASES_URL -OutFile $exePath -ErrorAction Stop
        info "下载成功"
    } catch {
        warn "下载预编译二进制失败，尝试安装 Go 并编译..."
        warn "请手动安装 Go (https://go.dev/dl/) 然后重新运行本脚本"
        warn "或者手动下载二进制放到: $exePath"
        exit 1
    }
}

# 验证二进制
$binSize = (Get-Item (Join-Path $BIN_DIR "zen2api.exe")).Length
info "zen2api.exe ($('{0:N0}' -f $binSize) bytes)"

# ── 加入 PATH ─────────────────────────────────────────────────────────────────
step "配置 PATH"

$currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentUserPath -notlike "*$BIN_DIR*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentUserPath;$BIN_DIR", "User")
    $env:Path = "$env:Path;$BIN_DIR"
    info "已将 $BIN_DIR 加入用户 PATH"
} else {
    info "$BIN_DIR 已在 PATH 中"
}

# ── 创建 zen 快捷命令 ─────────────────────────────────────────────────────────
step "创建 zen 命令"

$zenCmd = @'
@echo off
REM =============================================================================
REM zen — zen2api 一键启动器 (Windows)
REM 用法: zen               默认启动 (端口 9015)
REM        zen -p 8080       指定端口
REM        zen -k "my-key"   设置 API Key
REM        zen -m "model1,model2"  指定 Zen 模型列表
REM        zen status        查看状态
REM        zen stop          停止服务
REM        zen log           查看日志
REM =============================================================================

setlocal enabledelayedexpansion

set ZEN_HOST=127.0.0.1
set ZEN_PORT=9015
set ZEN_KEY=
set ZEN_MODELS=minimax-m2.5-free
set ZEN_LOG=%USERPROFILE%\zen2api\zen.log
set ZEN_PID_FILE=%USERPROFILE%\zen2api\zen.pid

REM ── 命令处理 ────────────────────────────────────────────────────────────────
if "%1"=="status" goto :status
if "%1"=="stop"   goto :stop
if "%1"=="log"    goto :log
if "%1"=="-h"     goto :help
if "%1"=="--help" goto :help
if "%1"=="help"   goto :help
goto :parse_args

:help
echo zen — zen2api 启动器
echo.
echo 命令:
echo   zen              启动服务 (后台)
echo   zen status       查看状态
echo   zen stop         停止服务
echo   zen log          查看实时日志
echo.
echo 选项:
echo   -p PORT          指定端口 (默认 9015)
echo   -k KEY           设置 API Key
echo   -m MODELS        设置 Zen 模型 (逗号分隔)
echo   -km MODELS       设置 Kilo 模型 (逗号分隔)
echo.
echo 环境变量:
echo   set ZEN_PORT=9015 & zen  等同于 zen -p 9015
exit /b 0

:status
if exist "%ZEN_PID_FILE%" (
    set /p PID=<"%ZEN_PID_FILE%"
    tasklist /fi "PID eq !PID!" 2>nul | find /i "zen2api" >nul
    if !errorlevel! equ 0 (
        echo zen2api 运行中 (PID: !PID!, 端口: %ZEN_PORT%)
        echo 管理面板: http://%ZEN_HOST%:%ZEN_PORT%/admin
    ) else (
        echo zen2api 未运行 (PID 文件过期)
        del "%ZEN_PID_FILE%" 2>nul
    )
) else (
    echo zen2api 未运行
)
exit /b 0

:stop
if exist "%ZEN_PID_FILE%" (
    set /p PID=<"%ZEN_PID_FILE%"
    taskkill /pid !PID! /f 2>nul
    echo zen2api 已停止 (PID: !PID!)
    del "%ZEN_PID_FILE%" 2>nul
) else (
    echo zen2api 没有在运行
)
exit /b 0

:log
if exist "%ZEN_LOG%" (
    type "%ZEN_LOG%"
) else (
    echo 日志文件不存在: %ZEN_LOG%
)
exit /b 0

:parse_args
REM ── 参数解析 ────────────────────────────────────────────────────────────────
:parse_loop
if "%~1"=="" goto :start
if "%~1"=="-p"  (set ZEN_PORT=%~2 & shift & shift & goto :parse_loop)
if "%~1"=="-k"  (set ZEN_KEY=%~2  & shift & shift & goto :parse_loop)
if "%~1"=="-m"  (set ZEN_MODELS=%~2 & shift & shift & goto :parse_loop)
if "%~1"=="-km" (set ZEN_KILO_MODELS=%~2 & shift & shift & goto :parse_loop)
echo 未知参数: %~1 (用 zen --help 查看帮助)
exit /b 1

:start
REM ── 检查是否已在运行 ──────────────────────────────────────────────────────────
if exist "%ZEN_PID_FILE%" (
    set /p PID=<"%ZEN_PID_FILE%"
    tasklist /fi "PID eq !PID!" 2>nul | find /i "zen2api" >nul
    if !errorlevel! equ 0 (
        echo zen2api 已在运行 (PID: !PID!, 端口: %ZEN_PORT%)
        echo 用 'zen stop' 停止，或 'zen status' 查看状态
        exit /b 1
    )
)

REM ── 启动 ────────────────────────────────────────────────────────────────────
set ZEN2API_ENABLED=1
set ZEN2API_HOST=%ZEN_HOST%
set ZEN2API_PORT=%ZEN_PORT%
if not "%ZEN_KEY%"=="" set ZEN2API_KEY=%ZEN_KEY%
set ZEN2API_ZEN_MODELS=%ZEN_MODELS%
if "%ZEN_KILO_MODELS%"=="" set ZEN_KILO_MODELS=kilo-auto/free,minimax/minimax-m2.5:free
set ZEN2API_LOG_FILE=%ZEN_LOG%
set ZEN2API_STATS_FILE=%USERPROFILE%\zen2api\stats.json

echo 启动 zen2api ...
echo   端口: %ZEN_PORT%
echo   管理面板: http://%ZEN_HOST%:%ZEN_PORT%/admin
echo   模型列表: http://%ZEN_HOST%:%ZEN_PORT%/v1/models
echo   日志: %ZEN_LOG%
echo.

start "" /B zen2api.exe
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq zen2api.exe" /fo list ^| findstr /i "PID"') do set PID=%%a
echo !PID! > "%ZEN_PID_FILE%"

timeout /t 2 /nobreak >nul
tasklist /fi "PID eq !PID!" 2>nul | find /i "zen2api" >nul
if !errorlevel! equ 0 (
    echo zen2api 启动成功! (PID: !PID!)
    echo.
    echo 试试这些:
    echo   zen status          查看状态
    echo   zen log             查看日志
    echo   curl localhost:%ZEN_PORT%/v1/models
    echo   curl localhost:%ZEN_PORT%/health
) else (
    echo 启动失败，查看日志: type %ZEN_LOG%
    del "%ZEN_PID_FILE%" 2>nul
    exit /b 1
)
exit /b 0
'@

$zenBatPath = Join-Path $BIN_DIR "zen.cmd"
Set-Content -Path $zenBatPath -Value $zenCmd -Encoding ASCII
info "zen.cmd 已创建: $zenBatPath"

# ── 环境变量 ──────────────────────────────────────────────────────────────────
step "配置环境变量"

[Environment]::SetEnvironmentVariable("ZEN2API_ENABLED", "1", "User")
[Environment]::SetEnvironmentVariable("ZEN2API_PORT", "9015", "User")
[Environment]::SetEnvironmentVariable("ZEN2API_HOST", "127.0.0.1", "User")
info "环境变量已设置 (ZEN2API_ENABLED=1, ZEN2API_PORT=9015)"

# ── Hermes Agent 安装 ────────────────────────────────────────────────────────────
step "Hermes Agent 安装"

$hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue

if ($hermesCmd) {
    info "Hermes Agent 已安装，跳过"
} else {
    Write-Host ""
    warn "Hermes Agent 未检测到"
    detail "Hermes 是 NousResearch 的 AI Agent，可与 zen2api 配合使用，提供终端 AI 助手能力"
    Write-Host ""
    $reply = Read-Host "是否安装 Hermes Agent? (y/N)"
    Write-Host ""
    if ($reply -match '^[Yy]') {
        $pipCmd = Get-Command pip -ErrorAction SilentlyContinue
        if ($pipCmd) {
            detail "正在安装 Hermes Agent (pip install hermes-agent)..."
            pip install hermes-agent 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                info "Hermes Agent 安装成功"
            } else {
                warn "pip 安装失败，尝试官方安装脚本..."
                detail "Windows 用户推荐通过 WSL2 安装: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
            }
        } else {
            warn "未检测到 pip，请先安装 Python"
            detail "或通过 WSL2 安装 Hermes Agent:"
            detail "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
        }
    } else {
        info "跳过 Hermes Agent 安装"
        detail "可稍后手动安装: pip install hermes-agent"
        detail "或 WSL2: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    }
}

# ── Hermes 配置 ────────────────────────────────────────────────────────────────
step "Hermes Agent 接入配置"

$hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue

if ($hermesCmd) {
    info "检测到 Hermes，使用官方 CLI 配置 provider..."

    $hermesCommands = @(
        @("config", "set", "providers.zenlocal.name", "ZenLocal"),
        @("config", "set", "providers.zenlocal.base_url", "http://127.0.0.1:9015/anthropic"),
        @("config", "set", "providers.zenlocal.transport", "anthropic_messages"),
        @("config", "set", "providers.zenlocal.key_env", "ZENLOCAL_API_KEY"),
        @("config", "set", "providers.zenlocal.api_key", "noauth"),
        @("config", "set", "model.default", "minimax-m2.5-free"),
        @("config", "set", "model.provider", "zenlocal")
    )

    foreach ($cmd in $hermesCommands) {
        & hermes $cmd 2>$null
    }

    info "Hermes 配置完成"
    detail "provider: zenlocal → http://127.0.0.1:9015/anthropic"
    detail "transport: anthropic_messages"
} else {
    warn "未检测到 Hermes，跳过配置"
    detail "安装 Hermes 后运行以下命令:"
    detail ""
    detail "  hermes config set providers.zenlocal.name ZenLocal"
    detail "  hermes config set providers.zenlocal.base_url http://127.0.0.1:9015/anthropic"
    detail "  hermes config set providers.zenlocal.transport anthropic_messages"
    detail "  hermes config set providers.zenlocal.key_env ZENLOCAL_API_KEY"
    detail "  hermes config set providers.zenlocal.api_key noauth"
    detail "  hermes config set model.default minimax-m2.5-free"
    detail "  hermes config set model.provider zenlocal"
}

# ── 安装完成 ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "+" -NoNewline -ForegroundColor Green
Write-Host ("─" * 70) -NoNewline -ForegroundColor Green
Write-Host "+" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "                    zen2api 安装完成!                                 " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host ("─" * 70) -NoNewline -ForegroundColor Green
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "                                                                      " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "  立即开始:                                                           " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    zen                     # 启动 zen2api                         " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "                                                                      " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "  常用命令:                                                           " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    zen                    启动服务 (后台)                        " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    zen status             查看状态                                " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    zen stop               停止服务                                " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    zen log                查看日志                                " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    zen -p 8080            使用其他端口                            " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "                                                                      " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "  服务端点:                                                           " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    http://127.0.0.1:9015/admin         管理面板                   " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    http://127.0.0.1:9015/v1/models      模型列表                  " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    http://127.0.0.1:9015/health         健康检查                  " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    http://127.0.0.1:9015/v1/messages    Anthropic Messages API    " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    http://127.0.0.1:9015/v1/chat/completions  OpenAI Chat API    " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "                                                                      " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "  Hermes 接入:                                                        " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    `$env:ZENLOCAL_API_KEY='noauth'; hermes -z '你的问题'`            " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "    `$env:ZENLOCAL_API_KEY='noauth'; hermes chat -q '你的问题'`       " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "|" -NoNewline -ForegroundColor Green
Write-Host "                                                                      " -NoNewline
Write-Host "|" -ForegroundColor Green
Write-Host "+" -NoNewline -ForegroundColor Green
Write-Host ("─" * 70) -NoNewline -ForegroundColor Green
Write-Host "+" -ForegroundColor Green
Write-Host ""

info "一切就绪！打开新终端，执行 'zen' 启动服务"
Write-Host ""
Write-Host "注意: 如果 PATH 未生效，请重新打开终端或运行: `$env:Path += ';$BIN_DIR'"
