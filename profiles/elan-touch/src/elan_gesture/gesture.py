"""Asymmetric three-finger gesture recognizer.

Only the unique moving finger is allowed to translate; the two static fingers
must remain individually and pairwise stable.  Tracking IDs define identity.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any

from evdev import ecodes

from .config import GestureConfig
from .mt import Contact, MTFrame

DIRECTIONS = ("up", "down", "left", "right")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclasses.dataclass(frozen=True)
class Decision:
    state: str
    contacts: int
    direction: str | None = None
    confidence: float = 0.0
    reason: str = ""
    static_ids: tuple[int, ...] = ()
    mover_id: int | None = None
    delta_x_mm: float = 0.0
    delta_y_mm: float = 0.0
    static_drift_mm: float = 0.0
    elapsed_ms: float = 0.0
    fire: bool = False
    candidate: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["confidence"] = round(self.confidence, 3)
        for key in ("delta_x_mm", "delta_y_mm", "static_drift_mm", "elapsed_ms"):
            data[key] = round(data[key], 2)
        data["static_ids"] = list(self.static_ids)
        return data


class GestureDetector:
    """IDLE -> SETTLING -> WATCHING -> MOVING -> ARMED -> COOLDOWN -> IDLE."""

    def __init__(self, config: GestureConfig, scale_x: float = 1.0, scale_y: float = 1.0,
                 bounds: tuple[float, float, float, float] | None = None) -> None:
        if scale_x <= 0 or scale_y <= 0:
            raise ValueError("coordinate scale must be positive")
        self.c = config
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.bounds = bounds  # x_min_mm, y_min_mm, x_max_mm, y_max_mm
        self.state = "IDLE"
        self._starts: dict[int, tuple[float, float]] = {}
        self._origins: dict[int, tuple[float, float]] = {}
        self._ids: frozenset[int] = frozenset()
        self._settle_since = 0.0
        self._session_since = 0.0
        self._mover: int | None = None
        self._mover_since = 0.0
        self._direction: str | None = None
        self._direction_since = 0.0
        self._best: Decision | None = None
        self._armed = False
        self._cooldown_until = 0.0
        self._candidate_seq = 0
        self._candidate_name: str | None = None

    @property
    def best_decision(self) -> Decision | None:
        return self._best

    def _mm(self, contact: Contact) -> tuple[float, float]:
        return contact.x / self.scale_x, contact.y / self.scale_y

    def _reset_candidate(self, state: str = "IDLE", reason: str = "") -> Decision:
        self.state = state
        self._starts.clear()
        self._origins.clear()
        self._ids = frozenset()
        self._mover = None
        self._direction = None
        self._best = None
        self._armed = False
        self._candidate_name = None
        return Decision(state=state, contacts=0, reason=reason)

    def reset(self) -> None:
        """Drop any in-flight candidate without recording a cooldown."""
        self._reset_candidate("IDLE", "reset")

    def _cancel(self, frame: MTFrame, reason: str, *, cooldown: bool = True) -> Decision:
        if cooldown:
            self._cooldown_until = frame.timestamp + self.c.cooldown_ms / 1000.0
        return self._reset_candidate("COOLDOWN" if cooldown else "IDLE", reason)

    @staticmethod
    def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _edge_or_palm(self, frame: MTFrame) -> bool:
        if self.c.palm_major > 0:
            for contact in frame.contacts.values():
                if contact.touch_major >= self.c.palm_major:
                    return True
        if self.bounds and self.c.edge_margin_mm > 0:
            xmin, ymin, xmax, ymax = self.bounds
            margin = self.c.edge_margin_mm
            for contact in frame.contacts.values():
                x, y = self._mm(contact)
                if x < xmin + margin or y < ymin + margin or x > xmax - margin or y > ymax - margin:
                    return True
        return False

    def update(self, frame: MTFrame) -> Decision:
        n = frame.contact_count
        tool_count = frame.tool_count()
        if frame.dropped or frame.timestamp < self._cooldown_until:
            return self._cancel(frame, "syn_dropped_or_resync" if frame.dropped else "cooldown")
        if any(frame.buttons.get(code) for code in (ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE)):
            return self._cancel(frame, "physical_button")
        if (tool_count is not None and tool_count > self.c.exact_contacts) or n > self.c.exact_contacts:
            return self._cancel(frame, "too_many_contacts")
        if self._edge_or_palm(frame):
            return self._cancel(frame, "palm_or_edge")
        ids = frozenset(frame.contacts)
        if self.state == "IDLE" or self.state == "COOLDOWN":
            if n == 0:
                if frame.timestamp >= self._cooldown_until:
                    self.state = "IDLE"
                return Decision(state=self.state, contacts=0, reason="no_contacts")
            if n != self.c.exact_contacts:
                return Decision(state=self.state, contacts=n,
                                reason=f"expected_{self.c.exact_contacts}_contacts")
            self._candidate_seq += 1
            self._candidate_name = f"c{self._candidate_seq}"
            self._ids = ids
            self._starts = {tid: self._mm(frame.contacts[tid]) for tid in ids}
            self._origins = dict(self._starts)
            self._settle_since = frame.timestamp
            self._session_since = frame.timestamp
            self._mover = None
            self._mover_since = 0.0
            self._direction = None
            self._direction_since = 0.0
            self._best = None
            self._armed = False
            self.state = "SETTLING"
            return Decision(state="SETTLING", contacts=n, static_ids=tuple(sorted(ids)),
                            reason="candidate_started", candidate=self._candidate_name)
        if tool_count is not None and tool_count > self.c.exact_contacts:
            return self._cancel(frame, "tool_count_changed")
        if ids != self._ids:
            return self._cancel(frame, "tracking_ids_changed")
        if n != self.c.exact_contacts:
            return self._cancel(frame, "contact_count_changed")
        elapsed_session = (frame.timestamp - self._session_since) * 1000.0
        if elapsed_session > self.c.session_timeout_ms:
            return self._cancel(frame, "session_timeout")

        deltas = {tid: (
            self._mm(frame.contacts[tid])[0] - self._starts[tid][0],
            self._mm(frame.contacts[tid])[1] - self._starts[tid][1],
        ) for tid in ids}
        magnitudes = {tid: math.hypot(*delta) for tid, delta in deltas.items()}
        if self.state == "SETTLING":
            settle_ms = (frame.timestamp - self._settle_since) * 1000.0
            if max(magnitudes.values()) > self.c.static_max_mm:
                return self._cancel(frame, "settle_movement")
            if settle_ms < self.c.settle_ms:
                return Decision(state="SETTLING", contacts=n, reason="settling",
                                elapsed_ms=settle_ms, static_ids=tuple(sorted(ids)),
                                candidate=self._candidate_name)
            self.state = "WATCHING"
            return Decision(state="WATCHING", contacts=n, reason="settled",
                            elapsed_ms=settle_ms, static_ids=tuple(sorted(ids)),
                            candidate=self._candidate_name)

        movers = [tid for tid, value in magnitudes.items() if value > self.c.static_max_mm]
        if len(movers) != 1:
            reason = "no_unique_mover" if not movers else "multiple_movers"
            return self._cancel(frame, reason)
        mover = movers[0]
        static_ids = tuple(sorted(set(ids) - {mover}))
        static_drift = max(magnitudes[tid] for tid in static_ids)
        if static_drift > self.c.static_max_mm:
            return self._cancel(frame, "static_finger_moved")
        now_pair = self._dist(self._mm(frame.contacts[static_ids[0]]),
                              self._mm(frame.contacts[static_ids[1]]))
        start_pair = self._dist(self._starts[static_ids[0]], self._starts[static_ids[1]])
        pair_change = abs(now_pair - start_pair)
        if pair_change > self.c.static_pair_mm:
            return self._cancel(frame, "static_pair_separation_changed")
        if self._mover is None:
            self._mover = mover
            self._mover_since = frame.timestamp
            self.state = "MOVING"
        elif self._mover != mover:
            return self._cancel(frame, "mover_identity_changed")
        move_ms = (frame.timestamp - self._mover_since) * 1000.0
        if move_ms > self.c.move_timeout_ms:
            return self._cancel(frame, "move_timeout")

        dx, dy = deltas[mover]
        if self.c.invert_x:
            dx = -dx
        if self.c.invert_y:
            dy = -dy
        abs_x, abs_y = abs(dx), abs(dy)
        main = max(abs_x, abs_y)
        orth = min(abs_x, abs_y)
        net = math.hypot(dx, dy)
        direction = ("left" if dx < 0 else "right") if abs_x >= abs_y else ("up" if dy < 0 else "down")
        ratio = orth / main if main > 0 else 1.0
        confidence = (
            0.40 * _clamp(net / self.c.move_min_mm)
            + 0.25 * (1.0 - _clamp(ratio))
            + 0.25 * (1.0 - _clamp(static_drift / self.c.static_max_mm))
            + 0.10 * (1.0 - _clamp(elapsed_session / self.c.move_timeout_ms))
        )
        metrics = dict(contacts=n, direction=direction, confidence=confidence,
                       static_ids=static_ids, mover_id=mover,
                       delta_x_mm=dx, delta_y_mm=dy,
                       static_drift_mm=static_drift, elapsed_ms=move_ms,
                       candidate=self._candidate_name)
        qualified = (
            net >= self.c.move_min_mm
            and main >= self.c.axis_min_mm
            and ratio <= self.c.max_orthogonal_ratio
            and confidence >= self.c.min_confidence
        )
        if not qualified:
            self._direction = None
            self._direction_since = 0.0
            self._best = None
            return Decision(state="MOVING", reason="below_threshold", **metrics)
        if direction != self._direction:
            self._direction = direction
            self._direction_since = frame.timestamp
        hold_ms = (frame.timestamp - self._direction_since) * 1000.0
        if hold_ms < self.c.direction_hold_ms:
            return Decision(state="MOVING", reason="direction_stabilizing", **metrics)
        if self._best is None or confidence > self._best.confidence:
            self._best = Decision(state="ARMED", reason="gesture_qualified", fire=False, **metrics)
        self.state = "ARMED"
        if self.c.trigger_on == "threshold" and not self._armed:
            self._armed = True
            self._cooldown_until = frame.timestamp + self.c.cooldown_ms / 1000.0
            result = dataclasses.replace(self._best, fire=True, reason="threshold_trigger")
            self._best = None
            return result
        return dataclasses.replace(self._best, reason="armed_awaiting_release")

    def finish(self, frame: MTFrame) -> Decision | None:
        """Called when contacts end/recede; fires one armed release gesture."""
        if self.state != "ARMED" or self._best is None:
            return None
        result = dataclasses.replace(self._best, fire=True, reason="release_trigger")
        self._reset_candidate("COOLDOWN", "gesture_consumed")
        self._cooldown_until = frame.timestamp + self.c.cooldown_ms / 1000.0
        return result


def confidence_formula(net: float, move_min: float, orth_ratio: float,
                       static_drift: float, static_max: float,
                       elapsed_ms: float, move_timeout_ms: float) -> float:
    """Expose the documented confidence formula for unit tests."""
    return (0.40 * _clamp(net / move_min)
            + 0.25 * (1.0 - _clamp(orth_ratio))
            + 0.25 * (1.0 - _clamp(static_drift / static_max))
            + 0.10 * (1.0 - _clamp(elapsed_ms / move_timeout_ms)))
