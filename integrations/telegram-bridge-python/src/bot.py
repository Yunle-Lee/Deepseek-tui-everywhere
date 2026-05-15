"""
Telegram bot bridge — directly invokes kiLee Agent core.

Architecture:
    Telegram app
        ↓ Telegram Bot API (long polling)
    telegram-bot (python-telegram-bot v20+)
        ↓ direct function call
    kilee.agent.run_agent()
        ↓
    DeepSeek API / local runtime
"""

import asyncio
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Optional, Tuple

from .env import get_config, BridgeConfig

logger = logging.getLogger("kilee.telegram")

# ── Helpers ─────────────────────────────────────────────────────────────────

HELP_TEXT = """DeepSeek Telegram Bridge Commands:

/help          — Show this help
/status        — Show runtime status and active thread info
/threads       — List your threads
/new           — Start a new thread
/resume <id>   — Resume an existing thread
/interrupt     — Interrupt the active turn
/compact       — Compact the active thread's context
/allow <id>    — Approve a pending tool call
/deny <id>     — Reject a pending tool call

Any other text is sent as a prompt to the AI."""


def split_message(text: str, max_chars: int = 4000) -> list:
    """Split a long message into Telegram-safe chunks."""
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


# ── Thread Store ────────────────────────────────────────────────────────────

class ThreadStore:
    """Persistent thread state per chat (mirrors upstream ThreadStore)."""

    def __init__(self, path: str):
        self._path = Path(path)
        self._data: dict = {"chats": {}}
        self._dirty = False

    @classmethod
    async def open(cls, path: str) -> "ThreadStore":
        store = cls(path)
        store._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = store._path.read_text()
            store._data = json.loads(raw)
        except (FileNotFoundError, json.JSONDecodeError):
            store._data = {"chats": {}}
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

    def all_chats(self) -> list:
        return [
            {"chat_id": cid, **state}
            for cid, state in self._data.get("chats", {}).items()
        ]


# ── Agent Bridge ────────────────────────────────────────────────────────────

# Single thread pool for running synchronous agent calls
_agent_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kilee-agent-")


def _build_telegram_system_prompt() -> str:
    """Build the system prompt for Telegram sessions."""
    from kilee.agent import build_system_prompt as base_prompt
    telegram_hint = (
        "You are being controlled from a Telegram chat. "
        "Keep status updates concise. "
        "Ask for tool approvals when needed."
    )
    base = base_prompt()
    # Insert the telegram hint after the first line-break double
    if "\n\n" in base:
        parts = base.split("\n\n", 1)
        return f"{parts[0]}\n\n{telegram_hint}\n\n{parts[1]}"
    return f"{base}\n\n{telegram_hint}"


async def run_agent_async(messages: list) -> Tuple[str, dict]:
    """
    Run the kiLee agent in a thread executor.
    
    Returns (response_text, state_dict) where state_dict has keys:
        response, state, steps, tool_results
    """
    from kilee.agent import run_agent_with_state

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _agent_executor,
        run_agent_with_state,
        messages,
    )
    return result.get("response", ""), result


# ── Bot Setup ───────────────────────────────────────────────────────────────

