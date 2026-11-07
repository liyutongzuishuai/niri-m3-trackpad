"""Strictly validated TOML configuration with fail-fast diagnostics."""
from __future__ import annotations

import copy
import dataclasses
import os
import tomllib
from pathlib import Path
from typing import Any

DIRECTIONS = ("up", "down", "left", "right")

# Command-style action types (dispatch one configured side effect).
ACTION_TYPES = {
    "noop",
    "niri_action",
    "niri_spawn",
    "niri_spawn_sh",
    "command",
    "inject",
    "niri_dynamic",
}
TRIGGER_MODES = {"release", "threshold"}

# Who owns a gesture.  "niri" means the compositor already handles it natively
# (three-finger workspace swipes, four-finger overview) and the daemon must
# only observe, never dispatch.
PROVIDERS = {"daemon", "niri", "auto"}

# Built-in state-aware handlers implemented in niri_dynamic.py.
DYNAMIC_HANDLERS = {"show-desktop", "app-expose", "notify-center"}

# Apple trackpad gestures that the daemon can own.  Anything niri or the
# focused application already provides is documented in docs/APPLE_GESTURES.md
# and deliberately absent here.
GESTURE_DEFAULTS: dict[str, dict[str, Any]] = {
    "three_finger_tap": {"finger_count": 3, "edge": "", "provider": "daemon"},
    "two_finger_edge_left": {"finger_count": 2, "edge": "right", "provider": "daemon"},
    "four_finger_up": {"finger_count": 4, "edge": "", "provider": "niri"},
    "four_finger_down": {"finger_count": 4, "edge": "", "provider": "auto"},
    "four_finger_left": {"finger_count": 4, "edge": "", "provider": "daemon"},
    "four_finger_right": {"finger_count": 4, "edge": "", "provider": "daemon"},
    "thumb_spread_open": {"finger_count": 4, "edge": "", "provider": "daemon"},
    "thumb_spread_pinch": {"finger_count": 4, "edge": "", "provider": "daemon"},
}
GESTURE_NAMES = tuple(GESTURE_DEFAULTS)

EDGE_VALUES = {"", "right", "left", "top", "bottom"}

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {"dry_run": False, "log_format": "text", "log_level": "INFO"},
    "device": {
        "match_name": "Elan Touchpad",
        "match_vendor": 0x04F3,
        "match_product": 0x002F,
        "path": "",
        "width_mm": 98.0,
        "height_mm": 60.0,
        "units_per_mm_x": 0.0,
        "units_per_mm_y": 0.0,
        "reconnect_initial_ms": 200,
        "reconnect_max_ms": 5000,
    },
    "gesture": {
        "exact_contacts": 3,
        "settle_ms": 100.0,
        "static_max_mm": 1.5,
        "static_pair_mm": 2.0,
        "move_min_mm": 8.0,
        "axis_min_mm": 6.0,
        "max_orthogonal_ratio": 0.45,
        "direction_hold_ms": 60.0,
        "move_timeout_ms": 700.0,
        "session_timeout_ms": 1500.0,
        "min_confidence": 0.65,
        "cooldown_ms": 350.0,
        "trigger_on": "release",
        "invert_x": False,
        "invert_y": False,
        "palm_major": 0,
        "edge_margin_mm": 0.0,
        # Multi-finger recognizer thresholds.
        "tap_max_ms": 220.0,
        "tap_max_mm": 2.5,
        "swipe_min_mm": 18.0,
        "swipe_axis_ratio": 0.35,
        "swipe_angle_tolerance_deg": 25.0,
        "spread_ratio_min": 0.18,
        "pinch_ratio_min": 0.18,
        "thumb_edge_mm": 12.0,
        "edge_trigger_mm": 15.0,
        "finger_change_timeout_ms": 800.0,
        "ipc_state_timeout_ms": 200.0,
    },
    "niri": {"socket_env": "NIRI_SOCKET", "timeout_ms": 1000},
    "actions": {
        d: {"enabled": False, "type": "noop", "description": f"{d} swipe",
            "request_json": "", "argv": [], "command": "", "shell": False,
            "command_timeout_ms": 3000, "keys": [], "handler": "",
            "scroll_direction": "", "scroll_amount": 0}
        for d in DIRECTIONS
    },
    "gestures": {
        name: {"enabled": False, "type": "noop", "description": name,
               "request_json": "", "argv": [], "command": "", "shell": False,
               "command_timeout_ms": 3000, "keys": [], "handler": "",
               "scroll_direction": "", "scroll_amount": 0, **spec}
        for name, spec in GESTURE_DEFAULTS.items()
    },
}

