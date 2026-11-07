"""Offline checks for the touchpad visualizer's decoder and axis mapping."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("touchviz", ROOT / "touchviz" / "touchviz.py")
touchviz = importlib.util.module_from_spec(spec)
sys.modules["touchviz"] = touchviz
spec.loader.exec_module(touchviz)


class TouchVizTest(unittest.TestCase):
    def test_axis_uses_kernel_resolution_and_preserves_mm_extent(self):
        m = touchviz.replay_model(None)
        self.assertEqual(m.x.units_per_mm, 31)
        self.assertEqual(m.y.units_per_mm, 31)
        width = (m.x.maximum - m.x.minimum) / m.x.units_per_mm
        height = (m.y.maximum - m.y.minimum) / m.y.units_per_mm
        self.assertAlmostEqual(width, 98.45, places=1)
        self.assertAlmostEqual(height, 60.90, places=1)
        self.assertAlmostEqual(m.x.normalized(0), 0.0)
        self.assertAlmostEqual(m.x.normalized(3052), 1.0)

    def test_contacts_keyed_by_tracking_id_not_slot(self):
        m = touchviz.replay_model(None)
        d = touchviz.MTDecoder(m)
        frames = []
        for event in touchviz.events_from_jsonl(ROOT / "tests/fixtures/gesture_up.jsonl"):
            frame = d.feed(event)
            if frame is not None:
                frames.append(frame)
        self.assertEqual(len(frames), 12)
        self.assertEqual(sorted(frames[0].contacts), [11, 22, 33])
        self.assertEqual([frames[0].contacts[k].slot for k in (11, 22, 33)], [0, 1, 2])
        self.assertEqual(len(frames[-1].contacts), 0)

    def test_tracking_id_reuse_gives_new_identity(self):
        m = touchviz.replay_model(None)
        d = touchviz.MTDecoder(m)
        seq = [
            (3, 1.0, 47, 0), (3, 1.0, 57, 11), (3, 1.0, 53, 100), (3, 1.0, 54, 100),
            (0, 1.0, 0, 0),
            (3, 1.1, 47, 0), (3, 1.1, 57, -1), (3, 1.1, 57, 77),
            (3, 1.1, 53, 120), (3, 1.1, 54, 130), (0, 1.1, 0, 0),
        ]
        frames = [f for e in seq if (f := d.feed(e)) is not None]
        self.assertEqual([sorted(f.contacts) for f in frames], [[11], [77]])
        self.assertEqual(frames[-1].contacts[77].x, 120)

    def test_release_keeps_tap_tail_for_visibility(self):
        m = touchviz.replay_model(None)
        d = touchviz.MTDecoder(m)
        seq = [
            (3, 1.0, 47, 0), (3, 1.0, 57, 11), (3, 1.0, 53, 100), (3, 1.0, 54, 100),
            (0, 1.0, 0, 0),
            (3, 1.1, 57, -1), (0, 1.1, 0, 0),
        ]
        frames = [f for e in seq if (f := d.feed(e)) is not None]
        self.assertEqual(len(frames[-1].contacts), 0)
        self.assertEqual(sorted(m.last_contacts), [11])
        self.assertGreater(m.last_contact_time, 0)

    def test_syn_dropped_clears_contacts(self):
        m = touchviz.replay_model(None)
        d = touchviz.MTDecoder(m)
        seq = [
            (3, 1.0, 47, 0), (3, 1.0, 57, 11), (3, 1.0, 53, 100), (3, 1.0, 54, 100),
            (0, 1.0, 0, 0), (0, 1.1, 3, 0), (0, 1.2, 0, 0),
        ]
        frames = [f for e in seq if (f := d.feed(e)) is not None]
        self.assertTrue(frames[-1].dropped)
        self.assertEqual(frames[-1].contacts, {})
        self.assertEqual(m.dropped_count, 1)


if __name__ == "__main__":
    unittest.main()
