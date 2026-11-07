import unittest
from evdev import ecodes

from elan_gesture.mt import MTParser, RawEvent, frames_from_events


def raw(t, typ, code, value):
    return RawEvent(t, typ, code, value)


def put(slot, tid, x, y, t=1.0):
    return [
        raw(t, ecodes.EV_ABS, ecodes.ABS_MT_SLOT, slot),
        raw(t, ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, tid),
        raw(t, ecodes.EV_ABS, ecodes.ABS_MT_POSITION_X, x),
        raw(t, ecodes.EV_ABS, ecodes.ABS_MT_POSITION_Y, y),
    ]


def syn(t=1.0):
    return raw(t, ecodes.EV_SYN, ecodes.SYN_REPORT, 0)


class MTParserTest(unittest.TestCase):
    def test_tracking_id_is_identity_not_slot(self):
        events = put(0, 11, 100, 100) + put(1, 22, 200, 200) + [syn()]
        frame = next(frames_from_events(events))
        self.assertEqual(set(frame.contacts), {11, 22})
        self.assertEqual(frame.contacts[11].slot, 0)
        self.assertEqual(frame.contacts[22].slot, 1)
        self.assertEqual(frame.contact_count, 2)

    def test_slot_reuse_with_new_tracking_id(self):
        events = put(0, 11, 100, 100, 1.0) + [syn(1.0)]
        events += [raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_SLOT, 0),
                   raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, -1),
                   raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, 77),
                   raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_POSITION_X, 120),
                   raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_POSITION_Y, 130), syn(1.1)]
        frames = list(frames_from_events(events))
        self.assertEqual([set(f.contacts) for f in frames], [{11}, {77}])
        self.assertEqual(frames[-1].contacts[77].x, 120)

    def test_release_removes_contact(self):
        p = MTParser()
        events = put(0, 11, 100, 100) + put(1, 22, 200, 200) + [
            raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_SLOT, 1),
            raw(1.1, ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, -1), syn(1.1)]
        frames = [p.feed(e) for e in events]
        self.assertIsNone(frames[-2])
        self.assertEqual(set(frames[-1].contacts), {11})

    def test_syn_dropped_clears_and_marks_frame(self):
        p = MTParser()
        p.feed(put(0, 11, 100, 100)[0])
        dropped = p.feed(raw(2.0, ecodes.EV_SYN, ecodes.SYN_DROPPED, 0))
        self.assertTrue(dropped.dropped)
        self.assertEqual(dropped.contact_count, 0)
        self.assertTrue(p.need_resync)
        p.acknowledge_resync()
        self.assertFalse(p.need_resync)

    def test_tool_count_prefers_highest_flag(self):
        f = next(frames_from_events([raw(1, ecodes.EV_KEY, ecodes.BTN_TOOL_TRIPLETAP, 1),
                                     raw(1, ecodes.EV_KEY, ecodes.BTN_TOOL_QUADTAP, 1), syn()]))
        self.assertEqual(f.tool_count(), 4)

    def test_json_roundtrip(self):
        e = raw(1762400000.123456, 3, 53, 100)
        obj = e.to_json()
        back = RawEvent.from_json(obj)
        self.assertEqual(back.type, 3)
        self.assertEqual(back.code, 53)
        self.assertEqual(back.value, 100)
        self.assertAlmostEqual(back.timestamp, 1762400000.123456, places=5)


if __name__ == "__main__":
    unittest.main()
