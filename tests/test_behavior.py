"""缓存、读取优先级、低电量确认与缩放回归：纯函数，不操作真机 HID。"""
import unittest

import battery
import float_window
from tray_app import low_battery_transition


class BleOutputTests(unittest.TestCase):
    def test_live_not_overwritten_by_idle(self):
        lines = ("name=MCHOSE K99 V3|bat=44|hid=1", "name=MCHOSE K99 V3|bat=70|hid=0|age=10")
        for output in ("\n".join(lines), "\n".join(reversed(lines))):
            data = battery.parse_ble_output(output)
            self.assertEqual(data["keyboard"], 44)
            self.assertTrue(data["keyboard_live"])

    def test_invalid_lines_ignored(self):
        data = battery.parse_ble_output("noise\nname=MCHOSE K7|bat=101|hid=1\nname=Other|bat=60|hid=1")
        self.assertIsNone(data["mouse"])
        self.assertIsNone(data["keyboard"])

    def test_zero_percent_is_valid_for_ble(self):
        self.assertEqual(battery.parse_ble_output("name=MCHOSE K7|bat=0|hid=1")["mouse"], 0)


class KeyboardStateTests(unittest.TestCase):
    def setUp(self):
        self.args = dict(ble=battery.parse_ble_output(""), percent=37, charging=True,
                         ts=1000, connected=None, receiver_present=True, fresh_push=False, now=2000)

    def select(self, **changes):
        return battery.select_keyboard_state(**(self.args | changes))

    def test_disk_cache_is_labelled_and_not_charging(self):
        result = self.select()
        self.assertEqual(result["percent"], 37)
        self.assertEqual(result["source"], "cache")
        self.assertEqual(result["connect"], "2.4G 缓存")
        self.assertFalse(result["charging"])

    def test_expired_future_invalid_cache_rejected(self):
        for changes in ({"now": 87400}, {"ts": 3000}, {"ts": "invalid"},
                        {"percent": 101}, {"percent": True}, {"percent": None}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.select(**changes))

    def test_receiver_missing_or_link_down(self):
        self.assertIsNone(self.select(receiver_present=False))
        self.assertIsNone(self.select(connected=False, fresh_push=True))

    def test_live_ble_wins(self):
        ble = self.args["ble"] | {"keyboard": 70, "keyboard_live": True}
        self.assertEqual(self.select(ble=ble, fresh_push=True)["percent"], 70)

    def test_push_wins_over_idle_ble(self):
        ble = self.args["ble"] | {"keyboard": 70}
        result = self.select(ble=ble, fresh_push=True)
        self.assertEqual(result["percent"], 37)
        self.assertEqual(result["source"], "push")
        self.assertTrue(result["charging"])

    def test_idle_ble_fallback_after_disconnect(self):
        ble = self.args["ble"] | {"keyboard": 70}
        self.assertEqual(self.select(ble=ble, connected=False)["source"], "ble")


class LowBatteryTests(unittest.TestCase):
    def transitions(self, values):
        streak, notified = 0, False
        results = []
        for value in values:
            streak, notified, fire = low_battery_transition(value, streak, notified)
            results.append((streak, notified, fire))
        return results

    def test_three_consecutive_readings_notify_once(self):
        results = self.transitions([15, 14, 13, 12, 11])
        self.assertEqual([r[2] for r in results], [False, False, True, False, False])

    def test_unknown_breaks_confirmation(self):
        results = self.transitions([15, 15, None, 15, 15, 15])
        self.assertEqual(results[2][0], 0)
        self.assertEqual([r[2] for r in results], [False] * 5 + [True])

    def test_above_low_threshold_breaks_confirmation(self):
        self.assertFalse(any(r[2] for r in self.transitions([15, 15, 16, 15, 15])))

    def test_rearm_requires_above_twenty(self):
        results = self.transitions([15, 15, 15, 20, 15, 15, 15, 21, 15, 15, 15])
        self.assertEqual([i for i, r in enumerate(results) if r[2]], [2, 10])

    def test_unknown_does_not_rearm_notified_device(self):
        self.assertEqual(low_battery_transition(None, 3, True), (0, True, False))

    def test_keyboard_zero_percent_can_notify(self):
        self.assertTrue(self.transitions([0, 0, 0])[-1][2])


class WidgetScaleTests(unittest.TestCase):
    def test_four_distinct_sizes_at_common_dpi(self):
        for dpi in (96, 120, 144, 168, 192):
            with self.subTest(dpi=dpi):
                sizes = [float_window.card_size(dpi / 96 * factor) for factor in (0.5, 0.65, 1, 1.25)]
                self.assertEqual(len(set(sizes)), 4)
        self.assertEqual(float_window.card_size(1.3), (429, 135))

    def test_red_threshold_matches_tray(self):
        self.assertEqual(float_window._level_color(15, False), float_window.RED)
        self.assertEqual(float_window._level_color(16, False), float_window.AMBER)


if __name__ == "__main__":
    unittest.main()
