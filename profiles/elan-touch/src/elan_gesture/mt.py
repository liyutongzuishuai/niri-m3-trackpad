"""Kernel MT type-B event assembly.

A slot is only an address for subsequent ABS_MT_* writes.  Finger identity is
ABS_MT_TRACKING_ID; slot numbers are deliberately never exposed as identities.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Iterable

from evdev import ecodes


@dataclasses.dataclass(frozen=True)
class Contact:
    tracking_id: int
    slot: int
    x: int
    y: int
    pressure: int = 0
    touch_major: int = 0
    touch_minor: int = 0


@dataclasses.dataclass(frozen=True)
class MTFrame:
    timestamp: float
    contacts: dict[int, Contact]
    tool_flags: dict[int, bool]
    buttons: dict[int, bool]
    dropped: bool = False

    @property
    def contact_count(self) -> int:
        return len(self.contacts)

    def tool_count(self) -> int | None:
        """Infer contact count from BTN_TOOL_* when present, else None."""
        mapping = (
            (ecodes.BTN_TOOL_QUINTTAP, 5),
            (ecodes.BTN_TOOL_QUADTAP, 4),
            (ecodes.BTN_TOOL_TRIPLETAP, 3),
            (ecodes.BTN_TOOL_DOUBLETAP, 2),
            (ecodes.BTN_TOOL_FINGER, 1),
        )
        for code, count in mapping:
            if self.tool_flags.get(code):
                return count
        return None


@dataclasses.dataclass
class RawEvent:
    timestamp: float
    type: int
    code: int
    value: int

    @classmethod
    def from_evdev(cls, event: Any) -> "RawEvent":
        return cls(float(event.sec) + float(event.usec) / 1_000_000.0,
                   int(event.type), int(event.code), int(event.value))

    @classmethod
    def from_json(cls, obj: dict[str, Any]) -> "RawEvent":
        # Accept timestamp, sec/usec pairs, and legacy ev_* names.
        if "timestamp" in obj:
            timestamp = float(obj["timestamp"])
        elif "sec" in obj or "usec" in obj:
            timestamp = float(obj.get("sec", 0)) + float(obj.get("usec", 0)) / 1_000_000.0
        else:
            timestamp = 0.0
        typ = obj.get("type", obj.get("ev_type"))
        code = obj.get("code", obj.get("ev_code"))
        value = obj.get("value", obj.get("ev_value"))
        if typ is None or code is None or value is None:
            raise ValueError(f"incomplete raw event: {obj!r}")
        return cls(timestamp, int(typ), int(code), int(value))

    def to_json(self) -> dict[str, Any]:
        sec = int(self.timestamp)
        usec = int(round((self.timestamp - sec) * 1_000_000))
        return {"sec": sec, "usec": usec, "type": self.type,
                "code": self.code, "value": self.value}

    def evdev_tuple(self) -> tuple[int, int, int, int, int]:
        sec = int(self.timestamp)
        usec = int(round((self.timestamp - sec) * 1_000_000))
        return (sec, usec, self.type, self.code, self.value)


class MTParser:
    """Consumes raw input events and emits one atomic frame per SYN_REPORT."""

    def __init__(self) -> None:
        self._slot = 0
        # _live and _draft are keyed by slot for protocol assembly; the public
        # MTFrame.contacts mapping is rebuilt keyed by tracking ID.
        self._live: dict[int, Contact] = {}
        self._draft: dict[int, dict[str, Any]] = {}
        self._tool_flags: dict[int, bool] = {}
        self._buttons: dict[int, bool] = {}
        self._frame_tool_flags: dict[int, bool] = {}
        self._frame_buttons: dict[int, bool] = {}
        self._timestamp = 0.0
        self._dropped = False
        self._need_resync = False

    @property
    def need_resync(self) -> bool:
        return self._need_resync

    def acknowledge_resync(self) -> None:
        self._need_resync = False
        self._dropped = False

    def feed(self, event: RawEvent) -> MTFrame | None:
        self._timestamp = event.timestamp
        if event.type == ecodes.EV_SYN:
            if event.code == ecodes.SYN_DROPPED:
                self.reset()
                self._dropped = True
                self._need_resync = True
                return MTFrame(event.timestamp, {}, dict(self._frame_tool_flags),
                               dict(self._frame_buttons), dropped=True)
            if event.code == ecodes.SYN_REPORT:
                if self._dropped:
                    return None
                contacts = {contact.tracking_id: contact
                            for contact in self._live.values()}
                frame = MTFrame(event.timestamp, contacts,
                                dict(self._frame_tool_flags), dict(self._frame_buttons))
                self._frame_tool_flags = dict(self._tool_flags)
                self._frame_buttons = dict(self._buttons)
                return frame
            return None
        if self._dropped or self._need_resync:
            return None
        if event.type == ecodes.EV_ABS:
            self._abs(event)
        elif event.type == ecodes.EV_KEY:
            self._key(event)
        return None

    def _abs(self, event: RawEvent) -> None:
        if event.code == ecodes.ABS_MT_SLOT:
            self._slot = max(0, int(event.value))
            return
        entry = self._draft.setdefault(self._slot, {
            "tracking_id": -1, "x": 0, "y": 0,
            "pressure": 0, "touch_major": 0, "touch_minor": 0,
        })
        if event.code == ecodes.ABS_MT_TRACKING_ID:
            tid = int(event.value)
            entry["tracking_id"] = tid
            if tid < 0:
                self._draft.pop(self._slot, None)
                self._live.pop(self._slot, None)
            else:
                self._live[self._slot] = Contact(
                    tracking_id=tid, slot=self._slot,
                    x=int(entry["x"]), y=int(entry["y"]),
                    pressure=int(entry["pressure"]),
                    touch_major=int(entry["touch_major"]),
                    touch_minor=int(entry["touch_minor"]),
                )
            return
        if entry.get("tracking_id", -1) < 0:
            return
        field = {
            ecodes.ABS_MT_POSITION_X: "x",
            ecodes.ABS_MT_POSITION_Y: "y",
            ecodes.ABS_MT_PRESSURE: "pressure",
            ecodes.ABS_MT_TOUCH_MAJOR: "touch_major",
            ecodes.ABS_MT_TOUCH_MINOR: "touch_minor",
        }.get(event.code)
        if field is None:
            return
        entry[field] = int(event.value)
        live = self._live.get(self._slot)
        if live is not None:
            self._live[self._slot] = dataclasses.replace(live, **{field: int(event.value)})

    def _key(self, event: RawEvent) -> None:
        pressed = bool(event.value)
        if event.code in {
            ecodes.BTN_TOOL_FINGER, ecodes.BTN_TOOL_DOUBLETAP,
            ecodes.BTN_TOOL_TRIPLETAP, ecodes.BTN_TOOL_QUADTAP,
            ecodes.BTN_TOOL_QUINTTAP, ecodes.BTN_TOUCH,
        }:
            self._tool_flags[event.code] = pressed
            self._frame_tool_flags[event.code] = pressed
        elif event.code in {ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE}:
            self._buttons[event.code] = pressed
            self._frame_buttons[event.code] = pressed

    def reset(self) -> None:
        self._slot = 0
        self._live.clear()
        self._draft.clear()
        self._tool_flags.clear()
        self._buttons.clear()
        self._frame_tool_flags.clear()
        self._frame_buttons.clear()
        self._dropped = False
        self._need_resync = False


def frames_from_events(events: Iterable[RawEvent]) -> Iterable[MTFrame]:
    parser = MTParser()
    for event in events:
        frame = parser.feed(event)
        if frame is not None:
            yield frame
        if parser.need_resync:
            parser.acknowledge_resync()
