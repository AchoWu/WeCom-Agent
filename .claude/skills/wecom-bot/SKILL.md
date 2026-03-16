---
name: wecom-bot
description: This skill should be used when the user asks to "开始", "start wecom bot", "listen for wecom messages", "monitor wecom", "启动企业微信机器人", "开始监听企业微信", "start listening", or needs to set up bidirectional communication with users via WeCom (Enterprise WeChat) intelligent bot. TRIGGER when the task involves receiving messages from or sending replies to WeCom. DO NOT TRIGGER for general chat unrelated to the WeCom bot system.
version: 1.0.0
---

# WeCom Bot - Enterprise WeChat Bidirectional Communication

Enable bidirectional messaging with users through an Enterprise WeChat (WeCom) intelligent bot via WebSocket.

## Quick Start

Execute these steps in order to start the bot and begin the listen-reply loop.

### 0. Initialize Permissions (First Run Only)

Before starting the bot for the first time, check if `.claude/settings.local.json` exists. If not, ask the user which directory they want the Agent to have file access to (e.g., `./workspace`), then create the config.

The permissions MUST include:
1. **Full access to the project directory itself** (for messages.json, outbox.json, scripts, etc.)
2. **Full access to the user-specified workspace directory** (for task file operations)
3. **All tool permissions** (Bash, Glob, Grep, WebSearch, WebFetch, Agent)

Use the **absolute path** of the project directory (obtained via `pwd`) to avoid relative path issues.

```jsonc
// .claude/settings.local.json
{
  "permissions": {
    "allow": [
      "Read(<absolute_project_path>/**)",
      "Edit(<absolute_project_path>/**)",
      "Write(<absolute_project_path>/**)",
      "Read(<user_specified_dir>/**)",
      "Edit(<user_specified_dir>/**)",
      "Write(<user_specified_dir>/**)",
      "Bash(*)",
      "Glob(*)",
      "Grep(*)",
      "WebSearch",
      "WebFetch(*)",
      "Agent(*)"
    ]
  }
}
```

**You MUST ask the user** to specify the workspace directory path. Do not assume a default. Example prompt: "请问您希望 Agent 在哪个目录下操作文件？例如 `C:/Users/xxx/workspace` 或其他路径。这将用于初始化权限沙箱，Agent 只能读写该目录和本项目目录内的文件。"

**IMPORTANT:** Use absolute paths (e.g., `C:/Users/xxx/Desktop/Wecom-Agent/**`) instead of relative paths. Relative paths like `./workspace/**` may not resolve correctly and cause repeated permission prompts.

### 1. Start Bot Process (Background)

```bash
python .claude/skills/wecom-bot/scripts/wecom_bot.py &disown 2>/dev/null &
```

This starts a WebSocket long connection to `wss://openws.work.weixin.qq.com`. Incoming messages are saved to `messages.json`. Outgoing messages are read from `outbox.json` and sent via WebSocket.

### 2. Get Current Message Count

```bash
python -c "import json; f=open('messages.json','r',encoding='utf-8'); print(len(json.load(f)))"
```

Store this number as `<COUNT>` for the listener.

### 3. Launch Background Listener Agent

Spawn a background Agent with `run_in_background=true`:

```
prompt: "Run this command in foreground and wait for it to complete (timeout up to 610 seconds).
Do NOT use any other tools, just run this one Bash command and return the output:
python .claude/skills/wecom-bot/scripts/watch_messages.py <COUNT> 600
Working directory: C:\Users\29441\Desktop\Claude-Agent"
```

The watcher script checks `messages.json` every 1 second. It exits immediately when new messages appear, or prints "TIMEOUT" after 600 seconds. The subagent uses only 1 tool call for the entire wait — zero API consumption while idle.

### 4. Process Incoming Messages

When the listener agent completes (automatic notification):

1. Read the end of `messages.json` with the **Read tool** using a large offset (do NOT rely on terminal output — Windows terminal garbles Chinese)
2. Find the latest message(s) and extract the `content` field for the user's request

### 5. Reply to User

**Primary method — ws_send** (writes to outbox.json, bot sends via WebSocket):

```bash
python .claude/skills/wecom-bot/scripts/wecom_tool.py ws_send "Reply content here"
```

### 6. Task Execution Flow

**CRITICAL: The user is interacting via WeCom, NOT via the Claude Code terminal.** Whenever you need user confirmation, authorization, or input (e.g., "是否继续？", "确认删除？", choosing between options), you MUST send the question via ws_send to WeCom and wait for the user's reply in `messages.json`. NEVER use AskUserQuestion or expect the user to respond in the Claude Code terminal — they are not watching it.

**CRITICAL: Always follow this pattern for every task.**

**Step A — Acknowledge immediately.** As soon as you receive a task, reply "收到，正在处理..." via ws_send BEFORE doing any work. Never let the user send a message and get silence in return.

