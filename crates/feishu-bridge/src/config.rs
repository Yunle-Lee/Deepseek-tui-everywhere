use anyhow::Result;
use serde::Deserialize;
use std::path::Path;

#[derive(Debug, Deserialize, Clone)]
pub struct Config {
    pub feishu: FeishuConfig,
    pub deepseek: DeepSeekConfig,
}

#[derive(Debug, Deserialize, Clone)]
pub struct FeishuConfig {
    pub app_id: String,
    pub app_secret: String,
    #[serde(default = "default_feishu_base_url")]
    pub base_url: String,
    #[serde(default = "default_ws_url")]
    pub ws_url: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct DeepSeekConfig {
    #[serde(default = "default_deepseek_api_url")]
    pub api_url: String,
    #[serde(default)]
    pub auth_token: Option<String>,
}

fn default_feishu_base_url() -> String {
    "https://open.feishu.cn".to_string()
}

fn default_ws_url() -> String {
    "wss://open.feishu.cn/ws/v1/events".to_string()
}

fn default_deepseek_api_url() -> String {
    "http://127.0.0.1:7878".to_string()
}

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        Ok(toml::from_str(&content)?)
    }
}
