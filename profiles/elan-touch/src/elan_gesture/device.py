"""Read-only evdev device discovery, capability probing, and reconnect policy."""
from __future__ import annotations

import ctypes
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evdev import InputDevice, ecodes, util

from .config import ConfigError, DeviceConfig

REQUIRED_ABS = (
    ecodes.ABS_MT_SLOT, ecodes.ABS_MT_TRACKING_ID,
    ecodes.ABS_MT_POSITION_X, ecodes.ABS_MT_POSITION_Y,
)
BTN_TOOLS = (
    ecodes.BTN_TOOL_FINGER, ecodes.BTN_TOOL_DOUBLETAP,
    ecodes.BTN_TOOL_TRIPLETAP, ecodes.BTN_TOOL_QUADTAP,
    ecodes.BTN_TOOL_QUINTTAP,
)


class DeviceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Scale:
    units_per_mm_x: float
    units_per_mm_y: float
    source: str
    bounds_mm: tuple[float, float, float, float]

    @property
    def scale_x(self) -> float:
        return self.units_per_mm_x

    @property
    def scale_y(self) -> float:
        return self.units_per_mm_y


def _hex_id(value: int) -> str:
    return f"{value:04x}"


def find_device(config: DeviceConfig) -> str:
    """Resolve the configured touchpad without assuming a fixed event number."""
    if config.path:
        p = Path(config.path)
        if not p.exists():
            raise DeviceUnavailable(f"configured device {p} does not exist")
        return str(p)
    matches: list[tuple[str, str, int, int]] = []
    for path in util.list_devices():
        try:
            dev = InputDevice(path, readonly=True)
        except (OSError, PermissionError):
            continue
        try:
            name = dev.name
            vendor, product = dev.info.vendor, dev.info.product
            caps = dev.capabilities(absinfo=False)
            has_mt = all(code in caps.get(ecodes.EV_ABS, []) for code in REQUIRED_ABS)
            if not has_mt:
                continue
            exact = (config.match_name in name
                     and vendor == config.match_vendor
                     and product == config.match_product)
            matches.append((path, name, vendor, product))
            if exact:
                return path
        finally:
            dev.close()
    if len(matches) == 1:
        return matches[0][0]
    if matches:
        detail = ", ".join(f"{p} {n!r} {_hex_id(v)}:{_hex_id(pr)}" for p, n, v, pr in matches)
        raise DeviceUnavailable(
            f"no exact match for {config.match_name!r} {_hex_id(config.match_vendor)}:"
            f"{_hex_id(config.match_product)}; MT candidates: {detail}")
    raise DeviceUnavailable(
        "no readable MT input device found; check 'getfacl /dev/input/event*' and the udev uaccess rule")


def open_readonly(path: str) -> InputDevice:
    """Open O_RDONLY|O_NONBLOCK; never O_RDWR, never EVIOCGRAB."""
    try:
        return InputDevice(path, readonly=True)
    except OSError as exc:
        raise DeviceUnavailable(
            f"cannot open {path} read-only: {exc}. Install the bundled udev uaccess rule "
            "and re-login/retrigger the device; do not run this daemon as root."
        ) from exc


def axis_info(dev: InputDevice, code: int) -> dict[str, Any] | None:
    try:
        info = dev.absinfo(code)
    except (OSError, ValueError):
        return None
    return {"value": info.value, "min": info.min, "max": info.max,
            "fuzz": info.fuzz, "flat": info.flat, "resolution": info.resolution}


