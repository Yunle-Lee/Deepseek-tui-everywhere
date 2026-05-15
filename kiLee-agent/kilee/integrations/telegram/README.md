# DeepSeek Telegram Bridge (Python-native)

Telegram bot bridge that connects Telegram chats directly to kiLee Agent.
Native Python implementation — **no Node.js required**.

## Architecture

```
Telegram app
    ↓ Telegram Bot API (long polling)
telegram-bridge (python-telegram-bot v20+)
    ↓ direct function call
kilee.agent.run_agent()
    ↓
DeepSeek API
```

Compatible with the **upstream Node.js bridge** command set.
This Python-native version skips the HTTP middle layer and calls the kiLee Agent core directly.

## Quick Start

### 1. Install with Telegram extras

```bash
cd kilee-agent
pip install -e ".[telegram]"
```

Or manually:

```bash
pip install python-telegram-bot python-dotenv
```

### 2. Create a Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 3. Configure

Copy the env example and fill in your values:

```bash
cp kilee/integrations/telegram/.env.example .env
```

**Minimal `.env`:**

```env
TELEGRAM_BOT_TOKEN=1234567890:AA...your-token
DEEPSEEK_RUNTIME_TOKEN=any-random-string
DEEPSEEK_ALLOW_UNLISTED=true
TELEGRAM_OWNER_ID=your-telegram-chat-id
```

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `DEEPSEEK_RUNTIME_TOKEN` | ✅ | Any random string (used for consistency with upstream bridge) |
| `TELEGRAM_CHAT_ALLOWLIST` | — | Comma-separated chat IDs allowed to use the bridge |
| `DEEPSEEK_ALLOW_UNLISTED` | — | Set `true` for initial pairing; allows any chat |
| `TELEGRAM_OWNER_ID` | — | Your chat ID; always allowed |
| `DEEPSEEK_MODEL` | — | Model name (default: auto) |
| `DEEPSEEK_WORKSPACE` | — | Working directory (default: cwd) |

### 4. Start

```bash
# CLI
kilee telegram

# Or as module
python -m kilee.integrations.telegram
```

### 5. Pair Your Chat

On first run with `DEEPSEEK_ALLOW_UNLISTED=true`:
1. Send any message to your bot on Telegram
2. Note your chat ID from the bridge logs
3. Add it to `TELEGRAM_CHAT_ALLOWLIST`
4. Set `DEEPSEEK_ALLOW_UNLISTED=false` and restart

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

Any other text is sent as a prompt to the AI.

## Differences from Upstream Node.js Bridge

| Feature | Node.js Bridge | Python Bridge |
|---------|---------------|---------------|
| Runtime | Requires `deepseek serve --http` | Direct calls to kiLee core |
| Dependencies | Node.js 18+, npm | Python 3.10+, pip |
| Approval flow | HTTP approval endpoints | Auto-approve (configurable) |
| Streaming | Event polling over REST | Blocking agent call |
| Thread storage | JSON file (compatible) | JSON file (identical format) |

## Security

- Use `TELEGRAM_CHAT_ALLOWLIST` to restrict which chats can use the bridge
- Set `DEEPSEEK_ALLOW_UNLISTED=true` **only** during initial pairing
- `TELEGRAM_OWNER_ID` is always allowed — useful for admin access
- `DEEPSEEK_TRUST_MODE=false` requires tool confirmations (use in production)
