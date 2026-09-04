"""3 分钟被动监听: 复刻页面初始化后监听 FA FB 07 / MANUAL_REPORT 推送。"""
import time

import hid

VID, PID = 0x3837, 0x3033


def hexs(b):
    return " ".join(f"{x:02x}" for x in b[:28])


def main(minutes=3):
    info = next(i for i in hid.enumerate(VID, PID)
                if i["usage_page"] == 0x0001 and i["usage"] == 0x0000)
    dev = hid.device()
    dev.open_path(info["path"])
    dev.set_nonblocking(True)
    print("opened if1/pg0001")

    # 复刻页面初始化: getInfo + getBase
    for frame in (bytes([0x55, 0x03, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00]),
                  bytes([0x55, 0x04, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00])):
        dev.write(bytes([0x00]) + frame + b"\x00" * 55)
        time.sleep(0.3)
    # 清空积压
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.5:
        dev.read(64, timeout_ms=0)
    print("warm-up done; listening...", flush=True)

    t0 = time.monotonic()
    counts = {}
    while time.monotonic() - t0 < minutes * 60:
        try:
            data = dev.read(64, timeout_ms=0)
        except OSError:
            continue
        if data:
            raw = bytes(data)
            key = raw[0]
            counts[key] = counts.get(key, 0) + 1
            if raw[0] != 0xAA or (raw[3] == 0x00 and raw[4] == 0x07):
                print(f"+{time.monotonic()-t0:6.1f}s NOTIFY {hexs(raw)}", flush=True)
            elif counts[key] <= 3:
                print(f"+{time.monotonic()-t0:6.1f}s reply  {hexs(raw)}", flush=True)
    print("frame-type counts:", {f"0x{k:02x}": v for k, v in sorted(counts.items())})
    dev.close()


if __name__ == "__main__":
    main(3)
