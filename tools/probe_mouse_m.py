"""M HUB 鼠标 M 帧协议实测 (K7 V2 Ultra+, PID 0x1014)。

发送: output report 0x4D, 载荷 [01 flags len cmdLo cmdHi biz seq data... xor校验]
电量查询 commandId=0x0900 -> 4D 01 01 00 00 09 00 00 08 + 零填充到 64 字节
回复: input 报告 bytes[3:5]==00 09, 载荷自 byte7:
      [10]=connectStatus [11]=chargeStatus [12]=batteryLevel [13]=gameMode
      载荷[0]==0xff 表示设备忙, 重试
"""
import time

import hid

VID = 0x3837


def hexs(b):
    return " ".join(f"{x:02x}" for x in b)


def m_frame(command_id, data=b"", flags=1, biz=0, seq=0):
    body = bytearray()
    body += bytes([0x01, flags, len(data), command_id & 0xFF, (command_id >> 8) & 0xFF, biz, seq])
    body += data
    if flags == 1:
        body.append(0)
        cs = 0
        for x in body[1:]:  # 对应官方 Iyt(o,2,7+len): flags..data 全部异或
            cs ^= x
        body[-1] = cs
    report = bytes([0x4D]) + bytes(body)
    return report + b"\x00" * (64 - len(report))


def parse_0900(report):
    """report: 含 report id 的完整字节。返回解析结果或 None。"""
    if len(report) < 8:
        return None
    if report[3] != 0x00 or report[4] != 0x09:
        return None
    payload = report[7:]
    return {
        "vid": payload[0] | payload[1] << 8,
        "pid": payload[2] | payload[3] << 8,
        "connectStatus": payload[10],
        "chargeStatus": payload[11],
        "batteryLevel": payload[12],
        "gameMode": payload[13],
        "raw_payload": hexs(payload[:20]),
    }


def main():
    colls = []
    for info in hid.enumerate(VID, 0x1014):
        if info["usage_page"] >= 0xFF00:
            name = f"if{info['interface_number']}/pg{info['usage_page']:04x}"
            dev = hid.device()
            try:
                dev.open_path(info["path"])
                dev.set_nonblocking(True)
                colls.append((name, dev))
            except OSError as e:
                print(f"open {name} failed: {e}")
    if not colls:
        print("no vendor collection")
        return

    frame = m_frame(0x0900)
    print("query frame:", hexs(frame[:16]), "...")
    for attempt in range(6):
        for name, dev in colls:
            try:
                n = dev.write(frame)
                print(f"try{attempt} write@{name}: {'ok' if n >= 0 else n}")
            except OSError as e:
                print(f"try{attempt} write@{name}: ERR{e.errno}")
        end = time.monotonic() + 2.0
        parsed = None
        while time.monotonic() < end and not parsed:
            for name, dev in colls:
                data = dev.read(64, timeout_ms=0)
                if data:
                    raw = bytes(data)
                    print(f"  [{name}] id=0x{raw[0]:02x} {hexs(raw[:28])}")
                    parsed = parse_0900(raw)
        if parsed:
            print("PARSED:", parsed)
            break
        print(f"try{attempt}: no reply")
        time.sleep(0.3)

    for _, dev in colls:
        dev.close()


if __name__ == "__main__":
    main()
