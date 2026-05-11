#!/usr/bin/env bash
# uninstall.sh — EvoCLI 卸载脚本 (Linux / macOS)
#
# 用法：
#   bash uninstall.sh           # 交互确认后卸载（保留用户数据）
#   bash uninstall.sh --purge   # 同时删除所有用户数据（config、memory、skills）
#   bash uninstall.sh --yes     # 跳过确认提示
#
# 本脚本会删除：
#   - evocli 二进制（从 PATH 中搜索或从默认安装目录）
#   - ~/.evocli/venv/         Python 虚拟环境
#   - ~/.evocli/bin/          uv 包管理器（若由 EvoCLI 安装）
#   - ~/.evocli/logs/         日志文件
#   - ~/.evocli/models/       向量模型缓存（~570 MB）
#
# --purge 额外删除（用户数据，不可恢复）：
#   - ~/.evocli/config.toml   用户配置
#   - ~/.evocli/data/         记忆与 JSONL 存储
#   - ~/.evocli/skills/       全局技能
#   - ~/.evocli/sessions/     会话历史
#   - ~/.evocli/events.db     事件数据库
#   - ~/.evocli/jobs.db       任务队列数据库
#   - ~/.evocli/contracts.db  任务合约数据库
#   - ~/.evocli/              整个目录（若已空）

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; GRAY='\033[0;37m'; BOLD='\033[1m'; NC='\033[0m'

ok()    { echo -e "  ${GREEN}✓${NC}  $*"; }
info()  { echo -e "  ${YELLOW}→${NC}  $*"; }
skip()  { echo -e "  ${GRAY}–${NC}  $* ${GRAY}(not found, skipping)${NC}"; }
die()   { echo -e "\n  ${RED}✗  ERROR:${NC} $*\n" >&2; exit 1; }

PURGE=0
AUTO_YES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge) PURGE=1; shift ;;
        --yes|-y) AUTO_YES=1; shift ;;
        --help|-h)
            echo "Usage: bash uninstall.sh [--purge] [--yes]"
            echo ""
            echo "  --purge  Also remove user data (config, memory, skills, sessions)"
            echo "  --yes    Skip confirmation prompt"
            exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

EVOCLI_HOME="$HOME/.evocli"

# ── 横幅 ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}━━━ EvoCLI Uninstaller (Linux / macOS) ━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [[ $PURGE -eq 1 ]]; then
    echo -e "  ${RED}${BOLD}Mode: PURGE — all user data will be permanently deleted!${NC}"
else
    echo -e "  Mode: standard (user data in ~/.evocli/ will be preserved)"
fi
echo ""

# ── 确认提示 ──────────────────────────────────────────────────────────
if [[ $AUTO_YES -eq 0 ]]; then
    if [[ $PURGE -eq 1 ]]; then
        read -r -p "  This will delete EvoCLI AND all your memory/skills/config. Continue? [y/N] " confirm
    else
        read -r -p "  This will remove EvoCLI binaries and Python environment. Continue? [y/N] " confirm
    fi
    case "$confirm" in
        [yY][eE][sS]|[yY]) ;;
        *) echo "  Aborted."; exit 0 ;;
    esac
    echo ""
fi

# ── 辅助函数 ──────────────────────────────────────────────────────────
remove_dir() {
    local path="$1" label="$2"
    if [[ -d "$path" ]]; then
        rm -rf "$path"
        ok "Removed $label: $path"
    else
        skip "$label"
    fi
}

remove_file() {
    local path="$1" label="$2"
    if [[ -f "$path" ]]; then
        rm -f "$path"
        ok "Removed $label: $path"
    else
        skip "$label"
    fi
}

# ── Step 1: 查找并删除 evocli 二进制 ──────────────────────────────────
echo -e "${YELLOW}[1/4] Removing evocli binary...${NC}"

BINARY_FOUND=0
# 搜索 PATH 中的 evocli
while IFS= read -r -d ':' dir; do
    if [[ -f "$dir/evocli" ]]; then
        rm -f "$dir/evocli"
        ok "Removed binary: $dir/evocli"
        # 同时清理同目录下的 Soul 和辅助脚本
        [[ -d "$dir/evocli-soul" ]] && rm -rf "$dir/evocli-soul" && ok "Removed Soul: $dir/evocli-soul"
        for f in setup.sh setup_env.py download_models.py preflight.py; do
            [[ -f "$dir/$f" ]] && rm -f "$dir/$f"
        done
        BINARY_FOUND=1
    fi
