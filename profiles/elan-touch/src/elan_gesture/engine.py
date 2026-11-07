"""Gesture engine: one entry point that arbitrates every recognizer.

The daemon and the replay tool both drive this class, so there is exactly one
implementation of "which gesture fired, and when".  Recognizers run in a fixed
priority order and at most one of them may commit per frame.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any, Callable

from evdev import ecodes

from .config import Config
from .edge_swipe import EdgeSwipeRecognizer
from .gesture import GestureDetector
from .mt import MTFrame
from .spread import SpreadRecognizer
from .swipe import SwipeRecognizer
from .tap import TapRecognizer
from .types import Detection, Fire

LOG = logging.getLogger("elan_gesture.engine")

ASYM_CLEAR_REASONS = {"below_threshold", "direction_stabilizing"}

# Priority: shortest and most specific gestures claim the frame first.
ORDER = ("tap", "spread", "edge", "swipe", "asymmetric")


@dataclasses.dataclass(frozen=True)
class EngineOutput:
    decisions: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    fires: list[Fire] = dataclasses.field(default_factory=list)
    overview_at_start: bool | None = None

    @property
    def states(self) -> dict[str, str]:
        return {d.get("recognizer", "?"): d.get("state", "?") for d in self.decisions}


class Engine:
    """Runs every enabled recognizer against each MT frame."""

    def __init__(self, config: Config, scale_x: float, scale_y: float,
                 bounds: tuple[float, float, float, float] | None = None,
                 *,
                 overview_probe: Callable[[], bool | None] | None = None) -> None:
        if scale_x <= 0 or scale_y <= 0:
            raise ValueError("coordinate scale must be positive")
        self.config = config
        self.gesture = config.gesture
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.bounds = bounds
        self.overview_probe = overview_probe
        g = config.gesture

        self.detector = GestureDetector(g, scale_x, scale_y, bounds)
        self._asym_snapshot: dict[str, Any] | None = None

        enabled = {name for name, spec in config.gestures.items() if spec.enabled}
        self.tap: TapRecognizer | None = None
        if "three_finger_tap" in enabled:
            spec = config.gestures["three_finger_tap"]
            self.tap = TapRecognizer(spec.name, spec.finger_count,
                                     scale_x=scale_x, scale_y=scale_y,
                                     tap_max_ms=g.tap_max_ms, tap_max_mm=g.tap_max_mm,
                                     cooldown_ms=g.cooldown_ms)

        self.spread: SpreadRecognizer | None = None
        if {"thumb_spread_open", "thumb_spread_pinch"} & enabled:
            self.spread = SpreadRecognizer(
                scale_x=scale_x, scale_y=scale_y,
                spread_ratio_min=g.spread_ratio_min, pinch_ratio_min=g.pinch_ratio_min,
                thumb_edge_mm=g.thumb_edge_mm, swipe_min_mm=g.swipe_min_mm,
                finger_change_timeout_ms=g.finger_change_timeout_ms, bounds=bounds)

        self.edge: EdgeSwipeRecognizer | None = None
        if "two_finger_edge_left" in enabled:
            spec = config.gestures["two_finger_edge_left"]
            self.edge = EdgeSwipeRecognizer(
                spec.edge or "right", finger_count=spec.finger_count,
                scale_x=scale_x, scale_y=scale_y, edge_trigger_mm=g.edge_trigger_mm,
                swipe_min_mm=g.swipe_min_mm,
                finger_change_timeout_ms=g.finger_change_timeout_ms, bounds=bounds)

        self.swipe: SwipeRecognizer | None = None
        if {"four_finger_up", "four_finger_down",
                "four_finger_left", "four_finger_right"} & enabled:
            self.swipe = SwipeRecognizer(
                4, scale_x=scale_x, scale_y=scale_y, swipe_min_mm=g.swipe_min_mm,
                swipe_axis_ratio=g.swipe_axis_ratio,
                swipe_angle_tolerance_deg=g.swipe_angle_tolerance_deg,
                spread_ratio_min=g.spread_ratio_min,
                finger_change_timeout_ms=g.finger_change_timeout_ms)

        self._overview_at_start: bool | None = None
        self._last_contacts = 0

    # -- helpers ---------------------------------------------------------

    def _probe_overview(self) -> bool | None:
        if self.overview_probe is None:
            return None
        try:
            return self.overview_probe()
        except Exception as exc:  # a broken probe must never stop the daemon
            LOG.warning("overview probe failed: %s", exc)
            return None

    def _reset_all(self, now: float = 0.0) -> None:
        for rec in (self.tap, self.spread, self.edge, self.swipe):
            if rec is not None:
                rec.reset(now)
        self.detector.reset()
        self._asym_snapshot = None

    def reset(self, now: float = 0.0) -> None:
        self._reset_all(now)
        self._overview_at_start = None
        self._last_contacts = 0

    # -- asymmetric three-finger (legacy [actions.*]) --------------------

    def _step_asymmetric(self, frame: MTFrame) -> tuple[dict[str, Any], Fire | None]:
        det = self.detector
        if det.state == "ARMED" and det.best_decision is not None:
            self._asym_snapshot = det.best_decision.to_dict()
        decision = det.update(frame)
        if decision.reason in ASYM_CLEAR_REASONS:
            self._asym_snapshot = None
        fire: Fire | None = None
        if frame.contact_count < det.c.exact_contacts and self._asym_snapshot is not None:
            snapshot = self._asym_snapshot
            self._asym_snapshot = None
            det.finish(frame)
            fire = Fire(gesture=str(snapshot["direction"]),
                        direction=snapshot["direction"],
                        confidence=float(snapshot["confidence"]),
                        reason="release_trigger",
                        context={"static_ids": snapshot.get("static_ids", []),
                                 "mover_id": snapshot.get("mover_id")})
        return {"recognizer": "asymmetric", **decision.to_dict()}, fire

    def _enabled(self, gesture: str) -> bool:
        spec = self.config.gestures.get(gesture)
        return bool(spec is not None and spec.enabled)

    # -- main step -------------------------------------------------------

    def step(self, frame: MTFrame) -> EngineOutput:
        n = frame.contact_count
        if frame.dropped:
            self._reset_all(frame.timestamp)
            return EngineOutput(decisions=[{"recognizer": "engine", "state": "IDLE",
                                            "reason": "syn_dropped"}])
        if any(frame.buttons.get(code)
               for code in (ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE)):
            self._reset_all(frame.timestamp)
            return EngineOutput(decisions=[{"recognizer": "engine", "state": "IDLE",
                                            "reason": "physical_button"}])

        if n == 4 and self._last_contacts != 4:
            self._overview_at_start = self._probe_overview()
        if n == 0:
            overview = self._overview_at_start
            self._overview_at_start = None
        else:
            overview = self._overview_at_start
        self._last_contacts = n

        decisions: list[dict[str, Any]] = []
        fires: list[Fire] = []

        if self.tap is not None:
            det = self.tap.update(frame)
            if det is not None:
                decisions.append({"recognizer": "tap", **det.to_dict()})
                if det.fire and self._enabled(det.gesture):
                    fires.append(Fire(gesture=det.gesture, direction=None,
                                      confidence=det.confidence, reason=det.reason,
                                      context=det.detail))
                    self._reset_all(frame.timestamp)

        if self.spread is not None and not fires:
            det = self.spread.update(frame)
            if det is not None:
                if det.fire and det.direction and self._enabled(f"thumb_spread_{det.direction}"):
                    gesture = f"thumb_spread_{det.direction}"
                    decisions.append({"recognizer": "spread", "gesture": gesture,
                                      **det.to_dict()})
                    fires.append(Fire(gesture=gesture, direction=det.direction,
                                      confidence=det.confidence, reason=det.reason,
                                      context=det.detail))
                    self._reset_all(frame.timestamp)
                else:
                    decisions.append({"recognizer": "spread", **det.to_dict()})

        if self.edge is not None and not fires:
            det = self.edge.update(frame)
            if det is not None:
                if det.fire and self._enabled("two_finger_edge_left"):
                    decisions.append({"recognizer": "edge",
                                      "gesture": "two_finger_edge_left",
                                      **det.to_dict()})
                    fires.append(Fire(gesture="two_finger_edge_left",
                                      direction=det.direction,
                                      confidence=det.confidence, reason=det.reason,
                                      context=det.detail))
                    self._reset_all(frame.timestamp)
                else:
                    decisions.append({"recognizer": "edge", **det.to_dict()})

        if self.swipe is not None and not fires:
            det = self.swipe.update(frame)
            if det is not None:
                if det.fire and det.direction and self._enabled(f"four_finger_{det.direction}"):
                    gesture = f"four_finger_{det.direction}"
                    decisions.append({"recognizer": "swipe", "gesture": gesture,
                                      **det.to_dict()})
                    fires.append(Fire(gesture=gesture, direction=det.direction,
                                      confidence=det.confidence, reason=det.reason,
                                      context={**det.detail,
                                               "overview_at_start": overview}))
                    self._reset_all(frame.timestamp)
                else:
                    decisions.append({"recognizer": "swipe", **det.to_dict()})

        if not fires:
            asym, asym_fire = self._step_asymmetric(frame)
            decisions.append(asym)
            if asym_fire is not None:
                fires.append(asym_fire)
                self._reset_all(frame.timestamp)

        return EngineOutput(decisions=decisions, fires=fires,
                            overview_at_start=overview)


def build_engine(config: Config, scale_x: float, scale_y: float,
                 bounds: tuple[float, float, float, float] | None = None,
                 *, overview_probe: Callable[[], bool | None] | None = None) -> Engine:
    return Engine(config, scale_x, scale_y, bounds, overview_probe=overview_probe)