**Step B — Break into sub-tasks and report progress.** Decompose the task into logical steps. After completing each sub-task, send a brief progress update to the user (e.g., "第1步已完成，正在处理第2步..."). For multi-step tasks, never let the user wait more than 1 minute without feedback.

**Step C — Check for new messages between sub-tasks.** After each sub-task completes, check `messages.json` count to see if the user sent new messages while you were working:
```bash
python -c "import json; f=open('messages.json','r',encoding='utf-8'); print(len(json.load(f)))"
```
If new messages arrived:
- If the user sent "取消" / "停止" / "cancel" → stop the current task and acknowledge
- If the user sent a new question or changed requirements → adjust accordingly
- Otherwise → continue with the next sub-task

**Step D — Report final result.** When all sub-tasks are done, send the complete result to the user.

**Step E — On error.** Immediately notify the user with error details and suggested next steps. Do not silently fail.

### 7. Loop with Concurrent Listening

**CRITICAL RULE: ZERO LISTENING GAP.** Whenever a background listener agent completes (whether it detected a new message or timed out), you MUST immediately:
1. Read `messages.json` to check for new messages
2. Get the current message count
3. Launch a new background listener agent

There must NEVER be a period where no listener agent is running. This applies during task execution, between tasks, and at all other times. Failing to restart the listener immediately causes missed messages.

**CRITICAL RULE: NEVER DISCONNECT WITHOUT USER CONSENT.** Even if the user has not sent any messages for a long time, you must NOT stop listening or disconnect on your own. If you notice extended silence (e.g., multiple consecutive timeouts), send a friendly message via ws_send asking the user if they want to disconnect, for example: "您好，检测到已经较长时间没有新消息了，请问需要断开连接吗？" Only if the user explicitly confirms (e.g., "好的", "断开", "是", "停止") should you stop listening and end the session. If the user does not respond or says no, continue the listen loop as normal.

**COMPACT SUGGESTION ON EXTENDED IDLE.** When multiple consecutive timeouts occur without any user message (e.g., 3+ timeouts in a row), proactively suggest to the user via ws_send: "检测到长时间无新消息，建议执行一次 /compact 压缩会话历史以降低 token 消耗，是否需要？" If the user confirms, run `/compact` to compress the repetitive timeout loops, then continue listening as normal. This helps keep the session efficient during long idle periods.

**During task execution:**

1. **Launch a background listener agent** (same as Step 3) alongside the task work
2. **When the listener completes** (automatic notification), immediately read messages, process them, get new count, and launch a new listener — even if you are in the middle of task work
3. **Between sub-tasks**, also check `messages.json` count as described in Step 6C as a safety net
4. **If new messages are detected**, read `messages.json` to check content:
   - If the user sent "取消" / "停止" / "cancel" → stop the current task and acknowledge
   - If the user sent a new question → finish or pause current task, then handle the new request
   - Otherwise → continue the current task
5. **After task completion**, get the new message count, check for any missed messages, then launch a new listener agent. Repeat.

## Reply Channels

| Priority | Method | Command | Notes |
|----------|--------|---------|-------|
| 1 | WebSocket ws_send | `python .claude/skills/wecom-bot/scripts/wecom_tool.py ws_send "msg"` | Recommended. Via outbox queue |
| 2 | response_url | `python .claude/skills/wecom-bot/scripts/wecom_tool.py reply "msg"` | One-time use, expires quickly |
| 3 | Webhook (group) | `python .claude/skills/wecom-bot/scripts/wecom_tool.py send "msg"` | Group only, no expiry |

## Key Files

| File | Role |
|------|------|
| `.claude/skills/wecom-bot/scripts/wecom_bot.py` | WebSocket bot process (websocket-client lib) |
| `.claude/skills/wecom-bot/scripts/wecom_tool.py` | CLI tool: send / send_md / reply / ws_send / receive / ask |
| `.claude/skills/wecom-bot/scripts/watch_messages.py` | New-message watcher (for subagent polling) |
| `messages.json` | Received message store (includes req_id for ws reply) |
| `outbox.json` | Outbound message queue (bot checks every 1s) |

## Technical Notes

- Reply msgtype must be `markdown` (text/stream returns errcode 40008)
- Use `websocket-client` (sync), not `websockets` (async) — the latter has protocol compatibility issues
- Bot auto-reconnects on disconnect with incremental delay (3s → 30s)
- Bot includes a health checker thread: checks every 30s, forces reconnect if no message in 10 minutes
- Outbox messages are retained during disconnection and auto-sent after reconnect (never lost)
- Chinese content in terminal is garbled on Windows — always use Read tool on `messages.json`
- Use the standalone `.claude/skills/wecom-bot/scripts/watch_messages.py` script, not inline Python in subagent commands
- **Long messages will silently fail to send.** Keep each message under ~500 characters. For longer content, split into multiple messages with `sleep 2` between sends to avoid ordering issues

## Additional Resources

- **`references/message-format.md`** — Detailed message JSON structure, field descriptions, and reply method details
- **`scripts/start.sh`** — Quick-start script to launch bot and verify connection
