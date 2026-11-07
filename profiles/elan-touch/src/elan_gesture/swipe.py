"""Whole-hand multi-finger swipe recognizer (Apple: four-finger swipes).

All contacts must travel together in one direction.  A spread or pinch moves
the contacts apart/together instead, so the pairwise-distance drift and the
centroid travel are both checked: that keeps this recognizer from claiming a
thumb-spread gesture.
"""
from __future__ import annotations

import math

from .mt import MTFrame
from .types import Detection

IDLE = "IDLE"
TRACKING = "TRACKING"

DIRECTIONS = ("up", "down", "left", "right")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class SwipeRecognizer:
    """Fires once when ``finger_count`` fingers translate together."""

    def __init__(self, finger_count: int, *, scale_x: float = 1.0, scale_y: float = 1.0,
                 swipe_min_mm: float = 18.0, swipe_axis_ratio: float = 0.35,
                 swipe_angle_tolerance_deg: float = 25.0,
                 spread_ratio_min: float = 0.18,
                 finger_change_timeout_ms: float = 800.0) -> None:
        if finger_count < 3:
            raise ValueError("swipe finger_count must be >= 3")
        if scale_x <= 0 or scale_y <= 0:
            raise ValueError("coordinate scale must be positive")
        self.finger_count = finger_count
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.swipe_min_mm = swipe_min_mm
        self.swipe_axis_ratio = swipe_axis_ratio
        self.swipe_angle_tolerance_deg = swipe_angle_tolerance_deg
        self.spread_ratio_min = spread_ratio_min
        self.finger_change_timeout_ms = finger_change_timeout_ms
        self.state = IDLE
        self._origins: dict[int, tuple[float, float]] = {}
        self._started_at = 0.0
        self._spread0 = 0.0
        self._last: dict[str, float] | None = None

    def _mm(self, x: int, y: int) -> tuple[float, float]:
        return x / self.scale_x, y / self.scale_y

    def reset(self, now: float = 0.0) -> None:
        self.state = IDLE
        self._origins.clear()
        self._started_at = now
        self._spread0 = 0.0
        self._last = None

    @staticmethod
    def _mean_pairwise(points: list[tuple[float, float]]) -> float:
        if len(points) < 2:
            return 0.0
        total = 0.0
        count = 0
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                total += math.hypot(points[i][0] - points[j][0],
                                    points[i][1] - points[j][1])
                count += 1
        return total / count if count else 0.0

    def update(self, frame: MTFrame) -> Detection | None:
        n = frame.contact_count
        if n == 0:
            if self.state != TRACKING or self._last is None:
                self.reset(frame.timestamp)
                return Detection(gesture="", state=IDLE, reason="no_contacts")
            last = dict(self._last)
            self.reset(frame.timestamp)
            if last["net"] < self.swipe_min_mm:
                return Detection(gesture="", state=IDLE, reason="swipe_too_short",
                                 detail={"net_mm": round(last["net"], 2)})
            if last["ratio"] > self.swipe_axis_ratio:
                return Detection(gesture="", state=IDLE, reason="swipe_too_diagonal",
                                 detail={"ratio": round(last["ratio"], 3)})
            if last["angle"] > self.swipe_angle_tolerance_deg:
                return Detection(gesture="", state=IDLE, reason="swipe_not_parallel",
                                 detail={"max_angle_deg": round(last["angle"], 1)})
            if last["spread"] > self.spread_ratio_min:
                return Detection(gesture="", state=IDLE, reason="swipe_looks_like_spread",
                                 detail={"spread_ratio": round(last["spread"], 3)})
            detail = {k: round(v, 3) for k, v in last.items()
                      if k not in ("direction", "confidence")}
            return Detection(gesture="", state="SWIPE", reason="swipe_release",
                             direction=last["direction"], confidence=last["confidence"],
                             contacts=self.finger_count, fire=True, detail=detail)

        if n != self.finger_count:
            if self.state == TRACKING and n < self.finger_count:
                # A finger lifted early; keep tracking the survivors.
                return Detection(gesture="", state=TRACKING, reason="partial_contacts",
                                 contacts=n)
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="wrong_finger_count",
                             contacts=n)

        if self.state == IDLE:
            self.state = TRACKING
            self._started_at = frame.timestamp
            self._origins = {tid: self._mm(c.x, c.y) for tid, c in frame.contacts.items()}
            self._spread0 = self._mean_pairwise(list(self._origins.values()))
            return Detection(gesture="", state=TRACKING, reason="swipe_started",
                             contacts=n)

        elapsed_ms = (frame.timestamp - self._started_at) * 1000.0
        if elapsed_ms > self.finger_change_timeout_ms:
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="swipe_timeout",
                             contacts=n)

        deltas: list[tuple[float, float]] = []
        points: list[tuple[float, float]] = []
        for tid, contact in frame.contacts.items():
            origin = self._origins.get(tid)
            if origin is None:
                continue
            here = self._mm(contact.x, contact.y)
            points.append(here)
            deltas.append((here[0] - origin[0], here[1] - origin[1]))
        if not deltas:
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="tracking_lost", contacts=n)

        cx = sum(d[0] for d in deltas) / len(deltas)
        cy = sum(d[1] for d in deltas) / len(deltas)
        net = math.hypot(cx, cy)
        main = max(abs(cx), abs(cy))
        orth = min(abs(cx), abs(cy))
        ratio = orth / main if main > 0 else 1.0
        direction = (("left" if cx < 0 else "right") if abs(cx) >= abs(cy)
                     else ("up" if cy < 0 else "down"))
        max_angle = 0.0
        for dx, dy in deltas:
            mag = math.hypot(dx, dy)
            if mag <= 0 or net <= 0:
                continue
            cos = (dx * cx + dy * cy) / (mag * net)
            angle = math.degrees(math.acos(_clamp(cos, -1.0, 1.0)))
            max_angle = max(max_angle, angle)
        spread_now = self._mean_pairwise(points)
        spread = (abs(spread_now - self._spread0) / self._spread0
                  if self._spread0 > 0 else 0.0)
        confidence = (0.5 * _clamp(net / self.swipe_min_mm)
                      + 0.3 * (1.0 - _clamp(ratio))
                      + 0.2 * (1.0 - _clamp(max_angle / max(self.swipe_angle_tolerance_deg, 1e-6))))
        self._last = {"direction": direction, "confidence": confidence, "net": net,
                      "ratio": ratio, "angle": max_angle, "spread": spread,
                      "elapsed_ms": elapsed_ms}
        return Detection(gesture="", state=TRACKING,
                         reason="swipe_tracking", direction=direction,
                         confidence=confidence, contacts=n,
                         detail={"net_mm": round(net, 2), "ratio": round(ratio, 3),
                                 "max_angle_deg": round(max_angle, 1),
                                 "spread_ratio": round(spread, 3)})
