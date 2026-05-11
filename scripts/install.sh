#!/bin/bash
# install.sh — EvoCLI 一键安装脚本（Section 13）
# 支持 macOS 和 Linux

set -e

EVOCLI_VERSION="${EVOCLI_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
SOUL_VERSION="${SOUL_VERSION:-0.1.0}"

echo "🚀 Installing EvoCLI..."

# Detect platform
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH_STR="x86_64" ;;
    aarch64|arm64) ARCH_STR="aarch64" ;;
    *)        echo "❌ Unsupported architecture: $ARCH"; exit 1 ;;
esac

# Create install directory
mkdir -p "$INSTALL_DIR"

echo ""
echo "Option 1: Build from source (recommended)"
echo "  git clone https://github.com/evocli/evocli"
echo "  cd evocli && cargo build --release"
echo "  cp target/release/evocli $INSTALL_DIR/"

echo ""
echo "Option 2: Install Python Soul"
echo "  pip install evocli-soul"
echo "  # or: uv pip install evocli-soul"

echo ""
echo "After installation:"
echo "  evocli init    # Configure API key and provider"
echo "  evocli doctor  # Verify installation"
echo "  evocli         # Start AI coding session"

echo ""

# Check if cargo is available for local build
if command -v cargo &>/dev/null; then
    echo "✅ Rust/Cargo found. You can build from source:"
    echo "  cargo install --path crates/host  # if in evocli repo"
fi

# Check if Python is available for Soul install
if command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
    echo "✅ Python/pip found. Install Soul with:"
    echo "  pip install evocli-soul"
fi

echo ""
echo "📚 Documentation: https://github.com/evocli/evocli"
