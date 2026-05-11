//! LSP Manager -- manages multiple language server instances (lazy-loaded, on-demand)

use crate::lsp_client::{CallHierarchyItem, CallSite, Location, LspClient};
use anyhow::Result;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Language {
    Rust,
    Python,
    TypeScript,
    JavaScript,
    Go,
}

pub struct LspManager {
    workspace: PathBuf,
    clients: HashMap<Language, LspClient>,
}

impl LspManager {
    pub fn new(workspace: &Path) -> Self {
        Self {
            workspace: workspace.to_path_buf(),
            clients: HashMap::new(),
        }
    }

    /// Detect file language and return (lang, server_cmd, args).
    pub fn detect_language(path: &Path) -> Option<(Language, &'static str, Vec<&'static str>)> {
        match path.extension()?.to_str()? {
            "rs" => Some((Language::Rust, "rust-analyzer", vec![])),
            "py" => Some((Language::Python, "pyright-langserver", vec!["--stdio"])),
            "ts" | "tsx" => Some((
                Language::TypeScript,
                "typescript-language-server",
                vec!["--stdio"],
            )),
            "js" | "jsx" => Some((
                Language::JavaScript,
                "typescript-language-server",
                vec!["--stdio"],
            )),
            "go" => Some((Language::Go, "gopls", vec!["serve"])),
            _ => None,
        }
    }

    /// Get (or lazily spawn) the LSP client for the given language.
    async fn get_or_spawn(
        &mut self,
        lang: Language,
        cmd: &str,
        args: &[&str],
    ) -> Result<&LspClient> {
        if !self.clients.contains_key(&lang) {
            let client = LspClient::spawn_and_init(cmd, args, &self.workspace).await?;
            self.clients.insert(lang.clone(), client);
        }
        Ok(self.clients.get(&lang).unwrap())
    }

    /// Full call-hierarchy analysis for a function at (file, line, character).
    pub async fn analyze_function(
        &mut self,
        file: &Path,
        line: u32,
        character: u32,
    ) -> Result<FunctionAnalysis> {
        let (lang, cmd, args) = Self::detect_language(file)
            .ok_or_else(|| anyhow::anyhow!("Unsupported file type: {:?}", file))?;

        let client = self.get_or_spawn(lang, cmd, &args).await?;
        client.open_file(file).await?;

        let items = client.prepare_call_hierarchy(file, line, character).await?;
        let item = items.into_iter().next();

        let (incoming, outgoing) = if let Some(ref item) = item {
            let inc = client.incoming_calls(item).await.unwrap_or_default();
            let out = client.outgoing_calls(item).await.unwrap_or_default();
            (inc, out)
        } else {
            (vec![], vec![])
        };

        Ok(FunctionAnalysis {
            item,
            incoming_calls: incoming,
            outgoing_calls: outgoing,
        })
    }

    /// Find all references to the symbol at (file, line, character).
    pub async fn find_references(
        &mut self,
        file: &Path,
        line: u32,
        character: u32,
    ) -> Result<Vec<Location>> {
        let (lang, cmd, args) = Self::detect_language(file)
            .ok_or_else(|| anyhow::anyhow!("Unsupported file type: {:?}", file))?;
        let client = self.get_or_spawn(lang, cmd, &args).await?;
        client.open_file(file).await?;
        client.references(file, line, character).await
    }

    /// Go to definition of the symbol at (file, line, character).
    pub async fn goto_definition(
        &mut self,
        file: &Path,
        line: u32,
        character: u32,
    ) -> Result<Option<Location>> {
        let (lang, cmd, args) = Self::detect_language(file)
            .ok_or_else(|| anyhow::anyhow!("Unsupported file type: {:?}", file))?;
        let client = self.get_or_spawn(lang, cmd, &args).await?;
        client.open_file(file).await?;
        client.goto_definition(file, line, character).await
    }
}

#[derive(Debug, serde::Serialize)]
pub struct FunctionAnalysis {
    pub item: Option<CallHierarchyItem>,
    pub incoming_calls: Vec<CallSite>,
    pub outgoing_calls: Vec<CallSite>,
}
