import unittest

from helpers import apple_config, fired_gestures, run_fixture


class EdgeSwipeFixtureTest(unittest.TestCase):
    def test_right_edge_swipe_fires(self):
        summary, _ = run_fixture("gesture_edge_swipe_right", apple_config())
        self.assertEqual(fired_gestures(summary), ["two_finger_edge_left"])

    def test_middle_two_finger_swipe_is_ignored(self):
        summary, records = run_fixture("false_edge_swipe_middle", apple_config())
        self.assertEqual(summary["fired"], [])
        reasons = {d["reason"] for r in records for d in r.decisions}
        self.assertIn("not_from_edge", reasons)


if __name__ == "__main__":
    unittest.main()
