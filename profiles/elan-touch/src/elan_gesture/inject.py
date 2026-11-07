"""Optional input injection backend (ydotool for keys, evdev UInput for wheel).

Injection is deliberately narrow: key chords and vertical/horizontal wheel
ticks only.  Pointer motion and pointer clicks are never synthesised, so normal
mouse behaviour is untouched.  Callers must honour ``dry_run`` themselves; this
module is side-effect free until ``key()``/``scroll()`` is invoked.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

KEYCODES: dict[str, int] = {
    # modifiers
    "ctrl": 29, "leftctrl": 29, "alt": 56, "leftalt": 56, "shift": 42,
    "leftshift": 42, "super": 125, "meta": 125, "leftmeta": 125,
    # editing / navigation
    "esc": 1, "escape": 1, "tab": 15, "return": 28, "enter": 28, "space": 57,
    "backspace": 14, "delete": 111, "insert": 110,
    "left": 105, "right": 106, "up": 103, "down": 108,
    "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
    # letters
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    # digits
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10,
    "0": 11,
    # function keys
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
}

MODIFIER_ORDER = ("ctrl", "alt", "shift", "super")


class InjectError(RuntimeError):
    pass


def _default_socket() -> str:
    explicit = os.environ.get("YDOTOOL_SOCKET")
    if explicit:
        return explicit
    return f"/run/user/{os.getuid()}/.ydotool_socket"


def resolve_keycode(name: str) -> int:
    key = name.strip().lower()
    if key in KEYCODES:
        return KEYCODES[key]
    raise InjectError(f"unknown key name {name!r}; known: {sorted(KEYCODES)}")


class Injector:
    """Synthesises key chords through ydotool and wheel ticks through UInput."""

    def __init__(self, *, socket_path: str | None = None,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None,
                 ydotool: str | None = None, timeout_ms: int = 3000,
                 logger: logging.Logger | None = None) -> None:
        self.socket_path = socket_path or _default_socket()
        self.runner = runner or subprocess.run
        # None means auto-detect; an empty string explicitly disables keys.
        self.ydotool = (shutil.which("ydotool") or "") if ydotool is None else ydotool
        self.timeout = timeout_ms / 1000.0
        self.log = logger or logging.getLogger("elan_gesture.inject")
        self._wheel_device = None

    # -- availability ----------------------------------------------------

    def available(self) -> bool:
        if not self.ydotool:
            return False
        return Path(self.socket_path).exists()

    def wheel_available(self) -> bool:
        return Path("/dev/uinput").exists() and os.access("/dev/uinput", os.W_OK)

    # -- keys ------------------------------------------------------------

    def key_tokens(self, combo: Sequence[str]) -> list[str]:
        """Build ydotool key arguments: press modifiers, press key, release all."""
        if not combo:
            raise InjectError("empty key chord")
        modifiers = [k for k in combo if k.strip().lower() in MODIFIER_ORDER]
        ordinary = [k for k in combo if k.strip().lower() not in MODIFIER_ORDER]
        if not ordinary:
            raise InjectError("key chord needs at least one non-modifier key")
        mods = [resolve_keycode(m) for m in modifiers]
        keys = [resolve_keycode(k) for k in ordinary]
        tokens: list[str] = []
        for code in mods:
            tokens.append(f"{code}:1")
        for code in keys:
            tokens.append(f"{code}:1")
        for code in reversed(keys):
            tokens.append(f"{code}:0")
        for code in reversed(mods):
            tokens.append(f"{code}:0")
        return tokens

    def key(self, combo: Sequence[str]) -> str:
        if not self.available():
            raise InjectError(
                f"ydotool unavailable (binary={self.ydotool or 'missing'}, "
                f"socket={self.socket_path})")
        tokens = self.key_tokens(combo)
        argv = [self.ydotool, "key", *tokens]
        proc = self.runner(argv, capture_output=True, text=True,
                           timeout=self.timeout, check=False)
        if proc.returncode != 0:
            raise InjectError(f"ydotool key failed ({proc.returncode}): "
                              f"{(proc.stderr or '').strip()}")
        return "inject_key:" + "+".join(combo)

    # -- wheel -----------------------------------------------------------

    def scroll(self, direction: str, amount: int = 1) -> str:
        if direction not in {"up", "down", "left", "right"}:
            raise InjectError(f"invalid scroll direction {direction!r}")
        if amount <= 0:
            raise InjectError("scroll amount must be positive")
        if not self.wheel_available():
            raise InjectError("/dev/uinput is not writable; wheel injection unavailable")
        from evdev import UInput, ecodes
        if self._wheel_device is None:
            self._wheel_device = UInput({ecodes.EV_REL: [ecodes.REL_WHEEL,
                                                         ecodes.REL_HWHEEL]},
                                        name="elan-gesture-wheel")
        code = ecodes.REL_WHEEL if direction in {"up", "down"} else ecodes.REL_HWHEEL
        sign = 1 if direction in {"up", "right"} else -1
        self._wheel_device.write(ecodes.EV_REL, code, sign * amount)
        self._wheel_device.syn()
        return f"inject_wheel:{direction}x{amount}"

    def close(self) -> None:
        if self._wheel_device is not None:
            try:
                self._wheel_device.close()
            finally:
                self._wheel_device = None
