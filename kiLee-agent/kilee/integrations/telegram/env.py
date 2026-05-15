"""
Telegram bridge environment configuration.

Reads config from environment variables (prefixed TELEGRAM_ / DEEPSEEK_)
and optional .env file in cwd or /etc/deepseek/telegram-bridge.env.

Mirrors the upstream Node.js bridge .env schema for compatibility.
"""

import os
import sys
from pathlib import Path
from typing import List


def parse_bool(raw: str | None, fallback: bool = False) -> bool:
    """Parse a boolean-ish environment value."""
    if raw is None or raw == "":
        return fallback
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def parse_list(raw: str | None) -> List[str]:
    """Parse a comma-separated list."""
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def _try_load_dotenv():
    """Best-effort: load a .env file if python-dotenv is available."""
    candidates = [
        Path.cwd() / ".env",
        Path("/etc/deepseek/telegram-bridge.env"),
    ]
    try:
        from dotenv import load_dotenv  # type: ignore
        for path in candidates:
            if path.exists():
                load_dotenv(path, override=False)
                break
    except ImportError:
        pass  # python-dotenv not installed; env vars only


_try_load_dotenv()


def required_env(name: str) -> str:
    """Read a required env var, exiting with a clear message if missing."""
    value = os.getenv(name, "")
    if not value:
        print(f"{name} is required", file=sys.stderr)
        sys.exit(1)
    return value


# ── Bridge config singleton ─────────────────────────────────────────────────

class BridgeConfig:
    """Immutable-ish config loaded once from the environment."""

    def __init__(self):
        self.bot_token: str = required_env("TELEGRAM_BOT_TOKEN")
        self.runtime_token: str = required_env("DEEPSEEK_RUNTIME_TOKEN")
        self.runtime_url: str = os.getenv("DEEPSEEK_RUNTIME_URL", "http://127.0.0.1:7878").rstrip("/")
        self.workspace: str = os.getenv("DEEPSEEK_WORKSPACE", str(Path.cwd()))
        self.model: str = os.getenv("DEEPSEEK_MODEL", "auto")
        self.mode: str = os.getenv("DEEPSEEK_MODE", "agent")
        self.allow_shell: bool = parse_bool(os.getenv("DEEPSEEK_ALLOW_SHELL"), True)
        self.trust_mode: bool = parse_bool(os.getenv("DEEPSEEK_TRUST_MODE"), False)
        self.auto_approve: bool = parse_bool(os.getenv("DEEPSEEK_AUTO_APPROVE"), False)
        self.allowlist: List[str] = parse_list(os.getenv("TELEGRAM_CHAT_ALLOWLIST"))
        self.allow_unlisted: bool = parse_bool(os.getenv("DEEPSEEK_ALLOW_UNLISTED"), False)
        self.owner_id: str = os.getenv("TELEGRAM_OWNER_ID", "")
        self.thread_map_path: str = os.getenv(
            "TELEGRAM_THREAD_MAP_PATH",
            "/var/lib/deepseek-telegram-bridge/thread-map.json",
        )
        self.max_reply_chars: int = int(os.getenv("TELEGRAM_MAX_REPLY_CHARS", "4000"))
        self.turn_timeout_ms: int = int(os.getenv("DEEPSEEK_TURN_TIMEOUT_MS", "900000"))


_config: BridgeConfig | None = None


def get_config() -> BridgeConfig:
    global _config
    if _config is None:
        _config = BridgeConfig()
    return _config
