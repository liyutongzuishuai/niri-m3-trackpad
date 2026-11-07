import unittest

from elan_gesture.spread import SpreadRecognizer

from helpers import PAD_BOUNDS, apple_config, fired_gestures, run_fixture


class SpreadFixtureTest(unittest.TestCase):
    def test_spread_and_pinch_fire(self):
        for name, gesture in (("gesture_thumb_spread_open", "thumb_spread_open"),
                              ("gesture_thumb_pinch", "thumb_spread_pinch")):
            with self.subTest(case=name):
                summary, _ = run_fixture(name, apple_config())
                self.assertEqual(fired_gestures(summary), [gesture])

    def test_four_finger_translation_is_not_a_spread(self):
        summary, _ = run_fixture("false_four_translate_not_spread", apple_config())
        self.assertNotIn("thumb_spread_open", fired_gestures(summary))
        self.assertNotIn("thumb_spread_pinch", fired_gestures(summary))


class SpreadRecognizerUnitTest(unittest.TestCase):
    def _recognizer(self):
        return SpreadRecognizer(scale_x=1.0, scale_y=1.0, bounds=PAD_BOUNDS)

    def test_flat_contacts_have_no_thumb(self):
        rec = self._recognizer()
        from elan_gesture.mt import Contact, MTFrame
        points = {1: (20, 30), 2: (40, 30), 3: (20, 40), 4: (40, 40)}
        frame = MTFrame(1.0, {tid: Contact(tid, i, x, y)
                              for i, (tid, (x, y)) in enumerate(points.items())}, {}, {})
        det = rec.update(frame)
        self.assertEqual(det.reason, "no_thumb_candidate")


if __name__ == "__main__":
    unittest.main()
