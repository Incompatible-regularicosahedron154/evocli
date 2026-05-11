//! commands/git_cmd.rs — evocli git 子命令
use crate::git;
use anyhow::Result;
use clap::Subcommand;

#[derive(Subcommand)]
pub enum GitAction {
    /// Show git status
    Status,
    /// Create a workspace snapshot (git stash)
    Snapshot,
    /// Show current branch
    Branch,
}

pub fn run(action: GitAction) -> Result<()> {
    let cwd = std::env::current_dir()?;
    match action {
        GitAction::Status => {
            let entries = git::git_status(&cwd)?;
            if entries.is_empty() {
                println!("Working tree clean.");
            } else {
                for e in entries {
                    println!("{} {}", e.code, e.path);
                }
            }
        }
        GitAction::Snapshot => {
            let r = git::git_snapshot(&cwd)?;
            println!("Snapshot created: {r}");
        }
        GitAction::Branch => {
            let b = git::git_branch(&cwd)?;
            println!("{b}");
        }
    }
    Ok(())
}