def derive_scale(config: DeviceConfig, dev: InputDevice | None) -> Scale:
    """Prefer kernel resolution, then configured override, then min/max over physical size.

    Offline replay has no device; in that case units/mm=1 makes recorded raw
    coordinates numerically equal to millimetres (our fixtures use 1 unit/mm).
    """
    ux = float(config.units_per_mm_x or 0)
    uy = float(config.units_per_mm_y or 0)
    source = "config"
    xinfo = axis_info(dev, ecodes.ABS_MT_POSITION_X) if dev else None
    yinfo = axis_info(dev, ecodes.ABS_MT_POSITION_Y) if dev else None
    if not ux and xinfo and xinfo["resolution"] > 0:
        ux = float(xinfo["resolution"])
        source = "kernel"
    if not uy and yinfo and yinfo["resolution"] > 0:
        uy = float(yinfo["resolution"])
    if not ux and xinfo and xinfo["max"] > xinfo["min"]:
        ux = (xinfo["max"] - xinfo["min"]) / config.width_mm
        source = "fallback_minmax"
    if not uy and yinfo and yinfo["max"] > yinfo["min"]:
        uy = (yinfo["max"] - yinfo["min"]) / config.height_mm
    if dev is None and ux <= 0 and uy <= 0:
        ux, uy, source = 1.0, 1.0, "offline_raw_units"
    elif dev is None:
        source = "config_offline"
    if ux <= 0 or uy <= 0:
        raise ConfigError(f"cannot derive positive units/mm (x={ux}, y={uy}, source={source})")
    if xinfo and yinfo:
        bounds = (xinfo["min"] / ux, yinfo["min"] / uy,
                  xinfo["max"] / ux, yinfo["max"] / uy)
    else:
        bounds = (0.0, 0.0, config.width_mm, config.height_mm)
    return Scale(ux, uy, source, bounds)


