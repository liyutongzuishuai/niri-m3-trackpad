#!/usr/bin/env python3
"""Static validators for niri-m3-trackpad (stdlib only)."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path


def strip_jsonc(text: str) -> str:
    """Remove // comments while preserving strings."""
    out: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(text):
        c = text[i]
        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def validate_jsonc(path: Path) -> None:
    data = json.loads(strip_jsonc(path.read_text()))
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    for key in ("modules-left", "modules-center", "modules-right"):
        if key not in data:
            raise ValueError(f"missing {key}")
    needed = set(data["modules-left"] + data["modules-center"] + data["modules-right"])
    # Modules with # suffixes refer to include files; only check obvious local custom names.
    declared = {k for k in data if "/" in k or k in {"clock", "tray", "battery"}}
    missing = sorted(m for m in needed if m.startswith("custom/") and "#" not in m and m not in declared)
    if missing:
        raise ValueError("custom modules without definitions: " + ", ".join(missing))


def roles_from_colors(path: Path) -> set[str]:
    text = path.read_text()
    return set(re.findall(r"^\s*@define-color\s+(\w+)", text, re.M))


def css_roles(style: Path, colors: Path) -> None:
    available = roles_from_colors(colors)
    used = set(re.findall(r"@(\w+)", style.read_text()))
    # GTK/waybar defines some pseudo roles; only validate project color roles.
    ignored = {"import", "define-color", "keyframes"}
    missing = sorted((used - available) - ignored)
    if missing:
        raise ValueError("style.css references undefined colors: " + ", ".join(missing))


def hardcoded_home(root: Path) -> None:
    offenders: list[str] = []
    text_suffixes = {".toml", ".jsonc", ".json", ".kdl", ".css", ".sh", ".fish", ".py", ".md", ".txt", ".conf", ".ini"}
    # Runtime artefacts are never committed; skip them by path component so
    # sandbox installs / venvs / backups cannot trip the audit.
    skip_dirs = {".sandbox", ".venv", "__pycache__", ".git", "captures", ".agent-teams"}
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in text_suffixes:
            continue
        parts = set(p.relative_to(root).parts)
        if parts & skip_dirs:
            continue
        # All generated / historical documentation is informational only.
        rel = str(p.relative_to(root))
        if rel.startswith("docs/") or any(part in rel for part in (
            "profiles/niri-dotfiles", "profiles/m3-waybar/README.md",
            "profiles/elan-touch/README.md", "profiles/elan-touch/touchviz/README.md",
            ".test-runtime", "validation-report.md", "README.md", "AGENTS.md")):
            continue
        # Installer, unit template and validator intentionally contain the
        # literal as a replacement source.
        if p.name in {"install.sh", "validate.py", "elan-gesture.service"}:
            continue
        try:
            if "/home/lancetfish" in p.read_text(errors="ignore"):
                offenders.append(str(p.relative_to(root)))
        except OSError:
            pass
    if offenders:
        raise ValueError("hard-coded /home/lancetfish in active files:\n  " + "\n  ".join(offenders[:30]))


def sources(root: Path) -> None:
    data = tomllib.loads((root / "manifest.toml").read_text())
    for name, profile in data["profiles"].items():
        source = root / profile["source"]
        if not source.exists():
            raise ValueError(f"profile {name}: missing source {source}")
    integration = data["integration"]
    for key in ("launcher_source", "template", "config_source", "systemd_unit", "udev_rule"):
        value = integration.get("waybar", {}).get(key) or integration.get("matugen", {}).get(key) or integration.get("elan", {}).get(key)
        if value and not (root / value).exists() and not (root / "profiles/elan-touch" / value).exists():
            raise ValueError(f"integration {key}: missing {value}")


def validate_wheel(root: Path) -> None:
    """The vendored wheel must exist and match the lockfile hash."""
    import hashlib
    import re
    wheels = sorted((root / "vendor/wheels").glob("*.whl"))
    if not wheels:
        raise ValueError("no vendored .whl under vendor/wheels")
    lock = (root / "profiles/elan-touch/requirements.lock").read_text()
    expected = re.search(r"sha256:([0-9a-f]{64})", lock)
    if not expected:
        raise ValueError("requirements.lock has no sha256 hash")
    for wheel in wheels:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if digest != expected.group(1):
            raise ValueError(f"{wheel.name}: sha256 {digest} != {expected.group(1)}")


def all_validators(root: Path) -> None:
    validate_jsonc(root / "profiles/m3-waybar/config.jsonc")
    css_roles(root / "profiles/m3-waybar/style.css", root / "profiles/m3-waybar/colors.css")
    for rel in ("profiles/elan-touch/config/default.toml",
                "profiles/elan-touch/config/examples/four-directions.toml",
                "profiles/elan-touch/config/examples/apple-trackpad.toml",
                "profiles/niri-dotfiles/dotfiles/.config/matugen/config.toml",
                "manifest.toml"):
        tomllib.loads((root / rel).read_text())
    sources(root)
    validate_wheel(root)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate niri-m3-trackpad static assets")
    p.add_argument("--jsonc", type=Path)
    p.add_argument("--css-roles", nargs=2, type=Path, metavar=("STYLE", "COLORS"))
    p.add_argument("--no-hardcoded-home", type=Path)
    p.add_argument("--sources", type=Path)
    p.add_argument("--all", type=Path)
    args = p.parse_args(argv)
    try:
        if args.jsonc: validate_jsonc(args.jsonc)
        if args.css_roles: css_roles(*args.css_roles)
        if args.no_hardcoded_home: hardcoded_home(args.no_hardcoded_home)
        if args.sources: sources(args.sources)
        if args.all: all_validators(args.all)
        if not any(vars(args).values()):
            p.error("no validation requested")
    except Exception as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    print("validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
