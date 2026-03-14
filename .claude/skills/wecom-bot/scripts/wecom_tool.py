# -*- coding: utf-8 -*-
"""
WeCom Tool for Claude Agent
通过企业微信群机器人 Webhook 发送消息，通过 WebSocket 长连接接收消息。

使用方式：
    # 发送消息（通过 Webhook 到群聊）
    python wecom_tool.py send "你好"

    # 回复机器人单聊里的最新消息（通过 response_url）
    python wecom_tool.py reply "回复内容"

    # 读取最新收到的消息
    python wecom_tool.py receive [N]

    # 发送消息并等待回复
    python wecom_tool.py ask "请回复确认" [超时秒数]

    # 连接测试
    python wecom_tool.py test
"""

import requests
import json
import sys
import time
import os

import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Data files live in project root (4 levels up: scripts/ → wecom-bot/ → skills/ → .claude/ → project root)
BASE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "..", ".."))
WEBHOOK_URL = os.environ.get("WECOM_WEBHOOK_URL", "")
MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")
OUTBOX_FILE = os.path.join(BASE_DIR, "outbox.json")
BOT_ID = os.environ.get("WECOM_BOT_ID", "")


def send_text(content: str, mentioned_list=None):
    """发送文本消息（通过 Webhook 到群聊）"""
    data = {
        "msgtype": "text",
        "text": {"content": content}
    }
    if mentioned_list:
        data["text"]["mentioned_list"] = mentioned_list

    resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
    result = resp.json()
    if result.get("errcode") != 0:
        print(f"send failed: {result}", file=sys.stderr)
        return False
    print("sent ok")
    return True


def send_markdown(content: str):
    """发送 Markdown 消息"""
    data = {
        "msgtype": "markdown",
        "markdown": {"content": content}
    }
    resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
    result = resp.json()
    if result.get("errcode") != 0:
        print(f"send failed: {result}", file=sys.stderr)
        return False
    print("sent ok")
    return True


def send_image(image_path: str):
    """发送图片消息"""
    import base64
    import hashlib

    with open(image_path, "rb") as f:
        image_data = f.read()

    data = {
        "msgtype": "image",
        "image": {
            "base64": base64.b64encode(image_data).decode("utf-8"),
            "md5": hashlib.md5(image_data).hexdigest(),
        }
    }
    resp = requests.post(WEBHOOK_URL, json=data, timeout=30)
    result = resp.json()
    if result.get("errcode") != 0:
        print(f"send failed: {result}", file=sys.stderr)
        return False
    print("sent ok")
    return True


def send_file(file_path: str):
    """上传并发送文件"""
    key = WEBHOOK_URL.split("key=")[-1]
    upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"

    with open(file_path, "rb") as f:
        files = {"media": (os.path.basename(file_path), f)}
        resp = requests.post(upload_url, files=files, timeout=30)

    result = resp.json()
    if result.get("errcode") != 0:
        print(f"upload failed: {result}", file=sys.stderr)
        return False

    data = {
        "msgtype": "file",
        "file": {"media_id": result["media_id"]}
    }
    resp = requests.post(WEBHOOK_URL, json=data, timeout=10)
    result = resp.json()
    if result.get("errcode") != 0:
        print(f"send failed: {result}", file=sys.stderr)
        return False
    print("sent ok")
    return True


def reply_to_bot(content: str):
    """通过 response_url 回复最新消息"""
    if not os.path.exists(MESSAGES_FILE):
        print("no messages to reply to")
        return False

    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        try:
            messages = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print("messages.json error")
            return False

    if not messages:
        print("no messages to reply to")
        return False

    for msg in reversed(messages):
        response_url = msg.get("response_url", "")
        if response_url:
            data = {
                "msgtype": "markdown",
                "markdown": {"content": content},
            }
            resp = requests.post(
                response_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                timeout=10,
            )
            result = resp.json()
            if result.get("errcode") == 0:
                print("replied ok")
                return True
            elif result.get("errcode") == 60140:
                continue
            else:
                print(f"reply failed: errcode={result.get('errcode')}, {result.get('errmsg', '')}")
                return False

    print("no valid response_url found (all expired)")
    return False