def run_bot():
    """
    Entry point: configure logging, import and launch the bot.
    
    Called from CLI (`kilee telegram`) or `python -m`.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    config = get_config()
    logger.info("Starting DeepSeek Telegram bridge (Python-native)")
    logger.info("Runtime: %s", config.runtime_url)
    logger.info("Workspace: %s", config.workspace)

    if not config.allowlist and not config.allow_unlisted:
        logger.warning("No allowlist configured. Incoming chats will be refused.")

    try:
        from telegram.ext import (
            Application,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except ImportError:
        logger.error(
            "python-telegram-bot is not installed. "
            "Install it with: pip install python-telegram-bot[job-queue]"
        )
        sys.exit(1)

    # Build the Application
    app = Application.builder().token(config.bot_token).build()

    # Create bridge instance
    bridge = TelegramBridge(config)

    # Register handlers
    app.add_handler(CommandHandler("start", bridge.cmd_start))
    app.add_handler(CommandHandler("help", bridge.cmd_help))
    app.add_handler(CommandHandler("status", bridge.cmd_status))
    app.add_handler(CommandHandler("threads", bridge.cmd_threads))
    app.add_handler(CommandHandler("new", bridge.cmd_new))
    app.add_handler(CommandHandler("resume", bridge.cmd_resume))
    app.add_handler(CommandHandler("interrupt", bridge.cmd_interrupt))
    app.add_handler(CommandHandler("compact", bridge.cmd_compact))
    app.add_handler(CommandHandler("allow", bridge.cmd_allow))
    app.add_handler(CommandHandler("deny", bridge.cmd_deny))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bridge.handle_prompt)
    )

    # Startup
    async def on_startup(app):
        await bridge.initialize()

    app.post_init = on_startup

    logger.info("Telegram bot starting (long polling)...")
    app.run_polling(drop_pending_updates=True)


class TelegramBridge:
    """Handles Telegram message routing and agent interaction."""

    def __init__(self, config: BridgeConfig):
        self.cfg = config
        self._store: Optional[ThreadStore] = None
        # Track active agent tasks per chat (for interrupt simulation)
        self._active_tasks: Dict[str, asyncio.Task] = {}

    async def initialize(self):
        self._store = await ThreadStore.open(self.cfg.thread_map_path)

    @property
    def store(self) -> ThreadStore:
        if self._store is None:
            raise RuntimeError("Bridge not initialized")
        return self._store

    # ── Security ─────────────────────────────────────────────────────────

    def is_allowed(self, chat_id: str) -> bool:
        if self.cfg.allow_unlisted:
            return True
        if chat_id in self.cfg.allowlist:
            return True
        if self.cfg.owner_id and chat_id == self.cfg.owner_id:
            return True
        logger.info("Refused chat %s — not in allowlist", chat_id)
        return False

    # ── Thread helpers ───────────────────────────────────────────────────

    def _new_thread_state(self) -> dict:
        return {
            "thread_id": f"tg_{int(time.time() * 1000)}",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "messages": [
                {"role": "system", "content": _build_telegram_system_prompt()}
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
        """Get or create message list for a chat."""
        state = await self._ensure_thread(chat_id)
        messages = state.get("messages", [])
        # Always ensure system prompt is first
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": _build_telegram_system_prompt()})
        return messages

    # ── Command handlers ─────────────────────────────────────────────────

    async def cmd_start(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return await update.message.reply_text(
                f"This chat ({chat_id}) is not in the allowlist. "
                "Contact the bridge owner to add it."
            )
        await update.message.reply_text(HELP_TEXT)

    async def cmd_help(self, update, context):
        if not self.is_allowed(str(update.effective_chat.id)):
            return
        await update.message.reply_text(HELP_TEXT)

    async def cmd_status(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        try:
            state = self.store.get_chat(chat_id)
            lines = [
                f"Runtime: {self.cfg.runtime_url}",
                f"Workspace: {self.cfg.workspace}",
                f"Model: {self.cfg.model}",
                f"Mode: {self.cfg.mode}",
                f"Active thread: {state.get('thread_id', 'none') if state else 'none'}",
                f"Messages in context: {len(state.get('messages', [])) if state else 0}",
            ]
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Status error: {e}")

    async def cmd_threads(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        try:
            all_chats = self.store.all_chats()
            if not all_chats:
                return await update.message.reply_text("No threads found.")
            lines = []
            for i, c in enumerate(all_chats[:10], 1):
                lines.append(f"{i}. {c.get('thread_id', '?')}  [{c.get('updated_at', '?')}]")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Threads error: {e}")

    async def cmd_new(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        state = await self._ensure_thread(chat_id, force_new=True)
        await update.message.reply_text(f"Created thread {state['thread_id']}")

    async def cmd_resume(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        args = (context.args or [""])[0] if context.args else ""
        if not args:
            return await update.message.reply_text("Usage: /resume <thread_id>")
        # In our model, each chat has one thread. Resume just confirms.
        state = self.store.get_chat(chat_id)
        if state:
            await update.message.reply_text(f"Resumed thread {state.get('thread_id', 'unknown')}")
        else:
            await update.message.reply_text("No thread found for this chat. Send a prompt or /new to start.")

    async def cmd_interrupt(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        # Cancel any active agent task for this chat
        task = self._active_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            await update.message.reply_text("Interrupted active turn.")
        else:
            await update.message.reply_text("No active turn to interrupt.")

    async def cmd_compact(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        state = self.store.get_chat(chat_id)
        if not state:
            return await update.message.reply_text("No active thread to compact.")
        try:
            messages = state.get("messages", [])
            if len(messages) <= 5:
                return await update.message.reply_text("Context is already short, no need to compact.")
            # Keep system prompt + last 4 user/assistant exchanges
            system_msgs = [m for m in messages if m.get("role") == "system"]
            non_system = [m for m in messages if m.get("role") != "system"]
            # Take last 8 non-system messages (4 exchanges)
            trimmed = system_msgs + non_system[-8:]
            state["messages"] = trimmed
            await self.store.set_chat(chat_id, state)
            await update.message.reply_text(
                f"Compacted thread context. {len(messages)} → {len(trimmed)} messages."
            )
        except Exception as e:
            await update.message.reply_text(f"Compact error: {e}")

    async def cmd_allow(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        await update.message.reply_text(
            "Approval system: tools are auto-approved in this bridge. "
            "Set DEEPSEEK_AUTO_APPROVE=false to enable manual approval."
        )

    async def cmd_deny(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return
        await update.message.reply_text(
            "Approval system: tools are auto-approved in this bridge."
        )

    # ── Prompt handler ───────────────────────────────────────────────────

    async def handle_prompt(self, update, context):
        chat_id = str(update.effective_chat.id)
        if not self.is_allowed(chat_id):
            return

        prompt = update.message.text.strip()
        if not prompt:
            return

        # Check if there's already an active task
        if chat_id in self._active_tasks and not self._active_tasks[chat_id].done():
            await update.message.reply_text(
                "A previous prompt is still being processed. "
                "Wait for it to finish or send /interrupt."
            )
            return

        status_msg = await update.message.reply_text("🤔 Processing...")

        task = asyncio.create_task(self._process_prompt(chat_id, prompt, status_msg, update, context))
        self._active_tasks[chat_id] = task

        try:
            await task
        except asyncio.CancelledError:
            await status_msg.edit_text("Turn interrupted.")
        except Exception as e:
            logger.exception("Error processing prompt for chat %s", chat_id)
            await status_msg.edit_text(f"Error: {e}")
        finally:
            self._active_tasks.pop(chat_id, None)

    async def _process_prompt(self, chat_id: str, prompt: str, status_msg, update, context):
        """Core processing: get messages, run agent, stream back response."""
        messages = await self._get_messages(chat_id)

        # Add user message
        messages.append({"role": "user", "content": prompt})

        # Run agent
        try:
            response, state = await run_agent_async(messages)
        except Exception as e:
            logger.exception("Agent error for chat %s", chat_id)
            # Remove the user message we just added (it wasn't processed)
            messages.pop() if messages and messages[-1].get("role") == "user" else None
            raise

        # Add assistant response to history
        if response:
            messages.append({"role": "assistant", "content": response})

        # Persist updated messages
        chat_state = self.store.get_chat(chat_id) or {}
        chat_state["messages"] = messages
        chat_state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self.store.set_chat(chat_id, chat_state)

        # Send response back, chunking if needed
        if response:
            chunks = split_message(response, self.cfg.max_reply_chars)
            # Edit the status message with the first chunk
            await status_msg.edit_text(chunks[0])
            # Send remaining chunks as new messages
            for chunk in chunks[1:]:
                await update.message.reply_text(chunk)
        else:
            await status_msg.edit_text("🤖 Done (no text response)")
