import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from elan_gesture.inject import InjectError, Injector, resolve_keycode


class KeycodeTest(unittest.TestCase):
    def test_known_and_unknown(self):
        self.assertEqual(resolve_keycode("ctrl"), 29)
        self.assertEqual(resolve_keycode("C"), 46)
        with self.assertRaises(InjectError):
            resolve_keycode("nope")


class TokenTest(unittest.TestCase):
    def test_modifiers_press_order_and_reverse_release(self):
        inj = Injector(socket_path="/nonexistent")
        tokens = inj.key_tokens(["ctrl", "shift", "c"])
        self.assertEqual(tokens, ["29:1", "42:1", "46:1", "46:0", "42:0", "29:0"])

    def test_empty_and_modifier_only_rejected(self):
        inj = Injector(socket_path="/nonexistent")
        with self.assertRaises(InjectError):
            inj.key_tokens([])
        with self.assertRaises(InjectError):
            inj.key_tokens(["ctrl"])


class AvailabilityTest(unittest.TestCase):
    def test_missing_socket_is_unavailable(self):
        inj = Injector(socket_path="/nonexistent/socket", ydotool="/usr/bin/ydotool")
        self.assertFalse(inj.available())

    def test_missing_binary_is_unavailable(self):
        inj = Injector(socket_path="/tmp", ydotool="")
        self.assertFalse(inj.available())

    def test_key_invokes_runner_with_expected_argv(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.NamedTemporaryFile() as fh:
            inj = Injector(socket_path=fh.name, runner=runner, ydotool="ydotool")
            self.assertTrue(inj.available())
            detail = inj.key(["ctrl", "c"])
        self.assertEqual(calls[0], ["ydotool", "key", "29:1", "46:1", "46:0", "29:0"])
        self.assertEqual(detail, "inject_key:ctrl+c")

    def test_failed_injection_raises(self):
        def runner(argv, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        with tempfile.NamedTemporaryFile() as fh:
            inj = Injector(socket_path=fh.name, runner=runner, ydotool="ydotool")
            with self.assertRaises(InjectError):
                inj.key(["ctrl", "c"])


if __name__ == "__main__":
    unittest.main()
