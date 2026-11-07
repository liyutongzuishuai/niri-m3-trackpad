"""Multi-finger tap recognizer (Apple: three-finger tap = Look Up).

A tap is a short, nearly motionless contact of exactly ``finger_count``
fingers.  Fingers do not land simultaneously, so the clock starts at the first
non-zero frame and the count must reach the target before everything lifts.
"""
from __future__ import annotations

from .mt import MTFrame
from .types import Detection

IDLE = "IDLE"
DOWN = "DOWN"


class TapRecognizer:
    """Fires once per short multi-finger tap."""

    def __init__(self, gesture: str, finger_count: int, *, scale_x: float = 1.0,
                 scale_y: float = 1.0, tap_max_ms: float = 220.0,
                 tap_max_mm: float = 2.5, cooldown_ms: float = 350.0) -> None:
        if finger_count < 2:
            raise ValueError("tap finger_count must be >= 2")
        if scale_x <= 0 or scale_y <= 0:
            raise ValueError("coordinate scale must be positive")
        self.gesture = gesture
        self.finger_count = finger_count
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.tap_max_ms = tap_max_ms
        self.tap_max_mm = tap_max_mm
        self.cooldown_ms = cooldown_ms
        self.state = IDLE
        self._started_at = 0.0
        self._origins: dict[int, tuple[float, float]] = {}
        self._reached = False
        self._invalid = ""
        self._max_travel = 0.0

    def _mm(self, x: int, y: int) -> tuple[float, float]:
        return x / self.scale_x, y / self.scale_y

    def reset(self, now: float = 0.0) -> None:
        self.state = IDLE
        self._started_at = now
        self._origins.clear()
        self._reached = False
        self._invalid = ""
        self._max_travel = 0.0

    def _reject(self, reason: str) -> Detection:
        self.reset()
        return Detection(gesture=self.gesture, state=IDLE, reason=reason)

    def update(self, frame: MTFrame) -> Detection | None:
        n = frame.contact_count
        if n == 0:
            if self.state != DOWN:
                return Detection(gesture=self.gesture, state=IDLE, reason="no_contacts")
            duration_ms = (frame.timestamp - self._started_at) * 1000.0
            invalid = self._invalid
            reached = self._reached
            travel = self._max_travel
            self.reset(frame.timestamp)
            if invalid:
                return Detection(gesture=self.gesture, state=IDLE, reason=invalid,
                                 contacts=0)
            if not reached:
                return Detection(gesture=self.gesture, state=IDLE,
                                 reason=f"expected_{self.finger_count}_contacts")
            if duration_ms > self.tap_max_ms:
                return Detection(gesture=self.gesture, state=IDLE, reason="tap_too_slow",
                                 detail={"duration_ms": round(duration_ms, 1)})
            confidence = max(0.0, min(1.0,
                                      (1.0 - duration_ms / self.tap_max_ms) * 0.5
                                      + (1.0 - travel / self.tap_max_mm) * 0.5))
            return Detection(gesture=self.gesture, state="TAP", reason="tap_release",
                             confidence=confidence, contacts=self.finger_count,
                             fire=True,
                             detail={"duration_ms": round(duration_ms, 1),
                                     "max_travel_mm": round(travel, 2)})

        if self.state == IDLE:
            self.state = DOWN
            self._started_at = frame.timestamp
            self._origins.clear()
            self._reached = False
            self._invalid = ""
            self._max_travel = 0.0

        if n > self.finger_count and not self._invalid:
            self._invalid = "too_many_contacts"
        if n == self.finger_count:
            self._reached = True

        for tid, contact in frame.contacts.items():
            point = self._mm(contact.x, contact.y)
            origin = self._origins.get(tid)
            if origin is None:
                self._origins[tid] = point
                continue
            travel = ((point[0] - origin[0]) ** 2 + (point[1] - origin[1]) ** 2) ** 0.5
            if travel > self._max_travel:
                self._max_travel = travel
            if travel > self.tap_max_mm and not self._invalid:
                self._invalid = "tap_moved"

        duration_ms = (frame.timestamp - self._started_at) * 1000.0
        if duration_ms > self.tap_max_ms and not self._invalid:
            self._invalid = "tap_too_slow"

        return Detection(gesture=self.gesture, state=self.state,
                         reason=self._invalid or "tap_tracking", contacts=n,
                         detail={"duration_ms": round(duration_ms, 1),
                                 "max_travel_mm": round(self._max_travel, 2)})
