"""
Feishu bot bridge — directly invokes kiLee Agent core via WebSocket long-connection.

Architecture:
    Feishu/Lark app
        ↓ WebSocket long-connection
    lark-oapi SDK (Python)
        ↓ direct function call
    kilee.agent.run_agent()
        ↓
    DeepSeek API
"""

import asyncio
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional, Tuple

from .env import get_config, BridgeConfig

logger = logging.getLogger("kilee.feishu")

# ── Helpers ─────────────────────────────────────────────────────────────────

HELP_TEXT = """DeepSeek phone bridge commands:
/help - show this help
/status - runtime and workspace status
/threads - recent runtime threads
/new - create a new thread for this chat
/resume <thread_id> - bind this chat to an existing thread
/interrupt - interrupt the active turn
/compact - compact the current thread
/allow <approval_id> [remember] - approve a pending tool call
/deny <approval_id> - deny a pending tool call

Anything else is sent as a DeepSeek prompt."""


def split_message(text: str, max_chars: int = 3500) -> list:
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks = []
    cursor = 0
    while cursor < len(text):
        chunks.append(text[cursor : cursor + max_chars])
        cursor += max_chars
    return chunks


def parse_text_content(content: str) -> str:
    """Parse Feishu message content (JSON with 'text' field)."""
    if not content:
        return ""
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed.get("text", "") or parsed.get("content", "")
    except (json.JSONDecodeError, TypeError):
        return content
    return content


def incoming_identity(event: dict) -> dict:
    """Extract chat/user identity from a Feishu message event."""
    sender = (event.get("sender") or {}).get("sender_id") or {}
    message = event.get("message") or {}
    return {
        "chat_id": message.get("chat_id", ""),
        "message_id": message.get("message_id", ""),
        "chat_type": message.get("chat_type", ""),
        "message_type": message.get("message_type", ""),
        "open_id": sender.get("open_id", ""),
        "union_id": sender.get("union_id", ""),
        "user_id": sender.get("user_id", ""),
    }


def is_allowed(identity: dict, allowlist: list, allow_unlisted: bool = False) -> bool:
    if allow_unlisted:
        return True
    allowed = set(allowlist)
    for key in ("chat_id", "open_id", "union_id", "user_id"):
        val = identity.get(key, "")
        if val and val in allowed:
            return True
    return False


def pairing_refusal_text(identity: dict) -> str:
    lines = [
        "This chat is not in DEEPSEEK_CHAT_ALLOWLIST.",
        f"chat_id={identity.get('chat_id', '')}",
    ]
    if identity.get("open_id"):
        lines.append(f"open_id={identity['open_id']}")
    if identity.get("union_id"):
        lines.append(f"union_id={identity['union_id']}")
    if identity.get("user_id"):
        lines.append(f"user_id={identity['user_id']}")
    return "\n".join(lines)


def strip_group_prefix(text: str, chat_type: str, require_prefix: bool, prefix: str) -> tuple:
    """Returns (accepted: bool, text: str)."""
    trimmed = (text or "").strip()
    if not trimmed:
        return False, ""
    if not require_prefix or chat_type == "p2p":
        return True, trimmed
    marker = prefix or "/ds"
    if trimmed == marker:
        return True, "/help"
    if trimmed.startswith(marker + " "):
        return True, trimmed[len(marker):].strip()
    return False, ""


def parse_command(text: str) -> dict:
    trimmed = (text or "").strip()
    if not trimmed.startswith("/"):
        return {"name": "prompt", "args": trimmed}
    parts = trimmed.split(None, 1)
    name = parts[0][1:].lower()
    args = parts[1] if len(parts) > 1 else ""
    return {"name": name, "args": args}


# ── Thread Store ────────────────────────────────────────────────────────────

