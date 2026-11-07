"""Generate deterministic raw evdev JSONL fixtures (1 raw unit = 1 mm)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 47, 48, 53, 54
ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 57, 58
BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP = 325, 333, 334
BTN_TOOL_QUADTAP, BTN_TOOL_QUINTTAP, BTN_TOUCH, BTN_LEFT = 335, 328, 330, 272

U = 1.0  # offline scale is 1 unit/mm


def ev(t: float, typ: int, code: int, value: int) -> dict:
    sec = int(t)
    usec = int(round((t - sec) * 1_000_000))
    return {"sec": sec, "usec": usec, "type": typ, "code": code, "value": value}


def contact_updates(slot: int, tid: int | None, x: int, y: int,
                    pressure: int = 30, major: int = 4) -> list[dict]:
    out = []
    if tid is not None:
        out.append((EV_ABS, ABS_MT_SLOT, slot))
        out.append((EV_ABS, ABS_MT_TRACKING_ID, tid))
        out.append((EV_ABS, ABS_MT_POSITION_X, x))
        out.append((EV_ABS, ABS_MT_POSITION_Y, y))
        out.append((EV_ABS, ABS_MT_PRESSURE, pressure))
        out.append((EV_ABS, ABS_MT_TOUCH_MAJOR, major))
    else:
        out.append((EV_ABS, ABS_MT_SLOT, slot))
        out.append((EV_ABS, ABS_MT_TRACKING_ID, -1))
    return out


def tools(n: int) -> list[tuple[int, int, int]]:
    mapping = {1: BTN_TOOL_FINGER, 2: BTN_TOOL_DOUBLETAP,
               3: BTN_TOOL_TRIPLETAP, 4: BTN_TOOL_QUADTAP, 5: BTN_TOOL_QUINTTAP}
    return [(EV_KEY, code, 1 if mapping[n] == code else 0)
            for code in mapping.values()] + [(EV_KEY, BTN_TOUCH, 1)]


_CLOCK = [1762400000.0]  # fixed epoch-like base avoids float32/timeval ambiguity


def raw(seq: Iterable[tuple[int, int, int]], *, clock: float | None = None) -> list[dict]:
    """Emit events with a globally monotonic fake clock (seconds)."""
    start = _CLOCK[0] if clock is None else clock
    out = [ev(start + i * 0.0001, typ, code, value)
           for i, (typ, code, value) in enumerate(seq)]
    _CLOCK[0] = start + len(seq) * 0.0001
    return out


def frame(events: list[dict], t: float | None = None) -> list[dict]:
    # SYN_REPORT uses the last event's timestamp; t is ignored for fixtures.
    stamp = events[-1]["sec"] + events[-1]["usec"] / 1_000_000 if events else 1.0
    return events + [ev(stamp, EV_SYN, SYN_REPORT, 0)]


def touch_down(positions: list[tuple[int, int, int]], n: int) -> list[dict]:
    seq: list[tuple[int, int, int]] = tools(n)
    for slot, tid, x, y in positions:
        seq.extend(contact_updates(slot, tid, x, y))
    return frame(raw(seq, clock=_CLOCK[0] + 0.12))


def touch_move(positions: list[tuple[int, int, int]]) -> list[dict]:
    seq: list[tuple[int, int, int]] = []
    for slot, tid, x, y in positions:
        seq.extend(contact_updates(slot, None, x, y)[:0])  # explicit below
        seq.append((EV_ABS, ABS_MT_SLOT, slot))
        seq.append((EV_ABS, ABS_MT_POSITION_X, x))
        seq.append((EV_ABS, ABS_MT_POSITION_Y, y))
    return frame(raw(seq, clock=_CLOCK[0] + 0.07))


def touch_release(slots: list[int], n: int) -> list[dict]:
    seq: list[tuple[int, int, int]] = []
    for slot in slots:
        seq.append((EV_ABS, ABS_MT_SLOT, slot))
        seq.append((EV_ABS, ABS_MT_TRACKING_ID, -1))
    # Tool flags should be cleared; emit zero for all BTN_TOOL_* and BTN_TOUCH.
    for code in (BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP,
                 BTN_TOOL_QUADTAP, BTN_TOOL_QUINTTAP, BTN_TOUCH):
        seq.append((EV_KEY, code, 0))
    return frame(raw(seq, clock=_CLOCK[0] + 0.07))


def gesture(direction: str, *, tids=(11, 22, 33), steps=8, distance=16,
            fast=False, static_drift=0, jitter=0, start_pause_s: float = 0.45) -> list[dict]:
    """Three contacts; tids[2] is the mover, tids[0:2] remain static."""
    base = [(0, tids[0], 100, 100), (1, tids[1], 160, 100), (2, tids[2], 130, 150)]
    _CLOCK[0] += start_pause_s
    out = touch_down(base, 3)
    # two settling frames (>= settle_ms=100ms) with all three fingers static
    out += touch_move([(0, tids[0], 100, 100), (1, tids[1], 160, 100), (2, tids[2], 130, 150)])
    out += touch_move([(0, tids[0], 100, 100), (1, tids[1], 160, 100), (2, tids[2], 130, 150)])
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
    for step in range(1, steps + 1):
        amount = distance * step / steps
        mx = 130 + int(round(dx * amount + jitter))
        my = 150 + int(round(dy * amount))
        drift = static_drift * step / steps
        sx1, sy1 = 100 + int(round(drift)), 100
        sx2, sy2 = 160 - int(round(drift)), 100
        out += touch_move([(0, tids[0], sx1, sy1), (1, tids[1], sx2, sy2), (2, tids[2], mx, my)])
    out += touch_release([0, 1, 2], 0)
    return out


def three_finger_all_move(direction: str = "up", distance: int = 16) -> list[dict]:
    out = touch_down([(0, 11, 100, 100), (1, 22, 160, 100), (2, 33, 130, 150)], 3)
    dx, dy = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
    for step in range(1, 9):
        amount = distance * step / 8
        offx, offy = int(dx * amount), int(dy * amount)
        out += touch_move([(0, 11, 100 + offx, 100 + offy),
                           (1, 22, 160 + offx, 100 + offy),
                           (2, 33, 130 + offx, 150 + offy)])
    out += touch_release([0, 1, 2], 0)
    return out


def two_finger_scroll(distance: int = 16) -> list[dict]:
    out = touch_down([(0, 11, 100, 100), (1, 22, 160, 100)], 2)
    for step in range(1, 9):
        amount = distance * step / 8
        out += touch_move([(0, 11, 100, 100 - amount), (1, 22, 160, 100 - amount)])
    out += touch_release([0, 1], 0)
    return out


def four_fingers() -> list[dict]:
    out = touch_down([(0, 11, 80, 80), (1, 22, 140, 80),
                      (2, 33, 200, 80), (3, 44, 140, 150)], 4)
    out += touch_move([(0, 11, 80, 80), (1, 22, 140, 80),
                       (2, 33, 200, 80), (3, 44, 140, 140)])
    out += touch_release([0, 1, 2, 3], 0)
    return out


def write(name: str, events: list[dict]) -> Path:
    root = Path(__file__).parent / "fixtures"
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{name}.jsonl"
    p.write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events))
    return p


# ---------------------------------------------------------------------------
# Apple gesture fixtures.  These use the real pad geometry from config
# (98 x 60 mm at 1 raw unit per mm), so the edge band and thumb prior work.
# ---------------------------------------------------------------------------

PAD_W = 98.0
PAD_H = 60.0


def frame_at(seq: Iterable[tuple[int, int, int]], t: float) -> list[dict]:
    """Emit one SYN_REPORT frame with an explicit start time."""
    out = [ev(t + i * 0.0001, typ, code, value)
           for i, (typ, code, value) in enumerate(seq)]
    out.append(ev(t + len(out) * 0.0001, EV_SYN, SYN_REPORT, 0))
    _CLOCK[0] = t + len(out) * 0.0001 + 0.001
    return out


def release_tools() -> list[tuple[int, int, int]]:
    return [(EV_KEY, code, 0) for code in
            (BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP,
             BTN_TOOL_QUADTAP, BTN_TOOL_QUINTTAP, BTN_TOUCH)]


def place(slot: int, tid: int, x: float, y: float) -> list[tuple[int, int, int]]:
    return [(EV_ABS, ABS_MT_SLOT, slot), (EV_ABS, ABS_MT_TRACKING_ID, tid),
            (EV_ABS, ABS_MT_POSITION_X, int(round(x))),
            (EV_ABS, ABS_MT_POSITION_Y, int(round(y))),
            (EV_ABS, ABS_MT_PRESSURE, 40)]


def move_to(slot: int, x: float, y: float) -> list[tuple[int, int, int]]:
    return [(EV_ABS, ABS_MT_SLOT, slot),
            (EV_ABS, ABS_MT_POSITION_X, int(round(x))),
            (EV_ABS, ABS_MT_POSITION_Y, int(round(y)))]


def lift(slot: int) -> list[tuple[int, int, int]]:
    return [(EV_ABS, ABS_MT_SLOT, slot), (EV_ABS, ABS_MT_TRACKING_ID, -1)]


def tap(n: int = 3, hold_ms: float = 80.0, travel: float = 0.0) -> list[dict]:
    """Short n-finger tap with an optional drift for negative tests."""
    base = [(30.0, 30.0), (45.0, 30.0), (60.0, 30.0), (37.5, 44.0)][:n]
    t0 = _CLOCK[0] + 0.4
    out: list[dict] = []
    # fingers land one after another, like a real tap
    for i, (x, y) in enumerate(base):
        out += frame_at(place(i, 100 + i, x, y), t0 + i * 0.008)
    mid = t0 + hold_ms / 1000.0
    for i, (x, y) in enumerate(base):
        out += frame_at([(EV_ABS, ABS_MT_SLOT, i),
                         (EV_ABS, ABS_MT_POSITION_X, int(round(x + travel))),
                         (EV_ABS, ABS_MT_POSITION_Y, int(round(y)))], mid)
    release = mid + 0.02
    for i in range(n):
        out += frame_at(lift(i), release)
    out += frame_at(release_tools(), release + 0.002)
    return out


def four_finger_swipe(direction: str = "left", distance: float = 30.0,
                      steps: int = 8) -> list[dict]:
    base = [(25.0, 30.0), (40.0, 30.0), (55.0, 30.0), (40.0, 44.0)]
    dx, dy = {"up": (0.0, -1.0), "down": (0.0, 1.0),
              "left": (-1.0, 0.0), "right": (1.0, 0.0)}[direction]
    t0 = _CLOCK[0] + 0.4
    out: list[dict] = []
    for i, (x, y) in enumerate(base):
        out += frame_at(place(i, 200 + i, x, y), t0 + i * 0.004)
    for step in range(1, steps + 1):
        amount = distance * step / steps
        seq: list[tuple[int, int, int]] = []
        for i, (x, y) in enumerate(base):
            seq += move_to(i, x + dx * amount, y + dy * amount)
        out += frame_at(seq, t0 + 0.02 + step * 0.012)
    release = t0 + 0.02 + (steps + 1) * 0.012
    for i in range(4):
        out += frame_at(lift(i), release)
    out += frame_at(release_tools(), release + 0.002)
    return out


def thumb_spread(kind: str = "open", ratio: float = 1.45, steps: int = 8) -> list[dict]:
    """Stationary thumb at the bottom edge; three fingers scale away or in."""
    thumb = (30.0, 52.0)
    fingers = [(12.0, 32.0), (48.0, 32.0), (30.0, 22.0)]
    target = ratio if kind == "open" else (2.0 - ratio)
    t0 = _CLOCK[0] + 0.4
    out: list[dict] = []
    out += frame_at(place(0, 300, *thumb), t0)
    for i, (x, y) in enumerate(fingers):
        out += frame_at(place(i + 1, 301 + i, x, y), t0 + 0.004 * (i + 1))
    for step in range(1, steps + 1):
        scale = 1.0 + (target - 1.0) * step / steps
        seq: list[tuple[int, int, int]] = list(move_to(0, *thumb))
        for i, (x, y) in enumerate(fingers):
            seq += move_to(i + 1, thumb[0] + (x - thumb[0]) * scale,
                           thumb[1] + (y - thumb[1]) * scale)
        out += frame_at(seq, t0 + 0.02 + step * 0.012)
    release = t0 + 0.02 + (steps + 1) * 0.012
    for i in range(4):
        out += frame_at(lift(i), release)
    out += frame_at(release_tools(), release + 0.002)
    return out


def edge_swipe(start_x: float = 90.0, distance: float = 32.0,
               steps: int = 8) -> list[dict]:
    """Two fingers starting in the right edge band and travelling inward."""
    t0 = _CLOCK[0] + 0.4
    out: list[dict] = []
    out += frame_at(place(0, 400, start_x, 28.0), t0)
    out += frame_at(place(1, 401, start_x, 36.0), t0 + 0.004)
    for step in range(1, steps + 1):
        amount = distance * step / steps
        out += frame_at([*move_to(0, start_x - amount, 28.0),
                         *move_to(1, start_x - amount, 36.0)], t0 + 0.02 + step * 0.012)
    release = t0 + 0.02 + (steps + 1) * 0.012
    for i in range(2):
        out += frame_at(lift(i), release)
    out += frame_at(release_tools(), release + 0.002)
    return out


def write_apple_fixtures() -> list[str]:
    names: list[str] = []
    def emit(name: str, events: list[dict]) -> None:
        write(name, events)
        names.append(name)

    emit("gesture_three_finger_tap", tap(3))
    emit("false_three_finger_tap_moved", tap(3, travel=6.0))
    emit("false_three_finger_hold", tap(3, hold_ms=400.0))
    emit("false_two_finger_tap", tap(2))
    for d in ("up", "down", "left", "right"):
        emit(f"gesture_four_swipe_{d}", four_finger_swipe(d))
    emit("false_four_swipe_short", four_finger_swipe("left", distance=8.0))
    emit("gesture_thumb_spread_open", thumb_spread("open", ratio=1.45))
    emit("gesture_thumb_pinch", thumb_spread("pinch", ratio=1.45))
    emit("false_four_translate_not_spread", four_finger_swipe("up", distance=26.0))
    emit("gesture_edge_swipe_right", edge_swipe())
    emit("false_edge_swipe_middle", edge_swipe(start_x=50.0))
    return names


def main() -> None:
    for direction in ("up", "down", "left", "right"):
        write(f"gesture_{direction}", gesture(direction))
    write("gesture_fast_up", gesture("up", steps=3, distance=18, fast=True))
    write("gesture_continuous", sum((gesture(d, tids=(11 + 40 * i, 22 + 40 * i, 33 + 40 * i))
                                     for i, d in enumerate(("up", "down", "left", "right"))), []))
    write("false_two_finger_scroll", two_finger_scroll())
    write("false_three_finger_swipe", three_finger_all_move())
    write("false_four_finger", four_fingers())
    write("false_static_drift", gesture("right", static_drift=6))
    write("false_short_move", gesture("up", distance=3))
    # A large orthogonal component must exceed max_orthogonal_ratio (0.45).
    write("false_diagonal", gesture("up", jitter=30))
    # Tracking ID changes mid-gesture (slot identity must not be trusted).
    events = gesture("down", tids=(11, 22, 33))
    change = frame(raw([(EV_ABS, ABS_MT_SLOT, 0), (EV_ABS, ABS_MT_TRACKING_ID, 77),
                        (EV_ABS, ABS_MT_POSITION_X, 100), (EV_ABS, ABS_MT_POSITION_Y, 100)]), 1.4)
    write("false_tracking_id_change", events[:20] + change + events[20:])
    # SYN_DROPPED in the middle of an otherwise valid gesture.
    dropped = frame(raw([(EV_SYN, SYN_DROPPED, 0)]), 1.5)
    write("false_syn_dropped", events[:30] + dropped + events[30:])
    # Consecutive releases with new tracking IDs after cooldown.
    write("repeat_gestures", gesture("up", tids=(11, 22, 33)) + gesture("up", tids=(91, 92, 93)))
    write_apple_fixtures()
    print("fixtures generated")


if __name__ == "__main__":
    main()
