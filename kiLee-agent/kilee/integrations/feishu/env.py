"""
Feishu bridge environment configuration.

Mirrors the upstream Node.js bridge .env schema for compatibility.
"""

import os
import sys
from pathlib import Path
from typing import List


def parse_bool(raw: str | None, fallback: bool = False) -> bool:
    if raw is None or raw == "":
        return fallback
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def parse_list(raw: str | None) -> List[str]:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _try_load_dotenv():
    candidates = [
        Path.cwd() / ".env",
        Path("/etc/deepseek/feishu-bridge.env"),
    ]
    try:
        from dotenv import load_dotenv
        for path in candidates:
            if path.exists():
                load_dotenv(path, override=False)
                break
    except ImportError:
        pass


_try_load_dotenv()


def required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        print(f"{name} is required", file=sys.stderr)
        sys.exit(1)
    return value


class BridgeConfig:
    def __init__(self):
        self.app_id: str = required_env("FEISHU_APP_ID")
        self.app_secret: str = required_env("FEISHU_APP_SECRET")
        self.domain: str = os.getenv("FEISHU_DOMAIN", "feishu")
        self.runtime_url: str = os.getenv("DEEPSEEK_RUNTIME_URL", "http://127.0.0.1:7878").rstrip("/")
        self.runtime_token: str = os.getenv("DEEPSEEK_RUNTIME_TOKEN", "kilee-feishu-bridge")
        self.workspace: str = os.getenv("DEEPSEEK_WORKSPACE", str(Path.cwd()))
        self.model: str = os.getenv("DEEPSEEK_MODEL", "auto")
        self.mode: str = os.getenv("DEEPSEEK_MODE", "agent")
        self.allow_shell: bool = parse_bool(os.getenv("DEEPSEEK_ALLOW_SHELL"), True)
        self.trust_mode: bool = parse_bool(os.getenv("DEEPSEEK_TRUST_MODE"), False)
        self.auto_approve: bool = parse_bool(os.getenv("DEEPSEEK_AUTO_APPROVE"), False)
        self.allowlist: List[str] = parse_list(os.getenv("DEEPSEEK_CHAT_ALLOWLIST"))
        self.allow_unlisted: bool = parse_bool(os.getenv("DEEPSEEK_ALLOW_UNLISTED"), False)
        self.thread_map_path: str = os.getenv(
            "FEISHU_THREAD_MAP_PATH",
            "/var/lib/deepseek-feishu-bridge/thread-map.json",
        )
        self.allow_groups: bool = parse_bool(os.getenv("FEISHU_ALLOW_GROUPS"), False)
        self.require_prefix_in_group: bool = parse_bool(os.getenv("FEISHU_REQUIRE_PREFIX_IN_GROUP"), True)
        self.group_prefix: str = os.getenv("FEISHU_GROUP_PREFIX", "/ds")
        self.max_reply_chars: int = int(os.getenv("FEISHU_MAX_REPLY_CHARS", "3500"))
        self.turn_timeout_ms: int = int(os.getenv("DEEPSEEK_TURN_TIMEOUT_MS", "900000"))


_config: BridgeConfig | None = None


def get_config() -> BridgeConfig:
    global _config
    if _config is None:
        _config = BridgeConfig()
    return _config
