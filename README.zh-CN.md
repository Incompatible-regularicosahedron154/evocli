# EvoCLI

[![CI](https://github.com/bambooqj/evocli/actions/workflows/ci.yml/badge.svg)](https://github.com/bambooqj/evocli/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT%2FApache--2.0-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-1.85%2B-orange.svg)](https://www.rust-lang.org)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

**AI 编程 Runtime — 本地优先，长期记忆，自我进化**

[English](README.md) | 简体中文

---

## 特性

### 核心能力
- **全屏 TUI** — ratatui 打造的现代终端界面，流式响应，实时 token 上下文进度条，思考动画，上下文构建阶段进度提示
- **64 个 AI 可见工具** — 文件系统、Git、Shell（Rust 原生跨平台）、代码智能、记忆、网页抓取、审批提示
- **长期记忆** — LanceDB 向量记忆（jina-embeddings-v2-base-zh，768 维中英双语）+ SQLite FTS 降级
- **多 LLM 支持** — OpenAI、Anthropic、DeepSeek、Ollama，通过 LiteLLM 路由，支持任何 OpenAI 兼容 API；支持按角色配置不同模型

### 智能工具系统
- **动态工具路由** — 根据意图每次只发送 12 个相关工具（节省 ~55% context token）。三阶段流水线：关键词门控 → 标签匹配 → embedding 相似度
- **工具流自动学习** — 重复使用的工具序列（如 `symbol_lookup → fs_read_range → fs_apply_search_replace → fs_lint_file`）会被自动抽象为命名工作流，下次遇到类似任务时自动建议或执行
- **原生网页抓取** — `web.fetch` 内置于 Rust（reqwest + scraper + htmd）：抓取任意 URL 并返回干净的 Markdown。无需浏览器、无需 curl、无需 Python HTTP 依赖
- **可执行技能** — TOML 定义的多步骤工作流，AI 可自动发现并执行

### Shell 层（跨平台 Rust 原生）

所有 Shell 工具都是纯 Rust 实现，不依赖系统 Shell：

| 工具 | 实现方式 |
|---|---|
| `shell.ls`, `shell.find` | `std::fs::read_dir` + `walkdir` |
| `shell.cat`, `shell.head`, `shell.tail`, `shell.wc` | `std::fs::read_to_string` |
| `shell.mkdir`, `shell.mv`, `shell.cp`, `shell.touch`, `shell.rm` | `std::fs` 操作 |
| `shell.grep` | Rust regex + walkdir |
| `shell.run` | Windows：bash (Git Bash/WSL) → pwsh → powershell 降级；Linux/macOS：sh -c |

### 安全与配置
- **安全配置全部在 `config.toml`** — 允许命令列表、危险模式黑名单、路径禁止列表均可在配置文件中完整替换，无硬编码限制
- **默认黑名单模式** — AI 可执行任何白名单命令；`config.toml` 是唯一的代码级保护文件
- **项目本地配置** — `.evocli/config.toml` 项目级配置深度合并全局配置

---

## 快速开始

### 下载预编译版本

前往 [Releases](https://github.com/bambooqj/evocli/releases) 下载对应平台压缩包。

```powershell
# Windows
.\setup.ps1          # 首次：自动安装 Python 环境（约 2-5 分钟）
.\evocli.exe init    # 配置 LLM 提供商和 API Key
.\evocli.exe         # 启动 TUI
```

```bash
# Linux / macOS
bash setup.sh
./evocli init
./evocli
```

### 从源码构建

**依赖**：Rust 1.85+，Python 3.11+

```bash
git clone https://github.com/bambooqj/evocli.git
cd evocli

# 开发模式
$env:EVOCLI_SOUL = "evocli-soul/evocli_soul/main.py"   # Windows
# export EVOCLI_SOUL="evocli-soul/evocli_soul/main.py"  # Linux/macOS
cargo run -p evocli
```

### 配置 API Key

```bash
evocli init   # 交互式向导，API Key 存入系统密钥链

# 或直接设置环境变量：
export OPENAI_API_KEY="sk-..."          # OpenAI / 兼容 API
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic Claude
export DEEPSEEK_API_KEY="..."           # DeepSeek
```

完整配置选项见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

---

## TUI 快捷键

| 按键 | 功能 |
|---|---|
| `Enter` | 发送消息 |
| `Shift+Enter` | 插入换行（多行输入）|
| `Tab` | 自动补全 `/` 命令 |
| `Esc` | 中断生成 / 关闭弹窗 |
| `PageUp / PageDown` | 滚动聊天历史 |
| `Home / End` | 跳到最旧 / 最新消息 |
| `Alt+Up / Alt+Down` | 快速滚动 5 行 |
| `Ctrl+Y` | 复制最后一条 AI 消息到剪贴板 |
| `Ctrl+L` | 清屏 |
| `F12` | 切换 Debug 日志面板 |
| `Ctrl+C` | 退出 |

**文本选择与复制：**
- **默认模式**（`enable_mouse = false`）：点击拖拽进行原生终端文本选择，Ctrl+C 复制
- **鼠标模式**（`enable_mouse = true`）：鼠标滚轮滚动消息列表，Ctrl+Y 复制最后一条 AI 消息

```toml
# ~/.evocli/config.toml
[tui]
enable_mouse = false   # false = 原生终端选择（默认）
                       # true  = 鼠标滚轮滚动
```

---

## 斜杠命令

| 命令 | 说明 |
|---|---|
| `/help` | 显示所有命令和快捷键 |
| `/compress` | 压缩会话历史，释放 context 空间 |
| `/flows` | 列出自动学习的工具流 |
| `/add <file>` | 将文件固定到每轮上下文 |
| `/chain <symbol>` | 查看函数调用链 |
| `/skills` | 列出可用技能 |
| `/skill <name>` | 运行技能 |
| `/cost` | 会话费用和 token 统计 |
| `/index` | 重新索引项目代码 |
| `/memory <query>` | 搜索项目记忆 |
| `/clear` | 清空聊天历史 |
| `/log [N]` | 显示最近 N 行日志（默认 30）|

---

## 配置说明

所有行为由 `~/.evocli/config.toml`（全局）和 `.evocli/config.toml`（项目本地）控制，项目配置深度合并全局配置。

```toml
[llm]
base_url = "https://api.openai.com/v1"   # 任何 OpenAI 兼容端点
# api_key 通过 evocli init 存入系统密钥链

[llm.tiers]
fast  = "gpt-4o-mini"   # 快速任务：提交信息、lint、问答
smart = "gpt-4o"        # 复杂任务：架构分析、重构

[llm.roles.architect]   # 按角色配置不同模型/provider
model    = "claude-opus-4-5"
base_url = "https://api.anthropic.com"

[agent]
first_chunk_timeout_s = 120  # 等待首个响应的超时时间（秒），默认 120
max_tool_calls        = 20

[tui]
enable_mouse = false   # true = 鼠标滚轮滚动；false = 原生终端选择

[security]
allow_all_commands     = true        # 黑名单模式（默认）
allowed_commands       = ["cargo", "git", "python", ...]  # 完整白名单（可完全替换）
blocked_patterns       = ["rm -rf /", "mkfs", ...]        # 危险模式（可完全替换）
extra_allowed_commands = ["docker", "kubectl"]            # 追加到白名单
extra_blocked_patterns = ["curl | bash"]                  # 追加到黑名单
```

完整参考：[docs/CONFIGURATION.md](docs/CONFIGURATION.md)

---

## 安全模型

EvoCLI 使用**配置驱动**的安全模型 — 所有列表都在 `config.toml` 中，无硬编码限制：

- `allow_all_commands = true`（默认）— 黑名单模式：AI 可执行任何命令，除 `blocked_patterns` 中的危险操作
- `allow_all_commands = false` — 严格白名单：只允许 `allowed_commands` + `extra_allowed_commands`
- `allow_all_paths = true`（默认）— 无路径限制；通过 `denied_paths` 添加限制

唯一的代码级保护：`~/.evocli/config.toml` 本身永久对 AI 不可见，防止 AI 修改自身安全策略或读取 API Key。

---

## 项目结构

```
evocli/
├── crates/
│   ├── host/            CLI 入口、配置、安全、Git、网页抓取
│   ├── soul_bridge/     Rust↔Python JSON-RPC 桥
│   ├── tui/             全屏 TUI（ratatui）— 鼠标配置、Ctrl+Y 复制
│   ├── code_intel/      符号索引（tree-sitter + BM25 + LSP）
│   ├── knowledge_graph/ 爆炸半径 + 社区检测
│   ├── mem_router/      自训练记忆分类器
│   ├── tools/           安全命令执行（跨平台 Rust 原生 Shell）
│   └── mcp/             MCP server/client
├── evocli-soul/
│   └── evocli_soul/     Python Soul（66 个模块）
│       ├── agent.py           Pydantic AI Agent（64 个工具）+ LiteLLM
│       ├── tool_registry.py   所有 66 个工具的统一注册表
│       ├── tool_router.py     意图驱动动态工具选择 + 记忆加权
│       ├── tool_flow_miner.py 工具流自动学习与执行
│       ├── memory_client.py   LanceDB 向量记忆
│       ├── skill_engine.py    TOML Skill 加载执行
│       ├── context_engine.py  Token 预算 + 上下文组装 + 进度事件
│       └── handlers/          RPC handler
├── docs/          文档
├── scripts/       构建和部署脚本
└── skills/        内置技能定义
```

---

## 文档导航

| 文档 | 说明 |
|---|---|
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | 所有配置项：LLM、agent、security、tui、context |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 双引擎设计、Crate 架构、JSON-RPC、记忆/安全 |
| [docs/TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md) | 全部 64+ Python 工具 + Rust 工具，含参数和返回值 |
| [docs/SKILLS_GUIDE.md](docs/SKILLS_GUIDE.md) | TOML 技能编写、所有 action、变量插值、Prompt 模板 |
| [docs/MEMORY_SYSTEM.md](docs/MEMORY_SYSTEM.md) | LanceDB、蒸馏、嵌入模型、上下文注入 |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | JSON-RPC 协议规范、事件类型、handler 编写示例 |
| [docs/TUI_INTERNALS.md](docs/TUI_INTERNALS.md) | App 状态机、事件循环、渲染器、虚拟滚动 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | v0.1.0 已完成 · v0.2.0 计划 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、构建、测试、代码风格、PR 流程 |
| [CHANGELOG.md](CHANGELOG.md) | 版本发布历史 |

## 参与贡献

欢迎所有形式的贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 开始参与。

- **Bug 报告** — 提 issue 并标记 `bug`
- **功能建议** — 提 issue 并标记 `enhancement`
- **路线图** — 查看 [docs/ROADMAP.md](docs/ROADMAP.md)

## 许可证

双重许可，你可以选择：
- MIT License ([LICENSE](LICENSE))
- Apache License, Version 2.0
