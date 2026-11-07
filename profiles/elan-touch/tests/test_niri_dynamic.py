import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from elan_gesture import niri_dynamic as nd


class ConfigResolverTest(unittest.TestCase):
    def test_resolves_control_sh_from_waybar_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            scripts = base / "waybar-m3/scripts"
            scripts.mkdir(parents=True)
            script = scripts / "control.sh"
            script.write_text("#!/bin/sh\n")
            script.chmod(0o755)
            cfg = base / "waybar/config.jsonc"
            cfg.parent.mkdir(parents=True)
            cfg.write_text('"custom/panel": {\n'
                           '"on-click": "' + str(script) + ' open"\n}\n')
            with (mock.patch.object(nd, "WAYBAR_CONFIGS", (cfg,)),
                  mock.patch.object(nd, "CONTROL_SCRIPT", script)):
                self.assertEqual(nd.control_center_command(), [str(script), "open"])

    def test_falls_back_to_default_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "control.sh"
            script.write_text("#!/bin/sh\n")
            script.chmod(0o755)
            with (mock.patch.object(nd, "WAYBAR_CONFIGS", ()),
                  mock.patch.object(nd, "CONTROL_SCRIPT", script)):
                self.assertEqual(nd.control_center_command(), [str(script), "open"])

    def test_returns_none_when_nothing_usable(self):
        with (mock.patch.object(nd, "WAYBAR_CONFIGS", ()),
              mock.patch.object(nd, "CONTROL_SCRIPT", Path("/nonexistent/control.sh"))):
            self.assertIsNone(nd.control_center_command())


class NotifyCentreToggleTest(unittest.TestCase):
    def test_first_call_opens_detached(self):
        with (mock.patch.object(nd, "control_center_command",
                                return_value=["/bin/true", "open"]),
              mock.patch.object(nd, "control_center_pid", return_value=None),
              mock.patch.object(nd, "clear_stale_control_center_pidfile"),
              mock.patch.object(nd, "_spawn", return_value="pid=1") as spawn):
            self.assertEqual(nd.notify_center(), "notify-center:opened")
            spawn.assert_called_once_with(["/bin/true", "open"])

    def test_second_call_closes_and_clears_pidfile(self):
        fake_pid = os.getpid()  # alive, but we only assert the signals target
        with (mock.patch.object(nd, "control_center_command",
                                return_value=["/bin/true", "open"]),
              mock.patch.object(nd, "control_center_pid", return_value=fake_pid),
              mock.patch.object(nd.os, "kill") as kill,
              mock.patch.object(nd, "clear_stale_control_center_pidfile") as clear,
              mock.patch.object(nd.time, "sleep")):
            self.assertEqual(nd.notify_center(), "notify-center:closed")
            kill.assert_any_call(fake_pid, 15)
            clear.assert_called_once_with()

    def test_falls_back_to_notification_when_no_config(self):
        with (mock.patch.object(nd, "control_center_command", return_value=None),
              mock.patch.object(nd, "swaync_running", return_value=False),
              mock.patch.object(nd, "_spawn", return_value="pid=2") as spawn):
            self.assertEqual(nd.notify_center(), "notify-center:unavailable")
            self.assertEqual(spawn.call_args[0][0][0], "notify-send")


class ShowDesktopTest(unittest.TestCase):
    def _ipc(self, workspaces):
        class IPC:
            def __init__(self):
                self.sent = []

            def request(self, payload):
                self.sent.append(payload)
                if payload == "Workspaces":
                    return {"Ok": {"Workspaces": workspaces}}
                return {"Ok": "Handled"}
        return IPC()

    def test_jumps_to_empty_workspace(self):
        ipc = self._ipc([
            {"id": 1, "idx": 1, "output": "eDP-1", "is_focused": True,
             "active_window_id": 56},
            {"id": 2, "idx": 2, "output": "eDP-1", "is_focused": False,
             "active_window_id": None}])
        self.assertEqual(nd.show_desktop(ipc), "show-desktop:focus-workspace:2")
        self.assertEqual(ipc.sent[-1],
                         {"Action": {"FocusWorkspace": {"reference": {"Index": 2}}}})

    def test_comes_back_when_empty_workspace_focused(self):
        ipc = self._ipc([
            {"id": 2, "idx": 2, "output": "eDP-1", "is_focused": True,
             "active_window_id": None}])
        self.assertEqual(nd.show_desktop(ipc), "show-desktop:focus-workspace-previous")
        self.assertEqual(ipc.sent[-1], {"Action": {"FocusWorkspacePrevious": {}}})


class AppExposeTest(unittest.TestCase):
    def test_cycles_same_app_window(self):
        class IPC:
            def __init__(self):
                self.sent = []

            def request(self, payload):
                self.sent.append(payload)
                if payload == "Windows":
                    return {"Ok": {"Windows": [
                        {"id": 5, "app_id": "foot", "is_focused": True},
                        {"id": 6, "app_id": "foot", "is_focused": False},
                        {"id": 7, "app_id": "zen", "is_focused": False}]}}
                return {"Ok": "Handled"}
        ipc = IPC()
        self.assertEqual(nd.app_expose(ipc), "app-expose:focus-window:6")
        self.assertEqual(ipc.sent[-1], {"Action": {"FocusWindow": {"id": 6}}})


if __name__ == "__main__":
    unittest.main()