def ws_send(content: str):
    """通过 WebSocket 发送消息（写入 outbox.json 由 wecom_bot.py 发出）

    单聊：用 aibot_respond_msg 回复最近一条消息的 req_id
    群聊：用 aibot_send_msg 发到群（需要 chatid）
    """
    if not os.path.exists(MESSAGES_FILE):
        print("no messages, cannot send")
        return False

    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        try:
            messages = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print("messages.json error")
            return False

    if not messages:
        print("no messages, cannot send")
        return False

    latest = messages[-1]
    raw = latest.get("raw", {})
    chat_type = latest.get("chat_type", "single")
    msg_id = latest.get("msg_id", raw.get("msgid", ""))

    if chat_type == "group":
        chatid = raw.get("chatid", "")
        if not chatid:
            print("no chatid found")
            return False
        msg = {
            "cmd": "aibot_send_msg",
            "headers": {"req_id": str(uuid.uuid4())},
            "body": {
                "chatid": chatid,
                "msgtype": "markdown",
                "markdown": {"content": content},
            },
        }
    else:
        # 单聊：用 aibot_respond_msg + 原始 req_id
        req_id = latest.get("req_id", "")
        if not req_id:
            print("no req_id found, falling back to response_url")
            return reply_to_bot(content)
        msg = {
            "cmd": "aibot_respond_msg",
            "headers": {"req_id": req_id},
            "body": {
                "msgtype": "markdown",
                "markdown": {"content": content},
            },
        }

    # 写入 outbox.json
    outbox = []
    if os.path.exists(OUTBOX_FILE):
        with open(OUTBOX_FILE, "r", encoding="utf-8") as f:
            try:
                existing = f.read().strip()
                if existing:
                    outbox = json.loads(existing)
            except (json.JSONDecodeError, ValueError):
                outbox = []

    outbox.append(msg)
    with open(OUTBOX_FILE, "w", encoding="utf-8") as f:
        json.dump(outbox, f, ensure_ascii=False, indent=2)

    print("queued to outbox")
    return True


def receive_messages(count=5):
    """读取最近收到的消息"""
    if not os.path.exists(MESSAGES_FILE):
        print("no messages yet")
        return []

    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        try:
            messages = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print("messages.json error")
            return []

    if not messages:
        print("no messages yet")
        return []

    recent = messages[-count:]
    for msg in recent:
        ts = msg.get("received_at", "?")
        user = msg.get("from_user", "?")
        content = msg.get("content", "")
        print(f"[{ts}] {user}: {content}")
    return recent


def ask_and_wait(question: str, timeout=120):
    """通过机器人回复发送问题，等待用户回复"""
    # 先回复到机器人单聊
    if not reply_to_bot(question):
        # 如果回复失败，用 webhook 发到群聊
        print("reply_to_bot failed, falling back to webhook")
        if not send_text(f"[Claude Agent] {question}"):
            return None

    # 记录当前消息数
    msg_count_before = 0
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            try:
                msg_count_before = len(json.load(f))
            except (json.JSONDecodeError, ValueError):
                pass

    print(f"waiting for reply ({timeout}s timeout)...")

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(2)
        if os.path.exists(MESSAGES_FILE):
            with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
                try:
                    messages = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    continue

            if len(messages) > msg_count_before:
                new_msg = messages[-1]
                content = new_msg.get("content", "")
                user = new_msg.get("from_user", "?")
                print(f"reply from {user}: {content}")
                return new_msg

    print(f"timeout ({timeout}s)")
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "send":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py send <message>")
            sys.exit(1)
        send_text(" ".join(sys.argv[2:]))

    elif command == "send_md":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py send_md <markdown>")
            sys.exit(1)
        send_markdown(" ".join(sys.argv[2:]).replace("\\n", "\n"))

    elif command == "send_image":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py send_image <path>")
            sys.exit(1)
        send_image(sys.argv[2])

    elif command == "send_file":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py send_file <path>")
            sys.exit(1)
        send_file(sys.argv[2])

    elif command == "reply":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py reply <message>")
            sys.exit(1)
        reply_to_bot(" ".join(sys.argv[2:]))

    elif command == "receive":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        receive_messages(count)

    elif command == "ask":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py ask <question> [timeout]")
            sys.exit(1)
        timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        ask_and_wait(sys.argv[2], timeout)

    elif command == "ws_send":
        if len(sys.argv) < 3:
            print("usage: python wecom_tool.py ws_send <message>")
            sys.exit(1)
        ws_send(" ".join(sys.argv[2:]))

    elif command == "test":
        send_text("Claude Agent test ok!")

    else:
        print(f"unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
