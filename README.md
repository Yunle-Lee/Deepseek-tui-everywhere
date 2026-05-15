# DeepSeek-TUI Bridge Integrations

Bot bridges for controlling a local `deepseek serve --http` runtime from your phone.

## Available Bridges

| Bridge | Directory | Docs |
|--------|-----------|------|
| Feishu / Lark | [`integrations/feishu-bridge/`](integrations/feishu-bridge/) | Node.js, WS long-connection |
| Telegram | [`integrations/telegram-bridge/`](integrations/telegram-bridge/) | Node.js, long polling |

## Quick Start

```bash
# 1. Start the DeepSeek-TUI runtime
deepseek serve --http --port 7878 --auth-token your-token

# 2. Pick a bridge
cd integrations/telegram-bridge  # or feishu-bridge

# 3. Install and run
cp .env.example .env
# edit .env with your credentials
npm install
node src/index.mjs
```

Both bridges share the same command interface:
- `/status` — runtime status
- `/new` — new thread
- `/interrupt` — interrupt active turn
- `/allow` / `/deny` — approve/reject tool calls
