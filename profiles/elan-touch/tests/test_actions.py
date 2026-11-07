import dataclasses
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from elan_gesture.actions import ActionDispatcher, DispatchResult, NiriIPC, NiriIPCError
from elan_gesture.config import ConfigError, default_config, load_config

ROOT = Path(__file__).parent.parent


class FakeSocket:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.timeout = None

    def __enter__(self): return self
    def __exit__(self, *args): return False
    def settimeout(self, value): self.timeout = value
    def sendall(self, data): self.sent.append(data)
    def recv(self, _size):
        return self.replies.pop(0) if self.replies else b""


class ActionTest(unittest.TestCase):
    def _config(self, *, dry_run=False):
        c = load_config(ROOT / "config/examples/four-directions.toml")
        if dry_run:
            import dataclasses
            c = dataclasses.replace(c, general={**c.general, "dry_run": True})
        return c

    def test_ipc_version_and_spawn_json(self):
        fake = FakeSocket([b'{"Ok":{"Version":"26.04"}}\n', b'"Handled"\n', b'"Handled"\n'])
        c = self._config()
        with tempfile.TemporaryDirectory() as tmp:
            sock_path = str(Path(tmp) / "niri.sock")
            Path(sock_path).touch()
            os.environ["NIRI_SOCKET"] = sock_path
            ipc = NiriIPC(c, connect=lambda _path: fake)
            self.assertEqual(ipc.version(), {"Ok": {"Version": "26.04"}})
            ipc.spawn(["true"])
            ipc.spawn_sh("true")
            self.assertEqual(fake.sent[0].decode().strip(), '"Version"')
            self.assertEqual(json.loads(fake.sent[1].decode()),
                             {"Action": {"Spawn": {"command": ["true"]}}})
            self.assertEqual(json.loads(fake.sent[2].decode()),
                             {"Action": {"SpawnSh": {"command": "true"}}})

    def test_ipc_error_reply_raises(self):
        fake = FakeSocket([b'{"Err":"bad action"}\n'])
        c = self._config()
        with tempfile.TemporaryDirectory() as tmp:
            sock_path = str(Path(tmp) / "niri.sock")
            Path(sock_path).touch()
            os.environ["NIRI_SOCKET"] = sock_path
            ipc = NiriIPC(c, connect=lambda _path: fake)
            with self.assertRaises(NiriIPCError):
                ipc.version()

    def test_dry_run_never_starts_process_or_connects(self):
        calls = []
        c = self._config(dry_run=True)

        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("runner must not be called in dry_run")

        dispatcher = ActionDispatcher(c, runner=forbidden)
        result = dispatcher.dispatch("right", now=100.0)
        self.assertFalse(result.executed)
        self.assertIn("dry_run", result.detail)
        self.assertEqual(calls, [])

    def test_command_action_uses_argv_no_shell(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(pid=4242)

        c = self._config()
        dispatcher = ActionDispatcher(c, runner=runner)
        result = dispatcher.dispatch("right", now=100.0, force=True)
        self.assertTrue(result.executed)
        self.assertEqual(calls[0][0], ["playerctl", "next"])
        self.assertFalse(calls[0][1]["shell"])

    def test_rate_limit(self):
        calls = []
        c = self._config()
        d = ActionDispatcher(c, runner=lambda argv, **kw: (calls.append(argv), SimpleNamespace(pid=1))[1])
        first = d.dispatch("right", now=10.0)
        second = d.dispatch("right", now=10.1)
        self.assertTrue(first.executed)
        self.assertEqual(second.detail, "rate_limited")

    def test_disabled_action_is_noop(self):
        c = default_config()
        d = ActionDispatcher(c, runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
        result = d.dispatch("up")
        self.assertFalse(result.executed)
        self.assertEqual(result.action_type, "noop")


class FakeIPC:
    """Minimal stand-in for NiriIPC in dynamic-action tests."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.sent = []

    def request(self, payload):
        self.sent.append(payload)
        return self.replies.pop(0) if self.replies else {"Ok": "Handled"}


class GestureDispatchTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config/examples/apple-trackpad.toml")

    def test_provider_niri_never_dispatches(self):
        d = ActionDispatcher(self.config, ipc=FakeIPC())
        result = d.dispatch("four_finger_up")
        self.assertFalse(result.executed)
        self.assertEqual(result.detail, "handled_by_niri")
        self.assertEqual(result.provider, "niri")

    def test_auto_provider_yields_to_open_overview(self):
        d = ActionDispatcher(self.config, ipc=FakeIPC())
        result = d.dispatch("four_finger_down", context={"overview_at_start": True})
        self.assertFalse(result.executed)
        self.assertEqual(result.detail, "niri_overview_busy")

    def test_auto_provider_runs_when_overview_closed(self):
        ipc = FakeIPC([{"Ok": {"Windows": [
            {"id": 5, "app_id": "foot", "is_focused": True},
            {"id": 6, "app_id": "foot", "is_focused": False}]}}])
        d = ActionDispatcher(self.config, ipc=ipc)
        result = d.dispatch("four_finger_down",
                            context={"overview_at_start": False}, force=True)
        self.assertTrue(result.executed)
        self.assertIn("app-expose", result.detail)
        self.assertEqual(ipc.sent[-1], {"Action": {"FocusWindow": {"id": 6}}})

    def test_show_desktop_jumps_to_empty_workspace(self):
        ipc = FakeIPC([{"Ok": {"Workspaces": [
            {"id": 1, "idx": 1, "output": "eDP-1", "is_focused": True,
             "active_window_id": 56},
            {"id": 2, "idx": 2, "output": "eDP-1", "is_focused": False,
             "active_window_id": None}]}}])
        d = ActionDispatcher(self.config, ipc=ipc)
        result = d.dispatch("thumb_spread_open", force=True)
        self.assertTrue(result.executed)
        self.assertIn("focus-workspace:2", result.detail)
        self.assertEqual(ipc.sent[-1],
                         {"Action": {"FocusWorkspace": {"reference": {"Index": 2}}}})

    def test_inject_action_uses_injector(self):
        calls = []

        class FakeInjector:
            def key(self, combo):
                calls.append(list(combo))
                return "inject_key:" + "+".join(combo)

            def scroll(self, direction, amount=1):
                calls.append([direction, amount])
                return f"inject_wheel:{direction}x{amount}"

        spec = self.config.gestures["three_finger_tap"]
        action = dataclasses.replace(spec.action, type="inject", keys=("ctrl", "c"))
        config = dataclasses.replace(self.config,
                                     gestures={**self.config.gestures,
                                               "three_finger_tap": dataclasses.replace(spec, action=action)})
        d = ActionDispatcher(config, ipc=FakeIPC(), injector=FakeInjector())
        result = d.dispatch("three_finger_tap", force=True)
        self.assertTrue(result.executed)
        self.assertEqual(calls, [["ctrl", "c"]])

    def test_dry_run_blocks_injection(self):
        spec = self.config.gestures["three_finger_tap"]
        action = dataclasses.replace(spec.action, type="inject", keys=("ctrl", "c"))
        config = dataclasses.replace(
            self.config, general={**self.config.general, "dry_run": True},
            gestures={**self.config.gestures,
                      "three_finger_tap": dataclasses.replace(spec, action=action)})
        d = ActionDispatcher(config, ipc=FakeIPC(),
                             injector=SimpleNamespace(key=lambda combo: (_ for _ in ()).throw(
                                 AssertionError("must not inject in dry_run"))))
        result = d.dispatch("three_finger_tap", force=True)
        self.assertFalse(result.executed)
        self.assertIn("dry_run", result.detail)


if __name__ == "__main__":
    unittest.main()