done <<< "$PATH:"

# 检查默认安装位置
for default_dir in "$HOME/.evocli/app" "$HOME/.local/bin" "/usr/local/bin"; do
    if [[ -f "$default_dir/evocli" ]] && [[ "$BINARY_FOUND" -eq 0 ]]; then
        rm -f "$default_dir/evocli"
        ok "Removed binary: $default_dir/evocli"
        [[ -d "$default_dir/evocli-soul" ]] && rm -rf "$default_dir/evocli-soul" && ok "Removed Soul: $default_dir/evocli-soul"
        BINARY_FOUND=1
    fi
done

[[ $BINARY_FOUND -eq 0 ]] && skip "evocli binary (not found in PATH or default locations)"

# ── Step 2: 删除 Python 环境（不可恢复，但可重建） ─────────────────────
echo ""
echo -e "${YELLOW}[2/4] Removing Python environment...${NC}"
remove_dir "$EVOCLI_HOME/venv"   "Python venv"
remove_dir "$EVOCLI_HOME/bin"    "uv package manager"

# ── Step 3: 删除运行时缓存 ─────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/4] Removing runtime cache...${NC}"
remove_dir  "$EVOCLI_HOME/logs"   "log files"
remove_dir  "$EVOCLI_HOME/models" "embedding model cache"

# ── Step 4: （可选）删除用户数据 ──────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/4] User data...${NC}"
if [[ $PURGE -eq 1 ]]; then
    remove_file "$EVOCLI_HOME/config.toml"  "config"
    remove_dir  "$EVOCLI_HOME/data"         "memory data"
    remove_dir  "$EVOCLI_HOME/skills"       "global skills"
    remove_dir  "$EVOCLI_HOME/sessions"     "session history"
    remove_file "$EVOCLI_HOME/events.db"    "events database"
    remove_file "$EVOCLI_HOME/jobs.db"      "job queue database"
    remove_file "$EVOCLI_HOME/contracts.db" "contracts database"
    remove_file "$EVOCLI_HOME/skill_stats.json" "skill stats"
    remove_file "$EVOCLI_HOME/mcp_servers.json" "MCP server config"
    remove_file "$EVOCLI_HOME/user_tools.toml"  "user tools"
    # 若目录已空则删除整个 ~/.evocli/
    if [[ -d "$EVOCLI_HOME" ]]; then
        remaining=$(find "$EVOCLI_HOME" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
        if [[ "$remaining" -eq 0 ]]; then
            rmdir "$EVOCLI_HOME"
            ok "Removed ~/.evocli/ (now empty)"
        else
            info "~/.evocli/ still has files — leaving in place"
        fi
    fi
else
    skip "user data (use --purge to also remove config/memory/skills)"
    if [[ -d "$EVOCLI_HOME" ]]; then
        echo ""
        echo -e "  ${GRAY}Preserved: $EVOCLI_HOME${NC}"
        echo -e "  ${GRAY}  config.toml, data/, skills/, sessions/ remain untouched.${NC}"
        echo -e "  ${GRAY}  To remove everything: bash uninstall.sh --purge${NC}"
    fi
fi

# ── 清理 shell rc PATH 条目 ───────────────────────────────────────────
for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    if [[ -f "$rc" ]] && grep -q "evocli" "$rc" 2>/dev/null; then
        sed -i.bak '/# EvoCLI/d; /evocli/d' "$rc" 2>/dev/null || true
        rm -f "${rc}.bak"
        ok "Cleaned PATH entry from $rc"
    fi
done

# ── 完成 ──────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}${BOLD}✅  EvoCLI uninstalled.${NC}"
echo ""
if [[ $PURGE -eq 0 ]]; then
    echo "  Your config and memory are preserved in ~/.evocli/"
    echo "  Reinstall anytime:"
    echo "    curl -fsSL https://raw.githubusercontent.com/bambooqj/evocli/main/scripts/install.sh | bash"
fi
echo ""
