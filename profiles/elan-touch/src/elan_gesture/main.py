"""CLI: probe / monitor / capture / replay / gestures / inject-test / daemon.

Safety invariant: probe, monitor, capture, replay and gestures never construct
an ActionDispatcher and never execute a configured command.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Sequence

from evdev import InputDevice, ecodes

from . import __version__
from .actions import ActionDispatcher, NiriIPC
from .config import Config, ConfigError, load_config, user_config_path
from .device import (DeviceUnavailable, derive_scale, find_device, open_readonly,
                     probe_report)
from .engine import Engine, EngineOutput
from .logging_utils import configure
from .mt import MTFrame, MTParser, RawEvent
from .replay import read_events, replay, summarize, write_events

LOG = logging.getLogger("elan_gesture")


def _default_config_path() -> str | None:
    p = user_config_path()
    return str(p) if p.is_file() else None


def _load(args: argparse.Namespace) -> Config:
    path = args.config or _default_config_path()
    config = load_config(path)
    if args.device:
        import dataclasses
        config = dataclasses.replace(config, device=dataclasses.replace(config.device, path=args.device))
    if args.dry_run:
        import dataclasses
        config = dataclasses.replace(config, general={**config.general, "dry_run": True})
    return config


def _engine(config: Config, dev: InputDevice | None = None,
            overview_probe=None) -> tuple[Engine, Any]:
    scale = derive_scale(config.device, dev)
    engine = Engine(config, scale.units_per_mm_x, scale.units_per_mm_y,
                    scale.bounds_mm, overview_probe=overview_probe)
    return engine, scale


def _contacts_payload(frame: MTFrame, scale) -> list[dict[str, Any]]:
    contacts = []
    for tid, contact in sorted(frame.contacts.items()):
        item: dict[str, Any] = {"tracking_id": tid, "slot": contact.slot,
                                "x": contact.x, "y": contact.y,
                                "pressure": contact.pressure}
        if scale:
            item["x_mm"] = round(contact.x / scale.units_per_mm_x, 2)
            item["y_mm"] = round(contact.y / scale.units_per_mm_y, 2)
        contacts.append(item)
    return contacts


def _frame_line(frame: MTFrame, output: EngineOutput, config: Config,
                scale=None, fmt: str = "text") -> str:
    positions = _contacts_payload(frame, scale)
    payload = {
        "ts": round(frame.timestamp, 6),
        "contacts": frame.contact_count,
        "positions": positions,
        "tool_flags": {ecodes.BTN.get(k, str(k)): v for k, v in frame.tool_flags.items()},
        "buttons": {ecodes.BTN.get(k, str(k)): v for k, v in frame.buttons.items()},
        "decisions": output.decisions,
        "fires": [f.to_dict() for f in output.fires],
        "overview_at_start": output.overview_at_start,
        "dropped": frame.dropped,
    }
    if fmt == "json" or config.general.get("log_format") == "json":
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    primary = next((d for d in output.decisions if d.get("state") not in ("IDLE", None)),
                   output.decisions[0] if output.decisions else {})
    states = ",".join(f"{d.get('recognizer')}:{d.get('state')}" for d in output.decisions)
    fires = ",".join(f"{f.gesture}({f.confidence:.2f})" for f in output.fires) or "-"
    return (f"t={frame.timestamp:.3f} contacts={frame.contact_count} "
            f"state={primary.get('state')} reason={primary.get('reason')} "
            f"direction={primary.get('direction')} "
            f"confidence={primary.get('confidence')} fires=[{fires}] "
            f"states=[{states}] "
            f"contacts_detail={json.dumps(positions, separators=(',', ':'))}")


def cmd_probe(args: argparse.Namespace, config: Config) -> int:
    report = probe_report(config.device, args.device)
    report["inject"] = _inject_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if "direct_open_error" in report:
        LOG.warning("Direct read-only open unavailable; capability data came from sysfs/borrowed ioctl: %s",
                    report["direct_open_error"])
    return 0


def _inject_report() -> dict[str, Any]:
    from .inject import Injector
    inj = Injector()
    return {
        "ydotool": inj.ydotool or None,
        "socket": inj.socket_path,
        "socket_present": Path(inj.socket_path).exists(),
        "available": inj.available(),
        "wheel_available": inj.wheel_available(),
        "note": "keys via ydotool, wheel via evdev UInput; never pointer motion or clicks",
    }


def _open_or_raise(config: Config) -> InputDevice:
    path = find_device(config.device)
    dev = open_readonly(path)
    required = (ecodes.ABS_MT_SLOT, ecodes.ABS_MT_TRACKING_ID,
                ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y)
    caps = dev.capabilities(absinfo=False)
    missing = [ecodes.ABS.get(c, str(c)) for c in required if c not in caps.get(ecodes.EV_ABS, [])]
    if missing:
        dev.close()
        raise DeviceUnavailable(f"{path} lacks required MT axes: {missing}")
    LOG.info("Opened %s (%s, %04x:%04x) read-only, no grab", path, dev.name,
             dev.info.vendor, dev.info.product)
    return dev


def _process_stream(config: Config, dev: InputDevice, *, fmt: str,
                    capture_path: str | None = None,
                    dispatcher: ActionDispatcher | None = None,
                    stop_flag: Any = None) -> int:
    probe = dispatcher.ipc.overview_open if dispatcher is not None else None
    engine, scale = _engine(config, dev, probe)
    parser = MTParser()
    capture = [] if capture_path else None

    def flush_capture() -> None:
        if capture_path and capture is not None:
            count = write_events(capture_path, capture)
            LOG.info("Wrote %d raw events to %s", count, capture_path)

    # SIGTERM/SIGINT must still flush a bounded `capture` session.
    old_int = signal.getsignal(signal.SIGINT)
    old_term = signal.getsignal(signal.SIGTERM)

    def stop_handler(signum, frame):
        flush_capture()
        signal.signal(signum, old_int if signum == signal.SIGINT else old_term)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    try:
        for event in dev.read_loop():
            if stop_flag is not None and stop_flag.is_set():
                break
            raw = RawEvent.from_evdev(event)
            if capture is not None:
                capture.append(raw)
            frame = parser.feed(raw)
            if frame is None:
                continue
            output = engine.step(frame)
            print(_frame_line(frame, output, config, scale, fmt), flush=True)
            if frame.dropped:
                parser.acknowledge_resync()
                try:
                    dev.sync()
                except (OSError, AttributeError):
                    pass
                continue
            for fire in output.fires:
                LOG.info("gesture fired: %s direction=%s confidence=%.3f reason=%s",
                         fire.gesture, fire.direction, fire.confidence, fire.reason)
                if dispatcher is not None:
                    dispatcher.dispatch(fire.gesture, direction=fire.direction,
                                        context=fire.context)
        flush_capture()
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
    dev.close()
    return 0


def cmd_monitor(args: argparse.Namespace, config: Config) -> int:
    dev = _open_or_raise(config)
    LOG.info("Read-only monitor: no actions can execute. Ctrl-C to stop.")
    return _process_stream(config, dev, fmt=args.format,
                           capture_path=args.out if hasattr(args, "out") else None)


def cmd_capture(args: argparse.Namespace, config: Config) -> int:
    if not args.out:
        LOG.error("capture requires --out PATH")
        return 2
    out = Path(args.out).expanduser()
    if out.exists() and not args.force:
        LOG.error("%s exists; pass --force to overwrite", out)
        return 2
    dev = _open_or_raise(config)
    LOG.info("Recording raw events to %s; no actions will execute.", out)
    return _process_stream(config, dev, fmt=args.format, capture_path=str(out))


def cmd_replay(args: argparse.Namespace, config: Config) -> int:
    if not args.input:
        LOG.error("replay requires --in PATH")
        return 2
    events = list(read_events(args.input))
    engine, scale = _engine(config, None)
    records = replay(events, engine)
    for record in records:
        if args.format == "json":
            print(json.dumps({"frame": {"ts": record.frame.timestamp,
                                       "contacts": record.frame.contact_count,
                                       "dropped": record.frame.dropped},
                              "decisions": record.decisions,
                              "fires": [f.to_dict() for f in record.fires]},
                             ensure_ascii=False, separators=(",", ":")))
        else:
            print(_frame_line(record.frame, EngineOutput(record.decisions, record.fires),
                              config, scale, "text"))
    print(json.dumps(summarize(records), ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


def cmd_gestures(args: argparse.Namespace, config: Config) -> int:
    rows: list[dict[str, Any]] = []
    for name, spec in config.gestures.items():
        rows.append({
            "gesture": name,
            "provider": spec.provider,
            "finger_count": spec.finger_count,
            "edge": spec.edge,
            "enabled": spec.enabled,
            "type": spec.action.type,
            "description": spec.action.description,
        })
    for direction, action in config.actions.items():
        rows.append({
            "gesture": f"asymmetric_{direction}",
            "provider": "daemon",
            "finger_count": 3,
            "edge": "",
            "enabled": action.enabled and action.type != "noop",
            "type": action.type,
            "description": action.description,
        })
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"{'gesture':26s} {'provider':8s} {'fingers':7s} {'enabled':7s} type")
        for row in rows:
            print(f"{row['gesture']:26s} {row['provider']:8s} "
                  f"{row['finger_count']:<7d} {str(row['enabled']):7s} {row['type']}")
    niri_native = [r["gesture"] for r in rows if r["provider"] == "niri"]
    if niri_native:
        print("\nHandled natively by niri (daemon observes only): "
              + ", ".join(niri_native), file=sys.stderr)
    return 0


def cmd_inject_test(args: argparse.Namespace, config: Config) -> int:
    from .inject import Injector
    inj = Injector(timeout_ms=args.timeout_ms)
    report = {"ydotool": inj.ydotool or None, "socket": inj.socket_path,
              "available": inj.available(), "wheel_available": inj.wheel_available(),
              "keys": list(args.keys) if args.keys else None,
              "scroll": args.scroll}
    if not args.yes:
        report["dry_run"] = True
        report["note"] = "pass --yes to actually inject"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    try:
        if args.keys:
            report["result"] = inj.key(list(args.keys))
        elif args.scroll:
            direction, _, amount = args.scroll.partition(":")
            report["result"] = inj.scroll(direction, int(amount or 1))
        else:
            print("nothing to inject; pass --keys or --scroll", file=sys.stderr)
            return 2
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    finally:
        inj.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_daemon(args: argparse.Namespace, config: Config) -> int:
    import threading
    stop = threading.Event()
    reload_requested = threading.Event()

    def on_stop(_signum, _frame):
        stop.set()

    def on_reload(_signum, _frame):
        reload_requested.set()

    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGHUP, on_reload)
    LOG.info("elan-gesture %s daemon starting (uid=%d, pid=%d, dry_run=%s)",
             __version__, os.getuid(), os.getpid(), config.dry_run)
    dispatcher = ActionDispatcher(config)
    if not config.dry_run:
        try:
            LOG.info("Niri IPC handshake: %s", dispatcher.ipc.version())
        except Exception as exc:
            LOG.warning("Niri IPC handshake failed (actions will retry): %s", exc)
        try:
            from .inject import Injector
            inj = Injector()
            LOG.info("Injection backend: available=%s wheel=%s socket=%s",
                     inj.available(), inj.wheel_available(), inj.socket_path)
        except Exception as exc:
            LOG.warning("Injection backend unavailable: %s", exc)
    active = sorted(name for name, spec in config.gestures.items() if spec.enabled)
    LOG.info("Daemon-owned gestures: %s", ", ".join(active) or "none")
    backoff = config.device.reconnect_initial_ms / 1000.0
    max_backoff = config.device.reconnect_max_ms / 1000.0
    while not stop.is_set():
        try:
            dev = _open_or_raise(config)
            backoff = config.device.reconnect_initial_ms / 1000.0
            _process_stream(config, dev, fmt="text", dispatcher=dispatcher, stop_flag=stop)
        except (DeviceUnavailable, OSError) as exc:
            LOG.error("device unavailable: %s; retry in %.2fs", exc, backoff)
            stop.wait(backoff)
            backoff = min(backoff * 2, max_backoff)
        finally:
            if reload_requested.is_set():
                reload_requested.clear()
                try:
                    config = load_config(args.config or _default_config_path())
                    dispatcher = ActionDispatcher(config)
                    LOG.info("Configuration reloaded from %s", config.source)
                except ConfigError as exc:
                    LOG.error("SIGHUP reload rejected: %s", exc)
    LOG.info("daemon stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m elan_gesture",
        description="ThinkPad Elan touchpad gestures (Apple trackpad port)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", help="TOML config path (default: ~/.config/elan-gesture/config.toml)")
    p.add_argument("--device", help="override /dev/input/eventN path")
    p.add_argument("--dry-run", action="store_true", help="never execute configured commands")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None)
    p.add_argument("--log-format", choices=["text", "json"], default=None)
    sub = p.add_subparsers(dest="command")
    sub.add_parser("probe", help="print hardware capability report (no event reads)")
    for name, help_text in (("monitor", "read-only live detector"),
                            ("capture", "record raw JSONL events")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--format", choices=["text", "json"], default="text")
        sp.add_argument("--out", help="JSONL capture output path (capture always requires it)")
        sp.add_argument("--force", action="store_true", help="overwrite existing capture")
    rp = sub.add_parser("replay", help="replay JSONL through the production engine")
    rp.add_argument("--in", dest="input", required=True, help="JSONL input path")
    rp.add_argument("--format", choices=["text", "json"], default="text")
    gp = sub.add_parser("gestures", help="print the effective gesture table")
    gp.add_argument("--format", choices=["text", "json"], default="text")
    ip = sub.add_parser("inject-test", help="diagnose the optional injection backend")
    ip.add_argument("--keys", nargs="+", help="key chord, e.g. --keys ctrl c")
    ip.add_argument("--scroll", help="direction[:amount], e.g. down:3")
    ip.add_argument("--yes", action="store_true", help="actually inject (default is dry)")
    ip.add_argument("--timeout-ms", type=int, default=3000)
    sub.add_parser("daemon", help="production daemon; dispatches configured actions")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        args.command = "monitor"
        if not hasattr(args, "format"):
            args.format = "text"
        if not hasattr(args, "out"):
            args.out = None
        if not hasattr(args, "force"):
            args.force = False
    try:
        config = _load(args)
        if args.log_level or args.log_format:
            import dataclasses
            config = dataclasses.replace(config, general={
                **config.general,
                "log_level": args.log_level or config.general["log_level"],
                "log_format": args.log_format or config.general["log_format"],
            })
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    configure(config.general["log_level"], config.general["log_format"])
    handlers = {"probe": cmd_probe, "monitor": cmd_monitor, "capture": cmd_capture,
                "replay": cmd_replay, "gestures": cmd_gestures,
                "inject-test": cmd_inject_test, "daemon": cmd_daemon}
    try:
        return handlers[args.command](args, config)
    except KeyboardInterrupt:
        LOG.info("interrupted")
        return 0
    except (ConfigError, DeviceUnavailable, ValueError) as exc:
        LOG.error("%s failed: %s", args.command, exc)
        return 1
    except OSError as exc:
        LOG.error("%s I/O error: %s", args.command, exc)
        return 1
