# CodeChunkIndex E2E 测试计划

**文件**: `evocli_soul/code_chunks.py`  
**测试文件**: `tests/test_code_chunks_e2e.py`  
**运行命令**: `pytest evocli-soul/tests/test_code_chunks_e2e.py -v`

---

## 背景

`CodeChunkIndex` 是 EvoCLI GraphRAG 的核心组件：
- 将函数/类体向量化存入 LanceDB
- 支持语义代码搜索、blast_radius 内容召回、社区摘要生成

测试策略：
- **纯函数**（`extract_body`、`_body_hash`）：直接调用，无外部依赖
- **LanceDB 相关**：monkeypatch `Path.home()` 指向 `tmp_path`，避免污染真实 `~/.evocli`
- **Embedder**：mock 掉，返回确定性伪向量（CI 无 API Key）
- **LLM client**：`AsyncMock`，返回固定摘要字符串

---

## Feature 1 — `extract_body`

### 功能
从磁盘文件按行号范围提取函数/类体文本。

### 两种模式
| 模式 | 触发条件 | 行为 |
|------|----------|------|
| 显式范围 | `line_end` 不为 None | 返回 `[line_start, line_end]` 行 |
| 缩进推断 | `line_end=None` | 扫描到缩进退出外层作用域时截止 |

### 期望行为
- 返回多行字符串，首行是函数定义行
- 文件不存在 → `None`
- `line_start` 越界 → `None`
- 行数超过 `max_lines` → 截断
- 最小行数 `MIN_BODY_LINES=1`，单行函数也能提取

### 测试用例
| 用例 | 输入 | 期望输出 |
|------|------|----------|
| 显式范围正常提取 | Python 函数文件，`line_start=1, line_end=4` | 包含函数定义的 4 行字符串 |
| 缩进推断 Python | 有缩进的函数体 | 自动在缩进退出时截止 |
| 文件不存在 | 路径不存在 | `None` |
| line_start 越界 | `line_start=9999` | `None` |
| max_lines 截断 | 函数体 200 行，`max_lines=5` | 最多 5 行 |
| 单行函数 | `def f(): return 1` | 返回该行 |

---

## Feature 2 — `_body_hash`

### 功能
对函数体文本生成 16 位 MD5 十六进制摘要，用于增量索引的去重判断。

### 期望行为
- 返回值固定为 16 个十六进制字符
- 相同输入 → 相同输出（确定性）
- 不同输入 → 不同输出（无碰撞）

### 测试用例
| 用例 | 输入 | 期望输出 |
|------|------|----------|
| 长度固定 | 任意字符串 | 长度 == 16 |
| 确定性 | 同字符串调用两次 | 两次结果相同 |
| 唯一性 | `"def foo"` vs `"def bar"` | 两值不同 |

---

## Feature 3 — Table 初始化 (`_get_table`)

### 功能
创建或打开 LanceDB `code_chunks` 表，建立完整 schema。

### 期望行为
- 表不存在时自动创建，schema 包含所有必填字段
- 特别验证新增字段 `rust_sym_id` 存在
- 第二次调用返回同一对象（缓存），不重复创建
- LanceDB 不可用时返回 `None`，不抛异常

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 首次创建 | 新 tmp_path | 返回非 None 表对象 |
| Schema 完整性 | 插入一行后读取字段 | 含 `id, rust_sym_id, symbol, file, body, vector` 等 |
| 幂等性 | 调用两次 `_get_table()` | 两次返回同一表对象 |
| LanceDB 缺失 | mock `lancedb.connect` 抛异常 | 返回 `None`，无异常 |

---

## Feature 4 — `ingest_symbols`

### 功能
接受 Rust 符号列表 → 提取函数体 → embed → 写入 LanceDB。

### 期望行为
- 返回 `{ingested, skipped, errors}` 计数
- `kind` 不在白名单（function/method/class/impl/struct/def）时跳过
- 相同 body_hash 二次 ingest → 全部 skipped
- `force=True` 强制重新 embed
- `rust_sym_id` 字段正确写入 LanceDB

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 正常 ingest | 2 个函数符号，有真实文件 | `ingested == 2, errors == 0` |
| kind 过滤 | constant/type 类型符号 | `ingested == 0`（被跳过） |
| 增量去重 | 相同符号 ingest 两次 | 第二次 `skipped == 2` |
| force 重建 | 相同符号 + `force=True` | 第二次 `ingested == 2` |
| rust_sym_id 写入 | ingest 后查 LanceDB | 行的 `rust_sym_id` == 传入的 `id` |
| 文件不存在 | 符号指向不存在的文件 | `ingested == 0`（extract_body 返回 None） |

---

## Feature 5 — `search`

### 功能
用自然语言 query 向量搜索最相似的代码块。

