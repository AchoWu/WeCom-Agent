# Message Format Reference

## Incoming Message Structure (messages.json)

Each entry in the JSON array:

```json
{
  "from_user": "USER_ID",
  "chat_type": "single",           // "single" or "group"
  "msg_type": "text",              // "text", "image", "file", etc.
  "content": "消息内容",
  "received_at": "2026-03-14T10:20:51.061819",
  "response_url": "https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=...",
  "msg_id": "MSG_ID_EXAMPLE",
  "req_id": "REQ_ID_EXAMPLE",
  "raw": { /* full raw message from WeCom WebSocket */ }
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `from_user` | string | Sender's WeCom userid |
| `chat_type` | string | `"single"` (DM) or `"group"` |
| `msg_type` | string | `"text"`, `"image"`, `"file"`, etc. |
| `content` | string | Extracted text content |
| `received_at` | string | ISO 8601 timestamp |
| `response_url` | string | One-time HTTP reply URL (expires) |
| `msg_id` | string | Unique message identifier |
| `req_id` | string | Request ID for WebSocket reply routing |
| `raw` | object | Full original message body |
| `raw.chatid` | string | Group chat ID (only present for group messages) |

## Reply Methods Detail

### 1. ws_send (Primary)

Writes a message to `outbox.json`. The `wecom_bot.py` process picks it up within 1 second and sends via WebSocket.

- **Single chat**: Uses `aibot_respond_msg` command with the original message's `req_id`
- **Group chat**: Uses `aibot_send_msg` command with `chatid`
- **Fallback**: If no `req_id` is available, automatically falls back to `response_url`

Message format sent via WebSocket:
```json
{
  "cmd": "aibot_respond_msg",
  "headers": {"req_id": "<original_req_id>"},
  "body": {
    "msgtype": "markdown",
    "markdown": {"content": "Reply text here"}
  }
}
```

### 2. response_url (Backup)

Direct HTTP POST to the `response_url` from the message. Format must be markdown:
```json
{
  "msgtype": "markdown",
  "markdown": {"content": "Reply text here"}
}
```
- Can only be used **once** per message
- URL **expires** after a short period
- If expired (errcode 60140), the tool tries older messages' URLs

### 3. Webhook (Fallback)

Posts to the group webhook. Does not expire. Suitable for long replies.

Webhook URL: configured via `WECOM_WEBHOOK_URL` environment variable

Supports: text, markdown, image (base64), file (upload then send)

## wecom_tool.py Commands

| Command | Usage | Description |
|---------|-------|-------------|
| `send` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py send "msg"` | Send text to group via Webhook |
| `send_md` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py send_md "md"` | Send markdown to group via Webhook |
| `send_image` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py send_image path` | Send image to group |
| `send_file` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py send_file path` | Upload and send file to group |
| `reply` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py reply "msg"` | Reply via response_url (markdown) |
| `ws_send` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py ws_send "msg"` | Reply via WebSocket outbox |
| `receive` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py receive [N]` | Print last N messages |
| `ask` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py ask "q" [timeout]` | Send question and wait for reply |
| `test` | `python .claude/skills/wecom-bot/scripts/wecom_tool.py test` | Send test message to group |
