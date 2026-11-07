"""Shared result types for the gesture engine and its recognizers."""
from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class Detection:
    """One recognizer's opinion about the current frame.

    fire=True means the gesture is committed and the engine may dispatch it.
    """

    gesture: str
    state: str
    reason: str
    confidence: float = 0.0
    direction: str | None = None
    contacts: int = 0
    fire: bool = False
    detail: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["confidence"] = round(self.confidence, 3)
        return data


@dataclasses.dataclass(frozen=True)
class Fire:
    """A committed gesture that the dispatcher must execute."""

    gesture: str
    direction: str | None
    confidence: float
    reason: str
    context: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"gesture": self.gesture, "direction": self.direction,
                "confidence": round(self.confidence, 3), "reason": self.reason,
                "context": self.context}