ACTION_KEYS = {"enabled", "type", "description", "request_json", "argv",
               "command", "shell", "command_timeout_ms", "keys", "handler",
               "scroll_direction", "scroll_amount"}
GESTURE_EXTRA_KEYS = {"provider", "finger_count", "edge"}


class ConfigError(ValueError):
    """Raised when a config file contains an invalid value."""


@dataclasses.dataclass(frozen=True)
class GestureConfig:
    exact_contacts: int
    settle_ms: float
    static_max_mm: float
    static_pair_mm: float
    move_min_mm: float
    axis_min_mm: float
    max_orthogonal_ratio: float
    direction_hold_ms: float
    move_timeout_ms: float
    session_timeout_ms: float
    min_confidence: float
    cooldown_ms: float
    trigger_on: str
    invert_x: bool
    invert_y: bool
    palm_major: int
    edge_margin_mm: float
    tap_max_ms: float = 220.0
    tap_max_mm: float = 2.5
    swipe_min_mm: float = 18.0
    swipe_axis_ratio: float = 0.35
    swipe_angle_tolerance_deg: float = 25.0
    spread_ratio_min: float = 0.18
    pinch_ratio_min: float = 0.18
    thumb_edge_mm: float = 12.0
    edge_trigger_mm: float = 15.0
    finger_change_timeout_ms: float = 800.0
    ipc_state_timeout_ms: float = 200.0


@dataclasses.dataclass(frozen=True)
class DeviceConfig:
    match_name: str
    match_vendor: int
    match_product: int
    path: str
    width_mm: float
    height_mm: float
    units_per_mm_x: float
    units_per_mm_y: float
    reconnect_initial_ms: int
    reconnect_max_ms: int


@dataclasses.dataclass(frozen=True)
class ActionConfig:
    enabled: bool
    type: str
    description: str = ""
    request_json: str = ""
    argv: tuple[str, ...] = ()
    command: str = ""
    shell: bool = False
    command_timeout_ms: int = 3000
    keys: tuple[str, ...] = ()
    handler: str = ""
    scroll_direction: str = ""
    scroll_amount: int = 0


@dataclasses.dataclass(frozen=True)
class GestureSpec:
    name: str
    provider: str
    finger_count: int
    edge: str
    action: ActionConfig

    @property
    def enabled(self) -> bool:
        return self.action.enabled and self.action.type != "noop"


@dataclasses.dataclass(frozen=True)
class Config:
    general: dict[str, Any]
    device: DeviceConfig
    gesture: GestureConfig
    niri: dict[str, Any]
    actions: dict[str, ActionConfig]
    gestures: dict[str, GestureSpec] = dataclasses.field(default_factory=dict)
    source: Path | None = None

    @property
    def dry_run(self) -> bool:
        return bool(self.general.get("dry_run", False))

    def disabled_gestures(self) -> dict[str, GestureSpec]:
        return {n: g for n, g in self.gestures.items() if g.provider != "daemon"}


def _merge(base: dict[str, Any], extra: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        where = f"{prefix}{key}"
        if prefix == "actions." and key in DIRECTIONS:
            if not isinstance(value, dict):
                raise ConfigError(f"{where} must be a table")
            out[key] = {**out[key], **copy.deepcopy(value)}
            continue
        if prefix == "gestures." and key in GESTURE_DEFAULTS:
            if not isinstance(value, dict):
                raise ConfigError(f"{where} must be a table")
            out[key] = {**out[key], **copy.deepcopy(value)}
            continue
        if key not in out:
            raise ConfigError(f"unknown config key: {where}")
        if isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value, where + ".")
        else:
            out[key] = value
    return out


