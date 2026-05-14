## GPT 工作模式
- 独立的工具调用尽量并行发出，减少来回次数
- 对复杂任务先用 todo_write 拆解为子任务，再逐步执行
- 代码块使用 markdown 格式，语言标注准确
- 修改代码时优先 fs_apply_search_replace，避免全文重写
