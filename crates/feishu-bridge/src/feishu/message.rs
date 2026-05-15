use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::auth::TokenManager;

pub struct MessageClient {
    client: reqwest::Client,
    auth: TokenManager,
    base_url: String,
}

#[derive(Debug, Serialize)]
struct SendMessageRequest {
    receive_id: String,
    msg_type: String,
    content: String,
}

#[derive(Debug, Deserialize)]
struct SendMessageResponse {
    code: i64,
    msg: String,
    data: Option<Value>,
}

impl MessageClient {
    pub fn new(auth: TokenManager, base_url: String) -> Self {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .build()
            .expect("Failed to build HTTP client");
        Self {
            client,
            auth,
            base_url,
        }
    }

    pub async fn send_text(
        &self,
        receive_id: &str,
        text: &str,
        is_group: bool,
    ) -> Result<()> {
        let token = self.auth.get_token().await?;
        let content = serde_json::json!({ "text": text }).to_string();
        let receive_id_type = if is_group {
            "chat_id"
        } else {
            "open_id"
        };
        let url = format!(
            "{}/open-apis/im/v1/messages?receive_id_type={}",
            self.base_url, receive_id_type
        );

        let resp: SendMessageResponse = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .json(&SendMessageRequest {
                receive_id: receive_id.to_string(),
                msg_type: "text".to_string(),
                content,
            })
            .send()
            .await
            .context("Failed to send message")?
            .json()
            .await
            .context("Failed to parse send response")?;

        if resp.code != 0 {
            anyhow::bail!("Feishu send error {}: {}", resp.code, resp.msg);
        }
        Ok(())
    }

    pub async fn send_card(
        &self,
        receive_id: &str,
        card: Value,
        is_group: bool,
    ) -> Result<()> {
        let token = self.auth.get_token().await?;
        let receive_id_type = if is_group {
            "chat_id"
        } else {
            "open_id"
        };
        let url = format!(
            "{}/open-apis/im/v1/messages?receive_id_type={}",
            self.base_url, receive_id_type
        );

        let resp: SendMessageResponse = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", token))
            .json(&SendMessageRequest {
                receive_id: receive_id.to_string(),
                msg_type: "interactive".to_string(),
                content: card.to_string(),
            })
            .send()
            .await
            .context("Failed to send card")?
            .json()
            .await
            .context("Failed to parse card response")?;

        if resp.code != 0 {
            anyhow::bail!("Feishu card error {}: {}", resp.code, resp.msg);
        }
        Ok(())
    }
}
