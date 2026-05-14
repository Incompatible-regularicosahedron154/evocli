## 工具使用规则

### 优先级（从高到低）
1. **代码智能工具**（只读，零风险）：`symbol_lookup`, `assume_*`, `impact_check`, `code_intel_*`
2. **搜索工具**（只读）：`search_code`, `shell_grep`, `shell_find`
3. **文件读取**（只读）：`fs_read`, `shell_cat`, `shell_head`, `shell_tail`
4. **构建/测试**（写入，可逆）：`shell_run("cargo build")`, `shell_run("pytest")`
5. **代码修改**（写入，影响代码）：`fs_apply_search_replace`（首选）, `fs_write`（新建文件）, `fs_apply_diff`（备选）
6. **版本控制**（写入，持久化）：`git_commit`, `git_snapshot`

### 关键规则
- **先读后写**：修改文件前必须先读取其内容
- **impact_check 优先**：修改被多处调用的函数前，先用 `impact_check` 评估风险
- **git_snapshot 安全网**：执行大规模修改前，先创建 snapshot
- **approval_request 触发条件**：删除文件、修改公共 API、影响半径为 CRITICAL 时，必须请求确认

### 禁止行为
- ❌ 不读取文件内容直接修改
- ❌ 删除或覆盖文件而不先确认其内容
- ❌ 在测试失败时通过删除测试"修复"问题
- ❌ 硬编码 API Key 或密码
- ❌ 使用 `rm -rf`、`chmod 777` 等危险命令
