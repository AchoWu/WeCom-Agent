---
name: wecom-bot
description: This skill should be used when the user asks to "开始", "start wecom bot", "listen for wecom messages", "monitor wecom", "启动企业微信机器人", "开始监听企业微信", "start listening", or needs to set up bidirectional communication with users via WeCom (Enterprise WeChat) intelligent bot. TRIGGER when the task involves receiving messages from or sending replies to WeCom. DO NOT TRIGGER for general chat unrelated to the WeCom bot system.
version: 1.0.0
---

# WeCom Bot - Enterprise WeChat Bidirectional Communication

## Step 0. Initialize (First Run Only)

**0a. Configure credentials** — Check if `.env` exists. If not, tell user:

  "检测到 `.env` 文件不存在，需要配置机器人凭据（在企业微信管理后台 → 智能机器人 → API模式 中获取）。
  您可以：
  1. 直接把 Bot ID 和 Secret 发给我，我来帮您创建
  2. 或自行复制 `.env.example` 为 `.env` 并填入，完成后告诉我"

  If user provides Bot ID and Secret, create `.env` with those values. Then continue.

**0b. Configure permissions** — If `.claude/settings.local.json` does not exist, ask user for workspace directory, then create it:

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

- Ask: "请问您希望 Agent 在哪个目录下操作文件？（请提供绝对路径）"
- Use `pwd` to get project path. **All paths must be absolute and end with `/**`** — relative paths cause repeated permission prompts, missing `/**` prevents recursive access.
- After writing, tell user the following restart instructions, then **stop** — permissions require restart:

  "权限配置已写入，需要重启 Claude Code 才能生效：
  1. 输入 `/exit` 或按 `Ctrl+C` 退出当前会话
  2. 重新运行 `claude` 命令进入项目
  3. 说「开始监听企业微信」即可"

## Step 1. Start Bot & Listen Loop

```bash
# Start bot daemon
python .claude/skills/wecom-bot/scripts/wecom_bot.py &disown 2>/dev/null &

# Get current message count (store as <COUNT>, 0 if file doesn't exist)
python -c "import json,os; print(len(json.load(open('messages.json','r',encoding='utf-8'))) if os.path.exists('messages.json') else 0)"
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

### Rule 1: Check Messages at Key Points

Check `messages.json` count for new messages at these moments:
- **Before starting a new task** (after receiving the request)
- **Between sub-tasks** (not between split parts of the same message)
- **Before sending the final result**

Do NOT check before every single ws_send — when a long reply is split into multiple messages, just send them consecutively without checking in between.

```bash
python -c "import json,os; print(len(json.load(open('messages.json','r',encoding='utf-8'))) if os.path.exists('messages.json') else 0)"
```
If count increased, read new messages first:
- User changed intent / new request → reply "收到", switch to new task
- User sent "取消" / "停止" / "cancel" → acknowledge, stop current task
- Follow-up info → incorporate and continue

### Rule 2: Task Execution Pattern

1. **Acknowledge immediately** — reply "收到，正在处理..." BEFORE any work
2. **Break into sub-tasks, report progress** — send updates at each milestone. For long-running tasks, send a progress update every 3-5 minutes so the user knows work is still ongoing (e.g., "仍在处理中，当前进度：已完成XX，正在进行YY...")
3. **Check messages between sub-tasks** — same check as Rule 1
4. **Report final result** or **notify on error** immediately

### Rule 3: Zero Listening Gap

Whenever a listener agent completes (new message OR timeout), IMMEDIATELY:
1. Read `messages.json` for new messages
2. Get current count
3. Launch a new background listener

No gap allowed — during tasks, between tasks, at all times.

### Rule 4: Never Disconnect Without Consent

Even after extended silence, never stop listening on your own. After 12+ consecutive timeouts (~60 minutes), ask via ws_send: "检测到长时间无新消息（约60分钟），请问需要断开连接吗？" Only disconnect if user explicitly confirms.

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
- Bot auto-reconnects with backoff (3s→30s), health check forces reconnect after 30min silence
- Outbox messages survive disconnection, auto-sent on reconnect
- Use `websocket-client` (sync), not `websockets` (async)
