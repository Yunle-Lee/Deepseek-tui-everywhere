mod config;
mod deepseek;
mod feishu;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::Result;
use clap::Parser;
use tokio::sync::{mpsc, Mutex};
use tracing::{error, info};

use config::Config;
use deepseek::client::{DeepSeekClient, StreamEvent};
use feishu::auth::TokenManager;
use feishu::event::{connect_and_listen, FeishuEvent};
use feishu::message::MessageClient;

#[derive(Parser)]
#[command(
    name = "deepseek-feishu",
    about = "Feishu/Lark bot bridge for DeepSeek-TUI"
)]
struct Cli {
    #[arg(short, long, default_value = "~/.deepseek/feishu.toml")]
    config: PathBuf,

    #[arg(short, long)]
    deepseek_url: Option<String>,

    #[arg(long)]
    feishu_app_id: Option<String>,

    #[arg(long)]
    feishu_app_secret: Option<String>,
}

struct SessionStore {
    sessions: HashMap<String, Session>,
}

struct Session {
    thread_id: String,
    last_seq: u64,
}

impl SessionStore {
    fn new() -> Self {
        Self {
            sessions: HashMap::new(),
        }
    }

    fn get_or_create(&mut self, key: &str) -> &mut Session {
        self.sessions.entry(key.to_string()).or_insert(Session {
            thread_id: String::new(),
            last_seq: 0,
        })
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let cli = Cli::parse();

    let config_path = if cli.config.to_string_lossy().starts_with('~') {
        let home = std::env::var("HOME")?;
        PathBuf::from(home).join(cli.config.strip_prefix("~/").unwrap())
    } else {
        cli.config.clone()
    };

    let mut cfg = if config_path.exists() {
        Config::load(&config_path)?
    } else {
        info!("No config found at {}, using defaults", config_path.display());
        Config {
            feishu: config::FeishuConfig {
                app_id: String::new(),
                app_secret: String::new(),
                base_url: "https://open.feishu.cn".to_string(),
                ws_url: "wss://open.feishu.cn/ws/v1/events".to_string(),
            },
            deepseek: config::DeepSeekConfig {
                api_url: "http://127.0.0.1:7878".to_string(),
                auth_token: None,
            },
        }
    };

    if let Some(url) = cli.deepseek_url {
        cfg.deepseek.api_url = url;
    }
    if let Some(id) = cli.feishu_app_id {
        cfg.feishu.app_id = id;
    }
    if let Some(secret) = cli.feishu_app_secret {
        cfg.feishu.app_secret = secret;
    }

    if cfg.feishu.app_id.is_empty() || cfg.feishu.app_secret.is_empty() {
        anyhow::bail!(
            "Feishu App ID and App Secret required. Set in config or via --feishu-app-id / --feishu-app-secret"
        );
    }

    info!("Feishu App ID: {}", cfg.feishu.app_id);
    info!("DeepSeek API: {}", cfg.deepseek.api_url);

    let auth = Arc::new(TokenManager::new(
        cfg.feishu.app_id.clone(),
        cfg.feishu.app_secret.clone(),
        cfg.feishu.base_url.clone(),
    ));

    let msg_client = MessageClient::new((*auth).clone(), cfg.feishu.base_url.clone());
    let ds_client = Arc::new(DeepSeekClient::new(
        cfg.deepseek.api_url.clone(),
        cfg.deepseek.auth_token.clone(),
    ));
    let sessions = Arc::new(Mutex::new(SessionStore::new()));

    let (event_tx, mut event_rx) = mpsc::unbounded_channel::<FeishuEvent>();
    let ws_url = cfg.feishu.ws_url.clone();
    let auth_ws = auth.clone();

    let ws_handle = tokio::spawn(async move {
        loop {
            match auth_ws.get_token().await {
                Ok(token) => {
                    if let Err(e) =
                        connect_and_listen(&ws_url, &token, event_tx.clone()).await
                    {
                        error!("Feishu WS: {}. Reconnecting...", e);
                    }
                }
                Err(e) => {
                    error!("Token error: {}. Retrying...", e);
                    tokio::time::sleep(std::time::Duration::from_secs(10)).await;
                    continue;
                }
            }
            tokio::time::sleep(std::time::Duration::from_secs(5)).await;
        }
    });

    info!("🚀 DeepSeek-Feishu Bridge started");

    while let Some(event) = event_rx.recv().await {
        let key = format!("{}:{}", event.chat_type, event.chat_id);
        let recipient = if event.is_group {
            &event.chat_id
        } else {
            &event.sender_id
        };
        info!(
            "📩 {} (group: {}): {}",
            event.chat_id, event.is_group, event.text
        );

        let thread_id = {
            let mut store = sessions.lock().await;
            let s = store.get_or_create(&key);
            if s.thread_id.is_empty() {
                match ds_client.create_thread(Some("Feishu Chat")).await {
                    Ok(id) => {
                        info!("Thread {} created for {}", id, key);
                        s.thread_id = id.clone();
                        id
                    }
                    Err(e) => {
                        error!("Create thread: {}", e);
                        let _ = msg_client
                            .send_text(recipient, "❌ Cannot connect to AI engine", event.is_group)
                            .await;
                        continue;
                    }
                }
            } else {
                s.thread_id.clone()
            }
        };

        match ds_client.send_turn(&thread_id, &event.text).await {
            Ok(_turn_id) => {}
            Err(e) => {
                error!("Send turn: {}", e);
                let _ = msg_client
                    .send_text(recipient, "❌ AI engine unavailable", event.is_group)
                    .await;
                continue;
            }
        }

        let _ = msg_client
            .send_text(recipient, "🤔 Processing...", event.is_group)
            .await;

        let (stream_tx, mut stream_rx) = mpsc::unbounded_channel::<StreamEvent>();
        let mut response = String::new();
        let last_seq = {
            let store = sessions.lock().await;
            store.sessions.get(&key).map(|s| s.last_seq).unwrap_or(0)
        };

        let ds = ds_client.clone();
        let tid = thread_id.clone();
        let handle = tokio::spawn(async move { ds.stream_events(&tid, last_seq, stream_tx).await });

        let mut turn_done = false;
        while let Some(ev) = stream_rx.recv().await {
            match ev {
                StreamEvent::Delta(d) => response.push_str(&d),
                StreamEvent::TurnCompleted => {
                    turn_done = true;
                    break;
                }
            }
        }

        let new_seq = if turn_done {
            handle.await.unwrap_or(Ok(last_seq)).unwrap_or(last_seq)
        } else {
            handle.await.unwrap_or(Ok(last_seq)).unwrap_or(last_seq)
        };

        {
            let mut store = sessions.lock().await;
            if let Some(s) = store.sessions.get_mut(&key) {
                s.last_seq = new_seq.max(s.last_seq);
            }
        }

        if response.is_empty() {
            let _ = msg_client
                .send_text(recipient, "🤖 Done (no text response)", event.is_group)
                .await;
        } else {
            info!("Response ({} chars)", response.len());
            let _ = msg_client
                .send_text(recipient, &response, event.is_group)
                .await;
        }
    }

    ws_handle.abort();
    Ok(())
}