### 期望行为
- 返回 `list[dict]`，每项含 `id, symbol, file, body` 等字段
- `top_k` 限制返回数量
- `language` 过滤只返回对应语言
- `kind` 过滤只返回对应类型
- `file_filter` 按文件路径子串过滤
- 空索引返回 `[]`

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 正常搜索 | ingest 3 条后 search | 返回 ≤ top_k 条结果 |
| top_k 限制 | `top_k=1` | 最多 1 条 |
| language 过滤 | ingest rust+python 后 `language="rust"` | 只返回 rust 条目 |
| kind 过滤 | `kind="class"` | 只返回 class 类型 |
| file_filter | `file_filter="utils"` | 只返回路径含 utils 的条目 |
| 空索引 | 未 ingest 直接 search | 返回 `[]` |

---

## Feature 6 — `get_body`

### 功能
按 chunk ID（`file:line` 格式）精确获取函数体文本。

### 期望行为
- 找到 → 返回 body 字符串
- 未找到 → 返回 `None`
- LanceDB 不可用 → 返回 `None`

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 命中 | ingest 后用对应 chunk_id 查询 | 返回 body 字符串，非空 |
| 未命中 | 随机 chunk_id | 返回 `None` |

---

## Feature 7 — `get_body_by_rust_id`（新功能）

### 功能
按 Rust 端生成的 symbol UUID 获取函数体，用于 `blast_radius` / `knowledge_graph` 结果的内容召回。

### 期望行为
- 找到匹配 `rust_sym_id` 的行 → 返回 body
- 未找到 → 返回 `None`
- 旧版索引（无该列）→ 静默返回 `None`，不抛异常

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 按 UUID 命中 | ingest 时传入 `id="uuid-123"` 后查询 | 返回 body |
| UUID 不存在 | 用不匹配 UUID 查询 | 返回 `None` |
| 旧索引兼容 | mock 表的 `.where()` 抛 ColumnNotFoundError | 返回 `None`，不崩溃 |

---

## Feature 8 — `get_bodies_for_symbols`

### 功能
按符号名批量获取代码体，用于 community_summaries 的 prompt 构建。

### 期望行为
- 返回 `list[dict]`，含 `symbol, file, body, line_start, kind`
- 空列表输入 → 直接返回 `[]`（不查 DB）
- 多个符号同时匹配 → 全部返回

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 正常批量查 | ingest 2 个符号后按名查询 | 返回 2 条 |
| 空输入 | `symbol_names=[]` | 返回 `[]` |
| 部分匹配 | 查 3 个名字，只有 2 个已 ingest | 返回 2 条 |

---

## Feature 9 — `stats`

### 功能
返回当前项目索引的统计摘要。

### 期望行为
- 返回 `{total: N, by_language: {...}, by_kind: {...}}`
- 空索引返回 `{total: 0}`
- LanceDB 不可用返回 `{total: 0, error: "..."}`

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 空索引 | 未 ingest 调用 | `total == 0` |
| 有数据 | ingest 2 rust + 1 python 后 | `total == 3, by_language["rust"] == 2` |

---

## Feature 10 — `generate_community_summaries`

### 功能
对每个代码社区：获取成员函数体 → 拼 prompt → 调 LLM → 返回摘要列表。

### 期望行为
- prompt 包含 `sym_name in file` 格式的 snippet header（新修复验证）
- 按社区大小降序处理，`max_communities` 限制数量
- LLM 失败时跳过该社区，继续其余
- 无符号的社区跳过
- 找不到代码体的社区跳过

### 测试用例
| 用例 | 操作 | 期望 |
|------|------|------|
| 正常生成 | 1 个社区，ingest 过符号，mock LLM | 返回 1 条摘要，含 `summary, label, symbols` |
| prompt 含符号名 | 捕获 mock LLM 的调用参数 | 调用参数含 `"sym_name in file"` 格式 |
| 按大小排序 | 3 个大小不同的社区 | 处理顺序为符号数量降序 |
| max_communities 限制 | 5 个社区，`max_communities=2` | 返回 2 条 |
| LLM 报错 | mock LLM 抛异常 | 返回 `[]`，不崩溃 |
| 无符号社区 | `symbols=[]` | 跳过，返回 `[]` |
| 无代码体 | 社区符号未被 ingest | 跳过，返回 `[]` |

---

## 测试隔离策略

```
每个 LanceDB 测试用例：
  tmp_path (pytest fixture)
    └─ monkeypatch Path.home() → tmp_path
         └─ 真实 LanceDB 实例写入 tmp_path/.evocli/vectors/
  
CodeChunkIndex._embed 全部 mock：
  返回 hash-seeded 的 768-dim 伪向量
  相同文本 → 相同向量（保证 search 结果确定性）
  
LLM client 使用 AsyncMock：
  complete_for_task → "Handles HTTP routing and middleware."
```

## CI 兼容性

- `lancedb` 未安装时所有 LanceDB 相关用例自动 `pytest.skip`
- 不产生任何真实网络请求（embedder + LLM 全 mock）
- 不写入 `~/.evocli`（Path.home 已重定向）
