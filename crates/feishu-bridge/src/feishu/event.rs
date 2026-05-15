use anyhow::{Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use serde_json::Value;
use tokio::sync::mpsc;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use tracing::{error, info, warn};

#[derive(Debug, Deserialize)]
struct WsEvent {
    #[serde(default)]
    r#type: String,
    header: Option<EventHeader>,
    event: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct EventHeader {
    event_type: String,
}

#[derive(Debug, Deserialize)]
struct MessageReceiveEvent {
    sender: SenderInfo,
    message: MessageBody,
}

#[derive(Debug, Deserialize)]
struct SenderInfo {
    sender_id: UserIdInfo,
}

#[derive(Debug, Deserialize)]
struct UserIdInfo {
    open_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct MessageBody {
    message_id: String,
    msg_type: String,
    content: String,
    chat_type: String,
    chat_id: Option<String>,
}

#[derive(Debug, Clone)]
pub struct FeishuEvent {
    pub sender_id: String,
    pub chat_id: String,
    pub chat_type: String,
    pub text: String,
    pub is_group: bool,
}

pub async fn connect_and_listen(
    ws_url: &str,
    token: &str,
    event_tx: mpsc::UnboundedSender<FeishuEvent>,
) -> Result<()> {
    let url = format!("{}/?token={}", ws_url, token);
    info!("Connecting to Feishu WebSocket...");

    let (ws, _) = connect_async(&url)
        .await
        .context("Failed to connect to Feishu WebSocket")?;

    info!("Feishu WebSocket connected");
    let (mut write, mut read) = ws.split();

    let (heartbeat_tx, mut heartbeat_rx) = mpsc::channel::<()>(1);
    let hb = tokio::spawn(async move {
        loop {
            tokio::time::sleep(std::time::Duration::from_secs(25)).await;
            if heartbeat_tx.send(()).await.is_err() {
                break;
            }
        }
    });

    loop {
        tokio::select! {
            msg = read.next() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        if let Err(e) = handle_event(&text, &event_tx).await {
                            error!("Failed to handle WS message: {}", e);
                        }
                    }
                    Some(Ok(Message::Ping(data))) => {
                        let _ = write.send(Message::Pong(data)).await;
                    }
                    Some(Ok(Message::Close(_))) => {
                        info!("Feishu WebSocket closed");
                        break;
                    }
                    Some(Err(e)) => {
                        error!("Feishu WebSocket error: {}", e);
                        break;
                    }
                    None => break,
                    _ => {}
                }
            }
            _ = heartbeat_rx.recv() => {
                if write.send(Message::Ping(vec![])).await.is_err() {
                    break;
                }
            }
        }
    }

    hb.abort();
    anyhow::bail!("Feishu WebSocket disconnected");
}

async fn handle_event(text: &str, event_tx: &mpsc::UnboundedSender<FeishuEvent>) -> Result<()> {
    let event: WsEvent = serde_json::from_str(text)?;

    if event.r#type == "url_verification" {
        return Ok(());
    }

    let event_type = event
        .header
        .as_ref()
        .map(|h| h.event_type.as_str())
        .unwrap_or("");

    if event_type != "im.message.receive_v1" {
        return Ok(());
    }

    let event_data = match event.event {
        Some(data) => data,
        None => return Ok(()),
    };

    let msg: MessageReceiveEvent = serde_json::from_value(event_data)?;
    if msg.message.msg_type != "text" {
        return Ok(());
    }

    let content: Value = serde_json::from_str(&msg.message.content)?;
    let text = content
        .get("text")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    if text.is_empty() {
        return Ok(());
    }

    let sender_id = msg.sender.sender_id.open_id.unwrap_or_default();
    let chat_type = msg.message.chat_type;
    let (chat_id, is_group) = if chat_type == "group" {
        (msg.message.chat_id.unwrap_or(sender_id.clone()), true)
    } else {
        (sender_id.clone(), false)
    };

    let _ = event_tx.send(FeishuEvent {
        sender_id,
        chat_id,
        chat_type,
        text,
        is_group,
    });

    Ok(())
}
