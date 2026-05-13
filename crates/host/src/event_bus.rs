//! event_bus.rs — 事件总线（Section 5.4）
//!
//! 所有行为进入统一事件流，写入 SQLite events 表。
//! 用于：观察、分析、Evolution、Replay、Telemetry
//!
//! 架构设计：
//!   - 进程级单例（`global()`），避免每次工具调用都创建新 DB 连接
//!   - project_id 列区分多项目事件，Evolution 引擎可按项目过滤
//!   - 后台 tokio 任务异步写入，不阻塞工具调用主路径

use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::sync::{Arc, OnceLock};
use tokio::sync::mpsc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvoEvent {
    pub id: String,
    pub session_id: String,
    pub project_id: String,
    pub event_type: String,
    pub payload: serde_json::Value,
    pub created_at: String,
}

pub struct EventBus {
    tx: mpsc::UnboundedSender<EvoEvent>,
    /// 规范化的项目 ID（通常是 project root 的绝对路径字符串）
    project_id: String,
}

impl EventBus {
    /// 创建并启动后台写入任务。
    /// `project_id`：项目根目录路径（或任何稳定的项目标识符）。
    pub fn new(project_id: String) -> Self {
        let (tx, mut rx) = mpsc::unbounded_channel::<EvoEvent>();

        tokio::spawn(async move {
            let db_path = dirs::home_dir()
                .unwrap_or_default()
                .join(".evocli")
                .join("events.db");
            let _ = std::fs::create_dir_all(
                db_path
                    .parent()
                    .unwrap_or_else(|| std::path::Path::new(".")),
            );

            let conn = match Connection::open(&db_path) {
                Ok(c) => c,
                Err(e) => {
                    eprintln!("EventBus DB error: {}", e);
                    return;
                }
            };

            // 建表（含 project_id 列）
            let _ = conn.execute_batch(
                "
                CREATE TABLE IF NOT EXISTS events (
                    id         TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    project_id TEXT NOT NULL DEFAULT '',
                    type       TEXT NOT NULL,
                    payload    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session   ON events(session_id);
                CREATE INDEX IF NOT EXISTS idx_events_type      ON events(type);
                CREATE INDEX IF NOT EXISTS idx_events_project   ON events(project_id);
                ",
            );

            // 迁移：旧表没有 project_id 列时自动补充（idempotent）
            let _ = conn
                .execute_batch("ALTER TABLE events ADD COLUMN project_id TEXT NOT NULL DEFAULT ''");
            // 迁移：旧表的索引
            let _ = conn.execute_batch(
                "CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id)",
            );

            while let Some(event) = rx.recv().await {
                let _ = conn.execute(
                    "INSERT OR IGNORE INTO events \
                     (id, session_id, project_id, type, payload, created_at) \
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    rusqlite::params![
                        event.id,
                        event.session_id,
                        event.project_id,
                        event.event_type,
                        serde_json::to_string(&event.payload).unwrap_or_default(),
                        event.created_at
                    ],
                );
            }
        });

        Self { tx, project_id }
    }

    pub fn emit(&self, session_id: &str, event_type: &str, payload: serde_json::Value) {
        let event = EvoEvent {
            id: uuid::Uuid::new_v4().to_string(),
            session_id: session_id.to_string(),
            project_id: self.project_id.clone(),
            event_type: event_type.to_string(),
            payload,
            created_at: chrono::Utc::now().to_rfc3339(),
        };
        let _ = self.tx.send(event);
    }

    pub fn tool_called(&self, session_id: &str, tool: &str, success: bool) {
        self.emit(
            session_id,
            "tool_call",
            serde_json::json!({ "tool": tool, "success": success }),
        );
    }

    #[allow(dead_code)]
    pub fn skill_executed(&self, session_id: &str, skill_id: &str, step: &str) {
        self.emit(
            session_id,
            "skill_exec",
            serde_json::json!({ "skill_id": skill_id, "step": step }),
        );
    }

    #[allow(dead_code)]
    pub fn memory_recalled(&self, session_id: &str, query: &str, hits: usize) {
        self.emit(
            session_id,
            "memory_recall",
            serde_json::json!({ "query": query, "hits": hits }),
        );
    }
}

// ── 进程级单例 ────────────────────────────────────────────────────────────────
//
// 用 OnceLock<Arc<EventBus>> 保证整个进程只创建一个后台写入任务，
// 避免之前每次工具调用都创建新实例（N 个 tokio task + N 个 SQLite 连接）。

static GLOBAL_EVENT_BUS: OnceLock<Arc<EventBus>> = OnceLock::new();

/// 初始化进程级 EventBus（必须在首次 `global()` 调用前调用）。
/// 重复调用安全：第二次调用被忽略（OnceLock 语义）。
pub fn init(project_id: String) -> Arc<EventBus> {
    GLOBAL_EVENT_BUS
        .get_or_init(|| Arc::new(EventBus::new(project_id)))
        .clone()
}

/// 获取进程级 EventBus 引用。若 `init()` 未调用，回退到无 project_id 实例。
/// Reserved for future use (e.g., background task telemetry that runs outside
/// the main request loop and cannot hold an Arc from init()).
#[allow(dead_code)]
pub fn global() -> Arc<EventBus> {
    GLOBAL_EVENT_BUS
        .get_or_init(|| Arc::new(EventBus::new(String::new())))
        .clone()
}

impl Default for EventBus {
    fn default() -> Self {
        Self::new(String::new())
    }
}
