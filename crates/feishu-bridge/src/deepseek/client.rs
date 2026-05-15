use anyhow::Result;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;
use tokio::sync::mpsc;
use tracing::{debug, info};

#[derive(Debug, Clone)]
pub struct DeepSeekClient {
    client: reqwest::Client,
    base_url: String,
    auth_token: Option<String>,
}

#[derive(Debug, Serialize)]
struct CreateThreadRequest {
    #[serde(skip_serializing_if = "Option::is_none")]
    title: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ThreadResponse {
    id: String,
}

#[derive(Debug, Serialize)]
struct SendTurnRequest {
    content: String,
}

#[derive(Debug, Deserialize)]
struct TurnResponse {
    id: String,
}

#[derive(Debug, Deserialize)]
struct SseEvent {
    seq: u64,
    event: String,
    payload: Option<SsePayload>,
}

#[derive(Debug, Deserialize)]
struct SsePayload {
    delta: Option<String>,
    kind: Option<String>,
}

#[derive(Debug, Clone)]
pub enum StreamEvent {
    Delta(String),
    TurnCompleted,
}

impl DeepSeekClient {
    pub fn new(base_url: String, auth_token: Option<String>) -> Self {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(600))
            .build()
            .expect("Failed to build HTTP client");
        Self {
            client,
            base_url,
            auth_token,
        }
    }

    fn headers(&self) -> reqwest::header::HeaderMap {
        let mut h = reqwest::header::HeaderMap::new();
        if let Some(token) = &self.auth_token {
            h.insert(
                reqwest::header::AUTHORIZATION,
                format!("Bearer {}", token).parse().unwrap(),
            );
        }
        h.insert(
            reqwest::header::ACCEPT,
            "text/event-stream".parse().unwrap(),
        );
        h
    }

    pub async fn create_thread(&self, title: Option<&str>) -> Result<String> {
        let req = CreateThreadRequest {
            title: title.map(String::from),
        };
        let resp: ThreadResponse = self
            .client
            .post(format!("{}/v1/threads", self.base_url))
            .headers(self.headers())
            .json(&req)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        Ok(resp.id)
    }

    pub async fn send_turn(&self, thread_id: &str, content: &str) -> Result<String> {
        let req = SendTurnRequest {
            content: content.to_string(),
        };
        let resp: TurnResponse = self
            .client
            .post(format!(
                "{}/v1/threads/{}/turns",
                self.base_url, thread_id
            ))
            .headers(self.headers())
            .json(&req)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?;
        Ok(resp.id)
    }

    pub async fn stream_events(
        &self,
        thread_id: &str,
        since_seq: u64,
        event_tx: mpsc::UnboundedSender<StreamEvent>,
    ) -> Result<u64> {
        let url = format!(
            "{}/v1/threads/{}/events?since_seq={}",
            self.base_url, thread_id, since_seq
        );
        info!("SSE: {}", url);

        let response = self
            .client
            .get(&url)
            .headers(self.headers())
            .send()
            .await?
            .error_for_status()?;

        let mut stream = response.bytes_stream();
        let mut buf = String::new();
        let mut last_seq = since_seq;

        while let Some(chunk) = stream.next().await {
            let chunk = chunk?;
            buf.push_str(&String::from_utf8_lossy(&chunk));

            loop {
                let end = match buf.find("\n\n") {
                    Some(pos) => pos,
                    None => break,
                };
                let event_str = buf[..end].trim().to_string();
                buf = buf[end + 2..].to_string();

                if event_str.is_empty() {
                    continue;
                }

                let data = match event_str
                    .lines()
                    .find(|l| l.starts_with("data: "))
                    .and_then(|l| l.strip_prefix("data: "))
                {
                    Some(d) => d.trim(),
                    None => continue,
                };

                if data == "[DONE]" {
                    info!("SSE [DONE]");
                    break;
                }

                match serde_json::from_str::<SseEvent>(data) {
                    Ok(ev) => {
                        last_seq = ev.seq;
                        match ev.event.as_str() {
                            "turn.completed" => {
                                let _ = event_tx.send(StreamEvent::TurnCompleted);
                            }
                            "item.delta" => {
                                if let Some(payload) = &ev.payload {
                                    if let Some(delta) = &payload.delta {
                                        let _ =
                                            event_tx.send(StreamEvent::Delta(delta.clone()));
                                    }
                                }
                            }
                            _ => debug!("SSE {} seq={}", ev.event, ev.seq),
                        }
                    }
                    Err(e) => debug!("SSE parse: {} — {}", e, data),
                }
            }
        }

        info!("SSE ended, last_seq={}", last_seq);
        Ok(last_seq)
    }
}
