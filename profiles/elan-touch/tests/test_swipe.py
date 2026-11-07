import dataclasses
import unittest

from helpers import apple_config, fired_gestures, run_fixture


def _enable(config, name):
    spec = dataclasses.replace(config.gestures[name],
                               action=dataclasses.replace(
                                   config.gestures[name].action, enabled=True,
                                   type="command", argv=("true",)))
    return dataclasses.replace(config, gestures={**config.gestures, name: spec})


class SwipeFixtureTest(unittest.TestCase):
    def test_horizontal_swipes_fire(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                summary, _ = run_fixture(f"gesture_four_swipe_{direction}",
                                         apple_config())
                self.assertEqual(fired_gestures(summary), [f"four_finger_{direction}"])

    def test_vertical_up_is_owned_by_niri(self):
        # apple-trackpad.toml keeps four_finger_up disabled with provider=niri.
        summary, _ = run_fixture("gesture_four_swipe_up", apple_config())
        self.assertEqual(summary["fired"], [])

    def test_vertical_down_is_daemon_owned(self):
        summary, _ = run_fixture("gesture_four_swipe_down", apple_config())
        self.assertEqual(fired_gestures(summary), ["four_finger_down"])

    def test_explicitly_enabled_four_finger_up_fires(self):
        config = _enable(apple_config(), "four_finger_up")
        summary, _ = run_fixture("gesture_four_swipe_up", config)
        self.assertEqual(fired_gestures(summary), ["four_finger_up"])

    def test_short_swipe_is_rejected(self):
        summary, records = run_fixture("false_four_swipe_short", apple_config())
        self.assertEqual(summary["fired"], [])
        reasons = {d["reason"] for r in records for d in r.decisions}
        self.assertIn("swipe_too_short", reasons)


if __name__ == "__main__":
    unittest.main()
