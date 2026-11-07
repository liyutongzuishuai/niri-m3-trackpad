"""Three-finger tap action: Apple's Look Up / data detector.

Reads the PRIMARY selection first, because that is what a text selection already
publishes on Wayland.  Only when it is empty does this inject Ctrl+C to copy the
focused selection, which is the single place where the daemon synthesises keys.

Nothing here talks to the network.  A ``--search-url`` template can be supplied
to hand the text to a browser instead of showing a notification.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from typing import Callable, Sequence
from urllib.parse import quote

URL_RE = re.compile(r"^(?:https?|ftp)://[^\s<>\"']+$", re.IGNORECASE)
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
DATE_RE = re.compile(
    r"^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
    r"|\d{1,2}\s*(?:年|月)\s*\d{1,2}\s*日?)$"
)
MAX_CHARS = 300


class LookupError(RuntimeError):
    pass


def _run(argv: Sequence[str], timeout: float = 0.5) -> str:
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def selection(kind: str) -> str:
    if not shutil.which("wl-paste"):
        return ""
    if kind == "primary":
        return _run(["wl-paste", "--primary", "--no-newline"]).strip()
    return _run(["wl-paste", "--no-newline"]).strip()


def notify(title: str, body: str, *, app: str = "elan-gesture") -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(["notify-send", "-a", app, title, body],
                       capture_output=True, timeout=3, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def open_url(url: str) -> bool:
    for opener in ("xdg-open", "gio"):
        if shutil.which(opener):
            argv = [opener, url] if opener == "xdg-open" else [opener, "open", url]
            try:
                subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return True
            except OSError:
                continue
    return False


def classify(text: str) -> str:
    if URL_RE.match(text):
        return "url"
    if EMAIL_RE.match(text):
        return "email"
    if DATE_RE.match(text.strip()):
        return "date"
    if PHONE_RE.match(text.strip()):
        return "phone"
    return "text"


def gather(*, allow_inject: bool = True,
           injector: object | None = None,
           sleeper: Callable[[float], None] | None = None) -> tuple[str, str]:
    """Return (text, source).  source is primary / clipboard / inject_copy / none."""
    text = selection("primary")
    if text:
        return text[:MAX_CHARS], "primary"
    text = selection("clipboard")
    if text:
        return text[:MAX_CHARS], "clipboard"
    if not allow_inject:
        return "", "none"
    if injector is None:
        try:
            from .inject import Injector
            injector = Injector()
        except Exception:
            return "", "none"
    try:
        injector.key(["ctrl", "c"])  # type: ignore[attr-defined]
    except Exception:
        return "", "none"
    (sleeper or (lambda s: __import__("time").sleep(s)))(0.12)
    text = selection("clipboard")
    return (text[:MAX_CHARS], "inject_copy") if text else ("", "none")


def perform(text: str, source: str, *, search_url: str = "") -> str:
    if not text:
        notify("查找", "没有可用于查询的选中文本")
        return "lookup:empty"
    kind = classify(text)
    if kind == "url":
        return f"lookup:url:{'opened' if open_url(text) else 'failed'}"
    if search_url:
        target = search_url.replace("{query}", quote(text, safe=""))
        return f"lookup:search:{'opened' if open_url(target) else 'failed'}"
    if kind == "email":
        notify("查找 — 邮件地址", f"{text}\n（{source}）")
        return "lookup:email"
    if kind == "date":
        notify("查找 — 日期", f"{text}\n（{source}）")
        return "lookup:date"
    if kind == "phone":
        notify("查找 — 电话号码", f"{text}\n（{source}）")
        return "lookup:phone"
    notify("查找", f"{text}\n（{source}）")
    return "lookup:text"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m elan_gesture.lookup",
        description="Look up the current selection (Apple three-finger tap)")
    parser.add_argument("--no-inject", action="store_true",
                        help="never synthesise Ctrl+C; use selections only")
    parser.add_argument("--search-url", default=os.environ.get("ELAN_LOOKUP_SEARCH_URL", ""),
                        help="template such as https://example.org/?q={query}")
    parser.add_argument("--print-only", action="store_true",
                        help="print the detected text instead of acting")
    args = parser.parse_args(argv)

    text, source = gather(allow_inject=not args.no_inject)
    if args.print_only:
        print(f"source={source} kind={classify(text) if text else 'none'} text={text!r}")
        return 0
    result = perform(text, source, search_url=args.search_url)
    print(result, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
