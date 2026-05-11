//! Task Contract tracking system.
//!
//! Stores task contracts and checkpoints in a local SQLite database.
//! A "contract" represents a user requirement the AI committed to fulfilling.
//! Checkpoints track incremental progress within a contract.

use anyhow::{Context, Result};
use chrono::Utc;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::path::Path;
use uuid::Uuid;

/// Summary view of a contract (for listing).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContractSummary {
    pub id: String,
    pub requirement: String,
    pub status: String,
    pub created_at: String,
    pub checkpoint_count: i64,
}

/// A single checkpoint within a contract.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Checkpoint {
    pub id: String,
    pub contract_id: String,
    pub seq: i64,
    pub description: String,
    pub status: String,
    pub completed_at: Option<String>,
}

/// Persistent store for task contracts.
pub struct ContractStore {
    conn: Connection,
}

impl ContractStore {
    /// Open (or create) the contract database at `db_path`.
    pub fn new(db_path: &Path) -> Result<Self> {
        let conn = Connection::open(db_path)
            .with_context(|| format!("failed to open contract db: {}", db_path.display()))?;

        conn.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS task_contracts (
                id            TEXT PRIMARY KEY,
                requirement   TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'active',
                created_at    TEXT NOT NULL,
                interrupted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                id            TEXT PRIMARY KEY,
                contract_id   TEXT NOT NULL REFERENCES task_contracts(id),
                seq           INTEGER NOT NULL,
                description   TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                completed_at  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoints_contract
                ON checkpoints(contract_id);
            ",
        )
        .context("failed to initialize contract schema")?;

        Ok(Self { conn })
    }

    /// Create a new contract. Returns the contract ID.
    pub fn create_contract(&self, requirement: &str) -> Result<String> {
        let id = Uuid::new_v4().to_string();
        let now = Utc::now().to_rfc3339();
        self.conn.execute(
            "INSERT INTO task_contracts (id, requirement, status, created_at) VALUES (?1, ?2, 'active', ?3)",
            rusqlite::params![id, requirement, now],
        )?;
        Ok(id)
    }

    /// Update a contract's status (e.g. "active" → "completed" | "interrupted" | "failed").
    pub fn update_status(&self, contract_id: &str, status: &str) -> Result<()> {
        let interrupted_at = if status == "interrupted" || status == "failed" {
            Some(Utc::now().to_rfc3339())
        } else {
            None
        };
        self.conn.execute(
            "UPDATE task_contracts SET status = ?1, interrupted_at = ?2 WHERE id = ?3",
            rusqlite::params![status, interrupted_at, contract_id],
        )?;
        Ok(())
    }

