"""Niri IPC, optional injection, and user-command action dispatch.

Only daemon mode constructs ActionDispatcher.  monitor/replay are guaranteed
to have no executable side effects.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import ActionConfig, Config
from . import niri_dynamic


class NiriIPCError(RuntimeError):
    pass


class NiriIPC:
    """One newline-delimited JSON Request/Reply per connection."""

    def __init__(self, config: Config, connect: Callable[[str], socket.socket] | None = None,
                 timeout_s: float | None = None) -> None:
        self.socket_env = config.niri["socket_env"]
        self.timeout = (timeout_s if timeout_s is not None
                        else config.niri["timeout_ms"] / 1000.0)
        self._connector = connect or self._default_connect

    @staticmethod
    def _default_connect(path: str) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
        return sock

    @property
    def socket_path(self) -> str | None:
        return os.environ.get(self.socket_env)

    def request(self, payload: dict[str, Any] | str, *, socket_path: str | None = None) -> dict[str, Any]:
        path = socket_path or self.socket_path
        if not path:
            raise NiriIPCError(f"environment variable {self.socket_env} is not set")
        if not Path(path).exists():
            raise NiriIPCError(f"Niri IPC socket does not exist: {path}")
        # A Python string argument denotes a unit Request variant such as
        # Version; it must be JSON-encoded to the bare string `"Version"`.
        line = json.dumps(payload, separators=(",", ":"))
        with self._connector(path) as sock:
            sock.settimeout(self.timeout)
            sock.sendall((line + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
            if not data.strip():
                raise NiriIPCError("empty IPC reply")
            reply = json.loads(data.decode("utf-8").splitlines()[0])
        if reply == "Handled":
            return {"Ok": "Handled"}
        if not isinstance(reply, dict):
            raise NiriIPCError(f"unexpected IPC reply: {reply!r}")
        if "Err" in reply:
            raise NiriIPCError(f"Niri returned error: {reply['Err']!r}")
        return reply

    def version(self) -> dict[str, Any]:
        # Niri 26.04 accepts the unit variant as a bare JSON string.
        return self.request("Version")

    def overview_open(self) -> bool | None:
        """Read-only overview state; None when the query fails."""
        try:
            reply = self.request("OverviewState")
        except (NiriIPCError, OSError, ValueError):
            return None
        body = reply.get("Ok")
        if isinstance(body, dict) and "OverviewState" in body:
            return bool(body["OverviewState"].get("is_open"))
        return None

    def spawn(self, argv: list[str]) -> dict[str, Any]:
        return self.request({"Action": {"Spawn": {"command": argv}}})

    def spawn_sh(self, command: str) -> dict[str, Any]:
        return self.request({"Action": {"SpawnSh": {"command": command}}})

    def action(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request(payload)


@dataclass(frozen=True)
class DispatchResult:
    gesture: str
    executed: bool
    detail: str
    action_type: str
    direction: str | None = None
    provider: str = "daemon"


class ActionDispatcher:
    def __init__(self, config: Config, ipc: NiriIPC | None = None,
                 runner: Callable[..., subprocess.Popen] | None = None,
                 logger: logging.Logger | None = None,
                 injector: Any | None = None) -> None:
        self.config = config
        self.ipc = ipc or NiriIPC(config)
        self.runner = runner or subprocess.Popen
        self.log = logger or logging.getLogger("elan_gesture.actions")
        self._injector = injector
        self._last: dict[str, float] = {}

    # -- lookup ----------------------------------------------------------

    def _resolve(self, gesture: str) -> tuple[ActionConfig | None, str]:
        spec = self.config.gestures.get(gesture)
        if spec is not None:
            return spec.action, spec.provider
        return self.config.actions.get(gesture), "daemon"

    @property
    def injector(self):
        if self._injector is None:
            from .inject import Injector
            self._injector = Injector()
        return self._injector

    # -- dispatch --------------------------------------------------------

    def dispatch(self, gesture: str, *, direction: str | None = None,
                 context: dict[str, Any] | None = None,
                 now: float | None = None, force: bool = False) -> DispatchResult:
        action, provider = self._resolve(gesture)
        if action is None:
            raise ValueError(f"unknown gesture {gesture!r}")
        if direction is None:
            direction = gesture

        if provider == "niri":
            return DispatchResult(gesture, False, "handled_by_niri", action.type,
                                  direction, provider)
        if provider == "auto" and (context or {}).get("overview_at_start") is True:
            return DispatchResult(gesture, False, "niri_overview_busy", action.type,
                                  direction, provider)
        if not action.enabled or action.type == "noop":
            return DispatchResult(gesture, False, f"disabled_or_noop:{action.type}",
                                  action.type, direction, provider)

        timestamp = time.monotonic() if now is None else now
        if not force:
            previous = self._last.get(gesture)
            cooldown = self.config.gesture.cooldown_ms / 1000.0
            if previous is not None and timestamp - previous < cooldown:
                return DispatchResult(gesture, False, "rate_limited", action.type,
                                      direction, provider)
        if self.config.dry_run:
            detail = f"dry_run:{json.dumps(self._describe(action), ensure_ascii=False)}"
            self.log.info("would execute %s: %s", gesture, detail)
            self._last[gesture] = timestamp
            return DispatchResult(gesture, False, detail, action.type, direction, provider)
        try:
            detail = self._run(action)
        except Exception as exc:  # daemon must survive a failing user action
            self.log.error("action %s failed: %s", gesture, exc)
            return DispatchResult(gesture, False, f"error:{type(exc).__name__}:{exc}",
                                  action.type, direction, provider)
        self._last[gesture] = timestamp
        self.log.info("executed %s: %s", gesture, detail)
        return DispatchResult(gesture, True, detail, action.type, direction, provider)

    @staticmethod
    def _describe(action: ActionConfig) -> dict[str, Any]:
        return {key: getattr(action, key) for key in
                ("type", "request_json", "argv", "command", "shell", "keys",
                 "handler", "scroll_direction", "scroll_amount")}

    def _run(self, action: ActionConfig) -> str:
        if action.type == "niri_action":
            payload = json.loads(action.request_json)
            reply = self.ipc.action(payload)
            return "niri_action:" + json.dumps(reply, separators=(",", ":"))
        if action.type == "niri_spawn":
            reply = self.ipc.spawn(list(action.argv))
            return "niri_spawn:" + json.dumps(reply, separators=(",", ":"))
        if action.type == "niri_spawn_sh":
            reply = self.ipc.spawn_sh(action.command)
            return "niri_spawn_sh:" + json.dumps(reply, separators=(",", ":"))
        if action.type == "niri_dynamic":
            return "niri_dynamic:" + niri_dynamic.run(action.handler, self.ipc)
        if action.type == "inject":
            if action.keys:
                return self.injector.key(list(action.keys))
            return self.injector.scroll(action.scroll_direction, action.scroll_amount or 1)
        if action.type == "command":
            if action.shell:
                argv: list[str] | str = action.command
                shell = True
            else:
                argv = list(action.argv)
                shell = False
            proc = self.runner(argv, shell=shell, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
            return f"command:pid={proc.pid}:argv={shlex.join(list(action.argv)) if not shell else action.command}"
        raise ValueError(f"unsupported action type {action.type!r}")
