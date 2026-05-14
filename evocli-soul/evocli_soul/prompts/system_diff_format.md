## 代码修改格式（Aider SEARCH/REPLACE 风格）

优先使用 SEARCH/REPLACE 块格式进行代码修改，比 unified diff 更可靠：

```
<<<<<<< SEARCH
def old_function():
    return "old"
=======
def new_function():
    return "new"
>>>>>>> REPLACE
```

**SEARCH/REPLACE 规则**（参考 Aider 最佳实践）：
1. **文件路径**：在代码块之前单独一行写文件路径（如 `src/main.rs`）
2. **SEARCH 内容**：必须与文件中的代码**完全匹配**（包括缩进）
3. **空白容错**：如果缩进不确定，尽量选取包含足够上下文的代码段
4. **最小修改**：只包含需要改变的行 + 足够的上下文（前后 2-3 行）
5. **多处修改**：每处修改用单独的 SEARCH/REPLACE 块

**当 SEARCH/REPLACE 不适用时**（新建文件）：
直接给出完整文件内容，并在前面注明：`新建文件：path/to/file.rs`

**备用格式**（文件差异较大时）：unified diff：
```diff
--- a/src/main.rs
+++ b/src/main.rs
@@ -10,7 +10,8 @@
-    old line
+    new line
```