    /// List all active contracts with checkpoint counts.
    pub fn list_active(&self) -> Result<Vec<ContractSummary>> {
        let mut stmt = self.conn.prepare(
            "
            SELECT c.id, c.requirement, c.status, c.created_at,
                   (SELECT COUNT(*) FROM checkpoints WHERE contract_id = c.id) as cp_count
            FROM task_contracts c
            WHERE c.status = 'active'
            ORDER BY c.created_at DESC
            ",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok(ContractSummary {
                id: row.get(0)?,
                requirement: row.get(1)?,
                status: row.get(2)?,
                created_at: row.get(3)?,
                checkpoint_count: row.get(4)?,
            })
        })?;
        let mut result = Vec::new();
        for row in rows {
            result.push(row?);
        }
        Ok(result)
    }

    /// Add a checkpoint to a contract. Returns the checkpoint ID.
    pub fn add_checkpoint(&self, contract_id: &str, description: &str) -> Result<String> {
        let id = Uuid::new_v4().to_string();
        // Auto-increment seq within this contract
        let seq: i64 = self
            .conn
            .query_row(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM checkpoints WHERE contract_id = ?1",
                rusqlite::params![contract_id],
                |row| row.get(0),
            )
            .unwrap_or(1);

        self.conn.execute(
            "INSERT INTO checkpoints (id, contract_id, seq, description, status) VALUES (?1, ?2, ?3, ?4, 'pending')",
            rusqlite::params![id, contract_id, seq, description],
        )?;
        Ok(id)
    }

    /// Mark a checkpoint as completed.
    pub fn complete_checkpoint(&self, checkpoint_id: &str) -> Result<()> {
        let now = Utc::now().to_rfc3339();
        self.conn.execute(
            "UPDATE checkpoints SET status = 'completed', completed_at = ?1 WHERE id = ?2",
            rusqlite::params![now, checkpoint_id],
        )?;
        Ok(())
    }

    /// Get all checkpoints for a contract.
    pub fn get_checkpoints(&self, contract_id: &str) -> Result<Vec<Checkpoint>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, contract_id, seq, description, status, completed_at
             FROM checkpoints WHERE contract_id = ?1 ORDER BY seq",
        )?;
        let rows = stmt.query_map(rusqlite::params![contract_id], |row| {
            Ok(Checkpoint {
                id: row.get(0)?,
                contract_id: row.get(1)?,
                seq: row.get(2)?,
                description: row.get(3)?,
                status: row.get(4)?,
                completed_at: row.get(5)?,
            })
        })?;
        let mut result = Vec::new();
        for row in rows {
            result.push(row?);
        }
        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn temp_db() -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("evocli_contracts_test_{}.db", Uuid::new_v4()));
        p
    }

    #[test]
    fn create_and_list_contracts() {
        let db = temp_db();
        let store = ContractStore::new(&db).unwrap();

        // Create two contracts
        let id1 = store.create_contract("Implement git integration").unwrap();
        let id2 = store.create_contract("Add skill system").unwrap();
        assert!(!id1.is_empty());
        assert!(!id2.is_empty());

        // Both should be active
        let active = store.list_active().unwrap();
        assert_eq!(active.len(), 2);

        // Complete one
        store.update_status(&id1, "completed").unwrap();
        let active = store.list_active().unwrap();
        assert_eq!(active.len(), 1);
        assert_eq!(active[0].id, id2);

        // Cleanup
        let _ = std::fs::remove_file(&db);
    }

    #[test]
    fn checkpoints_lifecycle() {
        let db = temp_db();
        let store = ContractStore::new(&db).unwrap();

        let cid = store.create_contract("Build TUI").unwrap();

        // Add checkpoints
        let cp1 = store.add_checkpoint(&cid, "Create layout").unwrap();
        let cp2 = store.add_checkpoint(&cid, "Add input handler").unwrap();

        let cps = store.get_checkpoints(&cid).unwrap();
        assert_eq!(cps.len(), 2);
        assert_eq!(cps[0].seq, 1);
        assert_eq!(cps[1].seq, 2);
        assert_eq!(cps[0].status, "pending");

        // Complete first checkpoint
        store.complete_checkpoint(&cp1).unwrap();
        let cps = store.get_checkpoints(&cid).unwrap();
        assert_eq!(cps[0].status, "completed");
        assert!(cps[0].completed_at.is_some());
        assert_eq!(cps[1].status, "pending");

        // Verify checkpoint count in summary
        let active = store.list_active().unwrap();
        assert_eq!(active[0].checkpoint_count, 2);

        // Complete second, mark contract done
        store.complete_checkpoint(&cp2).unwrap();
        store.update_status(&cid, "completed").unwrap();
        let active = store.list_active().unwrap();
        assert!(active.is_empty());

        let _ = std::fs::remove_file(&db);
    }

    #[test]
    fn interrupted_contract() {
        let db = temp_db();
        let store = ContractStore::new(&db).unwrap();

        let cid = store.create_contract("Risky refactor").unwrap();
        store.update_status(&cid, "interrupted").unwrap();

        let active = store.list_active().unwrap();
        assert!(active.is_empty());

        let _ = std::fs::remove_file(&db);
    }
}
