//! Keystore — Secure API key storage
//!
//! Priority chain: keyring (OS credential store) > environment variable > config.toml plaintext

use anyhow::{Context, Result};

const SERVICE_NAME: &str = "evocli";

/// Secure API key management
#[allow(dead_code)]
pub struct KeyStore;

#[allow(dead_code)]
impl KeyStore {
    /// Get API key for a provider.
    ///
    /// Resolution order:
    /// 1. OS keyring (Windows Credential Manager / macOS Keychain / Linux libsecret)
    /// 2. Environment variable (e.g., ANTHROPIC_API_KEY, OPENAI_API_KEY)
    /// 3. Config file plaintext (last resort)
    pub fn get(provider: &str) -> Result<Option<String>> {
        // 1. Try OS keyring
        match Self::get_from_keyring(provider) {
            Ok(Some(key)) => {
                tracing::debug!("API key for '{}' found in keyring", provider);
                return Ok(Some(key));
            }
            Ok(None) => {}
            Err(e) => {
                tracing::warn!("Keyring access failed for '{}': {}", provider, e);
            }
        }

        // 2. Try environment variable
        let env_key = Self::env_var_name(provider);
        if let Ok(key) = std::env::var(&env_key) {
            if !key.is_empty() {
                tracing::debug!("API key for '{}' found in env var {}", provider, env_key);
                return Ok(Some(key));
            }
        }

        // 3. Try config.toml plaintext
        let config = crate::config::Config::load_or_default()?;
        if let Some(ref key) = config.llm.api_key {
            if !key.is_empty() {
                tracing::warn!(
                    "Using plaintext API key from config.toml — consider `evocli init` for secure storage"
                );
                return Ok(Some(key.clone()));
            }
        }

        Ok(None)
    }

    /// Store API key in OS keyring
    pub fn set(provider: &str, key: &str) -> Result<()> {
        let entry = keyring::Entry::new(SERVICE_NAME, provider)
            .context("Failed to create keyring entry")?;
        entry
            .set_password(key)
            .context("Failed to store key in keyring")?;
        tracing::info!("API key for '{}' stored in OS keyring", provider);
        Ok(())
    }

    /// Delete API key from OS keyring
    pub fn delete(provider: &str) -> Result<()> {
        let entry = keyring::Entry::new(SERVICE_NAME, provider)
            .context("Failed to create keyring entry")?;
        match entry.delete_credential() {
            Ok(()) => {
                tracing::info!("API key for '{}' deleted from keyring", provider);
                Ok(())
            }
            Err(keyring::Error::NoEntry) => {
                tracing::debug!("No keyring entry for '{}'", provider);
                Ok(())
            }
            Err(e) => Err(anyhow::anyhow!("Failed to delete keyring entry: {}", e)),
        }
    }

    /// Check if keyring is available on this platform
    pub fn is_keyring_available() -> bool {
        let entry = keyring::Entry::new(SERVICE_NAME, "__probe__");
        match entry {
            Ok(e) => {
                // Try to read a non-existent entry — NoEntry means keyring works
                match e.get_password() {
                    Err(keyring::Error::NoEntry) => true,
                    Err(_) => false,
                    Ok(_) => true, // unlikely but OK
                }
            }
            Err(_) => false,
        }
    }

    // ── Helpers ───────────────────────────────────────────

    fn get_from_keyring(provider: &str) -> Result<Option<String>> {
        let entry = keyring::Entry::new(SERVICE_NAME, provider)
            .context("Failed to create keyring entry")?;
        match entry.get_password() {
            Ok(key) => Ok(Some(key)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(e) => Err(anyhow::anyhow!("Keyring read failed: {}", e)),
        }
    }

    fn env_var_name(provider: &str) -> String {
        match provider.to_lowercase().as_str() {
            "anthropic" => "ANTHROPIC_API_KEY".into(),
            "openai" => "OPENAI_API_KEY".into(),
            "deepseek" => "DEEPSEEK_API_KEY".into(),
            _ => format!("{}_API_KEY", provider.to_uppercase()),
        }
    }
}
