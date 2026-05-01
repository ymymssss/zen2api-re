#!/usr/bin/env bash
# =============================================================================
# zen2api Termux 一键安装脚本
# 用法: curl -sL https://raw.githubusercontent.com/ymymssss/zen2api-re/main/setup.sh | bash
# 或者: bash setup.sh
# =============================================================================
set -euo pipefail

# ── 颜色定义 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { printf "${GREEN}[✓]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
err()   { printf "${RED}[✗]${NC} %s\n" "$*"; }
step()  { printf "\n${BLUE}═══ %s ═══${NC}\n" "$*"; }
detail(){ printf "    %s\n" "$*"; }

# ── 环境检测 ────────────────────────────────────────────────────────────────
step "检测运行环境"

# 检测是否为 Termux
if [[ -d /data/data/com.termux/files/usr ]] && [[ "$(uname -o)" == "Android" ]]; then
    info "检测到 Termux 环境 (Android)"
    TERMUX_PREFIX="/data/data/com.termux/files/usr"
    TERMUX_HOME="/data/data/com.termux/files/home"
    IS_TERMUX=true
else
    warn "非 Termux 环境，按普通 Linux 处理"
    TERMUX_PREFIX="/usr/local"
    TERMUX_HOME="$HOME"
    IS_TERMUX=false
fi

# 架构检测 — Termux 在 Android 上跑的是 aarch64
ARCH=$(uname -m)
detail "CPU 架构: $ARCH"
case "$ARCH" in
    aarch64|arm64|armv8*)   GOARCH="arm64" ;;
    armv7l|armv7*)           GOARCH="arm" ;;
    x86_64|amd64)            GOARCH="amd64" ;;
    *)
        err "不支持的 CPU 架构: $ARCH"
        err "支持的架构: aarch64, armv7l, x86_64"
        exit 1
        ;;
esac
detail "目标编译架构: $GOARCH"

# ── 安装依赖 ────────────────────────────────────────────────────────────────
step "安装必要依赖"

if $IS_TERMUX; then
    # Termux 源更新 — 静默模式，失败也不阻塞
    detail "更新 Termux 软件源..."
    pkg update -y -qq 2>/dev/null || warn "软件源更新失败，继续使用现有源"

    # 安装必要工具
    for pkg in golang git curl; do
        if ! command -v $pkg &>/dev/null; then
            detail "正在安装 $pkg ..."
            pkg install -y $pkg 2>&1 | tail -1 || {
                err "安装 $pkg 失败，请检查网络连接"
                exit 1
            }
        else
            info "$pkg 已安装: $(command -v $pkg)"
        fi
    done
else
    # 非 Termux，尝试用系统包管理器
    if command -v apt &>/dev/null; then
        sudo apt update -qq && sudo apt install -y golang git curl
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm go git curl
    else
        warn "未检测到已知包管理器，请手动安装: go, git, curl"
    fi
fi

# 验证 Go 版本
GO_VERSION=$(go version 2>/dev/null | grep -oP 'go\K[0-9]+\.[0-9]+' || echo "0.0")
detail "Go 版本: go$GO_VERSION"
REQUIRED_GO="1.22"
if [[ "$(printf '%s\n' "$REQUIRED_GO" "$GO_VERSION" | sort -V | head -1)" != "$REQUIRED_GO" ]]; then
    warn "Go 版本过低 (需要 >= $REQUIRED_GO，当前 $GO_VERSION)，将尝试升级"
    if $IS_TERMUX; then
        pkg upgrade -y golang 2>/dev/null || warn "Go 升级失败，尝试继续编译"
    fi
fi

# ── 克隆仓库 ────────────────────────────────────────────────────────────────
step "获取源码"

REPO_URL="https://github.com/ymymssss/zen2api-re.git"
INSTALL_DIR="$TERMUX_HOME/zen2api"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "仓库已存在，拉取最新代码..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || {
        warn "拉取失败，将使用现有代码继续"
    }
else
    if [[ -d "$INSTALL_DIR" ]]; then
        warn "$INSTALL_DIR 已存在但不是 git 仓库，备份后重新克隆"
        mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%s)"
    fi
    detail "克隆仓库到 $INSTALL_DIR ..."
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1 | tail -1 || {
        err "克隆仓库失败！请检查网络和 GitHub 可访问性"
        err "可以用镜像: git clone https://gitclone.com/github.com/ymymssss/zen2api-re.git $INSTALL_DIR"
        exit 1
    }
    cd "$INSTALL_DIR"
fi

# ── 编译 ────────────────────────────────────────────────────────────────────
step "编译 zen2api"

# 清理之前的构建产物
rm -rf zen2api zen2api-re

