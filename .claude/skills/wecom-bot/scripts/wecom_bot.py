# -*- coding: utf-8 -*-
"""
企业微信智能机器人 WebSocket 长连接服务

功能：
1. 接收消息 → 存入 messages.json
2. 监听 outbox.json → 通过 WebSocket 发送消息（支持回复和主动发送）

启动方式：
    python wecom_bot.py
"""

import json
import os
import sys
import time
import uuid
import subprocess
import threading
from datetime import datetime

try:
    import websocket
except ImportError:
    print("pip install websocket-client")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Data files live in project root (4 levels up: scripts/ → wecom-bot/ → skills/ → .claude/ → project root)
BASE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "..", ".."))


def _load_env():
    """Load .env file from project root if it exists."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                os.environ.setdefault(key, value)


_load_env()

MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")
OUTBOX_FILE = os.path.join(BASE_DIR, "outbox.json")

BOT_ID = os.environ.get("WECOM_BOT_ID", "")
SECRET = os.environ.get("WECOM_BOT_SECRET", "")
WS_URL = "wss://openws.work.weixin.qq.com"

if not BOT_ID or not SECRET:
    print("Error: WECOM_BOT_ID and WECOM_BOT_SECRET environment variables are required.")
    print("Copy .env.example to .env and fill in your credentials.")
    sys.exit(1)

# 全局 ws 引用
_ws = None
_last_msg_time = time.time()
_subscribed = False  # subscribe 确认后才允许发消息


def _kill_existing_bot():
    """Kill any existing wecom_bot.py process (except self) to prevent duplicates."""
    my_pid = os.getpid()
    try:
        if sys.platform == "win32":
            # Windows: use tasklist + taskkill
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            # Also check via wmic for command line matching
            result = subprocess.run(
                ['wmic', 'process', 'where', "commandline like '%wecom_bot.py%'", 'get', 'processid'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid != my_pid:
                        print(f"Killing old bot process (PID {pid})...", flush=True)
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)], timeout=5)
        else:
            # Unix/Mac: use pgrep
            result = subprocess.run(
                ["pgrep", "-f", "wecom_bot.py"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid != my_pid:
                        print(f"Killing old bot process (PID {pid})...", flush=True)
                        os.kill(pid, 15)  # SIGTERM
    except Exception as e:
        print(f"Process check warning: {e}", flush=True)


def health_checker():
    """定期检查 WS 连接是否存活，超过 10 分钟无任何消息则强制断开重连"""
    global _ws
    while True:
        time.sleep(30)
        if _ws is not None and time.time() - _last_msg_time > 300:
            print("HEALTH: no message in 5min, forcing reconnect...", flush=True)
            try:
                _ws.close()
            except Exception:
                pass


def save_message(msg_data):
    """保存收到的消息到 messages.json"""
    messages = []
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            try:
                messages = json.load(f)
            except (json.JSONDecodeError, ValueError):
                messages = []
    messages.append(msg_data)
    messages = messages[-200:]
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def outbox_watcher():
    """监听 outbox.json，有待发消息就通过 WebSocket 发出"""
    global _ws
    while True:
        time.sleep(1)
        if not os.path.exists(OUTBOX_FILE):
            continue
        try:
            with open(OUTBOX_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    continue
                outbox = json.loads(content)

            if not outbox or not isinstance(outbox, list):
                # 无效内容，清空
                with open(OUTBOX_FILE, "w", encoding="utf-8") as f:
                    f.write("")
                continue

            # 检查 ws 是否就绪（已连接且已 subscribe）
            if _ws is None or not _subscribed:
                # 不清空 outbox，等连接就绪后再发
                continue

            # ws 就绪，清空文件然后发送
            with open(OUTBOX_FILE, "w", encoding="utf-8") as f:
                f.write("")

            for item in outbox:
                if _ws is None or not _subscribed:
                    # 发送中途断连，把剩余消息写回 outbox
                    remaining = outbox[outbox.index(item):]
                    _write_back_to_outbox(remaining)
                    print("  outbox: ws disconnected mid-send, saved remaining", flush=True)
                    break
                try:
                    msg = json.dumps(item, ensure_ascii=False)
                    _ws.send(msg)
                    cmd = item.get("cmd", "?")
                    print(f"  outbox sent: {cmd}", flush=True)
                except Exception as e:
                    print(f"  outbox send error: {e}", flush=True)
                    # 发送失败，把当前和剩余消息写回
                    remaining = outbox[outbox.index(item):]
                    _write_back_to_outbox(remaining)
                    break
        except (json.JSONDecodeError, ValueError):
            # 清空损坏的文件
            with open(OUTBOX_FILE, "w", encoding="utf-8") as f:
                f.write("")
        except Exception as e:
            print(f"  outbox error: {e}")


def _write_back_to_outbox(items):
    """将未发送的消息写回 outbox.json（合并已有内容）"""
    existing = []
    try:
        if os.path.exists(OUTBOX_FILE):
            with open(OUTBOX_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    existing = json.loads(content)
                    if not isinstance(existing, list):
                        existing = []
    except Exception:
        existing = []
    merged = items + existing
    with open(OUTBOX_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)


def on_message(ws, message):
    """收到消息"""
    global _last_msg_time
    _last_msg_time = time.time()
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        print(f"non-JSON: {message[:100]}")
        return

    cmd = data.get("cmd", "")
    body = data.get("body", {})

    if cmd == "aibot_msg_callback":
        msg_type = body.get("msgtype", "")
        from_user = body.get("from", {}).get("userid", "unknown")
        chat_type = body.get("chattype", "")
        response_url = body.get("response_url", "")
        msg_id = body.get("msgid", "")
        req_id = data.get("headers", {}).get("req_id", "")
        received_at = datetime.now().isoformat()

        content = ""
        if msg_type == "text":
            content = body.get("text", {}).get("content", "")
        elif msg_type == "image":
            content = "[image]"
        elif msg_type == "file":
            content = "[file]"
        else:
            content = f"[{msg_type}]"

        print(f"[{received_at}] {from_user} ({chat_type}): {content}", flush=True)

        save_message({
            "from_user": from_user,
            "chat_type": chat_type,
            "msg_type": msg_type,
            "content": content,
            "received_at": received_at,
            "response_url": response_url,
            "msg_id": msg_id,
            "req_id": req_id,
            "raw": body,
        })

    elif cmd == "aibot_subscribe" or data.get("errcode") is not None:
        errcode = data.get("errcode", body.get("errcode", -1))
        errmsg = data.get("errmsg", body.get("errmsg", ""))
        if errcode == 0:
            global _subscribed
            _subscribed = True
            retry_delay = 3  # 连接成功，重置重连延迟
            print("Subscribe OK!", flush=True)
        else:
            print(f"Subscribe FAILED: errcode={errcode}, errmsg={errmsg}", flush=True)

    elif cmd == "aibot_send_msg" or cmd == "aibot_respond_msg":
        # 发送/回复的响应
        errcode = body.get("errcode", data.get("errcode", -1))
        errmsg = body.get("errmsg", data.get("errmsg", ""))
        if errcode == 0:
            print(f"  {cmd} OK!", flush=True)
        else:
            print(f"  {cmd} failed: {errcode} {errmsg}", flush=True)

    else:
        print(f"unknown cmd: {cmd}, data: {json.dumps(data, ensure_ascii=False)[:200]}", flush=True)


def on_error(ws, error):
    print(f"WS error: {error}", flush=True)


def on_close(ws, close_status_code, close_msg):
    global _ws, _subscribed
    _ws = None
    _subscribed = False
    print(f"WS closed: code={close_status_code}, msg={close_msg}", flush=True)


def on_open(ws):
    global _ws, _last_msg_time
    _ws = ws
    _last_msg_time = time.time()
    print("WS connected, subscribing...", flush=True)
    subscribe_msg = {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": str(uuid.uuid4())},
        "body": {
            "bot_id": BOT_ID,
            "secret": SECRET,
        },
    }
    ws.send(json.dumps(subscribe_msg))


def run_bot():
    global retry_delay
    _kill_existing_bot()

    print("=" * 50)
    print(" WeCom Bot (WebSocket)")
    print("=" * 50)
    print(f"Bot ID: {BOT_ID}")
    print(f"Messages: {MESSAGES_FILE}")
    print(f"Outbox: {OUTBOX_FILE}")
    print()

    # 启动 outbox 监听线程
    t = threading.Thread(target=outbox_watcher, daemon=True)
    t.start()
    print("Outbox watcher started")

    # 启动健康检查线程
    t2 = threading.Thread(target=health_checker, daemon=True)
    t2.start()
    print("Health checker started")

    retry_delay = 3
    while True:
        try:
            print(f"Connecting to {WS_URL} ...")
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever(ping_interval=60, ping_timeout=30)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Exception: {e}")

        print(f"Reconnecting in {retry_delay}s...")
        time.sleep(retry_delay)
        retry_delay = min(retry_delay + 3, 30)


if __name__ == "__main__":
    run_bot()
