# DeepSeek Telegram Bridge

Telegram bot bridge for a local `deepseek serve --http` runtime.

## Setup

```bash
cd /opt/deepseek/bridge
npm install --omit=dev
cp .env.example /etc/deepseek/telegram-bridge.env
sudoedit /etc/deepseek/telegram-bridge.env
node src/index.mjs
```

### Creating a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token — set it as `TELEGRAM_BOT_TOKEN` in your env
4. Optionally set a profile photo and commands via BotFather

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show help text |
| `/status` | Show runtime status and active thread |
| `/threads` | List your threads |
| `/new` | Start a new thread |
| `/resume <id>` | Resume an existing thread |
| `/interrupt` | Interrupt the active turn |
| `/compact` | Compact the active thread's context |
| `/allow <id>` | Approve a pending tool call |
| `/deny <id>` | Reject a pending tool call |

Anything else is sent as a prompt.

## Security

- `TELEGRAM_CHAT_ALLOWLIST` — comma-separated chat IDs allowed to use the bridge
- `DEEPSEEK_ALLOW_UNLISTED=true` — allow any chat (use only for first pairing)
- `TELEGRAM_OWNER_ID` — always allowed, useful for admin access
- The runtime API token must match between bridge and runtime

## Architecture

```
Telegram app
    ↓ Telegram Bot API (long polling)
telegram-bridge (Node.js + telegraf)
    ↓ REST API
deepseek serve --http (127.0.0.1:7878)
```
