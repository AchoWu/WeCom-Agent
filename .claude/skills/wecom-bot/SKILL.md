---
name: wecom-bot
description: This skill should be used when the user asks to "开始", "start wecom bot", "listen for wecom messages", "monitor wecom", "启动企业微信机器人", "开始监听企业微信", "start listening", or needs to set up bidirectional communication with users via WeCom (Enterprise WeChat) intelligent bot. TRIGGER when the task involves receiving messages from or sending replies to WeCom. DO NOT TRIGGER for general chat unrelated to the WeCom bot system.
version: 1.0.0
---

# WeCom Bot - Enterprise WeChat Bidirectional Communication

## Step 0. Initialize Permissions (First Run Only)

If `.claude/settings.local.json` does not exist, ask the user for their workspace directory path, then create it:

```jsonc
{
  "permissions": {
    "allow": [
      "Read(<absolute_project_path>/**)", "Edit(<absolute_project_path>/**)", "Write(<absolute_project_path>/**)",
      "Read(<user_specified_dir>/**)", "Edit(<user_specified_dir>/**)", "Write(<user_specified_dir>/**)",
      "Bash(*)", "Glob(*)", "Grep(*)", "WebSearch", "WebFetch(*)", "Agent(*)"
    ]
  }
}
```

- Ask user: "请问您希望 Agent 在哪个目录下操作文件？（请提供绝对路径）"
- Use `pwd` to get project path. **All paths must be absolute and end with `/**`** — relative paths cause repeated permission prompts, missing `/**` prevents recursive access.
- After writing, tell user: "权限配置已写入，请重启 Claude Code 后再说「开始监听企业微信」即可生效。" Then **stop** — permissions require restart.

## Step 1. Start Bot & Listen Loop

```bash
# Start bot daemon
python .claude/skills/wecom-bot/scripts/wecom_bot.py &disown 2>/dev/null &

# Get current message count (store as <COUNT>)
python -c "import json; f=open('messages.json','r',encoding='utf-8'); print(len(json.load(f)))"
```

Launch background listener Agent (`run_in_background=true`):
```
prompt: "Run this command in foreground and wait for it to complete (timeout up to 310 seconds).
Do NOT use any other tools, just run this one Bash command and return the output:
python .claude/skills/wecom-bot/scripts/watch_messages.py <COUNT> 300
Working directory: <absolute_project_path>"
```

## Step 2. Process & Reply

When listener completes: Read `messages.json` with **Read tool** (NOT terminal — Windows garbles Chinese), extract user's request.

**Reply via ws_send:**
```bash
python .claude/skills/wecom-bot/scripts/wecom_tool.py ws_send "message"
```

## Core Rules

### Rule 1: Check Messages Before Every Send

Before sending ANY ws_send (ack, progress, result — no exceptions), check for new messages first:
```bash
python -c "import json; f=open('messages.json','r',encoding='utf-8'); print(len(json.load(f)))"
```
If count increased, read new messages first:
- User changed intent / new request → reply "收到", switch to new task
- User sent "取消" / "停止" / "cancel" → acknowledge, stop current task
- Follow-up info → incorporate and continue

### Rule 2: Task Execution Pattern

1. **Acknowledge immediately** — reply "收到，正在处理..." BEFORE any work
2. **Break into sub-tasks, report progress** — send updates at each milestone, never let user wait >1 min
3. **Check messages between sub-tasks** — same check as Rule 1
4. **Report final result** or **notify on error** immediately

### Rule 3: All User Interaction Via WeCom

The user is NOT watching Claude Code terminal. All confirmations, authorizations, and questions MUST go through ws_send + wait for reply in `messages.json`. NEVER use AskUserQuestion.

### Rule 4: Zero Listening Gap

Whenever a listener agent completes (new message OR timeout), IMMEDIATELY:
1. Read `messages.json` for new messages
2. Get current count
3. Launch a new background listener

No gap allowed — during tasks, between tasks, at all times.

### Rule 5: Never Disconnect Without Consent

Even after extended silence, never stop listening on your own. After 3+ consecutive timeouts, ask via ws_send: "检测到长时间无新消息，请问需要断开连接吗？" Only disconnect if user explicitly confirms.

Also suggest `/compact` on extended idle: "建议执行一次 /compact 压缩会话历史以降低 token 消耗，是否需要？"

## Reference

| Priority | Reply Method | Command |
|----------|-------------|---------|
| 1 | ws_send (recommended) | `wecom_tool.py ws_send "msg"` |
| 2 | response_url | `wecom_tool.py reply "msg"` |
| 3 | Webhook (group only) | `wecom_tool.py send "msg"` |

**Technical notes:**
- Reply msgtype must be `markdown` (text/stream → errcode 40008)
- Keep messages under ~500 chars, split longer content with `sleep 2` between sends
- Bot auto-reconnects with backoff (3s→30s), health check forces reconnect after 5min silence
- Outbox messages survive disconnection, auto-sent on reconnect
- Use `websocket-client` (sync), not `websockets` (async)
