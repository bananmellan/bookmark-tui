"""Fetch a web page's <title> using only the standard library.

Best-effort and strictly bounded: a short timeout, a small read cap, and
content-type/content-encoding guards so binary or huge pages never hang
or blow up the TUI. Any failure returns None.
"""

from __future__ import annotations

import gzip
import re
import zlib
from urllib.request import Request, urlopen

_TIMEOUT = 5
_MAX_BYTES = 256 * 1024
_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_CHARSET_RE = re.compile(rb'charset=["\']?([\w.-]+)', re.IGNORECASE)


def fetch_title(url: str) -> str | None:
    """Return the page title for `url`, or None on any failure."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    req = Request(url, headers={"User-Agent": "bookmark-tui/0.1 (+title fetch)"})
    try:
        with urlopen(req, timeout=_TIMEOUT) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if ctype and not ctype.startswith("text/"):
                return None
            cenc = (resp.headers.get("Content-Encoding") or "").lower()
            if cenc not in ("", "identity", "gzip", "deflate", "br"):
                return None
            raw = resp.read(_MAX_BYTES)
    except Exception:
        return None
    if cenc == "gzip":
        try:
            raw = gzip.decompress(raw)
        except Exception:
            return None
    elif cenc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except Exception:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:
                return None
    elif cenc == "br":
        return None  # brotli is not in the stdlib

    m = _TITLE_RE.search(raw)
    if not m:
        return None
    charset = "utf-8"
    cm = _CHARSET_RE.search(ctype.encode("ascii", errors="replace"))
    if not cm:
        cm = _CHARSET_RE.search(raw[:4096])
    if cm:
        charset = cm.group(1).decode("ascii", errors="replace")
    try:
        title = m.group(1).decode(charset, errors="replace")
    except (LookupError, ValueError):
        title = m.group(1).decode("utf-8", errors="replace")
    title = re.sub(r"\s+", " ", title).strip()
    return title or None
