# -*- coding: utf-8 -*-
"""监听 messages.json 新消息，检测到就输出并退出"""
import json
import time
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "..", ".."))
target_file = os.path.join(BASE_DIR, "messages.json")
known_count = int(sys.argv[1]) if len(sys.argv) > 1 else 0
timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 1800

start = time.time()
while time.time() - start < timeout:
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            msgs = json.load(f)
        if len(msgs) > known_count:
            for m in msgs[known_count:]:
                print(json.dumps(m, ensure_ascii=False))
            sys.exit(0)
    except Exception:
        pass
    time.sleep(1)

print("TIMEOUT")
