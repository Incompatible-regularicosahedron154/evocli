"""
EvoCLI Session Manager — Section 26 完整实现。

会话保存、恢复、暂停和列表管理。
通过 LangGraph thread_id 持久化到 SQLite Checkpointer。
"""
from __future__ import annotations
import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("evocli.session")

SESSIONS_DIR = Path.home() / ".evocli" / "sessions"
SESSIONS_DB  = Path.home() / ".evocli" / "sessions.db"


@dataclass
class SessionMeta:
    id:                   str
    created_at:           str
    last_active:          str
    project:              str
    goal:                 str
    status:               str              # active|interrupted|completed|paused
    interrupted_at_step:  Optional[str]  = None
    interrupt_reason:     Optional[str]  = None
    recent_files:         list           = None   # type: ignore[assignment]
    workspace_snapshot:   Optional[str]  = None

    def __post_init__(self):
        if self.recent_files is None:
            self.recent_files = []


class SessionManager:
    def __init__(self, bridge):
        self.bridge = bridge
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 내부 helpers ─────────────────────────────────────────────
    # NOTE: _save/_load 直接读写 ~/.evocli/sessions/ 下的 JSON 文件。
    # 这是 evocli 自身的内部状态数据（非项目文件），不受 bridge 路由约束。
    # 参见架构审计 X4：~/.evocli/ 内部数据目录豁免。

    def _path(self, session_id: str) -> Path:
        """Return safe on-disk path for a session file.
        
        Uses the same collision-resistant sanitization as state._history_path():
        - Readable prefix: only alphanumerics, hyphens, underscores, dots
        - SHA-256 suffix (12 hex chars) prevents collisions between IDs that
          differ only in unsafe characters (e.g. "a/b" vs "a?b")
        - Prevents path traversal attacks
        """
        import re
        import hashlib
        sid_str = str(session_id)
        safe_prefix = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', sid_str)[:80]
        suffix = hashlib.sha256(sid_str.encode()).hexdigest()[:12]
        safe_name = f"{safe_prefix}_{suffix}" if safe_prefix else suffix
        return SESSIONS_DIR / f"{safe_name}.json"

    def _save(self, meta: SessionMeta) -> None:
        self._path(meta.id).write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self, session_id: str) -> Optional[SessionMeta]:
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return SessionMeta(**data)
        except Exception as e:
            log.warning("Failed to load session %s: %s", session_id, e)
            return None

    # ── 공개 API ─────────────────────────────────────────────────

    def create(self, project: str, goal: str) -> SessionMeta:
        now  = datetime.now().isoformat()
        meta = SessionMeta(
            id          = f"ses_{uuid.uuid4().hex[:12]}",
            created_at  = now,
            last_active = now,
            project     = project,
            goal        = goal,
            status      = "active",
        )
        self._save(meta)
        log.info("Session created: %s", meta.id)
        return meta

    def list_sessions(self, status_filter: Optional[str] = None) -> list[dict]:
        sessions = []
        for p in SESSIONS_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if status_filter is None or data.get("status") == status_filter:
                    sessions.append(data)
            except Exception:
                continue
        sessions.sort(key=lambda s: s.get("last_active", ""), reverse=True)
        return sessions

    def latest_interrupted(self) -> Optional[SessionMeta]:
        for status in ("interrupted", "paused"):
            items = self.list_sessions(status_filter=status)
            if items:
                return SessionMeta(**items[0])
        return None

    def mark_interrupted(
        self, session_id: str, step: str, reason: str, snapshot: str = ""
    ) -> None:
        meta = self._load(session_id)
        if not meta:
            return
        meta.status              = "interrupted"
        meta.interrupted_at_step = step
        meta.interrupt_reason    = reason
        meta.workspace_snapshot  = snapshot
        meta.last_active         = datetime.now().isoformat()
        self._save(meta)

    def mark_paused(self, session_id: str, snapshot: str = "") -> None:
        meta = self._load(session_id)
        if not meta:
            return
        meta.status             = "paused"
        meta.workspace_snapshot = snapshot
        meta.last_active        = datetime.now().isoformat()
        self._save(meta)

    def mark_completed(self, session_id: str) -> None:
        meta = self._load(session_id)
        if not meta:
            return
        meta.status      = "completed"
        meta.last_active = datetime.now().isoformat()
        self._save(meta)

    def touch(self, session_id: str, recent_files: Optional[list] = None) -> None:
        """更新 last_active，可选更新最近文件列表。"""
        meta = self._load(session_id)
        if not meta:
            return
        meta.last_active = datetime.now().isoformat()
        if recent_files is not None:
            meta.recent_files = recent_files[-5:]
        self._save(meta)

    async def resume(self, session_id: str) -> dict:
        """恢复 Session：加载元数据并恢复工作区快照。"""
        meta = self._load(session_id)
        if not meta:
            return {"ok": False, "error": f"Session {session_id} not found"}

        # 尝试恢复工作区快照
        if meta.workspace_snapshot:
            try:
                await self.bridge.call("git.shadow_restore", {
                    "snapshot": meta.workspace_snapshot,
                    "project":  meta.project,
                })
                log.info("Workspace restored from: %s", meta.workspace_snapshot)
            except Exception as e:
                log.warning("Workspace restore failed: %s", e)

        meta.status      = "active"
        meta.last_active = datetime.now().isoformat()
        self._save(meta)

        return {
            "ok":       True,
            "session":  asdict(meta),
            "thread_id": session_id,   # LangGraph 用此恢复 checkpoint
        }
