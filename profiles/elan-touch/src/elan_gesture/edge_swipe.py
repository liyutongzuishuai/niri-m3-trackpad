"""Edge-anchored two-finger swipe recognizer (Apple: notification centre).

Apple's gesture starts at the right edge of the pad and travels inward (to the
left).  Requiring an edge-anchored start is what separates it from an ordinary
two-finger horizontal scroll, which libinput still receives because the device
is never grabbed.
"""
from __future__ import annotations

import math

from .mt import MTFrame
from .types import Detection

IDLE = "IDLE"
TRACKING = "TRACKING"

# Which physical edge the swipe starts from -> the direction it travels inward.
INWARD = {"right": "left", "left": "right", "bottom": "up", "top": "down"}


class EdgeSwipeRecognizer:
    """Fires once on a two-finger swipe that starts in an edge band."""

    def __init__(self, edge: str, *, finger_count: int = 2,
                 scale_x: float = 1.0, scale_y: float = 1.0,
                 edge_trigger_mm: float = 15.0, swipe_min_mm: float = 18.0,
                 finger_change_timeout_ms: float = 800.0,
                 bounds: tuple[float, float, float, float] | None = None) -> None:
        if edge not in INWARD:
            raise ValueError(f"edge must be one of {sorted(INWARD)}")
        if scale_x <= 0 or scale_y <= 0:
            raise ValueError("coordinate scale must be positive")
        self.edge = edge
        self.finger_count = finger_count
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.edge_trigger_mm = edge_trigger_mm
        self.swipe_min_mm = max(swipe_min_mm, edge_trigger_mm)
        self.finger_change_timeout_ms = finger_change_timeout_ms
        self.bounds = bounds
        self.state = IDLE
        self._origin: tuple[float, float] | None = None
        self._started_at = 0.0
        self._last: dict[str, float | str] | None = None

    def _mm(self, x: int, y: int) -> tuple[float, float]:
        return x / self.scale_x, y / self.scale_y

    def _in_band(self, point: tuple[float, float]) -> bool:
        if self.bounds is None:
            return True
        xmin, ymin, xmax, ymax = self.bounds
        # A contact outside the advertised axis range is not a real touch, so it
        # can never start an edge gesture (guards synthetic/out-of-range data).
        if not (xmin - 1.0 <= point[0] <= xmax + 1.0
                and ymin - 1.0 <= point[1] <= ymax + 1.0):
            return False
        margin = self.edge_trigger_mm
        if self.edge == "right":
            return point[0] >= xmax - margin
        if self.edge == "left":
            return point[0] <= xmin + margin
        if self.edge == "bottom":
            return point[1] >= ymax - margin
        return point[1] <= ymin + margin

    def reset(self, now: float = 0.0) -> None:
        self.state = IDLE
        self._origin = None
        self._started_at = now
        self._last = None

    def update(self, frame: MTFrame) -> Detection | None:
        n = frame.contact_count
        if n == 0:
            if self.state != TRACKING or self._last is None or self._origin is None:
                self.reset(frame.timestamp)
                return Detection(gesture="", state=IDLE, reason="no_contacts")
            last = dict(self._last)
            self.reset(frame.timestamp)
            if last.get("rejected"):
                return Detection(gesture="", state=IDLE, reason=str(last["rejected"]),
                                 detail={"travel_mm": round(float(last["travel"]), 2)})
            if float(last["inward"]) < self.swipe_min_mm:
                return Detection(gesture="", state=IDLE, reason="edge_swipe_too_short",
                                 detail={"inward_mm": round(float(last["inward"]), 2)})
            if float(last["cross"]) > 0.6 * float(last["inward"]):
                return Detection(gesture="", state=IDLE, reason="edge_swipe_not_inward",
                                 detail={"inward_mm": round(float(last["inward"]), 2),
                                         "cross_mm": round(float(last["cross"]), 2)})
            return Detection(gesture="", state="EDGE_SWIPE", reason="edge_swipe_release",
                             direction=INWARD[self.edge],
                             confidence=float(last["confidence"]),
                             contacts=self.finger_count, fire=True,
                             detail={"travel_mm": round(float(last["travel"]), 2),
                                     "cross_mm": round(float(last["cross"]), 2),
                                     "edge": self.edge})

        if n != self.finger_count:
            if self.state == TRACKING and n < self.finger_count:
                return Detection(gesture="", state=TRACKING, reason="partial_contacts",
                                 contacts=n)
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="wrong_finger_count",
                             contacts=n)

        cx = sum(self._mm(c.x, c.y)[0] for c in frame.contacts.values()) / n
        cy = sum(self._mm(c.x, c.y)[1] for c in frame.contacts.values()) / n
        if self.state == IDLE:
            if not self._in_band((cx, cy)):
                return Detection(gesture="", state=IDLE, reason="not_from_edge",
                                 contacts=n)
            self.state = TRACKING
            self._origin = (cx, cy)
            self._started_at = frame.timestamp
            return Detection(gesture="", state=TRACKING, reason="edge_swipe_started",
                             contacts=n,
                             detail={"origin_x_mm": round(cx, 2),
                                     "origin_y_mm": round(cy, 2)})

        elapsed_ms = (frame.timestamp - self._started_at) * 1000.0
        if elapsed_ms > self.finger_change_timeout_ms:
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="edge_swipe_timeout",
                             contacts=n)

        assert self._origin is not None
        dx = cx - self._origin[0]
        dy = cy - self._origin[1]
        if self.edge in ("right", "left"):
            inward = -dx if self.edge == "right" else dx
            cross = abs(dy)
        else:
            inward = -dy if self.edge == "bottom" else dy
            cross = abs(dx)
        travel = math.hypot(dx, dy)
        rejected = ""
        if inward > 0 and cross > 0.6 * inward:
            rejected = "edge_swipe_not_inward"
        elif inward <= 0:
            rejected = "edge_swipe_not_inward"
        confidence = min(1.0, max(0.0, inward) / max(self.swipe_min_mm, 1e-6)) * \
            (1.0 if cross <= 0.5 * max(inward, 1e-6) else 0.5)
        self._last = {"travel": travel, "cross": cross, "inward": inward,
                      "confidence": confidence, "rejected": rejected}
        return Detection(gesture="", state=TRACKING, reason=rejected or "edge_swipe_tracking",
                         confidence=confidence, contacts=n,
                         detail={"inward_mm": round(inward, 2),
                                 "cross_mm": round(cross, 2)})
