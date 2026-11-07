import dataclasses
import tempfile
import unittest
from pathlib import Path

from elan_gesture.config import ConfigError, default_config, load_config

ROOT = Path(__file__).parent.parent


class ConfigTest(unittest.TestCase):
    def test_bundled_configs_load(self):
        for rel in ("config/default.toml", "config/examples/four-directions.toml"):
            with self.subTest(config=rel):
                c = load_config(ROOT / rel)
                self.assertEqual(set(c.actions), {"up", "down", "left", "right"})
                self.assertEqual(c.gesture.trigger_on, "release")

    def test_four_direction_example_defines_four_distinct_actions(self):
        c = load_config(ROOT / "config/examples/four-directions.toml")
        types = [c.actions[d].type for d in ("up", "down", "left", "right")]
        self.assertEqual(types, ["niri_action", "niri_spawn_sh", "niri_spawn", "command"])
        self.assertTrue(all(c.actions[d].enabled for d in c.actions))

    def test_bad_trigger_and_bad_json_fail(self):
        cases = [
            '[gesture]\ntrigger_on = "invalid"\n',
            '[actions.up]\nenabled = true\ntype = "niri_action"\nrequest_json = "not-json"\n',
            '[gesture]\nstatic_max_mm = -1\n',
            '[general]\nlog_format = "xml"\n',
        ]
        for i, text in enumerate(cases):
            with self.subTest(case=i), tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
                fh.write(text)
                name = fh.name
            try:
                with self.assertRaises(ConfigError):
                    load_config(name)
            finally:
                Path(name).unlink()

    def test_dry_run_dataclass_is_immutable_and_replaceable(self):
        c = default_config()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.general = {}
        c2 = dataclasses.replace(c, general={**c.general, "dry_run": True})
        self.assertTrue(c2.dry_run)
        self.assertFalse(c.dry_run)

    def test_unknown_key_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write('[gesture]\nunknown_knob = 1\n')
            name = fh.name
        try:
            with self.assertRaises(ConfigError):
                load_config(name)
        finally:
            Path(name).unlink()


class AppleGestureConfigTest(unittest.TestCase):
    def test_apple_profile_enables_daemon_gestures(self):
        c = load_config(ROOT / "config/examples/apple-trackpad.toml")
        enabled = sorted(n for n, g in c.gestures.items() if g.enabled)
        self.assertEqual(enabled, ["four_finger_down", "four_finger_left",
                                   "four_finger_right", "three_finger_tap",
                                   "thumb_spread_open", "thumb_spread_pinch",
                                   "two_finger_edge_left"])
        self.assertEqual(c.gestures["four_finger_up"].provider, "niri")
        self.assertEqual(c.gestures["four_finger_down"].provider, "auto")
        self.assertEqual(c.gestures["two_finger_edge_left"].edge, "right")

    def test_default_config_disables_every_apple_gesture(self):
        c = default_config()
        self.assertEqual(len(c.gestures), 8)
        self.assertFalse(any(g.enabled for g in c.gestures.values()))

    def test_legacy_config_still_loads_unchanged(self):
        c = load_config(ROOT / "config/examples/four-directions.toml")
        self.assertEqual(sorted(c.actions), ["down", "left", "right", "up"])
        self.assertFalse(any(g.enabled for g in c.gestures.values()))

    def test_unknown_gesture_name_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write('[gestures.five_finger_tap]\nenabled = true\n')
            name = fh.name
        try:
            with self.assertRaises(ConfigError):
                load_config(name)
        finally:
            Path(name).unlink()

    def test_bad_new_action_types_are_rejected(self):
        cases = [
            '[gestures.three_finger_tap]\nenabled = true\ntype = "inject"\n',
            '[gestures.three_finger_tap]\nenabled = true\ntype = "niri_dynamic"\nhandler = "nope"\n',
            '[gestures.three_finger_tap]\nprovider = "somebody"\n',
            '[gestures.three_finger_tap]\nfinger_count = 9\n',
            '[gesture]\ntap_max_ms = 5\n',
            '[gesture]\nspread_ratio_min = 0\n',
        ]
        for i, text in enumerate(cases):
            with self.subTest(case=i), tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
                fh.write(text)
                name = fh.name
            try:
                with self.assertRaises(ConfigError):
                    load_config(name)
            finally:
                Path(name).unlink()

    def test_valid_inject_and_dynamic_actions_load(self):
        text = (
            '[gestures.three_finger_tap]\nenabled = true\ntype = "inject"\nkeys = ["ctrl", "c"]\n'
            '[gestures.thumb_spread_open]\nenabled = true\ntype = "niri_dynamic"\nhandler = "show-desktop"\n'
        )
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(text)
            name = fh.name
        try:
            c = load_config(name)
            self.assertEqual(c.gestures["three_finger_tap"].action.keys, ("ctrl", "c"))
            self.assertEqual(c.gestures["thumb_spread_open"].action.handler, "show-desktop")
        finally:
            Path(name).unlink()


if __name__ == "__main__":
    unittest.main()