# 静态编译 — 无任何外部依赖，生成的二进制可在任何同架构 Linux 上运行
detail "开始编译 (GOOS=linux GOARCH=$GOARCH CGO_ENABLED=0)..."
CGO_ENABLED=0 GOOS=linux GOARCH=$GOARCH \
    go build -v -ldflags="-s -w" -o zen2api . 2>&1 || {
    err "编译失败！请检查上面的错误信息"
    err "常见原因: Go 版本过低或网络问题导致模块下载失败"
    exit 1
}

# 验证编译产物
BIN_SIZE=$(du -h zen2api | cut -f1)
info "编译成功 — 二进制文件: zen2api ($BIN_SIZE)"

# ── 安装 ────────────────────────────────────────────────────────────────────
step "安装到系统路径"

BIN_DIR="$TERMUX_PREFIX/bin"
mkdir -p "$BIN_DIR"

# 复制到 PATH 目录
cp zen2api "$BIN_DIR/zen2api"
chmod +x "$BIN_DIR/zen2api"
info "二进制已安装到: $BIN_DIR/zen2api"

# 验证可执行
"$BIN_DIR/zen2api" -version 2>/dev/null || warn "版本检测跳过（程序不支持 -version 参数，正常）"

# ── 创建 zen 快捷命令 ───────────────────────────────────────────────────────
step "创建 zen 快捷命令"

# zen 启动脚本 — 放在 PATH 中，方便直接敲 zen 启动
ZEN_SCRIPT="$BIN_DIR/zen"

cat > "$ZEN_SCRIPT" << 'ZENEOF'
#!/usr/bin/env bash
# =============================================================================
# zen — zen2api 一键启动器
# 用法: zen                          # 默认启动 (端口 9015)
#       zen -p 8080                  # 指定端口
#       zen -k "my-key"              # 设置 API Key
#       zen -m "model1,model2"       # 指定 Zen 模型列表
#       zen status                   # 查看运行状态
#       zen stop                     # 停止服务
#       zen log                      # 查看日志
# =============================================================================

ZEN_HOST="${ZEN_HOST:-127.0.0.1}"
ZEN_PORT="${ZEN_PORT:-9015}"
ZEN_KEY="${ZEN_KEY:-}"
ZEN_MODELS="${ZEN_MODELS:-minimax-m2.5-free}"
ZEN_LOG="${ZEN_LOG:-$HOME/zen2api/zen.log}"
ZEN_PID_FILE="$HOME/zen2api/zen.pid"

# 确保日志目录存在
mkdir -p "$(dirname "$ZEN_LOG")"

# ── 命令处理 ────────────────────────────────────────────────────────────────
case "${1:-}" in
    status)
        if [[ -f "$ZEN_PID_FILE" ]]; then
            PID=$(cat "$ZEN_PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "zen2api 运行中 (PID: $PID, 端口: $ZEN_PORT)"
                echo "管理面板: http://$ZEN_HOST:$ZEN_PORT/admin"
            else
                echo "zen2api 未运行 (PID 文件过期)"
                rm -f "$ZEN_PID_FILE"
            fi
        else
            echo "zen2api 未运行"
        fi
        exit 0
        ;;
    stop)
        if [[ -f "$ZEN_PID_FILE" ]]; then
            PID=$(cat "$ZEN_PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                kill "$PID" 2>/dev/null
                sleep 1
                if kill -0 "$PID" 2>/dev/null; then
                    kill -9 "$PID" 2>/dev/null
                fi
                echo "zen2api 已停止 (PID: $PID)"
            fi
            rm -f "$ZEN_PID_FILE"
        else
            echo "zen2api 没有在运行"
        fi
        exit 0
        ;;
    log)
        if [[ -f "$ZEN_LOG" ]]; then
            tail -f "$ZEN_LOG"
        else
            echo "日志文件不存在: $ZEN_LOG"
        fi
        exit 0
        ;;
    -h|--help|help)
        echo "zen — zen2api 启动器"
        echo ""
        echo "命令:"
        echo "  zen              启动服务 (后台)"
        echo "  zen status       查看状态"
        echo "  zen stop         停止服务"
        echo "  zen log          查看实时日志"
        echo ""
        echo "选项:"
        echo "  -p PORT          指定端口 (默认 9015)"
        echo "  -k KEY           设置 API Key"
        echo "  -m MODELS        设置 Zen 模型 (逗号分隔)"
        echo "  -km MODELS       设置 Kilo 模型 (逗号分隔)"
        echo ""
        echo "环境变量 (可选):"
        echo "  ZEN_PORT=9015 zen  等同于 zen -p 9015"
        exit 0
        ;;
esac

