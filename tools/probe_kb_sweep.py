"""Z 协议命令全扫描: [55 cmd 00 38 38 00 00 00] rid0 -> if1, 找电量回复。"""
import time

import hid

VID, PID = 0x3837, 0x3033


def hexs(b):
    return " ".join(f"{x:02x}" for x in b[:20])


def main():
    dev = hid.device()
    info = next(i for i in hid.enumerate(VID, PID)
                if i["usage_page"] == 0x0001 and i["usage"] == 0x0000)
    dev.open_path(info["path"])
    dev.set_nonblocking(True)
    print("opened if1/pg0001")

    results = {}
    for cmd in range(0x00, 0x100):
        frame = bytes([0x55, cmd, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00])
        try:
            dev.write(bytes([0x00]) + frame + b"\x00" * 55)
        except OSError as e:
            print(f"cmd {cmd:02x}: write ERR {e}")
            continue
        end = time.monotonic() + 0.28
        while time.monotonic() < end:
            try:
                data = dev.read(64, timeout_ms=0)
            except OSError:
                data = None
            if data:
                raw = bytes(data)
                key = raw[:4]
                if key not in results:
                    results[key] = (cmd, raw)
                elif results[key][0] != cmd and key == raw[:4]:
                    pass
    dev.close()

    print(f"\n=== unique reply types: {len(results)} ===")
    for key, (cmd, raw) in sorted(results.items(), key=lambda kv: kv[1][0]):
        tag = ""
        if 70 in raw[8:24]:
            tag = "  <== CONTAINS 70"
        print(f"first-cmd=0x{cmd:02x} reply: {hexs(raw)}{tag}")


if __name__ == "__main__":
    main()