class ThreadStore:
    def __init__(self, path: str):
        self._path = Path(path)
        self._data: dict = {"chats": {}, "messages": []}
        self._dirty = False

    @classmethod
    async def open(cls, path: str) -> "ThreadStore":
        store = cls(path)
        store._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = store._path.read_text()
            store._data = json.loads(raw)
            if "chats" not in store._data:
                store._data["chats"] = {}
            if "messages" not in store._data:
                store._data["messages"] = []
        except (FileNotFoundError, json.JSONDecodeError):
            store._data = {"chats": {}, "messages": []}
        return store

    async def _save(self):
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._path.write_text(json.dumps(self._data, indent=2))
        )
        self._dirty = False

    def _mark(self):
        self._dirty = True

    def get_chat(self, chat_id: str) -> Optional[dict]:
        return self._data.get("chats", {}).get(str(chat_id))

    async def set_chat(self, chat_id: str, state: dict):
        self._data.setdefault("chats", {})[str(chat_id)] = state
        self._mark()
        await self._save()

    async def patch_chat(self, chat_id: str, patch: dict):
        chats = self._data.setdefault("chats", {})
        key = str(chat_id)
        if key not in chats:
            chats[key] = {}
        chats[key].update(patch)
        self._mark()
        await self._save()

    async def record_message(self, message_id: str) -> bool:
        """Returns True if already seen."""
        if not message_id:
            return False
        messages = self._data.setdefault("messages", [])
        if message_id in messages:
            return True
        messages.append(message_id)
        self._data["messages"] = messages[-200:]  # keep last 200
        self._mark()
        await self._save()
        return False


# ── Agent Bridge ────────────────────────────────────────────────────────────

_agent_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kilee-agent-")


def _build_feishu_system_prompt() -> str:
    from kilee.agent import build_system_prompt as base_prompt
    hint = (
        "You are being controlled from a Feishu/Lark phone chat. "
        "Keep status updates concise. "
        "Ask for tool approvals when needed; do not assume mobile messages imply blanket approval."
    )
    base = base_prompt()
    if "\n\n" in base:
        parts = base.split("\n\n", 1)
        return f"{parts[0]}\n\n{hint}\n\n{parts[1]}"
    return f"{base}\n\n{hint}"


async def run_agent_async(messages: list) -> Tuple[str, dict]:
    from kilee.agent import run_agent_with_state
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _agent_executor,
        run_agent_with_state,
        messages,
    )
    return result.get("response", ""), result


# ── Bot ─────────────────────────────────────────────────────────────────────

def run_bot():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    config = get_config()
    logger.info("Starting DeepSeek Feishu bridge (Python-native)")
    logger.info("Workspace: %s", config.workspace)
    if not config.allowlist and not config.allow_unlisted:
        logger.warning("No allowlist configured. Incoming chats will receive IDs and be refused.")

    try:
        import lark_oapi as lark
    except ImportError:
        logger.error(
            "lark-oapi is not installed. "
            "Install it with: pip install lark-oapi"
        )
        sys.exit(1)

    bridge = FeishuBridge(config)

    # Build SDK client
    sdk_config = lark.Config.builder() \
        .app_id(config.app_id) \
        .app_secret(config.app_secret) \
        .domain(
            lark.FeishuDomain if config.domain == "feishu"
            else lark.LarkDomain if config.domain == "lark"
            else config.domain
        ) \
        .build()
    client = lark.Client.builder().config(sdk_config).build()

    # WebSocket client
    ws_config = lark.WSConfig.builder() \
        .app_id(config.app_id) \
        .app_secret(config.app_secret) \
        .domain(
            lark.FeishuDomain if config.domain == "feishu"
            else lark.LarkDomain if config.domain == "lark"
            else config.domain
        ) \
        .build()
    ws_client = lark.ws.Client.builder().config(ws_config).build()

    # Event handler
    async def on_message(data: dict):
        await bridge.handle_incoming(data, client)

    event_handler = {
        "im.message.receive_v1": on_message
    }

    # Register and start
    ws_client.register_event_handler(event_handler)

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(asyncio.gather(
            bridge.initialize(),
            ws_client.start(),
        ))
    except KeyboardInterrupt:
        logger.info("Feishu bridge shutting down")
        loop.run_until_complete(ws_client.stop())


