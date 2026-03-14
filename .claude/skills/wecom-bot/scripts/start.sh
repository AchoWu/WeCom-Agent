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
python .claude/skills/wecom-bot/scripts/wecom_bot.py &disown 2>/dev/null &
sleep 3

# Check if bot is running
if pgrep -f "wecom_bot.py" > /dev/null 2>&1; then
    echo "Bot started successfully"
else
    echo "Bot may have failed to start, check manually"
fi

# Show current message count
COUNT=$(python -c "import json; f=open('messages.json','r',encoding='utf-8'); print(len(json.load(f)))" 2>/dev/null || echo "0")
echo "Current message count: $COUNT"
