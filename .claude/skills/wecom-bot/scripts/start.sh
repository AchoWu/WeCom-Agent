#!/bin/bash
# Quick start script for WeCom bot
# Usage: bash .claude/skills/wecom-bot/scripts/start.sh

cd "$(dirname "$0")/../../../.." || exit 1

# Load environment variables from .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

echo "Starting WeCom bot..."
python .claude/skills/wecom-bot/scripts/wecom_bot.py > /dev/null 2>&1 & disown

sleep 3

# Check if bot is running (cross-platform: ps fallback for systems without pgrep)
BOT_RUNNING=false
if command -v pgrep > /dev/null 2>&1; then
    pgrep -f "wecom_bot.py" > /dev/null 2>&1 && BOT_RUNNING=true
else
    ps aux 2>/dev/null | grep -v grep | grep "wecom_bot.py" > /dev/null 2>&1 && BOT_RUNNING=true
fi

if $BOT_RUNNING; then
    echo "Bot started successfully"
else
    echo "Bot may have failed to start, check manually"
fi

# Show current message count (handle missing file)
COUNT=$(python -c "import json,os; print(len(json.load(open('messages.json','r',encoding='utf-8'))) if os.path.exists('messages.json') else 0)" 2>/dev/null || echo "0")
echo "Current message count: $COUNT"
