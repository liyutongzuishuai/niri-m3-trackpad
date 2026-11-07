import unittest

from elan_gesture.mt import Contact, MTFrame
from elan_gesture.tap import TapRecognizer

from helpers import apple_config, fired_gestures, run_fixture


def frame(t, points, ids=(11, 22, 33)):
    return MTFrame(t, {tid: Contact(tid, i, int(x), int(y))
                       for i, (tid, (x, y)) in enumerate(zip(ids, points))}, {}, {})


class TapFixtureTest(unittest.TestCase):
    def test_three_finger_tap_fires(self):
        summary, _ = run_fixture("gesture_three_finger_tap", apple_config())
        self.assertEqual(fired_gestures(summary), ["three_finger_tap"])
        self.assertGreater(summary["fired"][0]["confidence"], 0.5)

    def test_moved_hold_and_wrong_count_are_rejected(self):
        for name, reason in (("false_three_finger_tap_moved", "tap_moved"),
                             ("false_three_finger_hold", "tap_too_slow"),
                             ("false_two_finger_tap", None)):
            with self.subTest(case=name):
                summary, records = run_fixture(name, apple_config())
                self.assertEqual(summary["fired"], [])
                if reason:
                    reasons = {d["reason"] for r in records for d in r.decisions}
                    self.assertIn(reason, reasons)


class TapRecognizerUnitTest(unittest.TestCase):
    def _tap(self, hold_s=0.08, travel=0.0):
        rec = TapRecognizer("three_finger_tap", 3, tap_max_ms=220, tap_max_mm=2.5)
        points = [(30, 30), (45, 30), (60, 30)]
        rec.update(frame(1.00, points))
        rec.update(frame(1.00 + hold_s, [(x + travel, y) for x, y in points]))
        return rec.update(frame(1.00 + hold_s + 0.01, []))

    def test_short_still_tap_fires(self):
        det = self._tap()
        self.assertTrue(det.fire)
        self.assertEqual(det.gesture, "three_finger_tap")

    def test_travel_rejects_tap(self):
        det = self._tap(travel=6.0)
        self.assertFalse(det.fire)
        self.assertEqual(det.reason, "tap_moved")

    def test_slow_release_rejects_tap(self):
        det = self._tap(hold_s=0.4)
        self.assertFalse(det.fire)
        self.assertEqual(det.reason, "tap_too_slow")


if __name__ == "__main__":
    unittest.main()
