"""Shared fixture helpers for the gesture tests."""
from __future__ import annotations

from pathlib import Path

from elan_gesture.config import Config, default_config, load_config
from elan_gesture.engine import Engine
from elan_gesture.replay import read_events, replay, summarize

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
PAD_BOUNDS = (0.0, 0.0, 98.0, 60.0)


def apple_config() -> Config:
    return load_config(ROOT / "config/examples/apple-trackpad.toml")


def run_fixture(name: str, config: Config | None = None, *, overview_at_start=None):
    cfg = config or default_config()
    engine = Engine(cfg, 1.0, 1.0, PAD_BOUNDS,
                    overview_probe=(lambda: overview_at_start)
                    if overview_at_start is not None else None)
    records = replay(read_events(FIXTURES / f"{name}.jsonl"), engine)
    return summarize(records), records


def fired_gestures(summary) -> list[str]:
    return [item["gesture"] for item in summary["fired"]]
