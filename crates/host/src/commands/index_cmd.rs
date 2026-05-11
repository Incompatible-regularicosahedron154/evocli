//! commands/index_cmd.rs — evocli index 子命令（代码符号索引）
//!
//! Builds two indexes in .evocli/:
//!   1. code_index.db     — SQLite symbol index (ts_indexer)
//!   2. bm25_index/       — Tantivy BM25 full-text index (for hybrid search)
use anyhow::{Context as _, Result};

pub fn run(dir: Option<&str>) -> Result<()> {
    let root = dir.map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::env::current_dir().unwrap());

    println!("Indexing: {}", root.display());

    // Ensure .evocli/ directory exists before opening SQLite databases.
    // SQLite cannot create the parent directory automatically — if .evocli/
    // doesn't exist (e.g., first-time index on --dir path), the open() call fails.
    let evocli_dir = root.join(".evocli");
    std::fs::create_dir_all(&evocli_dir)
        .with_context(|| format!("Failed to create .evocli directory: {}", evocli_dir.display()))?;

    // Step 1: Build SQLite symbol index (tree-sitter AST parsing)
    let db_path = root.join(".evocli").join("code_index.db");
    let mut index = code_intel::CodeIndex::new(&db_path)?;
    let extensions = ["rs", "py", "ts", "tsx", "js", "go"];
    let count = index.index_directory(&root, &extensions)?;
    println!("  ✓ Indexed {} symbols → {}", count, db_path.display());

    // Step 2: Build BM25 tantivy index from the SQLite symbol data
    // Required for code_intel.bm25_search and code_intel.hybrid_search
    let bm25_dir = root.join(".evocli").join("bm25_index");
    match knowledge_graph::Bm25Index::open_or_create(&bm25_dir) {
        Ok(bm25) => {
            match bm25.rebuild_from_sqlite(&db_path) {
                Ok(n) => println!("  ✓ BM25 index built ({} symbols) → {}", n, bm25_dir.display()),
                Err(e) => eprintln!("  ⚠ BM25 index failed (non-fatal): {}", e),
            }
        }
        Err(e) => eprintln!("  ⚠ BM25 index creation failed (non-fatal): {}", e),
    }

    println!("\nIndexed {} symbols in {}", count, root.display());
    Ok(())
}
