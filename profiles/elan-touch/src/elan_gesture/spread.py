"""Thumb + three-finger spread/pinch recognizer.

Apple's "Show Desktop" and "Launchpad" gestures are a stationary thumb while
the other three fingers move apart or together.  The thumb is identified as the
contact whose mean distance to the other three is largest, with a bonus when it
sits near the bottom edge of the pad, because that is where a thumb rests.
"""
from __future__ import annotations

import math

from .mt import MTFrame
from .types import Detection

IDLE = "IDLE"
TRACKING = "TRACKING"

# A genuine thumb-plus-three layout has one clearly separated contact.
MIN_OUTLIER_RATIO = 1.25


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class SpreadRecognizer:
    """Fires once on a thumb-anchored spread or pinch."""

    def __init__(self, *, scale_x: float = 1.0, scale_y: float = 1.0,
                 spread_ratio_min: float = 0.18, pinch_ratio_min: float = 0.18,
                 thumb_edge_mm: float = 12.0, swipe_min_mm: float = 18.0,
                 finger_change_timeout_ms: float = 800.0,
                 bounds: tuple[float, float, float, float] | None = None) -> None:
        if scale_x <= 0 or scale_y <= 0:
            raise ValueError("coordinate scale must be positive")
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.spread_ratio_min = spread_ratio_min
        self.pinch_ratio_min = pinch_ratio_min
        self.thumb_edge_mm = thumb_edge_mm
        self.swipe_min_mm = swipe_min_mm
        self.finger_change_timeout_ms = finger_change_timeout_ms
        self.bounds = bounds
        self.state = IDLE
        self._origins: dict[int, tuple[float, float]] = {}
        self._started_at = 0.0
        self._thumb_tid: int | None = None
        self._radius0 = 0.0
        self._last: dict[str, float | str] | None = None

    def _mm(self, x: int, y: int) -> tuple[float, float]:
        return x / self.scale_x, y / self.scale_y

    def reset(self, now: float = 0.0) -> None:
        self.state = IDLE
        self._origins.clear()
        self._started_at = now
        self._thumb_tid = None
        self._radius0 = 0.0
        self._last = None

    def _pick_thumb(self, points: dict[int, tuple[float, float]]) -> tuple[int | None, float]:
        """Return (thumb tracking id, confidence ratio).

        A resting thumb sits clearly below the other three contacts, so a large
        vertical gap is the strongest signal.  When the contacts are level (a
        thumb resting on the side of the pad, or a synthetic fixture), fall back
        to picking the outlier contact and require a clear separation.
        """
        if len(points) != 4:
            return None, 0.0
        ordered = sorted(points, key=lambda tid: points[tid][1], reverse=True)
        top_y = points[ordered[0]][1]
        second_y = points[ordered[1]][1]
        gap = top_y - second_y
        if gap >= self.thumb_edge_mm:
            return ordered[0], 1.0 + gap / max(self.thumb_edge_mm, 1e-6)
        scores: dict[int, float] = {}
        for tid, point in points.items():
            others = [p for other, p in points.items() if other != tid]
            scores[tid] = _mean([math.hypot(point[0] - o[0], point[1] - o[1])
                                 for o in others])
        best = max(scores, key=lambda t: scores[t])
        worst = min(scores.values())
        ratio = scores[best] / worst if worst > 0 else 0.0
        if self.bounds is not None:
            _, ymin, _, ymax = self.bounds
            best_y = points[best][1]
            if best_y >= ymax - self.thumb_edge_mm:
                ratio += 0.05  # bottom-edge prior, enough to break near-ties
            elif best_y <= ymin + self.thumb_edge_mm:
                ratio -= 0.05
        return best, ratio

    def _radius(self, points: dict[int, tuple[float, float]], thumb: int) -> float:
        tip = points[thumb]
        return _mean([math.hypot(p[0] - tip[0], p[1] - tip[1])
                      for tid, p in points.items() if tid != thumb])

    def update(self, frame: MTFrame) -> Detection | None:
        n = frame.contact_count
        if n == 0:
            if self.state != TRACKING or self._last is None:
                self.reset(frame.timestamp)
                return Detection(gesture="", state=IDLE, reason="no_contacts")
            last = dict(self._last)
            self.reset(frame.timestamp)
            kind = last.get("kind")
            if not kind:
                return Detection(gesture="", state=IDLE,
                                 reason=str(last.get("reason") or "spread_incomplete"),
                                 detail={k: round(float(v), 3) for k, v in last.items()
                                         if isinstance(v, (int, float))})
            return Detection(gesture="", state="SPREAD", reason=f"{kind}_release",
                             direction=str(kind), confidence=float(last["confidence"]),
                             contacts=4, fire=True,
                             detail={k: round(float(v), 3) for k, v in last.items()
                                     if isinstance(v, (int, float))})
        if n != 4:
            if self.state == TRACKING and n < 4:
                # Fingers lift one by one; keep the tracked radius until the
                # last one leaves so the release decision can still fire.
                return Detection(gesture="", state=TRACKING, reason="partial_contacts",
                                 contacts=n)
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="wrong_finger_count",
                             contacts=n)

        points = {tid: self._mm(c.x, c.y) for tid, c in frame.contacts.items()}

        if self.state == IDLE:
            self._thumb_tid, outlier = self._pick_thumb(points)
            if self._thumb_tid is None or outlier < MIN_OUTLIER_RATIO:
                return Detection(gesture="", state=IDLE, reason="no_thumb_candidate",
                                 contacts=4,
                                 detail={"outlier_ratio": round(outlier, 3)})
            self.state = TRACKING
            self._started_at = frame.timestamp
            self._origins = dict(points)
            self._radius0 = self._radius(points, self._thumb_tid)
            return Detection(gesture="", state=TRACKING, reason="spread_started",
                             contacts=4,
                             detail={"outlier_ratio": round(outlier, 3),
                                     "radius0_mm": round(self._radius0, 2)})

        elapsed_ms = (frame.timestamp - self._started_at) * 1000.0
        if elapsed_ms > self.finger_change_timeout_ms:
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="spread_timeout", contacts=4)

        if self._thumb_tid is None or self._thumb_tid not in points:
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="thumb_lost", contacts=4)

        radius = self._radius(points, self._thumb_tid)
        if self._radius0 <= 0:
            self.reset(frame.timestamp)
            return Detection(gesture="", state=IDLE, reason="degenerate_radius", contacts=4)
        ratio = radius / self._radius0

        origin = self._origins.get(self._thumb_tid)
        thumb_point = points[self._thumb_tid]
        thumb_travel = (math.hypot(thumb_point[0] - origin[0], thumb_point[1] - origin[1])
                        if origin else 0.0)

        kind = ""
        reason = "spread_tracking"
        if ratio >= 1.0 + self.spread_ratio_min:
            kind = "open"
        elif ratio <= 1.0 - self.pinch_ratio_min:
            kind = "pinch"
        if kind and thumb_travel > self.swipe_min_mm:
            kind = ""
            reason = "thumb_moved"

        confidence = min(1.0, abs(ratio - 1.0) / max(self.spread_ratio_min, 1e-6) * 0.6
                         + (1.0 - min(1.0, thumb_travel / max(self.swipe_min_mm, 1e-6))) * 0.4)
        self._last = {"kind": kind or "", "confidence": confidence if kind else 0.0,
                      "radius_ratio": ratio, "thumb_travel_mm": thumb_travel,
                      "radius0_mm": self._radius0, "elapsed_ms": elapsed_ms,
                      "reason": reason}
        return Detection(gesture="", state=TRACKING, reason=reason,
                         direction=kind or None,
                         confidence=confidence if kind else 0.0, contacts=4,
                         detail={"radius_ratio": round(ratio, 3),
                                 "thumb_travel_mm": round(thumb_travel, 2),
                                 "thumb_tid": self._thumb_tid})
