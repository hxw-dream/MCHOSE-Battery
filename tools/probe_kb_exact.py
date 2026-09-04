"""精确复刻官方首命令 (cmd3 getInfo, Z 格式, rid0), 验证会话门假设。"""
import time

import hid

VID, PID = 0x3837, 0x3033


def hexs(b):
    return " ".join(f"{x:02x}" for x in b)


def main():
    colls = {}
    for info in hid.enumerate(VID, PID):
        up, us = info["usage_page"], info["usage"]
        keep = (up == 0xFF70) or (up == 0xFF31) or (up == 0x0001 and us == 0x0000)
        if not keep:
            continue
        name = f"if{info['interface_number']}/pg{up:04x}"
        dev = hid.device()
        try:
            dev.open_path(info["path"])
            dev.set_nonblocking(True)
            colls[name] = dev
            print("opened", name)
        except OSError as e:
            print("open fail", name, e)

    def drain(seconds, tag):
        end = time.monotonic() + seconds
        got = False
        while time.monotonic() < end:
            for name, dev in colls.items():
                try:
                    data = dev.read(64, timeout_ms=0)
                except OSError:
                    continue
                if data:
                    got = True
                    print(f"  [{tag}@{name}] {hexs(bytes(data)[:32])}")
        if not got:
            print(f"  [{tag}] (nothing)")

    # 官方 getBaseInfo 命令 (M帧 0x0900, 但 Z 风格变体也试)
    # 1) 官方 cmd3 getInfo Z 帧 (逐字节复刻)
    z_get3 = bytes([0x55, 0x03, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00])
    z_get4 = bytes([0x55, 0x04, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00])
    for target_name in ("if3/pgff70", "if1/pg0001"):
        dev = colls.get(target_name)
        if not dev:
            continue
        print(f"== send exact cmd3 getInfo @{target_name} ==")
        dev.write(bytes([0x00]) + z_get3 + b"\x00" * 55)
        drain(1.5, "cmd3")
        print(f"== send exact cmd4 getBase @{target_name} ==")
        dev.write(bytes([0x00]) + z_get4 + b"\x00" * 55)
        drain(1.5, "cmd4")

    # 2) M 帧 0x0900 (鼠标 baseInfo) rid0 于 if1/if3
    m900 = bytes([0x01, 0x01, 0x00, 0x00, 0x09, 0x00, 0x00])
    cs = 0
    for x in m900[1:]:
        cs ^= x
    m900 += bytes([cs])
    for target_name in ("if3/pgff70", "if1/pg0001"):
        dev = colls.get(target_name)
        if not dev:
            continue
        print(f"== send M-frame 0x0900 @{target_name} ==")
        dev.write(bytes([0x00]) + m900 + b"\x00" * 55)
        drain(1.5, "m900")

    for d in colls.values():
        d.close()


if __name__ == "__main__":
    main()
