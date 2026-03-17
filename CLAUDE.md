# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WeCom (Enterprise WeChat) intelligent bot integration for Claude Code. Enables bidirectional real-time messaging between users and Claude Agent via WebSocket long connections.

## Commands

### Start the bot
```bash
bash .claude/skills/wecom-bot/scripts/start.sh
# Or manually:
python .claude/skills/wecom-bot/scripts/wecom_bot.py &disown 2>/dev/null &
```

### Send/receive messages
```bash
# Send via WebSocket (preferred)
python .claude/skills/wecom-bot/scripts/wecom_tool.py ws_send "message"

# Read last N incoming messages
python .claude/skills/wecom-bot/scripts/wecom_tool.py receive 5

# Wait for new messages (polling)
python .claude/skills/wecom-bot/scripts/watch_messages.py <current_count> <timeout_seconds>

# Send test message to group webhook
python .claude/skills/wecom-bot/scripts/wecom_tool.py test
```

### Dependencies
Python 3.10 with `requests` and `websocket-client` (sync, not `websockets` async).

### Configuration
Credentials are loaded from environment variables. Copy `.env.example` to `.env` and fill in:
- `WECOM_BOT_ID` — Bot ID from WeCom admin console
- `WECOM_BOT_SECRET` — Bot secret
- `WECOM_WEBHOOK_URL` — Group webhook URL (optional)

## Architecture

**File-based IPC with WebSocket daemon:**

```
WeCom API ←→ WebSocket ←→ wecom_bot.py (background daemon)
                                ↓ writes incoming     ↑ reads outgoing
                          messages.json            outbox.json
                                ↑ reads                ↓ writes
                            Claude Agent (wecom_tool.py / watch_messages.py)
```

- **wecom_bot.py** — Background daemon maintaining WebSocket connection. Receives messages into `messages.json`, monitors `outbox.json` every 1s to send queued messages. Auto-reconnects with exponential backoff (3s→30s). Health checker forces reconnect after 30min silence.
- **wecom_tool.py** — CLI utility for sending (webhook, reply URL, or WebSocket queue) and receiving messages.
- **watch_messages.py** — Polls `messages.json` for new messages, exits on arrival or timeout.

## Important Technical Constraints

- Reply format **must be `markdown`** — text/stream returns error 40008
- Long messages (>~500 chars) silently fail — keep messages short
- Windows terminal garbles Chinese — always use the Read tool on `messages.json`, not terminal output
- Response URLs expire quickly — prefer `ws_send` over `reply` for reliable delivery
- Only the last 200 messages are retained in `messages.json`
