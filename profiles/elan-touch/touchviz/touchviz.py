#!/usr/bin/env python3
"""Visualize Elan Touchpad contacts like a small touchscreen.

Read-only evdev type-B event stream; GTK4 + Cairo overlay.  No grab, no X11,
no writes to input configuration.  `--replay` consumes JSONL raw events so the
mapping and drawing can be tested even while /dev/input/event11 is not readable.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("GLibUnix", "2.0")
gi.require_foreign("cairo")
from gi.repository import Gdk, Gio, GLib, GLibUnix, Gtk  # noqa: E402

# Project venv provides `evdev`; system python may not.  Import lazily so
# --replay and --help work even without the module installed globally.
try:
    from evdev import InputDevice, ecodes, util
except ImportError:  # pragma: no cover - replay mode does not need it
    InputDevice = None
    ecodes = None
    util = None

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
except (ValueError, ImportError):  # pragma: no cover
    LayerShell = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = Path.home() / ".config" / "elan-gesture" / "config.toml"

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_MT_SLOT = 0x2F
ABS_MT_TOUCH_MAJOR = 0x30
ABS_MT_TOUCH_MINOR = 0x31
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
ABS_MT_PRESSURE = 0x3A
BTN_TOUCH = 0x14A
BTN_LEFT = 0x110
BTN_TOOL_FINGER = 0x145
BTN_TOOL_DOUBLETAP = 0x14D
BTN_TOOL_TRIPLETAP = 0x14E
BTN_TOOL_QUADTAP = 0x14F
BTN_TOOL_QUINTTAP = 0x148

COLORS = [
    (0.20, 0.75, 1.00),
    (1.00, 0.45, 0.35),
    (0.45, 0.95, 0.55),
    (1.00, 0.80, 0.25),
    (0.80, 0.55, 1.00),
]


@dataclass
class Contact:
    tid: int
    slot: int
    x: int
    y: int
    pressure: int = 0
    major: int = 0
    minor: int = 0
    born: float = 0.0
    color: tuple[float, float, float] = COLORS[0]


@dataclass
class Frame:
    timestamp: float
    contacts: dict[int, Contact]
    click: bool = False
    dropped: bool = False


@dataclass
class Axis:
    minimum: float
    maximum: float
    resolution: float
    physical_mm: float

    @property
    def units_per_mm(self) -> float:
        if self.resolution > 0:
            return self.resolution
        return (self.maximum - self.minimum) / self.physical_mm

    def normalized(self, value: float) -> float:
        if self.maximum <= self.minimum:
            return 0.0
        return (value - self.minimum) / (self.maximum - self.minimum)


@dataclass
class Model:
    x: Axis
    y: Axis
    source: str
    device_path: str = ""
    device_name: str = "Elan Touchpad"
    click_until: float = 0.0
    last_frame: float = 0.0
    frame_count: int = 0
    dropped_count: int = 0
    contacts: dict[int, Contact] = field(default_factory=dict)
    button_down: bool = False
    next_color: int = 0
    last_contacts: dict[int, Contact] = field(default_factory=dict)
    last_contact_time: float = 0.0

    def color_for(self) -> tuple[float, float, float]:
        c = COLORS[self.next_color % len(COLORS)]
        self.next_color += 1
        return c


def _toml_device_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        import tomllib
        with path.open("rb") as fh:
            return tomllib.load(fh).get("device", {})
    except Exception:
        return {}


def _axis_from_evdev(info, physical_mm: float) -> Axis:
    # info is evdev.device.AbsInfo namedtuple-like
    return Axis(float(info.min), float(info.max), float(info.resolution), physical_mm)


def discover_model(path_override: str | None = None, config_path: Path | None = DEFAULT_CONFIG) -> tuple[Model, Any]:
    """Open the touchpad read-only and derive precise axis->mm mapping."""
    if InputDevice is None:
        raise RuntimeError("python evdev module is unavailable; use the project .venv or --replay")
    cfg = _toml_device_config(config_path)
    width_mm = float(cfg.get("width_mm", 98.0))
    height_mm = float(cfg.get("height_mm", 60.0))
    name = str(cfg.get("match_name", "Elan Touchpad"))
    vendor = int(cfg.get("match_vendor", 0x04F3))
    product = int(cfg.get("match_product", 0x002F))
    if path_override:
        paths = [path_override]
    else:
        paths = list(util.list_devices())
    dev = None
    chosen = ""
    for p in paths:
        try:
            candidate = InputDevice(p, readonly=True)
        except OSError:
            continue
        try:
            caps = candidate.capabilities(absinfo=False)
            abs_codes = caps.get(EV_ABS, [])
            needed = {ABS_MT_SLOT, ABS_MT_TRACKING_ID, ABS_MT_POSITION_X, ABS_MT_POSITION_Y}
            if not needed.issubset(set(abs_codes)):
                candidate.close()
                continue
            exact = (name in candidate.name and candidate.info.vendor == vendor
                     and candidate.info.product == product)
            if path_override or exact or dev is None:
                if dev is not None:
                    dev.close()
                dev = candidate
                chosen = p
                if exact or path_override:
                    break
            else:
                candidate.close()
        except Exception:
            candidate.close()
    if dev is None:
        raise RuntimeError(
            "no readable MT touchpad found. Install the udev uaccess rule first:\n"
            f"  sudo {ROOT / 'scripts/bootstrap-permissions.sh'} --root-stage\n"
            "then re-login or restart the user service.")
    xinfo = dev.absinfo(ABS_MT_POSITION_X)
    yinfo = dev.absinfo(ABS_MT_POSITION_Y)
    x = _axis_from_evdev(xinfo, width_mm)
    y = _axis_from_evdev(yinfo, height_mm)
    model = Model(x=x, y=y, source="kernel evdev", device_path=chosen,
                  device_name=dev.name)
    return model, dev


def replay_model(config_path: Path | None = DEFAULT_CONFIG) -> Model:
    cfg = _toml_device_config(config_path)
    width = float(cfg.get("width_mm", 98.0))
    height = float(cfg.get("height_mm", 60.0))
    # Known real hardware ranges from this machine; replay fixtures use raw units.
    return Model(x=Axis(0, 3052, 31, width), y=Axis(0, 1888, 31, height),
                 source="hardware replay fallback", device_path="replay")


class MTDecoder:
    """Type-B frames keyed by ABS_MT_TRACKING_ID, never by slot."""

    def __init__(self, model: Model) -> None:
        self.model = model
        self.slot = 0
        self.slot_tid: dict[int, int] = {}
        self.slot_values: dict[int, dict[str, int]] = {}
        self.button_down = False
        self.dropped = False
        self._timestamp = 0.0

    def feed(self, event: tuple[int, float, int, int]) -> Frame | None:
        etype, timestamp, code, value = event
        self._timestamp = timestamp
        if etype == EV_SYN:
            if code == SYN_DROPPED:
                self.dropped = True
                self.slot_tid.clear()
                self.slot_values.clear()
                self.model.contacts.clear()
                self.model.dropped_count += 1
                return Frame(timestamp, {}, click=self.button_down, dropped=True)
            if code == SYN_REPORT:
                if self.dropped:
                    self.dropped = False
                    return None
                frame_contacts: dict[int, Contact] = {}
                for slot, tid in self.slot_tid.items():
                    v = self.slot_values.setdefault(slot, {})
                    old = self.model.contacts.get(tid)
                    color = old.color if old else self.model.color_for()
                    born = old.born if old else timestamp
                    frame_contacts[tid] = Contact(
                        tid=tid, slot=slot, x=v.get("x", 0), y=v.get("y", 0),
                        pressure=v.get("pressure", 0), major=v.get("major", 0),
                        minor=v.get("minor", 0), born=born, color=color)
                self.model.contacts = frame_contacts
                if frame_contacts:
                    self.model.last_contacts = dict(frame_contacts)
                    self.model.last_contact_time = time.monotonic()
                self.model.last_frame = timestamp
                self.model.frame_count += 1
                return Frame(timestamp, dict(frame_contacts), click=self.button_down)
            return None
        if self.dropped:
            return None
        if etype == EV_ABS:
            if code == ABS_MT_SLOT:
                self.slot = max(0, value)
                return None
            v = self.slot_values.setdefault(self.slot, {})
            if code == ABS_MT_TRACKING_ID:
                if value < 0:
                    self.slot_tid.pop(self.slot, None)
                    v.clear()
                else:
                    self.slot_tid[self.slot] = value
                return None
            if self.slot not in self.slot_tid:
                return None
            key = {ABS_MT_POSITION_X: "x", ABS_MT_POSITION_Y: "y",
                   ABS_MT_PRESSURE: "pressure", ABS_MT_TOUCH_MAJOR: "major",
                   ABS_MT_TOUCH_MINOR: "minor"}.get(code)
            if key:
                v[key] = value
        elif etype == EV_KEY:
            if code == BTN_LEFT:
                self.button_down = bool(value)
                self.model.button_down = self.button_down
                if self.button_down:
                    self.model.click_until = timestamp + 0.20
            elif code == BTN_TOUCH and value == 0:
                # BTN_TOUCH release can precede -1 tracking IDs; keep contacts
                # until explicit ABS_MT_TRACKING_ID=-1 to avoid flicker.
                pass
        return None


def events_from_jsonl(path: str | Path) -> Iterable[tuple[int, float, int, int]]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            o = json.loads(line)
            if "event" in o:
                o = o["event"]
            sec = float(o.get("sec", o.get("timestamp", 0)))
            usec = float(o.get("usec", 0))
            ts = sec + usec / 1_000_000.0
            typ = int(o.get("type", o.get("ev_type")))
            code = int(o.get("code", o.get("ev_code")))
            value = int(o.get("value", o.get("ev_value")))
            yield (typ, ts, code, value)


def events_from_device(dev: InputDevice) -> Iterable[tuple[int, float, int, int]]:
    for event in dev.read_loop():
        yield (event.type, float(event.sec) + float(event.usec) / 1_000_000.0,
               event.code, event.value)


class TouchViz(Gtk.Application):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(application_id="io.github.lancetfish.TouchViz",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.args = args
        self.window: Gtk.Window | None = None
        self.area: Gtk.DrawingArea | None = None
        self.model: Model | None = None
        self.decoder: MTDecoder | None = None
        self.dev: Any = None
        self.replay_source: Iterable[tuple[int, float, int, int]] | None = None
        self.source_id = 0

    def do_activate(self) -> None:  # GTK4 callback
        self.build_window()
        try:
            self.open_source()
            self.window.present()
        except Exception as exc:
            self.show_error(str(exc))

    def build_window(self) -> None:
        w = Gtk.ApplicationWindow(application=self, title="Elan Touchpad — contact visualizer")
        w.set_default_size(int(self.args.width), int(self.args.height))
        if self.args.x is not None and self.args.y is not None and LayerShell is not None:
            LayerShell.init_for_window(w)
            LayerShell.set_layer(w, LayerShell.Layer.OVERLAY)
            LayerShell.set_anchor(w, LayerShell.Edge.TOP, True)
            LayerShell.set_anchor(w, LayerShell.Edge.LEFT, True)
            LayerShell.set_margin(w, LayerShell.Edge.TOP, self.args.y)
            LayerShell.set_margin(w, LayerShell.Edge.LEFT, self.args.x)
            LayerShell.set_exclusive_zone(w, -1)
            LayerShell.set_keyboard_mode(w, LayerShell.KeyboardMode.NONE)
        elif self.args.x is not None and self.args.y is not None:
            print("warning: gtk4-layer-shell unavailable; position ignored", file=sys.stderr)
        if self.args.transparent:
            w.set_decorated(False)
            try:
                w.set_opacity(0.92)
            except Exception:
                pass
        else:
            w.set_decorated(True)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self.draw)
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        w.set_child(self.area)
        w.connect("close-request", self.on_close)
        self.window = w
        # Make the surface fully click-through where possible.
        w.connect("realize", self.make_click_through)

    def make_click_through(self, window: Gtk.Window) -> None:
        try:
            surface = window.get_surface()
            empty = cairo.Region()
            surface.set_input_region(empty)
        except Exception as exc:
            print(f"warning: could not set empty input region: {exc}", file=sys.stderr)
        if LayerShell is not None and self.args.transparent:
            try:
                LayerShell.set_namespace(window, "elan-touchviz")
            except Exception:
                pass

    def open_source(self) -> None:
        if self.args.replay:
            self.model = replay_model(Path(self.args.config) if self.args.config else DEFAULT_CONFIG)
            self.replay_source = events_from_jsonl(Path(self.args.replay))
            self.decoder = MTDecoder(self.model)
            self.source_id = GLib.idle_add(self.pump_replay)
        else:
            self.model, self.dev = discover_model(
                self.args.device, Path(self.args.config) if self.args.config else DEFAULT_CONFIG)
            self.decoder = MTDecoder(self.model)
            fd = self.dev.fileno()
            self.source_id = GLibUnix.fd_add_full(
                GLib.PRIORITY_DEFAULT, fd, GLib.IOCondition.IN,
                self.on_device_readable, None)
        self.refresh()

    def pump_replay(self) -> bool:
        assert self.replay_source is not None and self.decoder is not None
        count = 0
        try:
            for event in self.replay_source:
                frame = self.decoder.feed(event)
                if frame is not None:
                    self.on_frame(frame)
                count += 1
                if count >= 12:
                    self.refresh()
                    return True
        except StopIteration:
            self.refresh()
            return False
        except Exception as exc:
            print(f"replay error: {exc}", file=sys.stderr)
            return False
        self.refresh()
        return False

    def on_device_readable(self, fd: int, _condition, _data=None) -> bool:
        assert self.decoder is not None and self.dev is not None
        try:
            for event in self.dev.read():
                frame = self.decoder.feed(
                    (event.type, event.sec + event.usec / 1_000_000.0,
                     event.code, event.value))
                if frame is not None:
                    self.on_frame(frame)
        except BlockingIOError:
            return True
        except OSError as exc:
            print(f"device read error: {exc}", file=sys.stderr)
            return False
        self.refresh()
        return True

    def on_frame(self, frame: Frame) -> None:
        # Keep contact highlights for a short tail so quick taps remain visible.
        self.refresh()

    def refresh(self) -> None:
        if self.area is not None:
            self.area.queue_draw()

    def show_error(self, message: str) -> None:
        print(f"touchviz: {message}", file=sys.stderr)
        if self.window is None:
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24); box.set_margin_bottom(24)
        box.set_margin_start(24); box.set_margin_end(24)
        label = Gtk.Label(label=message)
        label.set_wrap(True)
        label.set_max_width_chars(80)
        box.append(label)
        btn = Gtk.Button(label="Close")
        btn.connect("clicked", lambda *_: self.window.close())
        box.append(btn)
        self.window.set_child(box)
        self.window.present()

    @staticmethod
    def rgba(rgb: tuple[float, float, float], alpha: float = 1.0) -> tuple[float, float, float, float]:
        return (*rgb, alpha)

    def draw(self, area: Gtk.DrawingArea, cr, width: int, height: int, _data=None) -> None:
        model = self.model
        # Background: transparent in overlay mode, dark slate in window mode.
        if self.args.transparent:
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
        else:
            cr.set_source_rgb(0.055, 0.065, 0.085)
            cr.paint()
        if model is None:
            return
        pad = 22.0
        header = 44.0 if not self.args.transparent else 16.0
        footer = 24.0
        x0, y0 = pad, header
        w = max(10.0, width - 2 * pad)
        h = max(10.0, height - header - footer - pad)
        # Preserve the physical aspect ratio of the touchpad inside the widget.
        ar = (model.x.maximum - model.x.minimum) / model.x.units_per_mm / (
            (model.y.maximum - model.y.minimum) / model.y.units_per_mm)
        box_w, box_h = w, w / ar
        if box_h > h:
            box_h, box_w = h, h * ar
        x0 += (w - box_w) / 2.0
        y0 += (h - box_h) / 2.0
        # Touchpad outline and fine grid.
        cr.save()
        cr.rectangle(x0, y0, box_w, box_h)
        cr.set_source_rgba(0.10, 0.13, 0.18, 0.88 if self.args.transparent else 1.0)
        cr.fill()
        cr.set_line_width(1.2)
        cr.set_source_rgba(0.55, 0.72, 0.95, 0.75)
        cr.stroke()
        for i in range(1, 10):
            gx = x0 + box_w * i / 10.0
            gy = y0 + box_h * i / 10.0
            cr.set_source_rgba(0.45, 0.58, 0.75, 0.13)
            cr.set_line_width(0.5)
            cr.move_to(gx, y0); cr.line_to(gx, y0 + box_h); cr.stroke()
            cr.move_to(x0, gy); cr.line_to(x0 + box_w, gy); cr.stroke()
        # Contacts. A short tail keeps quick taps visible for ~350 ms.
        active = model.contacts
        tail = False
        if not active and time.monotonic() - model.last_contact_time < 0.35:
            active = model.last_contacts
            tail = True
            alpha_scale = max(0.25, 1.0 - (time.monotonic() - model.last_contact_time) / 0.35)
        else:
            alpha_scale = 1.0
        for tid, contact in sorted(active.items()):
            nx = model.x.normalized(contact.x)
            ny = model.y.normalized(contact.y)
            cx = x0 + nx * box_w
            cy = y0 + ny * box_h
            r, g, b = contact.color
            contact_alpha = alpha_scale
            # Optional pressure/contact ellipse, scaled from TOUCH_MAJOR units.
            major_mm = contact.major / model.x.units_per_mm if contact.major else 0.0
            ellipse_radius = max(5.0, min(28.0, major_mm / max(1.0, model.x.units_per_mm) * box_w / model.x.physical_mm))
            if contact.major > 0:
                cr.save()
                cr.set_source_rgba(r, g, b, 0.12 * contact_alpha)
                cr.arc(cx, cy, ellipse_radius, 0, 2 * math.pi)
                cr.fill()
                cr.set_source_rgba(r, g, b, 0.35 * contact_alpha)
                cr.set_line_width(1.0)
                cr.arc(cx, cy, ellipse_radius, 0, 2 * math.pi)
                cr.stroke()
                cr.restore()
            # Crosshair for coordinate precision.
            cr.set_source_rgba(r, g, b, 0.45 * contact_alpha)
            cr.set_line_width(0.8)
            cr.move_to(cx - 8, cy); cr.line_to(cx + 8, cy); cr.stroke()
            cr.move_to(cx, cy - 8); cr.line_to(cx, cy + 8); cr.stroke()
            # Core dot with click highlight.
            clicking = model.button_down or time.monotonic() < model.click_until
            core_r = 7.5 if not clicking else 10.5
            cr.set_source_rgba(r, g, b, (0.95 if not clicking else 1.0) * contact_alpha)
            cr.arc(cx, cy, core_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.90 * contact_alpha)
            cr.set_line_width(1.0)
            cr.arc(cx, cy, core_r, 0, 2 * math.pi)
            cr.stroke()
            if self.args.labels:
                mm_x = (contact.x - model.x.minimum) / model.x.units_per_mm
                mm_y = (contact.y - model.y.minimum) / model.y.units_per_mm
                label = f"ID {tid} · {mm_x:.1f},{mm_y:.1f} mm · p{contact.pressure}"
                cr.set_font_size(10)
                ext = cr.text_extents(label)
                lx = min(max(4.0, cx + 12), x0 + box_w - ext.width - 6)
                ly = min(max(y0 + 14, cy - 12), y0 + box_h - 6)
                cr.set_source_rgba(0, 0, 0, 0.65)
                cr.rectangle(lx - 3, ly - 11, ext.width + 6, 15)
                cr.fill()
                cr.set_source_rgba(r, g, b, 1.0)
                cr.move_to(lx, ly)
                cr.show_text(label)
        # Header text.
        cr.set_font_size(12)
        cr.set_source_rgba(0.88, 0.94, 1.0, 0.95)
        status = (f"{model.device_name} · {len(active)} contact(s){' (tap tail)' if tail else ''} · "
                  f"{model.x.minimum:.0f}–{model.x.maximum:.0f} × "
                  f"{model.y.minimum:.0f}–{model.y.maximum:.0f} · "
                  f"{model.x.units_per_mm:.0f}/{model.y.units_per_mm:.0f} u/mm · "
                  f"frames {model.frame_count} · drops {model.dropped_count}")
        if not self.args.transparent:
            cr.move_to(pad, 26)
            cr.show_text(status)
        cr.set_source_rgba(0.45, 0.62, 0.85, 0.85)
        cr.move_to(x0, y0 + box_h + 16)
        cr.set_font_size(10)
        cr.show_text("read-only evdev · tracking IDs are finger identities · click-through overlay")
        cr.restore()

    def on_close(self, _window) -> bool:
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0
        if self.dev is not None:
            try:
                self.dev.close()
            except Exception:
                pass
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Show Elan Touchpad contact positions like a touchscreen")
    p.add_argument("--device", help="override /dev/input/eventN")
    p.add_argument("--config", help="TOML config containing [device] width_mm/height_mm")
    p.add_argument("--replay", help="JSONL raw-event file; does not need device permission")
    p.add_argument("--width", type=int, default=760, help="window width")
    p.add_argument("--height", type=int, default=520, help="window height")
    p.add_argument("--x", type=int, help="overlay left position (requires gtk4-layer-shell)")
    p.add_argument("--y", type=int, help="overlay top position (requires gtk4-layer-shell)")
    p.add_argument("--transparent", action="store_true", help="undecorated click-through overlay")
    p.add_argument("--labels", action="store_true", help="show ID / mm / pressure labels")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    app = TouchViz(args)
    return app.run(sys.argv[:1] + [] if argv is None else sys.argv[:1] + argv)


if __name__ == "__main__":
    raise SystemExit(main())
