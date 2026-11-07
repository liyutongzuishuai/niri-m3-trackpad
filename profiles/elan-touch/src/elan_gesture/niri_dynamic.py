"""State-aware Niri actions that a static JSON request cannot express.

Each handler performs read-only Niri IPC queries first, then issues exactly one
action request.  Nothing here shells out to ``niri msg``; the caller supplies an
object with a ``request(payload)`` method (normally ``actions.NiriIPC``).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Protocol


class IPC(Protocol):
    def request(self, payload: dict[str, Any] | str) -> dict[str, Any]: ...


class DynamicError(RuntimeError):
    pass


LOG = logging.getLogger("elan_gesture.niri_dynamic")

# The control centre is an independent GTK program, not a waybar module.
# Both "custom/panel" (the tune icon) and "battery" in the waybar config call
# control.sh on click.  We resolve the very same command from that config so a
# gesture is exactly equivalent to clicking the bar.
WAYBAR_CONFIGS = (
    Path.home() / ".config/waybar/config.jsonc",
    Path.home() / ".config/waybar-m3/config.jsonc",
)
CONTROL_SCRIPT = Path.home() / ".config/waybar-m3/scripts/control.sh"


def _ok(reply: dict[str, Any], key: str) -> Any:
    if "Err" in reply:
        raise DynamicError(f"niri error: {reply['Err']!r}")
    body = reply.get("Ok")
    if isinstance(body, dict) and key in body:
        return body[key]
    raise DynamicError(f"unexpected niri reply for {key}: {reply!r}")


def _proc_argv(skip_pid: int | None = None) -> list[list[str]]:
    """Return argv for every visible process except ourselves."""
    me = os.getpid() if skip_pid is None else skip_pid
    out: list[list[str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if raw:
            out.append([p.decode("utf-8", "replace") for p in raw.split(b"\0") if p])
    return out


def _basename(argv: list[str]) -> str:
    return os.path.basename(argv[0]) if argv else ""


def control_center_command() -> list[str] | None:
    """Return the argv bound to waybar's control-centre button, if usable.

    waybar's ``custom/panel`` (tune icon) and ``battery`` modules both use
    ``on-click: ~/.config/waybar-m3/scripts/control.sh open``.  Reading that
    value out of the config means we reuse the exact click handler, regardless
    of whether waybar was started with ``-c`` or with its default config, and
    regardless of the process name (``waybar`` vs ``integrated-waybar``).

    ``control.sh`` itself checks for PyGObject/gtk-layer-shell and falls back to
    a fuzzel menu, so no capability probe is needed here.  The GTK control
    centre keeps a pidfile: invoking it again closes the open window.
    """
    import re
    import shlex

    pattern = re.compile(
        r'"on-click(?:-right|-middle)?"\s*:\s*"([^"]*control\.sh[^"]*)"')
    for cfg in WAYBAR_CONFIGS:
        try:
            text = cfg.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in pattern.finditer(text):
            try:
                argv = shlex.split(os.path.expanduser(match.group(1).strip()))
            except ValueError:
                continue
            if argv and Path(argv[0]).is_file() and os.access(argv[0], os.X_OK):
                return argv
    if CONTROL_SCRIPT.is_file() and os.access(CONTROL_SCRIPT, os.X_OK):
        return [str(CONTROL_SCRIPT), "open"]
    return None


def swaync_running() -> bool:
    return any(_basename(argv) == "swaync" for argv in _proc_argv())


def _run(argv: list[str], timeout: float = 3.0) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DynamicError(f"failed to run {argv[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise DynamicError(f"{argv[0]} exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout or '').strip()}")
    return "ok"


def _spawn(argv: list[str]) -> str:
    """Start a long-lived GUI process without blocking the gesture daemon.

    The GTK control centre (and its fuzzel fallback) stays open until the user
    dismisses it, so ``subprocess.run`` would time out and the daemon would
    never dispatch again.  ``start_new_session`` detaches it from the daemon.
    """
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as exc:
        raise DynamicError(f"failed to start {argv[0]}: {exc}") from exc
    return f"pid={proc.pid}"


def control_center_pidfile() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "waybar-m3-cc.pid"


def control_center_pid() -> int | None:
    """Return the live GTK control-centre PID, or None (incl. stale pidfile)."""
    pidfile = control_center_pidfile()
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None
    if b"controlcenter.py" not in cmdline:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def clear_stale_control_center_pidfile() -> None:
    try:
        control_center_pidfile().unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

def show_desktop(ipc: IPC) -> str:
    """Apple Show Desktop: jump to an empty workspace, or come back."""
    workspaces = _ok(ipc.request("Workspaces"), "Workspaces")
    focused = next((w for w in workspaces if w.get("is_focused")), None)
    if focused is None:
        raise DynamicError("no focused workspace")
    output = focused.get("output")
    if focused.get("active_window_id") is not None:
        empty = next((w for w in workspaces
                      if w.get("output") == output
                      and w.get("active_window_id") is None
                      and w.get("id") != focused.get("id")), None)
        if empty is not None:
            ipc.request({"Action": {"FocusWorkspace":
                                    {"reference": {"Index": int(empty["idx"])}}}})
            return f"show-desktop:focus-workspace:{empty['idx']}"
        ipc.request({"Action": {"FocusWorkspaceDown": {}}})
        return "show-desktop:focus-workspace-down"
    ipc.request({"Action": {"FocusWorkspacePrevious": {}}})
    return "show-desktop:focus-workspace-previous"


def app_expose(ipc: IPC) -> str:
    """Apple App Exposé: cycle windows of the focused app.

    Niri has no app-level window grid, so the closest honest equivalent is
    focusing the next window that shares the focused window's app_id.
    """
    windows = _ok(ipc.request("Windows"), "Windows")
    focused = next((w for w in windows if w.get("is_focused")), None)
    if focused is None:
        raise DynamicError("no focused window")
    same = [w for w in windows if w.get("app_id") == focused.get("app_id")]
    if len(same) < 2:
        return "app-expose:single-window"
    ordered = sorted(same, key=lambda w: int(w["id"]))
    ids = [int(w["id"]) for w in ordered]
    index = ids.index(int(focused["id"])) if int(focused["id"]) in ids else -1
    target = ids[(index + 1) % len(ids)]
    ipc.request({"Action": {"FocusWindow": {"id": target}}})
    return f"app-expose:focus-window:{target}"


def notify_center(ipc: IPC | None = None) -> str:
    """Apple Notification Centre -> the same command as waybar's tune button.

    The M3 waybar control centre is a standalone GTK window launched by
    ``control.sh``; it does not require the waybar process to be a particular
    build.  Invoking it twice toggles the window (pidfile in controlcenter.py),
    which matches the Apple gesture's open/close behaviour.  Falls back to
    swaync, then to a plain notification.
    """
    argv = control_center_command()
    if argv is not None:
        live = control_center_pid()
        if live is not None:
            # Same toggle a second waybar click performs: controlcenter.py
            # SIGTERMs its first instance.  Its ``finally`` cleanup does not run
            # on SIGTERM, so remove the stale pidfile ourselves; otherwise the
            # next gesture would think a window is still open.
            try:
                os.kill(live, 15)
            except OSError:
                pass
            for _ in range(10):
                time.sleep(0.05)
                try:
                    os.kill(live, 0)
                except OSError:
                    break
            clear_stale_control_center_pidfile()
            return "notify-center:closed"
        # No live window: drop any stale pidfile so controlcenter.py starts a
        # fresh one instead of trying to kill a dead PID.
        clear_stale_control_center_pidfile()
        _spawn(argv)
        return "notify-center:opened"
    if swaync_running():
        _run(["swaync-client", "-t"])
        return "notify-center:swaync"
    hint = "没有找到 waybar-m3 的 control.sh，且 swaync 未运行"
    _spawn(["notify-send", "-a", "elan-gesture", "通知中心", hint])
    return "notify-center:unavailable"


HANDLERS: dict[str, Callable[..., str]] = {
    "show-desktop": show_desktop,
    "app-expose": app_expose,
    "notify-center": notify_center,
}


def run(handler: str, ipc: IPC | None = None) -> str:
    if handler not in HANDLERS:
        raise DynamicError(f"unknown dynamic handler {handler!r}")
    return HANDLERS[handler](ipc)
