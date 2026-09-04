"""键盘抓包 v7: 同一会话内 connectDevice <-> keyboard 双导航, 覆盖完整爆发期,
之后在日志里搜索电量值 (0x46=70) 所在帧。补丁跨导航持续有效。
"""
import json
import re
import time
import urllib.request

import websocket

OUT = open("tools/kb_capture.log", "a", encoding="utf-8")


def log(line):
    OUT.write(line + "\n")
    OUT.flush()


PATCH = open("tools/kb_patch.js", encoding="utf-8").read().replace("__kbpatched", "__kbpatched2")

data = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json/list"))
target = next(t for t in data if t["type"] == "page" and "mchose.com.cn" in t["url"])
ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=15)
mid = 0


def send(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    return mid


def pump(seconds):
    end = time.time() + seconds
    ws.settimeout(0.3)
    while time.time() < end:
        try:
            m = json.loads(ws.recv())
        except Exception:
            continue
        if m.get("method") == "Runtime.consoleAPICalled":
            args = [str(a.get("value") if a.get("value") is not None else a.get("description", ""))
                    for a in m["params"].get("args", [])]
            line = " ".join(args).strip()
            log(line)
            if line.startswith("[KB-"):
                print(line[:260], flush=True)


send("Runtime.enable")
send("Page.enable")
send("Page.addScriptToEvaluateOnNewDocument", {"source": PATCH})
send("Page.navigate", {"url": "https://www.mchose.com.cn/#/connectDevice"})
print("-> connectDevice", flush=True)
pump(14)
send("Page.navigate", {"url": "https://www.mchose.com.cn/#/keyboard?deviceName=MCHOSE+K99+V3+2.4G"})
print("-> keyboard", flush=True)
pump(25)
print("--- done ---", flush=True)
ws.close()

# 分析: 找含 70 (0x46) 的回复帧 及全部 send 命令清单
print("\n===== analysis =====", flush=True)
sends, ins = [], []
for line in OUT and open("tools/kb_capture.log", encoding="utf-8"):
    m = re.search(r"\[KB-sendReport\] rid=(\d+) pid=(\d+) (\[\d+(?:,\d+)*\])", line)
    if m:
        sends.append((int(m.group(2)), [int(x) for x in m.group(3).strip("[]").split(",")]))
    m = re.search(r"\[KB-IN\] rid=(\d+) pid=(\d+) (\[\d+(?:,\d+)*\])", line)
    if m:
        ins.append((int(m.group(2)), [int(x) for x in m.group(3).strip("[]").split(",")]))

print(f"total sends={len(sends)} ins={len(ins)}", flush=True)
print("\n-- unique send commands (flag,cmd,size,offLo,offHi) --", flush=True)
seen = set()
for pid, b in sends:
    if pid == 12339 and len(b) >= 7:
        key = (b[0], b[1], b[4], b[5], b[6])
        if key not in seen:
            seen.add(key)
            print(f"  flag=0x{b[0]:02x} cmd=0x{b[1]:02x} cs=0x{b[3]:02x} size={b[4]} off={b[5]+b[6]*256}", flush=True)

print("\n-- frames containing byte 70 (0x46) in data area --", flush=True)
for pid, b in ins:
    if pid == 12339 and 70 in b[8:24]:
        print("  IN:", [f"{x:02x}" for x in b[:28]], flush=True)
for pid, b in sends:
    if pid == 12339 and 70 in b[8:24]:
        print("  OUT:", [f"{x:02x}" for x in b[:28]], flush=True)
OUT.close()