def _number(section: str, key: str, value: Any, *, integer: bool = False,
            minimum: float | None = None, maximum: float | None = None) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{section}.{key} must be {'an integer' if integer else 'a number'}")
    if integer and not isinstance(value, int):
        raise ConfigError(f"{section}.{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{section}.{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{section}.{key} must be <= {maximum}")
    return int(value) if integer else float(value)


def _boolean(section: str, key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{section}.{key} must be true or false")
    return value


def _string(section: str, key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{section}.{key} must be a string")
    return value


def _string_list(section: str, key: str, value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(a, str) for a in value):
        raise ConfigError(f"{section}.{key} must be an array of strings")
    return tuple(value)


def _check_action(section: str, spec: dict[str, Any], allowed: set[str]) -> ActionConfig:
    unknown = set(spec) - allowed
    if unknown:
        raise ConfigError(f"{section} has unknown keys: {sorted(unknown)}")
    enabled = _boolean(section, "enabled", spec.get("enabled", False))
    atype = spec.get("type", "noop")
    if atype not in ACTION_TYPES:
        raise ConfigError(f"{section}.type must be one of {sorted(ACTION_TYPES)}")
    description = _string(section, "description", spec.get("description", ""))
    request_json = _string(section, "request_json", spec.get("request_json", ""))
    command = _string(section, "command", spec.get("command", ""))
    argv = _string_list(section, "argv", spec.get("argv", []))
    keys = _string_list(section, "keys", spec.get("keys", []))
    handler = _string(section, "handler", spec.get("handler", ""))
    scroll_direction = _string(section, "scroll_direction", spec.get("scroll_direction", ""))
    scroll_amount = _number(section, "scroll_amount", spec.get("scroll_amount", 0),
                            integer=True, minimum=0)
    shell = _boolean(section, "shell", spec.get("shell", False))
    timeout = _number(section, "command_timeout_ms", spec.get("command_timeout_ms", 3000),
                      integer=True, minimum=1)

    if atype == "niri_action":
        if not request_json.strip():
            raise ConfigError(f"{section}.request_json is required for niri_action")
        import json
        try:
            parsed = json.loads(request_json)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{section}.request_json invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ConfigError(f"{section}.request_json must be a JSON object")
    if atype in {"niri_spawn", "command"} and not argv and not shell:
        raise ConfigError(f"{section}.argv is required unless shell=true")
    if atype == "niri_spawn_sh" and not command.strip():
        raise ConfigError(f"{section}.command is required for niri_spawn_sh")
    if atype == "command" and shell and not command.strip():
        raise ConfigError(f"{section}.command is required when shell=true")
    if atype == "inject":
        if not keys and not scroll_direction:
            raise ConfigError(f"{section}.keys (or scroll_direction) is required for inject")
        if scroll_direction and scroll_direction not in {"up", "down", "left", "right"}:
            raise ConfigError(f"{section}.scroll_direction must be up, down, left or right")
        if scroll_direction and scroll_amount <= 0:
            raise ConfigError(f"{section}.scroll_amount must be > 0 when scroll_direction is set")
    if atype == "niri_dynamic":
        if handler not in DYNAMIC_HANDLERS:
            raise ConfigError(f"{section}.handler must be one of {sorted(DYNAMIC_HANDLERS)}")

    return ActionConfig(
        enabled=enabled, type=atype, description=description,
        request_json=request_json, argv=argv, command=command,
        shell=shell, command_timeout_ms=int(timeout), keys=keys, handler=handler,
        scroll_direction=scroll_direction, scroll_amount=int(scroll_amount),
    )


def _validate_actions(raw: dict[str, Any]) -> dict[str, ActionConfig]:
    result: dict[str, ActionConfig] = {}
    for direction in DIRECTIONS:
        spec = raw.get(direction, DEFAULT_CONFIG["actions"][direction])
        if not isinstance(spec, dict):
            raise ConfigError(f"actions.{direction} must be a table")
        result[direction] = _check_action(f"actions.{direction}", spec, ACTION_KEYS)
    return result


def _validate_gestures(raw: dict[str, Any]) -> dict[str, GestureSpec]:
    result: dict[str, GestureSpec] = {}
    for name in GESTURE_NAMES:
        spec = raw.get(name, DEFAULT_CONFIG["gestures"][name])
        if not isinstance(spec, dict):
            raise ConfigError(f"gestures.{name} must be a table")
        section = f"gestures.{name}"
        provider = _string(section, "provider", spec.get("provider", "daemon"))
        if provider not in PROVIDERS:
            raise ConfigError(f"{section}.provider must be one of {sorted(PROVIDERS)}")
        finger_count = _number(section, "finger_count", spec.get("finger_count", 3),
                               integer=True, minimum=2, maximum=4)
        edge = _string(section, "edge", spec.get("edge", ""))
        if edge not in EDGE_VALUES:
            raise ConfigError(f"{section}.edge must be one of {sorted(EDGE_VALUES)}")
        action = _check_action(section, spec, ACTION_KEYS | GESTURE_EXTRA_KEYS)
        result[name] = GestureSpec(name=name, provider=provider,
                                   finger_count=int(finger_count), edge=edge,
                                   action=action)
    return result


def _validate(data: dict[str, Any], source: Path | None) -> Config:
    merged = _merge(DEFAULT_CONFIG, data)
    g = merged["gesture"]
    d = merged["device"]
    n = merged["niri"]
    gen = merged["general"]
    for section, key, value in (
        ("device", "match_name", d["match_name"]),
        ("device", "path", d["path"]),
        ("general", "log_format", gen["log_format"]),
        ("general", "log_level", gen["log_level"]),
        ("niri", "socket_env", n["socket_env"]),
    ):
        if not isinstance(value, str):
            raise ConfigError(f"{section}.{key} must be a string")
    if gen["log_format"] not in {"text", "json"}:
        raise ConfigError("general.log_format must be text or json")
    if gen["log_level"] not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigError("general.log_level must be DEBUG, INFO, WARNING or ERROR")
    if g["trigger_on"] not in TRIGGER_MODES:
        raise ConfigError(f"gesture.trigger_on must be one of {sorted(TRIGGER_MODES)}")
    if n["timeout_ms"] <= 0:
        raise ConfigError("niri.timeout_ms must be positive")

    gesture = GestureConfig(
        exact_contacts=int(_number("gesture", "exact_contacts", g["exact_contacts"], integer=True, minimum=3, maximum=3)),
        settle_ms=float(_number("gesture", "settle_ms", g["settle_ms"], minimum=0)),
        static_max_mm=float(_number("gesture", "static_max_mm", g["static_max_mm"], minimum=0.1)),
        static_pair_mm=float(_number("gesture", "static_pair_mm", g["static_pair_mm"], minimum=0.1)),
        move_min_mm=float(_number("gesture", "move_min_mm", g["move_min_mm"], minimum=0.1)),
        axis_min_mm=float(_number("gesture", "axis_min_mm", g["axis_min_mm"], minimum=0.1)),
        max_orthogonal_ratio=float(_number("gesture", "max_orthogonal_ratio", g["max_orthogonal_ratio"], minimum=0, maximum=1)),
        direction_hold_ms=float(_number("gesture", "direction_hold_ms", g["direction_hold_ms"], minimum=0)),
        move_timeout_ms=float(_number("gesture", "move_timeout_ms", g["move_timeout_ms"], minimum=1)),
        session_timeout_ms=float(_number("gesture", "session_timeout_ms", g["session_timeout_ms"], minimum=1)),
        min_confidence=float(_number("gesture", "min_confidence", g["min_confidence"], minimum=0, maximum=1)),
        cooldown_ms=float(_number("gesture", "cooldown_ms", g["cooldown_ms"], minimum=0)),
        trigger_on=g["trigger_on"],
        invert_x=_boolean("gesture", "invert_x", g["invert_x"]),
        invert_y=_boolean("gesture", "invert_y", g["invert_y"]),
        palm_major=int(_number("gesture", "palm_major", g["palm_major"], integer=True, minimum=0)),
        edge_margin_mm=float(_number("gesture", "edge_margin_mm", g["edge_margin_mm"], minimum=0)),
        tap_max_ms=float(_number("gesture", "tap_max_ms", g["tap_max_ms"], minimum=20)),
        tap_max_mm=float(_number("gesture", "tap_max_mm", g["tap_max_mm"], minimum=0.1)),
        swipe_min_mm=float(_number("gesture", "swipe_min_mm", g["swipe_min_mm"], minimum=0.1)),
        swipe_axis_ratio=float(_number("gesture", "swipe_axis_ratio", g["swipe_axis_ratio"], minimum=0, maximum=1)),
        swipe_angle_tolerance_deg=float(_number("gesture", "swipe_angle_tolerance_deg", g["swipe_angle_tolerance_deg"], minimum=0, maximum=90)),
        spread_ratio_min=float(_number("gesture", "spread_ratio_min", g["spread_ratio_min"], minimum=0.01)),
        pinch_ratio_min=float(_number("gesture", "pinch_ratio_min", g["pinch_ratio_min"], minimum=0.01)),
        thumb_edge_mm=float(_number("gesture", "thumb_edge_mm", g["thumb_edge_mm"], minimum=0)),
        edge_trigger_mm=float(_number("gesture", "edge_trigger_mm", g["edge_trigger_mm"], minimum=0.1)),
        finger_change_timeout_ms=float(_number("gesture", "finger_change_timeout_ms", g["finger_change_timeout_ms"], minimum=1)),
        ipc_state_timeout_ms=float(_number("gesture", "ipc_state_timeout_ms", g["ipc_state_timeout_ms"], minimum=1)),
    )
    if gesture.axis_min_mm > gesture.move_min_mm:
        raise ConfigError("gesture.axis_min_mm must be <= gesture.move_min_mm")
    device = DeviceConfig(
        match_name=d["match_name"],
        match_vendor=int(_number("device", "match_vendor", d["match_vendor"], integer=True, minimum=0, maximum=0xFFFF)),
        match_product=int(_number("device", "match_product", d["match_product"], integer=True, minimum=0, maximum=0xFFFF)),
        path=d["path"],
        width_mm=float(_number("device", "width_mm", d["width_mm"], minimum=1)),
        height_mm=float(_number("device", "height_mm", d["height_mm"], minimum=1)),
        units_per_mm_x=float(_number("device", "units_per_mm_x", d["units_per_mm_x"], minimum=0)),
        units_per_mm_y=float(_number("device", "units_per_mm_y", d["units_per_mm_y"], minimum=0)),
        reconnect_initial_ms=int(_number("device", "reconnect_initial_ms", d["reconnect_initial_ms"], integer=True, minimum=10)),
        reconnect_max_ms=int(_number("device", "reconnect_max_ms", d["reconnect_max_ms"], integer=True, minimum=10)),
    )
    niri = {
        "socket_env": n["socket_env"],
        "timeout_ms": int(_number("niri", "timeout_ms", n["timeout_ms"], integer=True, minimum=1)),
    }
    return Config(
        general=copy.deepcopy(gen), device=device, gesture=gesture, niri=niri,
        actions=_validate_actions(merged["actions"]),
        gestures=_validate_gestures(merged["gestures"]),
        source=source,
    )


def default_config() -> Config:
    return _validate({}, None)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load a TOML file; no path means built-in defaults."""
    if path is None:
        return default_config()
    p = Path(path).expanduser()
    try:
        with p.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError(f"cannot read config {p}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{p} must contain TOML tables")
    return _validate(data, p)


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "elan-gesture" / "config.toml"
