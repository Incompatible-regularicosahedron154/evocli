//! Soul Bridge — Rust Host ↔ Python Soul JSON-RPC over stdin/stdout
//!
//! 通信方向：
//!   Rust → Python (stdin)：发送请求，等待响应
//!   Python → Rust (stdout)：
//!     1. 普通响应 (result/error)
//!     2. 流式 chunk (method: "stream.chunk")
//!     3. 工具调用 (method: "tool.call") ← Python Soul 请求 Rust 执行工具
//!     4. 事件通知 (method: "event.emit")

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{mpsc, oneshot, Mutex};
use uuid::Uuid;

// ── 消息类型 ─────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RpcRequest {
    pub id:     String,
    pub method: String,
    pub params: Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RpcResponse {
    pub id:     String,
    pub result: Option<Value>,
    pub error:  Option<RpcError>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RpcError {
    pub code:    i32,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct StreamChunk {
    pub id:   String,
    pub text: String,
    pub done: bool,
}

/// Python Soul 发来的工具调用请求
#[derive(Debug, Serialize, Deserialize)]
pub struct ToolCallRequest {
    pub id:   String,           // request id，用于回复
    pub tool: String,           // 如 "fs.read" / "shell.run"
    pub args: Value,
}

/// Rust 处理工具调用的函数签名
pub type ToolHandler = Arc<dyn Fn(Value) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<Value>> + Send>> + Send + Sync>;

/// 用于 prompt.choice 的单个选项
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChoiceOption {
    pub id:    String,
    pub label: String,
}

/// prompt.choice 的用户响应
#[derive(Debug, Clone)]
pub enum ChoiceResult {
    /// 用户选择了某个列表选项
    Selected(String),
    /// 用户输入了自定义文本（allow_custom = true 时）
    Custom(String),
    /// 用户取消（Esc / 超时）
    Cancelled,
}

/// soul_bridge 内部存储的选择请求
#[derive(Debug, Clone)]
pub struct ChoiceRequest {
    pub title:        String,
    pub options:      Vec<ChoiceOption>,
    pub allow_custom: bool,
}

// ── SoulBridge ───────────────────────────────────────────────────

pub struct SoulBridge {
    _child:     Child,
    pending:    Arc<Mutex<HashMap<String, oneshot::Sender<RpcResponse>>>>,
    streams:    Arc<Mutex<HashMap<String, mpsc::UnboundedSender<StreamChunk>>>>,
    stdin_tx:   mpsc::UnboundedSender<String>,
    /// 工具调用队列：Python 发来的 tool.call 请求
    tool_rx:    Arc<Mutex<mpsc::UnboundedReceiver<ToolCallRequest>>>,
    /// 事件驱动通知：tool.call 入队时触发，替代 busy-wait 轮询
    tool_notify: Arc<tokio::sync::Notify>,
    tool_reply: mpsc::UnboundedSender<String>,
    /// P2-5: 事件通知通道（event.emit 从 Python → Rust）
    event_rx:   Arc<Mutex<mpsc::UnboundedReceiver<serde_json::Value>>>,
    /// TUI Approval channel: stores (message, oneshot::Sender<bool>) for pending approval
    approval_request: Arc<Mutex<Option<(String, oneshot::Sender<bool>)>>>,
    /// TUI Choice channel: stores pending prompt.choice request
    choice_request: Arc<Mutex<Option<(ChoiceRequest, oneshot::Sender<ChoiceResult>)>>>,
}

impl SoulBridge {
    pub async fn spawn(soul_script: &str) -> Result<Self> {
        // Strip the Windows long-path prefix \\?\ that canonicalize() may add.
        // Python cannot resolve \\?\D:\... paths in PYTHONPATH or as a module path,
        // causing ModuleNotFoundError when the binary is run from another directory.
        // See config.rs::resolve_soul_path() for the same note.
        //
        // Known edge cases (not handled, acceptable in practice):
        //   • Path > 260 chars on Windows < 10-1607 without long-path support:
        //     stripping \\?\ may cause "path not found". Very unlikely in typical installs.
        //   • evocli-soul/ is a symlink: PYTHONPATH will point to the symlink, not
        //     the real target. Python follows symlinks natively so this usually works.
        #[cfg(windows)]
        let soul_script = soul_script.trim_start_matches(r"\\?\");
        #[cfg(not(windows))]
        let soul_script = soul_script;
        // v3.x: 优先使用 ~/.evocli/venv 中的托管 Python，不依赖系统环境
        let managed_python = {
            let venv_base = dirs::home_dir()
                .unwrap_or_default()
                .join(".evocli")
                .join("venv");
            let managed = if cfg!(windows) {
                venv_base.join("Scripts").join("python.exe")
            } else {
                venv_base.join("bin").join("python3")
            };
            if managed.exists() { Some(managed) } else { None }
        };

        let python_exe = managed_python
            .as_ref()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| {
                if cfg!(target_os = "windows") { "python".into() } else { "python3".into() }
            });

        // 将 .py 文件路径转换为模块模式，防止目录被加入 sys.path[0] 导致 stdlib 遮蔽
        // 规则：`.../<pkg>/main.py` → module=`<pkg>.main`, pythonpath=`<parent_of_pkg>/`
        let (run_args, pythonpath): (Vec<String>, Option<String>) = if soul_script.ends_with(".py") {
            let p = std::path::Path::new(soul_script);
            // 尝试从文件路径推断包名和 PYTHONPATH
            // evocli-soul/evocli_soul/main.py → pkg=evocli_soul, parent=evocli-soul/
            if let (Some(pkg_dir), Some(filename)) = (p.parent(), p.file_stem()) {
                if let Some(pkg_name) = pkg_dir.file_name().and_then(|n| n.to_str()) {
                    let module = format!("{}.{}", pkg_name, filename.to_str().unwrap_or("main"));
                    let pp = pkg_dir.parent()
                        .map(|pp| {
                            // Do NOT canonicalize: on Windows it adds a \\?\ prefix
                            // that Python cannot resolve in PYTHONPATH.
                            // Use the path as-is; if relative, it resolves correctly
                            // because the child process inherits the same CWD.
                            //
                            // Edge cases (not handled, acceptable in practice):
                            //   • symlinks: not resolved, but Python follows them natively.
                            //   • relative paths with ..: work as long as CWD doesn't change
                            //     between spawn() call and Python module import.
                            let s = pp.to_string_lossy();
                            #[cfg(windows)]
                            let s = s.trim_start_matches(r"\\?\").to_string();
                            #[cfg(not(windows))]
                            let s = s.to_string();
                            s
                        });
                    (vec!["-u".into(), "-m".into(), module], pp)
                } else {
                    // fallback: 直接运行文件
                    (vec!["-u".into(), soul_script.to_string()], None)
                }
            } else {
                (vec!["-u".into(), soul_script.to_string()], None)
            }
        } else {
            // 已经是模块名（如 evocli_soul.main）
            (vec!["-u".into(), "-m".into(), soul_script.to_string()], None)
        };

        // 构建环境变量：PYTHONPATH + UTF-8 编码
        let mut cmd = Command::new(&python_exe);
        cmd.args(run_args.iter().map(|s| s.as_str()))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .env("PYTHONIOENCODING", "utf-8");

        // Redirect Soul stderr → log file, NOT the terminal.
        // soul_logging.py already routes WARNING+ to both evocli.log AND the TUI
        // event channel.  Inheriting stderr would let raw Python output bleed
        // directly into the ratatui TUI, corrupting the rendered frame.
        let log_dir = dirs::home_dir()
            .unwrap_or_default()
            .join(".evocli")
            .join("logs");
        let _ = std::fs::create_dir_all(&log_dir);
        let stderr_sink = std::fs::OpenOptions::new()
            .create(true).append(true)
            .open(log_dir.join("soul_stderr.log"))
            .map(Stdio::from)
            .unwrap_or_else(|_| Stdio::null());
        cmd.stderr(stderr_sink);

        // Prevent orphan Python Soul processes.
        cmd.kill_on_drop(true);

        if let Some(ref pp) = pythonpath {
            // 追加到现有 PYTHONPATH 而非覆盖
            let sep = if cfg!(windows) { ";" } else { ":" };
            let existing = std::env::var("PYTHONPATH").unwrap_or_default();
            let merged = if existing.is_empty() {
                pp.clone()
            } else {
                format!("{}{}{}", pp, sep, existing)
            };
            cmd.env("PYTHONPATH", &merged);
        }

        let mut child = cmd.spawn()
            .with_context(|| format!(
                "Failed to spawn Python Soul.\n  Python: {}\n  Args: {:?}\n  PYTHONPATH: {:?}\n  \
                  Tip: run `evocli init` to set up managed Python environment.",
                python_exe, run_args, pythonpath
            ))?;

        let stdout = child.stdout.take().unwrap();
        let stdin  = child.stdin.take().unwrap();

        let pending: Arc<Mutex<HashMap<String, oneshot::Sender<RpcResponse>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let streams: Arc<Mutex<HashMap<String, mpsc::UnboundedSender<StreamChunk>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        // stdin writer（统一写入通道）
        let (stdin_tx, mut stdin_rx) = mpsc::unbounded_channel::<String>();
        let tool_reply = stdin_tx.clone();   // 工具结果也走同一 stdin

        tokio::spawn(async move {
            let mut w = tokio::io::BufWriter::new(stdin);
            while let Some(line) = stdin_rx.recv().await {
                if w.write_all(line.as_bytes()).await.is_err() { break; }
                if w.write_all(b"\n").await.is_err() { break; }
                let _ = w.flush().await;
            }
        });

        // 工具调用队列（Python → Rust tool.call）
        let (tool_tx, tool_rx_inner) = mpsc::unbounded_channel::<ToolCallRequest>();
        let tool_rx = Arc::new(Mutex::new(tool_rx_inner));
        let tool_notify = Arc::new(tokio::sync::Notify::new());

        // P2-5: 事件通知通道（Python → Rust event.emit）
        let (event_tx, event_rx_inner) = mpsc::unbounded_channel::<serde_json::Value>();
        let event_rx = Arc::new(Mutex::new(event_rx_inner));

        // stdout reader
        let pending_r = Arc::clone(&pending);
        let streams_r = Arc::clone(&streams);
        let tool_notify_w = Arc::clone(&tool_notify);
        tokio::spawn(async move {
            let mut lines = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let line = line.trim().to_string();
                if line.is_empty() { continue; }

                let v = match serde_json::from_str::<Value>(&line) {
                    Ok(v) => v,
                    Err(_) => continue,
                };

                let method = v.get("method").and_then(|m| m.as_str()).unwrap_or("");

                match method {
                    // Python → Rust 工具调用（新增）
                    "tool.call" => {
                        if let Some(params) = v.get("params") {
                            let id   = v["id"].as_str().unwrap_or("").to_string();
                            let tool = params["tool"].as_str().unwrap_or("").to_string();
                            let args = params["args"].clone();
                            let _ = tool_tx.send(ToolCallRequest { id, tool, args });
                            tool_notify_w.notify_one();
                        }
                    }

                    // 流式 chunk
                    "stream.chunk" => {
                        if let Ok(chunk) = serde_json::from_value::<StreamChunk>(v["params"].clone()) {
                            let id = chunk.id.clone();
                            if let Some(tx) = streams_r.lock().await.get(&id) {
                                let _ = tx.send(chunk);
                            }
                        }
                    }

                    // 事件通知（无需响应）— P2-5: 转发到事件通道
                    "event.emit" => {
                        if let Some(params) = v.get("params") {
                            let _ = event_tx.send(params.clone());
                        }
                    }

                    // 普通响应 (id + result/error)
                    _ => {
                        if let Ok(resp) = serde_json::from_value::<RpcResponse>(v) {
                            let id = resp.id.clone();
                            // First: try the pending map (normal request/response)
                            if let Some(tx) = pending_r.lock().await.remove(&id) {
                                let _ = tx.send(resp);
                            }
                            // Second: if ID is in streams map and this is an error response,
                            // the backend sent send.error() instead of stream_chunk().
                            // Convert to a done stream chunk so TUI exits Streaming state.
                            // Without this, the stream channel never closes and the TUI
                            // gets stuck in "Streaming..." state forever.
                            else if let Some(err) = resp.error {
                                if let Some(tx) = streams_r.lock().await.remove(&id) {
                                    let error_chunk = StreamChunk {
                                        id:   id.clone(),
                                        text: format!("ERROR: {} (code {})", err.message, err.code),
                                        done: true,
                                    };
                                    let _ = tx.send(error_chunk);
                                    tracing::debug!("Converted JSON-RPC error to stream done-chunk for {}", id);
                                }
                            }
                        }
                    }
                }
            }

            // ── Python 进程退出清理 ──────────────────────────────────────────
            // Python Soul 的 stdout 已关闭（进程正常退出或崩溃）。
            // 主动清理所有挂起的请求和流，避免 TUI/调用者永久阻塞。
            tracing::warn!("Python Soul stdout EOF — process terminated, cleaning up pending state");

            // 清理 pending map: dropping Sender 使 oneshot Receiver 得到 RecvError
            // → call_with_timeout 收到 Err("Response channel closed") 并返回错误
            pending_r.lock().await.drain();

            // 清理 stream map: 向所有活跃流注入 done-chunk，TUI 退出 Streaming 状态
            let mut smap = streams_r.lock().await;
            for (id, tx) in smap.drain() {
                let _ = tx.send(StreamChunk {
                    id:   id,
                    text: "\n\n⚠️  EvoCLI Soul process has terminated. Please restart EvoCLI.".to_string(),
                    done: true,
                });
            }
        });

        let approval_request: Arc<Mutex<Option<(String, oneshot::Sender<bool>)>>> =
            Arc::new(Mutex::new(None));
        let choice_request: Arc<Mutex<Option<(ChoiceRequest, oneshot::Sender<ChoiceResult>)>>> =
            Arc::new(Mutex::new(None));

        Ok(Self { _child: child, pending, streams, stdin_tx, tool_rx, tool_notify,
                  tool_reply, event_rx, approval_request, choice_request })
    }

    // ── Rust → Python 请求 ────────────────────────────────────

    pub async fn call(&self, method: &str, params: Value) -> Result<Value> {
        self.call_with_timeout(method, params, 60_000).await
    }

    pub async fn call_with_timeout(&self, method: &str, params: Value, timeout_ms: u64) -> Result<Value> {
        let id  = Uuid::new_v4().to_string();
        let req = RpcRequest { id: id.clone(), method: method.to_string(), params };
        let (tx, rx) = oneshot::channel();
        self.pending.lock().await.insert(id.clone(), tx);
        self.stdin_tx.send(serde_json::to_string(&req)?)?;
        // Fix (Oracle E2): clean up pending entry on timeout to avoid map leak
        match tokio::time::timeout(std::time::Duration::from_millis(timeout_ms), rx).await {
            Ok(Ok(resp)) => {
                if let Some(err) = resp.error { bail!("[{}] {}", err.code, err.message); }
                Ok(resp.result.unwrap_or(Value::Null))
            }
            Ok(Err(e))   => bail!("Response channel closed: {}", e),
            Err(_elapsed) => {
                // Remove the orphaned pending entry before returning the error
                self.pending.lock().await.remove(&id);
                bail!("RPC call '{}' timed out after {}ms", method, timeout_ms)
            }
        }
    }

    pub async fn call_stream(&self, method: &str, params: Value) -> Result<mpsc::UnboundedReceiver<StreamChunk>> {
        let id  = Uuid::new_v4().to_string();
        let req = RpcRequest { id: id.clone(), method: method.to_string(), params };
        let (tx, rx) = mpsc::unbounded_channel();
        self.streams.lock().await.insert(id.clone(), tx);
        self.stdin_tx.send(serde_json::to_string(&req)?)?;
        Ok(rx)
    }

    pub async fn ping(&self) -> Result<bool> {
        // Retry up to 3 times with 200ms between attempts.
        // Removed the original hardcoded 800ms sleep — callers should not pay
        // a fixed penalty when Python starts quickly (e.g., warm venv).
        let mut last_err = anyhow::anyhow!("ping failed after 3 attempts");
        for attempt in 0..3u8 {
            if attempt > 0 {
                tokio::time::sleep(std::time::Duration::from_millis(200)).await;
            }
            match self.call("tracer.ping", serde_json::json!({})).await {
                Ok(result) => return Ok(result.as_str() == Some("pong")),
                Err(e)     => last_err = e,
            }
        }
        Err(last_err)
    }

    // ── Python → Rust 工具调用处理 ────────────────────────────

    /// 接收 Python 发来的下一个工具调用请求（非阻塞轮询）
    pub async fn next_tool_call(&self) -> Option<ToolCallRequest> {
        self.tool_rx.lock().await.try_recv().ok()
    }

    /// 等待直到有新的工具调用请求（事件驱动，替代 busy-wait sleep）
    pub async fn wait_for_tool(&self) {
        self.tool_notify.notified().await;
    }

    /// P2-5: 接收 Python 发来的下一个事件通知（非阻塞）
    pub async fn next_event(&self) -> Option<serde_json::Value> {
        self.event_rx.lock().await.try_recv().ok()
    }

    // ── TUI Approval channel ──────────────────────────────────

    /// Request approval from TUI user. Blocks until user responds or 30s timeout.
    /// Returns true if approved, false if rejected or timed out.
    /// On timeout: cleans up approval_request state to prevent stale modal + race condition
    /// where a subsequent approval request would inherit the old TUI modal message.
    pub async fn request_approval(&self, message: String) -> bool {
        let (tx, rx) = oneshot::channel();
        *self.approval_request.lock().await = Some((message, tx));
        let result = tokio::time::timeout(std::time::Duration::from_secs(30), rx)
            .await
            .unwrap_or(Ok(false))
            .unwrap_or(false);
        // Cleanup: clear stale approval_request on timeout so TUI exits WaitingApproval
        // and a subsequent approval request doesn't inherit the old message.
        // (On success/rejection, resolve_approval already cleared this via .take())
        *self.approval_request.lock().await = None;
        result
    }

    /// Check if there's a pending approval request (TUI polls this).
    pub async fn get_pending_approval(&self) -> Option<String> {
        self.approval_request.lock().await
            .as_ref()
            .map(|(msg, _)| msg.clone())
    }

    /// Resolve a pending approval (TUI calls this when user presses y/n).
    pub async fn resolve_approval(&self, approved: bool) {
        if let Some((_, tx)) = self.approval_request.lock().await.take() {
            let _ = tx.send(approved);
        }
    }

    // ── prompt.choice ─────────────────────────────────────────────

    /// Request the user to pick one of several options (or type custom text).
    /// Blocks until the user responds or the 120s timeout fires.
    pub async fn request_choice(&self, req: ChoiceRequest) -> ChoiceResult {
        let (tx, rx) = oneshot::channel();
        *self.choice_request.lock().await = Some((req, tx));
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(120), rx
        ).await
            .ok()
            .and_then(|r| r.ok())
            .unwrap_or(ChoiceResult::Cancelled);
        *self.choice_request.lock().await = None;
        result
    }

    /// TUI polls this to detect a pending choice prompt.
    pub async fn get_pending_choice(&self) -> Option<ChoiceRequest> {
        self.choice_request.lock().await
            .as_ref()
            .map(|(req, _)| req.clone())
    }

    /// TUI calls this when the user has made a selection.
    pub async fn resolve_choice(&self, result: ChoiceResult) {
        if let Some((_, tx)) = self.choice_request.lock().await.take() {
            let _ = tx.send(result);
        }
    }

    /// 向 Python 回复工具调用结果
    pub fn reply_tool(&self, req_id: &str, result: Result<Value>) {
        let resp = match result {
            Ok(r) => serde_json::json!({ "id": req_id, "result": r, "error": null }),
            Err(e) => serde_json::json!({
                "id": req_id, "result": null,
                "error": { "code": -32603, "message": e.to_string() }
            }),
        };
        let _ = self.tool_reply.send(serde_json::to_string(&resp).unwrap_or_default());
    }
}
