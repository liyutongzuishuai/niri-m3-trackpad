import unittest
from pathlib import Path

from elan_gesture.config import default_config
from elan_gesture.gesture import GestureDetector, confidence_formula
from helpers import run_fixture as run


class GestureFixtureTest(unittest.TestCase):
    def test_four_directions(self):
        for direction in ("up", "down", "left", "right"):
            with self.subTest(direction=direction):
                summary, _ = run(f"gesture_{direction}")
                self.assertEqual(len(summary["fired"]), 1)
                self.assertEqual(summary["fired"][0]["direction"], direction)
                self.assertGreaterEqual(summary["fired"][0]["confidence"], 0.65)

    def test_fast_and_continuous_and_repeat(self):
        summary, _ = run("gesture_fast_up")
        self.assertEqual([f["direction"] for f in summary["fired"]], ["up"])
        summary, _ = run("gesture_continuous")
        self.assertEqual([f["direction"] for f in summary["fired"]],
                         ["up", "down", "left", "right"])
        summary, _ = run("repeat_gestures")
        self.assertEqual(len(summary["fired"]), 2)

    def test_false_positives_are_all_rejected(self):
        for name in ("false_two_finger_scroll", "false_three_finger_swipe",
                     "false_four_finger", "false_static_drift", "false_short_move",
                     "false_diagonal", "false_tracking_id_change", "false_syn_dropped"):
            with self.subTest(case=name):
                summary, _ = run(name)
                self.assertEqual(summary["fired"], [], f"{name} produced {summary['fired']}")

    def test_three_finger_swipe_rejected_during_settle(self):
        _, records = run("false_three_finger_swipe")
        reasons = {r.decision["reason"] for r in records}
        self.assertIn("settle_movement", reasons)
        self.assertNotIn("gesture_qualified", reasons)

    def test_unique_mover_is_enforced_after_settle(self):
        # Two fingers start moving only after the settle window has elapsed.
        from elan_gesture.mt import Contact, MTFrame
        from elan_gesture.config import default_config
        d = GestureDetector(default_config().gesture, 1.0, 1.0)
        ids = (11, 22, 33)
        base = {tid: Contact(tid, i, x, y) for i, (tid, x, y) in
                enumerate(zip(ids, (100, 160, 130), (100, 100, 150)))}
        d.update(MTFrame(1.0, base, {}, {}))
        d.update(MTFrame(1.06, base, {}, {}))
        d.update(MTFrame(1.13, base, {}, {}))
        moved = {11: Contact(11, 0, 100, 80),
                 22: Contact(22, 1, 160, 80),
                 33: Contact(33, 2, 130, 150)}
        decision = d.update(MTFrame(1.20, moved, {}, {}))
        self.assertEqual(decision.reason, "multiple_movers")

    def test_confidence_formula_bounds(self):
        high = confidence_formula(20, 8, 0.0, 0.0, 1.5, 10, 700)
        low = confidence_formula(0, 8, 1.0, 1.5, 1.5, 700, 700)
        self.assertGreater(high, 0.9)
        self.assertLess(low, 0.4)
        self.assertGreaterEqual(min(high, low), 0.0)
        self.assertLessEqual(max(high, low), 1.0)


if __name__ == "__main__":
    unittest.main()
