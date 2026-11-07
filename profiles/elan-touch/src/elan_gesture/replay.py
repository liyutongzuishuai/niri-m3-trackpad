"""JSONL raw-event capture and deterministic replay through production code."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from .engine import Engine, EngineOutput
from .mt import MTFrame, MTParser, RawEvent
from .types import Fire


def read_events(path: str | Path) -> Iterator[RawEvent]:
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if isinstance(obj, dict) and "event" in obj:
                obj = obj["event"]
            yield RawEvent.from_json(obj)


def write_events(path: str | Path, events: Iterable[RawEvent]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with p.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.to_json(), separators=(",", ":")) + "\n")
            count += 1
    return count


@dataclasses.dataclass(frozen=True)
class ReplayRecord:
    frame: MTFrame
    decisions: list[dict[str, Any]]
    fires: list[Fire]

    @property
    def decision(self) -> dict[str, Any]:
        """The asymmetric three-finger decision, kept for older callers."""
        for item in self.decisions:
            if item.get("recognizer") == "asymmetric":
                return item
        return self.decisions[0] if self.decisions else {"state": "IDLE", "reason": "none"}

    @property
    def fire(self) -> dict[str, Any] | None:
        return self.fires[0].to_dict() if self.fires else None


def replay(events: Iterable[RawEvent], engine: Engine) -> list[ReplayRecord]:
    """Run the exact MTParser + Engine pipeline used by the daemon."""
    parser = MTParser()
    records: list[ReplayRecord] = []
    for event in events:
        frame = parser.feed(event)
        if frame is None:
            continue
        output: EngineOutput = engine.step(frame)
        records.append(ReplayRecord(frame, output.decisions, output.fires))
        if frame.dropped:
            parser.acknowledge_resync()
    return records


def summarize(records: Iterable[ReplayRecord]) -> dict[str, Any]:
    records = list(records)
    fired = [f for r in records for f in r.fires]
    reasons: dict[str, int] = {}
    for record in records:
        for item in record.decisions:
            reason = item.get("reason") or "none"
            reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "frames": len(records),
        "fired": [{"gesture": f.gesture, "direction": f.direction,
                   "confidence": round(f.confidence, 3), "reason": f.reason}
                  for f in fired],
        "reasons": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