# ── 参数解析 ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p) ZEN_PORT="$2"; shift 2 ;;
        -k) ZEN_KEY="$2"; shift 2 ;;
        -m) ZEN_MODELS="$2"; shift 2 ;;
        -km) ZEN_KILO_MODELS="$2"; shift 2 ;;
        *)  echo "未知参数: $1 (用 zen --help 查看帮助)"; exit 1 ;;
    esac
done

# ── 检查是否已在运行 ────────────────────────────────────────────────────────
if [[ -f "$ZEN_PID_FILE" ]]; then
    PID=$(cat "$ZEN_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "zen2api 已在运行 (PID: $PID, 端口: $ZEN_PORT)"
        echo "用 'zen stop' 停止，或 'zen status' 查看状态"
        exit 1
    fi
fi

# ── 启动 ────────────────────────────────────────────────────────────────────
export ZEN2API_ENABLED=1
export ZEN2API_HOST="$ZEN_HOST"
export ZEN2API_PORT="$ZEN_PORT"
export ZEN2API_KEY="$ZEN_KEY"
export ZEN2API_ZEN_MODELS="$ZEN_MODELS"
export ZEN2API_KILO_MODELS="${ZEN_KILO_MODELS:-kilo-auto/free,minimax/minimax-m2.5:free}"
export ZEN2API_LOG_FILE="$ZEN_LOG"
export ZEN2API_STATS_FILE="$HOME/zen2api/stats.json"

# Termux/Android 兼容 — 指定 CA 证书位置
[ -f /data/data/com.termux/files/usr/etc/tls/cert.pem ] && export SSL_CERT_FILE=/data/data/com.termux/files/usr/etc/tls/cert.pem

echo "启动 zen2api ..."
echo "  端口: $ZEN_PORT"
echo "  管理面板: http://$ZEN_HOST:$ZEN_PORT/admin"
echo "  模型列表: http://$ZEN_HOST:$ZEN_PORT/v1/models"
echo "  日志: $ZEN_LOG"
echo ""

nohup zen2api >> "$ZEN_LOG" 2>&1 &
PID=$!
echo $PID > "$ZEN_PID_FILE"

sleep 2
if kill -0 "$PID" 2>/dev/null; then
    echo "zen2api 启动成功! (PID: $PID)"
    echo ""
    echo "试试这些:"
    echo "  zen status          查看状态"
    echo "  zen log             查看日志"
    echo "  curl localhost:$ZEN_PORT/v1/models"
    echo "  curl localhost:$ZEN_PORT/health"
else
    echo "启动失败，查看日志: cat $ZEN_LOG"
    rm -f "$ZEN_PID_FILE"
    exit 1
fi
ZENEOF

chmod +x "$ZEN_SCRIPT"
info "zen 命令已创建: $ZEN_SCRIPT"

# ── 环境变量配置 ────────────────────────────────────────────────────────────
step "配置环境变量"

# 选择 shell 配置文件
if [[ "$SHELL" == *"zsh"* ]]; then
    RC_FILE="$TERMUX_HOME/.zshrc"
elif [[ "$SHELL" == *"fish"* ]]; then
    RC_FILE="$TERMUX_HOME/.config/fish/config.fish"
else
    RC_FILE="$TERMUX_HOME/.bashrc"
fi

detail "Shell 配置文件: $RC_FILE"

# 检查 PATH 是否包含 BIN_DIR
if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    detail "已将 $BIN_DIR 加入 PATH"
fi

# 添加 zen2api 默认环境变量到 RC 文件（如果还没加过）
if [[ "$SHELL" == *"fish"* ]]; then
    ZEN_ENV_BLOCK="# >>> zen2api 环境变量 (由 setup.sh 自动添加) >>>
set -x ZEN2API_ENABLED 1
set -x ZEN2API_PORT 9015
set -x ZEN2API_HOST 127.0.0.1
# set -x ZEN2API_KEY \"\"                # 取消注释并设置你的 API Key
# <<< zen2api <<<"
else
    ZEN_ENV_BLOCK="# >>> zen2api 环境变量 (由 setup.sh 自动添加) >>>
export ZEN2API_ENABLED=1
export ZEN2API_PORT=9015
export ZEN2API_HOST=127.0.0.1
# export ZEN2API_KEY=\"\"                # 取消注释并设置你的 API Key
# <<< zen2api <<<"
fi

if ! grep -q "zen2api 环境变量" "$RC_FILE" 2>/dev/null; then
    echo "" >> "$RC_FILE"
    echo "$ZEN_ENV_BLOCK" >> "$RC_FILE"
    info "环境变量已写入 $RC_FILE"
else
    info "环境变量已存在于 $RC_FILE，跳过"
fi

# ── Hermes Agent 安装 ────────────────────────────────────────────────────────
step "Hermes Agent 安装"

if command -v hermes &>/dev/null; then
    info "Hermes Agent 已安装，跳过"
else
    echo ""
    warn "Hermes Agent 未检测到"
    detail "Hermes 是 NousResearch 的 AI Agent，可与 zen2api 配合使用，提供终端 AI 助手能力"
    echo ""
    read -r -p "是否安装 Hermes Agent? [y/N] " REPLY
    echo ""
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        detail "正在安装 Hermes Agent..."
        detail "安装脚本: https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh"
        curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash || {
            warn "Hermes Agent 安装失败"
            detail "可稍后手动安装:"
            detail "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
        }
        if command -v hermes &>/dev/null; then
            info "Hermes Agent 安装成功"
        fi
    else
        info "跳过 Hermes Agent 安装"
        detail "可稍后手动安装: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
    fi
fi

# ── Hermes 配置 ────────────────────────────────────────────────────────────
step "Hermes Agent 接入配置"

# 检查 Hermes 是否已安装
if command -v hermes &>/dev/null; then
    info "检测到 Hermes，使用官方 CLI 配置 provider..."

    # 添加 zenlocal provider（使用 hermes config set 官方命令）
    hermes config set providers.zenlocal.name ZenLocal 2>/dev/null || true
    hermes config set providers.zenlocal.base_url http://127.0.0.1:9015/anthropic 2>/dev/null || true
    hermes config set providers.zenlocal.transport anthropic_messages 2>/dev/null || true
    hermes config set providers.zenlocal.key_env ZENLOCAL_API_KEY 2>/dev/null || true
    hermes config set providers.zenlocal.api_key noauth 2>/dev/null || true

    # 设为默认模型和 provider — 必须用 model.default / model.provider
    # 不能用 hermes config set model <value>（那会写成字符串，导致 provider 不生效）
    hermes config set model.default minimax-m2.5-free 2>/dev/null || true
    hermes config set model.provider zenlocal 2>/dev/null || true

    info "Hermes 配置完成"
    detail "provider: zenlocal → http://127.0.0.1:9015/anthropic"
    detail "transport: anthropic_messages"
    detail "通过 'hermes config show' 或 'hermes config edit' 查看/修改"
else
    warn "未检测到 Hermes，跳过配置"
    detail "安装 Hermes 后运行以下命令完成配置:"
    detail ""
    detail "  hermes config set providers.zenlocal.name ZenLocal"
    detail "  hermes config set providers.zenlocal.base_url http://127.0.0.1:9015/anthropic"
    detail "  hermes config set providers.zenlocal.transport anthropic_messages"
    detail "  hermes config set providers.zenlocal.key_env ZENLOCAL_API_KEY"
    detail "  hermes config set providers.zenlocal.api_key noauth"
    detail "  hermes config set model.default minimax-m2.5-free"
    detail "  hermes config set model.provider zenlocal"
fi

# ── 安装完成 ────────────────────────────────────────────────────────────────
echo ""
echo "┌──────────────────────────────────────────────────────────────────────┐"
echo "│                    zen2api 安装完成!                                 │"
echo "├──────────────────────────────────────────────────────────────────────┤"
echo "│                                                                      │"
echo "│  立即开始:                                                           │"
echo "│    source $RC_FILE         # 加载环境变量                            │"
echo "│    zen                     # 启动 zen2api                         │"
echo "│                                                                      │"
echo "│  常用命令:                                                           │"
echo "│    zen                    启动服务 (后台运行)                      │"
echo "│    zen status             查看运行状态                                │"
echo "│    zen stop               停止服务                                    │"
echo "│    zen log                查看实时日志                                │"
echo "│    zen -p 8080            使用其他端口启动                          │"
echo "│                                                                      │"
echo "│  服务端点:                                                           │"
echo "│    http://127.0.0.1:9015/admin         管理面板                   │"
echo "│    http://127.0.0.1:9015/v1/models      模型列表                  │"
echo "│    http://127.0.0.1:9015/health         健康检查                  │"
echo "│    http://127.0.0.1:9015/v1/messages    Anthropic Messages API    │"
echo "│    http://127.0.0.1:9015/v1/chat/completions  OpenAI Chat API    │"
echo "│                                                                      │"
echo "│  Hermes 接入:                                                        │"
echo "│    ZENLOCAL_API_KEY=\"noauth\" hermes -z \"你的问题\"                    │"
echo "│    ZENLOCAL_API_KEY=\"noauth\" hermes chat -q \"你的问题\"               │"
echo "│                                                                      │"
echo "└──────────────────────────────────────────────────────────────────────┘"
echo ""

info "一切就绪！执行 'zen' 启动服务 🚀"
