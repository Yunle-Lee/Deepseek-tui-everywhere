use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Debug, Clone)]
pub struct TokenManager {
    client: reqwest::Client,
    app_id: String,
    app_secret: String,
    base_url: String,
    cached: Arc<RwLock<CachedToken>>,
}

#[derive(Debug, Clone)]
struct CachedToken {
    token: String,
    expires_at: i64,
}

#[derive(Debug, Serialize)]
struct TokenRequest {
    app_id: String,
    app_secret: String,
}

#[derive(Debug, Deserialize)]
struct TokenResponse {
    code: i64,
    msg: String,
    tenant_access_token: Option<String>,
    expire: Option<i64>,
}

impl TokenManager {
    pub fn new(app_id: String, app_secret: String, base_url: String) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .expect("Failed to build HTTP client");
        Self {
            client,
            app_id,
            app_secret,
            base_url,
            cached: Arc::new(RwLock::new(CachedToken {
                token: String::new(),
                expires_at: 0,
            })),
        }
    }

    pub async fn get_token(&self) -> Result<String> {
        {
            let cached = self.cached.read().await;
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs() as i64;
            if !cached.token.is_empty() && now < cached.expires_at - 60 {
                return Ok(cached.token.clone());
            }
        }

        let url = format!(
            "{}/open-apis/auth/v3/tenant_access_token/internal",
            self.base_url
        );
        let req = TokenRequest {
            app_id: self.app_id.clone(),
            app_secret: self.app_secret.clone(),
        };

        let resp: TokenResponse = self
            .client
            .post(&url)
            .json(&req)
            .send()
            .await
            .context("Failed to request tenant access token")?
            .json()
            .await
            .context("Failed to parse token response")?;

        if resp.code != 0 {
            anyhow::bail!("Feishu auth error {}: {}", resp.code, resp.msg);
        }

        let token = resp.tenant_access_token.unwrap();
        let expire = resp.expire.unwrap_or(7200);
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;

        {
            let mut cached = self.cached.write().await;
            cached.token = token.clone();
            cached.expires_at = now + expire;
        }

        Ok(token)
    }
}
