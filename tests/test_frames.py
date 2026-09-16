"""协议解析单元测试: python -m unittest discover tests -v"""
import unittest

import battery


class MouseFrameTests(unittest.TestCase):
    def test_frame_layout(self):
        f = battery.mouse_query_frame()
        self.assertEqual(len(f), 64)
        self.assertEqual(f[0], 0x4D)
        self.assertEqual(f[1:9], bytes([0x01, 0x01, 0x00, 0x00, 0x09, 0x00, 0x00, 0x08]))
        self.assertTrue(all(x == 0 for x in f[9:]))

    def test_checksum(self):
        f = battery.mouse_query_frame()
        cs = 0
        for x in f[2:8]:  # flags..seq (除版本字节)
            cs ^= x
        self.assertEqual(cs, f[8])


class MouseReplyTests(unittest.TestCase):
    def _reply(self, battery=90, charging=False, connect=2, busy=0):
        raw = bytearray(64)
        raw[0] = 0x4D
        raw[4], raw[5] = 0x00, 0x09
        raw[8] = busy
        raw[18], raw[19], raw[20] = connect, 1 if charging else 0, battery
        return bytes(raw)

    def test_parse(self):
        st = battery.parse_mouse_reply(self._reply(87, True))
        self.assertEqual(st["percent"], 87)
        self.assertTrue(st["charging"])
        self.assertEqual(st["connect"], "2.4G")

    def test_busy_returns_none(self):
        self.assertIsNone(battery.parse_mouse_reply(self._reply(busy=0xFF)))

    def test_wrong_cmd_returns_none(self):
        raw = bytearray(self._reply())
        raw[5] = 0x08
        self.assertIsNone(battery.parse_mouse_reply(bytes(raw)))


class KeyboardPushTests(unittest.TestCase):
    def test_legacy_battery(self):
        raw = bytes([0xFA, 0xFB, 0x07, 68, 0x01]) + bytes(59)
        self.assertEqual(battery.parse_legacy_battery(raw), (68, True))

    def test_legacy_battery_off(self):
        raw = bytes([0xFA, 0xFB, 0x07, 44, 0x00]) + bytes(59)
        self.assertEqual(battery.parse_legacy_battery(raw), (44, False))

    def test_legacy_out_of_range(self):
        raw = bytes([0xFA, 0xFB, 0x07, 200, 0x00]) + bytes(59)
        self.assertIsNone(battery.parse_legacy_battery(raw))

    def test_manual_report(self):
        raw = bytearray(64)
        raw[0:8] = bytes([0xAA, 0x07, 0x00, 0x17, 0x00, 0x00, 0x00, 0x00])
        raw[8] = 0x00  # 掩码 Lo
        raw[9] = 0x02  # 掩码 Hi (bit9 = batteryLevel)
        raw[10] = 0x01  # 充电中
        raw[11] = 70  # 电量
        raw[12] = 0x02  # 无线
        self.assertEqual(battery.parse_manual_report(bytes(raw)), (70, True))

    def test_manual_report_invalid_percent(self):
        raw = bytearray(64)
        raw[0:8] = bytes([0xAA, 0x07, 0x00, 0x17, 0x00, 0x00, 0x00, 0x00])
        raw[11] = 0xFF
        self.assertIsNone(battery.parse_manual_report(bytes(raw)))


class DeviceNameTests(unittest.TestCase):
    def test_match(self):
        self.assertEqual(battery.match_device_name("MCHOSE K7 V2 Ultra+"), "mouse")
        self.assertEqual(battery.match_device_name("MCHOSE K99 V3-1"), "keyboard")
        self.assertIsNone(battery.match_device_name("Redmi Buds 5"))
        self.assertIsNone(battery.match_device_name(""))


if __name__ == "__main__":
    unittest.main()
