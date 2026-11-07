import unittest

from evdev import ecodes

from elan_gesture.engine import Engine
from elan_gesture.mt import Contact, MTFrame

from helpers import PAD_BOUNDS, apple_config


def four(x_shift=0.0, y_shift=0.0, scale=1.0):
    thumb = (30.0, 52.0)
    fingers = [(12.0, 32.0), (48.0, 32.0), (30.0, 22.0)]
    points = [thumb] + [(thumb[0] + (x - thumb[0]) * scale + x_shift,
                         thumb[1] + (y - thumb[1]) * scale + y_shift)
                        for x, y in fingers]
    return points


def frame(t, points, ids=(300, 301, 302, 303), buttons=None, tool=None):
    contacts = {tid: Contact(tid, i, int(round(x)), int(round(y)))
                for i, (tid, (x, y)) in enumerate(zip(ids, points))}
    return MTFrame(t, contacts, tool or {}, buttons or {})


class EngineArbitrationTest(unittest.TestCase):
    def _engine(self, **kwargs):
        return Engine(apple_config(), 1.0, 1.0, PAD_BOUNDS, **kwargs)

    def test_dropped_frame_resets_everything(self):
        engine = self._engine()
        engine.step(frame(1.0, four()))
        out = engine.step(MTFrame(1.1, {}, {}, {}, dropped=True))
        self.assertEqual(out.fires, [])
        self.assertEqual(out.decisions[0]["reason"], "syn_dropped")

    def test_physical_button_resets_everything(self):
        engine = self._engine()
        engine.step(frame(1.0, four()))
        out = engine.step(frame(1.1, four(), buttons={ecodes.BTN_LEFT: True}))
        self.assertEqual(out.fires, [])
        self.assertEqual(out.decisions[0]["reason"], "physical_button")

    def test_only_one_fire_per_release(self):
        engine = self._engine()
        points = four()
        engine.step(frame(1.0, points))
        engine.step(frame(1.02, four(scale=1.45)))
        out = engine.step(frame(1.04, []))
        self.assertEqual(len(out.fires), 1)
        self.assertEqual(out.fires[0].gesture, "thumb_spread_open")

    def test_overview_probe_is_sampled_once_at_four_fingers(self):
        calls = []
        engine = self._engine(overview_probe=lambda: calls.append(1) or True)
        engine.step(frame(1.0, four()))
        engine.step(frame(1.02, four(scale=1.45)))
        out = engine.step(frame(1.04, []))
        self.assertEqual(len(calls), 1)
        self.assertTrue(out.overview_at_start)

    def test_disabled_gesture_never_fires(self):
        config = apple_config()
        engine = Engine(config, 1.0, 1.0, PAD_BOUNDS)
        # four_finger_up keeps provider=niri and enabled=false.
        engine.step(frame(1.0, [(25, 30), (40, 30), (55, 30), (40, 44)]))
        engine.step(frame(1.02, [(25, 4), (40, 4), (55, 4), (40, 18)]))
        out = engine.step(frame(1.04, []))
        self.assertEqual([f.gesture for f in out.fires], [])


if __name__ == "__main__":
    unittest.main()