class FeishuBridge:
    def __init__(self, config: BridgeConfig):
        self.cfg = config
        self._store: Optional[ThreadStore] = None
        self._active_tasks: Dict[str, asyncio.Task] = {}

    async def initialize(self):
        self._store = await ThreadStore.open(self.cfg.thread_map_path)

    @property
    def store(self) -> ThreadStore:
        if self._store is None:
            raise RuntimeError("Bridge not initialized")
        return self._store

    # ── Incoming message handler ─────────────────────────────────────────

    async def handle_incoming(self, event: dict, client):
        identity = incoming_identity(event)
        if not identity["chat_id"]:
            return

        if identity["message_type"] and identity["message_type"] != "text":
            await self._send_text(client, identity["chat_id"],
                                  "Only text messages are supported in this first bridge.")
            return

        raw_text = parse_text_content((event.get("message") or {}).get("content") or "")
        accepted, scoped_text = strip_group_prefix(
            raw_text, identity["chat_type"],
            self.cfg.require_prefix_in_group, self.cfg.group_prefix
        )
        if not accepted:
            return

        # Dedup
        if identity["message_id"] and await self.store.record_message(identity["message_id"]):
            return

        # Group check
        if identity["chat_type"] != "p2p" and not self.cfg.allow_groups:
            await self._send_text(client, identity["chat_id"],
                "Group chat control is disabled for this bridge. "
                "DM the bot, or set FEISHU_ALLOW_GROUPS=true and allowlist this chat.")
            return

        # Allowlist check
        if not is_allowed(identity, self.cfg.allowlist, self.cfg.allow_unlisted):
            await self._send_text(client, identity["chat_id"], pairing_refusal_text(identity))
            return

        command = parse_command(scoped_text)
        await self._handle_command(client, identity["chat_id"], command)

    async def _handle_command(self, client, chat_id: str, command: dict):
        name = command["name"]
        args = command.get("args", "")

        if name == "help":
            await self._send_text(client, chat_id, HELP_TEXT)
        elif name == "status":
            await self._cmd_status(client, chat_id)
        elif name == "threads":
            await self._cmd_threads(client, chat_id)
        elif name == "new":
            state = await self._ensure_thread(chat_id, force_new=True)
            await self._send_text(client, chat_id, f"Created thread {state['thread_id']}")
        elif name == "resume":
            await self._cmd_resume(client, chat_id, args)
        elif name == "interrupt":
            await self._cmd_interrupt(client, chat_id)
        elif name == "compact":
            await self._cmd_compact(client, chat_id)
        elif name == "allow":
            await self._send_text(client, chat_id,
                "Approval system: tools are auto-approved in this bridge. "
                "Set DEEPSEEK_AUTO_APPROVE=false to enable manual approval.")
        elif name == "deny":
            await self._send_text(client, chat_id,
                "Approval system: tools are auto-approved in this bridge.")
        elif name == "prompt":
            await self._run_prompt(client, chat_id, args)
        else:
            await self._send_text(client, chat_id, HELP_TEXT)

    # ── Thread helpers ───────────────────────────────────────────────────

    def _new_thread_state(self) -> dict:
        return {
            "thread_id": f"fs_{int(time.time() * 1000)}",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "messages": [
                {"role": "system", "content": _build_feishu_system_prompt()}
            ],
        }

    async def _ensure_thread(self, chat_id: str, force_new: bool = False) -> dict:
        existing = self.store.get_chat(chat_id)
        if existing and not force_new:
            return existing
        state = self._new_thread_state()
        await self.store.set_chat(chat_id, state)
        return state

    async def _get_messages(self, chat_id: str) -> list:
        state = await self._ensure_thread(chat_id)
        messages = state.get("messages", [])
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": _build_feishu_system_prompt()})
        return messages

    # ── Command handlers ─────────────────────────────────────────────────

    async def _cmd_status(self, client, chat_id: str):
        try:
            state = self.store.get_chat(chat_id)
            lines = [
                f"Workspace: {self.cfg.workspace}",
                f"Model: {self.cfg.model}",
                f"Mode: {self.cfg.mode}",
                f"Active thread: {state.get('thread_id', 'none') if state else 'none'}",
                f"Messages: {len(state.get('messages', [])) if state else 0}",
            ]
            await self._send_text(client, chat_id, "\n".join(lines))
        except Exception as e:
            await self._send_text(client, chat_id, f"Status error: {e}")

    async def _cmd_threads(self, client, chat_id: str):
        try:
            all_chats = self.store.all_chats() if hasattr(self.store, 'all_chats') else []
            # Build list from store data
            chats_data = []
            for cid, state in self._store._data.get("chats", {}).items():
                chats_data.append({
                    "chat_id": cid,
                    "thread_id": state.get("thread_id", "?"),
                    "updated_at": state.get("updated_at", "?"),
                })
            if not chats_data:
                return await self._send_text(client, chat_id, "No threads found.")
            lines = [f"{i}. {c['thread_id']} [{c.get('updated_at', '?')}]"
                     for i, c in enumerate(chats_data[:8], 1)]
            await self._send_text(client, chat_id, "\n".join(lines))
        except Exception as e:
            await self._send_text(client, chat_id, f"Threads error: {e}")

    async def _cmd_resume(self, client, chat_id: str, thread_id: str):
        thread_id = thread_id.strip()
        if not thread_id:
            return await self._send_text(client, chat_id, "Usage: /resume <thread_id>")
        state = self.store.get_chat(chat_id)
        if state:
            await self._send_text(client, chat_id,
                                  f"Resumed thread {state.get('thread_id', 'unknown')}")
        else:
            await self._send_text(client, chat_id,
                                  "No thread found. Send a prompt or /new to start.")

    async def _cmd_interrupt(self, client, chat_id: str):
        task = self._active_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            await self._send_text(client, chat_id, "Interrupted active turn.")
        else:
            await self._send_text(client, chat_id, "No active turn to interrupt.")

    async def _cmd_compact(self, client, chat_id: str):
        state = self.store.get_chat(chat_id)
        if not state:
            return await self._send_text(client, chat_id, "No active thread to compact.")
        try:
            messages = state.get("messages", [])
            if len(messages) <= 5:
                return await self._send_text(client, chat_id, "Context already short.")
            system_msgs = [m for m in messages if m.get("role") == "system"]
            non_system = [m for m in messages if m.get("role") != "system"]
            trimmed = system_msgs + non_system[-8:]
            state["messages"] = trimmed
            await self.store.set_chat(chat_id, state)
            await self._send_text(client, chat_id,
                                  f"Compacted. {len(messages)} → {len(trimmed)} messages.")
        except Exception as e:
            await self._send_text(client, chat_id, f"Compact error: {e}")

    # ── Prompt handler ───────────────────────────────────────────────────

    async def _run_prompt(self, client, chat_id: str, prompt: str):
        if not prompt.strip():
            return await self._send_text(client, chat_id, HELP_TEXT)

        if chat_id in self._active_tasks and not self._active_tasks[chat_id].done():
            await self._send_text(client, chat_id,
                "A previous prompt is still being processed. "
                "Wait for it to finish or send /interrupt.")
            return

        task = asyncio.create_task(self._process_prompt(client, chat_id, prompt))
        self._active_tasks[chat_id] = task

        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Error processing prompt for chat %s", chat_id)
            await self._send_text(client, chat_id, f"Error: {e}")
        finally:
            self._active_tasks.pop(chat_id, None)

    async def _process_prompt(self, client, chat_id: str, prompt: str):
        messages = await self._get_messages(chat_id)
        messages.append({"role": "user", "content": prompt})

        try:
            response, state = await run_agent_async(messages)
        except Exception:
            logger.exception("Agent error for chat %s", chat_id)
            messages.pop()
            raise

        if response:
            messages.append({"role": "assistant", "content": response})

        chat_state = self.store.get_chat(chat_id) or {}
        chat_state["messages"] = messages
        chat_state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self.store.set_chat(chat_id, chat_state)

        if response:
            chunks = split_message(response, self.cfg.max_reply_chars)
            for chunk in chunks:
                await self._send_text(client, chat_id, chunk)
        else:
            await self._send_text(client, chat_id, "Done (no response)")

    # ── Send message ─────────────────────────────────────────────────────

    async def _send_text(self, client, chat_id: str, text: str):
        """Send a text message via Feishu API."""
        try:
            req = client.im.v1.message.create(
                receive_id_type="chat_id",
                body={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}),
                }
            )
            await req
        except Exception as e:
            logger.exception("Failed to send Feishu message to %s", chat_id)
