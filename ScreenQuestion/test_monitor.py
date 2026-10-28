import unittest
import core

MONS = [{"left": -1920, "top": 0, "width": 3840, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -1920, "top": 0, "width": 1920, "height": 1080}]


class MonitorTests(unittest.TestCase):
    def test_monitor_at(self):
        self.assertEqual(core.monitor_at(MONS, 100, 100), 1)
        self.assertEqual(core.monitor_at(MONS, -100, 100), 2)
        self.assertEqual(core.monitor_at(MONS, 1920, 100), None)

    def test_follow_cursor(self):
        s = {"follow_cursor": True, "monitor": 1}
        self.assertEqual(core.resolve_monitor(s, MONS, (-500, 50)), 2)
        self.assertEqual(core.resolve_monitor(s, MONS, (500, 50)), 1)

    def test_fallbacks(self):
        self.assertEqual(core.resolve_monitor({"follow_cursor": False, "monitor": 2}, MONS, (500, 50)), 2)
        self.assertEqual(core.resolve_monitor({"follow_cursor": True, "monitor": 2}, MONS, None), 2)
        self.assertEqual(core.resolve_monitor({"follow_cursor": True, "monitor": 1}, MONS, (9999, 9)), 1)

    def test_validate(self):
        s = core.validate(dict(core.DEFAULTS, mode="select"))
        self.assertEqual(s["mode"], "select")
        self.assertTrue(s["follow_cursor"])
        self.assertEqual(core.validate(dict(core.DEFAULTS, mode="x"))["mode"], "online")


if __name__ == "__main__":
    unittest.main()
