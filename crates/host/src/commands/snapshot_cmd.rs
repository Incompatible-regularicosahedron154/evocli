//! commands/snapshot_cmd.rs — evocli snapshot 子命令（Section 27, side-git）
use crate::git;
use anyhow::Result;
use clap::Subcommand;

#[derive(Subcommand)]
pub enum SnapshotAction {
    /// List recent snapshots
    List {
        #[arg(short, long, default_value = "20")]
        limit: usize,
    },
    /// Restore workspace to a snapshot (does NOT affect project .git)
    Restore { snapshot: String },
    /// Undo the last N AI turns
    Revert {
        #[arg(default_value = "1")]
        turns: usize,
    },
    /// Create a manual snapshot
    Create {
        #[arg(default_value = "manual-checkpoint")]
        label: String,
    },
}

pub fn run(action: SnapshotAction) -> Result<()> {
    let cwd = std::env::current_dir()?;
    match action {
        SnapshotAction::List { limit } => {
            let entries = git::shadow_log(&cwd, limit)?;
            if entries.is_empty() {
                println!("无工作区快照。使用 `evocli snapshot create` 创建。");
                return Ok(());
            }
            println!("{:<12} {:<34} {}", "Hash", "Label", "Age");
            println!("{}", "─".repeat(60));
            for e in entries {
                println!("{:<12} {:<34} {}", e.hash, e.label, e.age);
            }
        }
        SnapshotAction::Restore { snapshot } => {
            println!("回滚到快照 {}…", snapshot);
            git::shadow_restore(&cwd, &snapshot)?;
            println!("✅ 已恢复（项目 .git 未受影响）");
        }
        SnapshotAction::Revert { turns } => {
            println!("撤销最近 {} 轮…", turns);
            git::shadow_revert_turns(&cwd, turns)?;
            println!("✅ 已撤销 {} 轮（项目 .git 未受影响）", turns);
        }
        SnapshotAction::Create { label } => {
            let hash = git::shadow_snapshot(&cwd, &label)?;
            println!("✅ 快照 '{}' 创建成功 ({})", label, hash);
        }
    }
    Ok(())
}