def capability_report(dev: InputDevice, config: DeviceConfig, path: str) -> dict[str, Any]:
    caps = dev.capabilities(absinfo=False)
    abs_codes = caps.get(ecodes.EV_ABS, [])
    key_codes = caps.get(ecodes.EV_KEY, [])
    abs_details = {ecodes.ABS.get(code, str(code)): axis_info(dev, code)
                   for code in abs_codes if 0x2F <= code <= 0x3D or code in (
                       ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_PRESSURE,
                       ecodes.ABS_DISTANCE, ecodes.ABS_TOOL_WIDTH)}
    scale = derive_scale(config, dev)
    slot = axis_info(dev, ecodes.ABS_MT_SLOT) or {}
    return {
        "path": path,
        "name": dev.name,
        "phys": dev.phys,
        "uniq": dev.uniq,
        "id": {"bustype": f"{dev.info.bustype:04x}",
               "vendor": f"{dev.info.vendor:04x}",
               "product": f"{dev.info.product:04x}",
               "version": f"{dev.info.version:04x}"},
        "open_mode": "O_RDONLY|O_NONBLOCK (no EVIOCGRAB)",
        "device_mode": stat.filemode(os.stat(path).st_mode),
        "owner": f"{os.stat(path).st_uid}:{os.stat(path).st_gid}",
        "ev_types": [ecodes.EV.get(code, str(code)) for code in sorted(caps)],
        "mt_abs_codes": [ecodes.ABS.get(code, str(code)) for code in abs_codes
                         if 0x2F <= code <= 0x3D],
        "btn_tools": [ecodes.BTN.get(code, str(code)) for code in key_codes
                      if code in BTN_TOOLS],
        "abs_details": abs_details,
        "max_mt_slot": slot.get("max"),
        "type_b_mt": all(code in abs_codes for code in REQUIRED_ABS),
        "supports_three_tool_event": ecodes.BTN_TOOL_TRIPLETAP in key_codes,
        "scale": {"units_per_mm_x": scale.units_per_mm_x,
                  "units_per_mm_y": scale.units_per_mm_y,
                  "source": scale.source,
                  "bounds_mm": list(scale.bounds_mm)},
        "physical_mm": {"width": config.width_mm, "height": config.height_mm},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def probe_without_open(config: DeviceConfig) -> dict[str, Any]:
    """Read-only sysfs probe used when /dev/input/eventN is not user-readable."""
    sysfs = Path("/sys/class/input")
    found: list[dict[str, Any]] = []
    for event in sorted(sysfs.glob("event*")):
        try:
            uevent = dict(line.split("=", 1) for line in
                          (event / "device" / "uevent").read_text().splitlines()
                          if "=" in line)
        except OSError:
            continue
        name = uevent.get("NAME", "").strip('"')
        product = uevent.get("PRODUCT", "")
        if config.match_name not in name and product:
            continue
        modalias = uevent.get("MODALIAS", "")
        devnode = "/dev/input/" + event.name
        found.append({
            "path": devnode, "name": name,
            "product": product, "modalias": modalias,
            "ev": uevent.get("EV"), "key": uevent.get("KEY"),
            "abs": uevent.get("ABS"), "prop": uevent.get("PROP"),
            "sysfs": str(event.resolve()),
            "note": "sysfs capability probe only; opening the device requires uaccess/input ACL",
        })
    return {"sysfs_devices": found, "type_b_mt": bool(found),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def borrowed_fd_ioctl_probe(pid: int, fd_number: int, config: DeviceConfig) -> dict[str, Any]:
    """Duplicate an already-open Niri fd for ioctl-only capability probing.

    pidfd_getfd is a same-user kernel syscall.  This is deliberately NOT used
    for event streaming: the duplicate shares Niri's evdev client queue and
    reading it would steal events from the compositor.
    """
    from evdev import device as evdev_device

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        pfd = os.pidfd_open(pid, 0)
    except (AttributeError, OSError) as exc:
        raise DeviceUnavailable(f"pidfd_open({pid}) failed: {exc}") from exc
    syscall_nr = 438  # SYS_pidfd_getfd on x86_64
    dup = libc.syscall(ctypes.c_int(syscall_nr), ctypes.c_int(pfd),
                       ctypes.c_int(fd_number), ctypes.c_uint(0))
    if dup < 0:
        errno = ctypes.get_errno()
        os.close(pfd)
        raise DeviceUnavailable(f"pidfd_getfd failed: {os.strerror(errno)}")
    fd = int(dup)
    dev: Any = object.__new__(evdev_device.InputDevice)
    try:
        path = os.readlink(f"/proc/self/fd/{fd}")
        # Initialize all __slots__ without calling os.open() on the fd path.
        dev.path = path
        dev.fd = fd
        info_res = evdev_device._input.ioctl_devinfo(fd)
        dev.info = evdev_device.DeviceInfo(*info_res[:4])
        dev.name = info_res[4]
        dev.phys = info_res[5]
        dev.uniq = info_res[6]
        dev.version = evdev_device._input.ioctl_EVIOCGVERSION(fd)
        dev._rawcapabilities = evdev_device._input.ioctl_capabilities(fd)
        dev.ff_effects_count = evdev_device._input.ioctl_EVIOCGEFFECTS(fd)
        report = capability_report(dev, config, path)
        report["probe_method"] = "pidfd_getfd (ioctl only, no event reads)"
        report["source_pid"] = pid
        report["source_fd"] = fd_number
        report["open_mode"] = "borrowed O_RDWR fd, ioctl only; no EVIOCGRAB"
        return report
    except OSError as exc:
        raise DeviceUnavailable(f"borrowed fd ioctl failed: {exc}") from exc
    finally:
        # The borrowed fd is closed here, not by InputDevice.__del__.
        dev.fd = -1
        os.close(fd)
        os.close(pfd)


def find_niri_event_fd(pid: int, wanted: str) -> tuple[int, str] | None:
    base = Path(f"/proc/{pid}/fd")
    try:
        entries = list(base.iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target == wanted or target.endswith("/" + Path(wanted).name):
            return int(entry.name), target
    return None


def probe_report(config: DeviceConfig, path_override: str | None = None) -> dict[str, Any]:
    cfg = config
    if path_override:
        cfg = dataclasses.replace(cfg, path=path_override)
    try:
        path = find_device(cfg)
        dev = open_readonly(path)
    except DeviceUnavailable as exc:
        # Fall back to sysfs + borrowed-fd ioctl probe.  Never silently read
        # the compositor's event queue.
        result = probe_without_open(cfg)
        result["direct_open_error"] = str(exc)
        for pid_path in sorted(Path("/proc").glob("[0-9]*"), key=lambda p: int(p.name)):
            try:
                if pid_path.name == "self" or not (pid_path / "comm").exists():
                    continue
                comm = (pid_path / "comm").read_text().strip()
                if comm != "niri":
                    continue
                hit = find_niri_event_fd(int(pid_path.name), cfg.path or "/dev/input/event11")
                if hit:
                    nfd, target = hit
                    try:
                        result["borrowed_ioctl_probe"] = borrowed_fd_ioctl_probe(
                            int(pid_path.name), nfd, cfg)
                        result["borrowed_ioctl_probe"]["fd_target"] = target
                    except (DeviceUnavailable, OSError) as borrow_exc:
                        result["borrowed_ioctl_probe_error"] = str(borrow_exc)
                    break
            except (OSError, ValueError):
                continue
        return result
    try:
        return capability_report(dev, cfg, path)
    finally:
        dev.close()
