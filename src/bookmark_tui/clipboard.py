"""Clipboard reading and URL extraction for bookmark-tui.

Reading the clipboard is best-effort: any failure (no clipboard tool,
empty clipboard, non-text content) returns an empty string and the add
form simply opens blank.

Set BOOKMARK_TUI_CLIPBOARD_CMD to override the reader with a shell
command whose stdout is the clipboard content.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_SCHEMELESS_RE = re.compile(r"^(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?$", re.IGNORECASE)


def is_termux() -> bool:
    """Detect the Termux environment (Android terminal emulator)."""
    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix or "TERMUX_VERSION" in os.environ


def extract_url(text: str) -> str:
    """Return a URL from clipboard text, or "" when there is none.

    Only the first line is considered. http(s) URLs are used as-is;
    scheme-less hosts like "example.com/page" are normalized to
    "https://...". Anything else (prose, file paths, ...) is rejected.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    first_line = stripped.splitlines()[0].strip()
    if _URL_RE.match(first_line):
        return first_line
    if _SCHEMELESS_RE.match(first_line):
        return "https://" + first_line
    return ""


def read_clipboard() -> str:
    """Read the system clipboard as text. "" on any failure."""
    override = os.environ.get("BOOKMARK_TUI_CLIPBOARD_CMD")
    if override:
        return _run(override, shell=True)
    if is_termux():
        return _run("termux-clipboard-get", shell=True)
    if sys.platform == "darwin":
        return _run(["pbpaste"])
    if sys.platform == "win32":
        return _run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"])
    for tool in (
        ["wl-paste", "--no-newline"],
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
    ):
        if shutil.which(tool[0]):
            out = _run(tool)
            if out:
                return out
    return ""


def _run(argv, shell: bool = False) -> str:
    try:
        proc = subprocess.run(
            argv,
            shell=shell,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace")
