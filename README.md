# EvoCLI

**AI 编程 Runtime — 本地优先，长期记忆，自我进化**

EvoCLI 是一个高性能的 AI 编程助手，采用 Rust Host + Python Soul 双引擎架构，在终端中提供全屏 TUI 界面，支持长期记忆、可执行技能（Skill）、代码智能索引，以及多 LLM 提供商。

```
┌─ Rust Host (不可变核心) ──────────────────────────────────┐
│  TUI · 安全检查 · IPC调度 · SQLite存储 · Git · 代码索引    │
└──────────────────────────────────────────────────────────┘
              ↕ JSON-RPC over stdin/stdout
┌─ Python Soul (可进化层) ──────────────────────────────────┐
│  LLM调用 · Agent编排 · Skill执行 · 记忆蒸馏 · 进化引擎    │
└──────────────────────────────────────────────────────────┘
```

---

## 功能特性

- **全屏 TUI** — ratatui 打造的现代终端界面，流式响应，token 进度条，思考动画
- **62 Rust 工具** — 文件系统、Git、Shell、代码智能、记忆、审批等，安全黑名单保护
- **多 LLM 支持** — OpenAI、Anthropic、DeepSeek、Ollama，通过 LiteLLM 路由
- **长期记忆** — LanceDB 向量记忆（中英双语 jina embeddings）+ SQLite FTS fallback
- **Skill 系统** — TOML 定义的可执行技能，支持多步骤、LLM 分析、审批流
- **代码智能** — tree-sitter AST + BM25 + PageRank 混合搜索
- **MCP 集成** — 作为 MCP server/client，与其他 AI 工具互联
- **进化引擎** — PrefixSpan 模式检测，自动归纳 Skill 草稿
- **交互提示** — AI 可向用户展示多选项弹窗（`prompt.choice`），支持自定义输入

---

## 快速开始

### 下载预编译版本

前往 [Releases](https://github.com/bambooqj/evocli/releases) 下载对应平台压缩包，解压后：

```powershell
# Windows
.\setup.ps1          # 首次：自动安装 Python 环境（约 2-5 分钟）
.\evocli.exe init    # 配置 LLM 提供商和 API Key
.\evocli.exe         # 启动 TUI
```

```bash
# Linux / macOS
bash setup.sh        # 首次：自动安装 Python 环境
./evocli init        # 配置 LLM 提供商和 API Key
./evocli             # 启动 TUI
```

### 从源码构建

**依赖：** Rust 1.82+、Python 3.11+

```bash
git clone https://github.com/bambooqj/evocli.git
cd evocli

# 开发模式运行
$env:EVOCLI_SOUL = "evocli-soul/evocli_soul/main.py"
cargo run -p evocli

# Release 构建
cargo build --release -p evocli
```

---

## 配置

配置文件位于 `~/.evocli/config.toml`，运行 `evocli init` 交互式配置，或参考 [docs/config.toml.example](docs/config.toml.example)。

**推荐配置方式：**
```bash
evocli init          # 交互式向导，API Key 存入系统密钥链
evocli doctor        # 健康检查（10 项）
```

**API Key 不要写入 config.toml**，请使用环境变量或系统密钥链：
```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
export OPENAI_API_KEY="sk-..."          # OpenAI
export DEEPSEEK_API_KEY="..."           # DeepSeek
```

---

## TUI 快捷键

| 按键 | 功能 |
|---|---|
| `Enter` | 发送消息 |
| `Shift+Enter` | 插入换行（多行输入）|
| `Tab` | `/` 命令补全 |
| `Esc` | 中断生成 / 关闭弹窗 |
| `PageUp/Down` | 滚动聊天历史 |
| `Home/End` | 跳到最旧/最新消息 |
| `F12` | 切换 Debug 日志面板 |
| `Ctrl+C` | 退出 |

---

## 斜杠命令

```
/help               显示所有命令
/chain <symbol>     查看函数调用链
/skills             列出可用技能
/skill <name>       运行技能
/cost               查看会话费用和 token 统计
/index              重新索引项目代码
/memory <query>     搜索项目记忆
/clear              清空聊天历史
/log [N]            显示最近 N 行日志（默认 30）
```

---

## 项目结构

```
evocli/
├── crates/
│   ├── host/            CLI 入口、TUI 启动、Config、Git、Logging
│   ├── soul_bridge/     Rust↔Python JSON-RPC 桥
│   ├── protocol/        ToolCall/Event 类型定义
│   ├── tui/             ratatui 全屏 UI（App/ui/event_handler）
│   ├── code_intel/      符号索引（tree-sitter + LSP）
│   ├── knowledge_graph/ BM25 + 社区检测 + 爆炸半径分析
│   ├── mem_router/      LLM 标签 → CPU 分类器（自训练）
│   ├── contracts/       Task Contract + Checkpoint（SQLite）
│   ├── tools/           安全命令白名单执行
│   └── mcp/             MCP server/client
├── evocli-soul/
│   └── evocli_soul/     Python Soul（43 个模块）
│       ├── agent.py         Pydantic AI Agent + LiteLLM
│       ├── memory_client.py LanceDB + fastembed 向量记忆
│       ├── skill_engine.py  TOML Skill 加载与执行
│       ├── context_engine.py Token 预算与上下文组装
│       ├── evolution/       进化引擎（7 个子模块）
│       └── handlers/        66 个 RPC handler
├── docs/                文档和配置示例
├── scripts/             构建和部署脚本
└── skills/              内置 Skill 定义
```

---

## 安全模型

EvoCLI 默认使用**黑名单模式**：AI 可执行任何命令，但以下危险操作永久禁止：

```
rm -rf /  •  dd if=  •  mkfs  •  format c:  •  :(){ :|: }  •  ...
```

用户可在 `~/.evocli/config.toml` 中追加自定义限制（此文件对 AI 不可见，防止自我修改安全策略）：

```toml
[security]
extra_blocked_patterns = ["curl * | bash"]
extra_denied_paths = ["/prod"]
```

---

## 架构边界

```
Rust Host（不可变核心）    Python Soul（可进化层）
─────────────────────────────────────────────────
TUI 渲染                   LLM 调用（LiteLLM）
安全检查（黑名单）           Agent 编排（Pydantic AI）
IPC 调度                   Skill 执行
SQLite 存储                记忆蒸馏
Git 操作                   Context 组装
代码索引                   进化逻辑
```

**核心约束**：Python Soul 不能直接访问文件系统、Shell、SQLite——所有操作必须通过 `bridge.call(tool, params)` 转发给 Rust Host。

---

## 开发

```bash
# 编译检查
cargo check                    # 全 workspace
cargo check -p evocli-tui      # 单 crate

# 测试
cargo test -p contracts
cargo test -p code_intel

# Python Soul 测试
echo '{"id":"1","method":"tracer.ping","params":{}}' | \
  python evocli-soul/evocli_soul/main.py

# 构建发行版
.\scripts\build_dist.ps1 -Clean   # Windows
```

---

## 许可证

MIT OR Apache-2.0
