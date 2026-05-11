#!/usr/bin/env bash
# install.sh — EvoCLI 一键安装脚本 (Linux / macOS)
#
# 用法（推荐）：
#   curl -fsSL https://raw.githubusercontent.com/bambooqj/evocli/main/scripts/install.sh | bash
#
# 本地运行：
#   bash install.sh [--version v0.1.0] [--dir ~/.local/bin] [--yes]
#
# 环境变量：
#   EVOCLI_VERSION   指定版本（默认 latest）
#   EVOCLI_INSTALL_DIR  安装目录（默认 ~/.local/bin）
#   EVOCLI_NO_MODIFY_PATH=1  安装后不修改 shell rc 文件

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; GRAY='\033[0;37m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
info() { echo -e "  ${YELLOW}→${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
die()  { echo -e "\n  ${RED}✗  ERROR:${NC} $*\n" >&2; exit 1; }

# ── 解析参数 ──────────────────────────────────────────────────────────
REPO="bambooqj/evocli"
VERSION="${EVOCLI_VERSION:-latest}"
INSTALL_DIR="${EVOCLI_INSTALL_DIR:-$HOME/.local/bin}"
AUTO_YES="${EVOCLI_YES:-0}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version|-v) VERSION="$2"; shift 2 ;;
        --dir|-d)     INSTALL_DIR="$2"; shift 2 ;;
        --yes|-y)     AUTO_YES=1; shift ;;
        --help|-h)
            echo "Usage: bash install.sh [--version v0.1.0] [--dir ~/.local/bin] [--yes]"
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

# ── 横幅 ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}━━━ EvoCLI Installer (Linux / macOS) ━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── 依赖检查 ──────────────────────────────────────────────────────────
for cmd in curl tar; do
    command -v "$cmd" &>/dev/null || die "'$cmd' is required but not found."
done

# ── Step 1: 获取版本信息 ──────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Resolving version...${NC}"
if [[ "$VERSION" == "latest" ]]; then
    info "Fetching latest release from GitHub..."
    RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null) \
        || die "Failed to reach GitHub API. Check your network connection."
    VERSION=$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
    [[ -n "$VERSION" ]] || die "Could not parse release version from GitHub API response."
fi
ok "Version: $VERSION"

# ── Step 2: 检测平台 ──────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/5] Detecting platform...${NC}"
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$OS" in
    linux)  OS_STR="linux" ;;
    darwin) OS_STR="macos" ;;
    *) die "Unsupported OS: $OS" ;;
esac
case "$ARCH" in
    x86_64)        ARCH_STR="x86_64" ;;
    aarch64|arm64) ARCH_STR="aarch64" ;;
    *) die "Unsupported architecture: $ARCH" ;;
esac
PLATFORM="${OS_STR}-${ARCH_STR}"
ok "Platform: $PLATFORM"

# ── Step 3: 下载 ──────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/5] Downloading evocli ${VERSION}...${NC}"

# 版本号去掉前缀 v
VER_NUM="${VERSION#v}"
PKG_NAME="evocli-v${VER_NUM}-${PLATFORM}"
PKG_FILE="${PKG_NAME}.tar.gz"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${PKG_FILE}"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

info "URL: $DOWNLOAD_URL"
curl -fsSL --progress-bar "$DOWNLOAD_URL" -o "$TMP_DIR/$PKG_FILE" \
    || die "Download failed. Check the URL or try specifying --version manually."
ok "Downloaded $PKG_FILE"

# ── Step 4: 解压 & 运行 setup ─────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/5] Installing...${NC}"

mkdir -p "$INSTALL_DIR"
tar -xzf "$TMP_DIR/$PKG_FILE" -C "$TMP_DIR"
EXTRACTED="$TMP_DIR/$PKG_NAME"
[[ -d "$EXTRACTED" ]] || die "Unexpected archive structure. Expected directory: $PKG_NAME"

# 拷贝二进制
cp "$EXTRACTED/evocli" "$INSTALL_DIR/evocli"
chmod +x "$INSTALL_DIR/evocli"
ok "Binary installed: $INSTALL_DIR/evocli"

# 拷贝 Python Soul（放在 binary 同级的 evocli-soul/ 目录）
SOUL_DST="$INSTALL_DIR/evocli-soul"
rm -rf "$SOUL_DST"
cp -r "$EXTRACTED/evocli-soul" "$SOUL_DST"
ok "Python Soul installed: $SOUL_DST"

# 拷贝辅助脚本（download_models.py, preflight.py, setup.sh 等）
for f in setup.sh setup_env.py download_models.py preflight.py; do
    [[ -f "$EXTRACTED/$f" ]] && cp "$EXTRACTED/$f" "$INSTALL_DIR/$f"
done

# 运行 Python 环境 setup
info "Setting up Python environment (first run: 2-5 min)..."
bash "$INSTALL_DIR/setup.sh" \
    || warn "setup.sh encountered an error — run manually: bash $INSTALL_DIR/setup.sh"

# ── Step 5: PATH 配置 ─────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[5/5] Configuring PATH...${NC}"

# 判断 INSTALL_DIR 是否已在 PATH
if echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
    ok "$INSTALL_DIR is already in PATH"
elif [[ "${EVOCLI_NO_MODIFY_PATH:-0}" == "1" ]]; then
    warn "Skipping PATH modification (EVOCLI_NO_MODIFY_PATH=1)"
    warn "Add manually: export PATH=\"\$PATH:$INSTALL_DIR\""
else
    # 写入 shell rc
    SHELL_RC=""
    case "${SHELL:-}" in
        */zsh)  SHELL_RC="$HOME/.zshrc" ;;
        */fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
        *)      SHELL_RC="$HOME/.bashrc" ;;
    esac

    PATH_LINE="export PATH=\"\$PATH:$INSTALL_DIR\""
    if [[ -n "$SHELL_RC" ]] && ! grep -qF "$INSTALL_DIR" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# EvoCLI" >> "$SHELL_RC"
        echo "$PATH_LINE" >> "$SHELL_RC"
        ok "Added to $SHELL_RC"
    fi
    export PATH="$PATH:$INSTALL_DIR"
    ok "PATH updated for current session"
fi

# ── 完成 ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}${BOLD}✅  EvoCLI ${VERSION} installed!${NC}"
echo ""
echo "  Next steps:"
echo "    evocli init    ← configure LLM provider + API key"
echo "    evocli doctor  ← verify installation"
echo "    evocli         ← start AI coding session"
echo ""
echo -e "  ${GRAY}To uninstall:  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/uninstall.sh | bash${NC}"
echo ""
