"""Subprocess wrapper around the `buku` CLI.

Listing uses `buku --nostdin -j -p`, which prints every bookmark as a
JSON array of ``{"index", "uri", "title", "tags", "description"}``
objects. `--nostdin` is always passed (it must be the first argument)
so buku never blocks on a password prompt or confirmation inside the
TUI — a locked database or an interrupted edit fails fast instead.

Opening delegates to `buku --nostdin -o <index>` so the user's browser
configuration (`BROWSER`, `xdg-open`, desktop default) is resolved by
buku exactly as it is on the command line.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable

from .models import BookmarkRef


class BukuCliError(RuntimeError):
    pass


def _run(argv: list[str], timeout: float | None = None) -> str:
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BukuCliError(f"executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BukuCliError(f"timed out: {' '.join(argv)}") from exc
    stderr = proc.stderr.decode("utf-8", errors="replace")
    stdout = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip().splitlines()
        raise BukuCliError(detail[-1] if detail else f"{argv[0]} failed")
    return stdout


def _strip_ansi(text: str) -> str:
    """Remove ANSI color escapes (buku colors diagnostics on stdout)."""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\x1b" and i + 1 < len(text) and text[i + 1] == "[":
            j = i + 2
            while j < len(text) and text[j] not in "m":
                j += 1
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_bookmarks(data: Any) -> list[BookmarkRef]:
    """Parse `buku -j -p` output into bookmark refs, deduped by index."""
    if not isinstance(data, list):
        raise BukuCliError("buku JSON output is not a list")
    bookmarks = []
    seen: set[int] = set()
    for raw in data:
        if not isinstance(raw, dict):
            continue
        index = raw.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            continue
        if index in seen:
            continue
        seen.add(index)
        url = raw.get("uri")
        if not isinstance(url, str) or not url:
            continue
        tags_raw = raw.get("tags")
        tags = ()
        if isinstance(tags_raw, str):
            # buku serializes the tagset as a comma-separated string; the
            # internal form has leading/trailing commas, the JSON form
            # usually does not — strip empties either way.
            tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
        elif isinstance(tags_raw, list):
            tags = tuple(str(t) for t in tags_raw if isinstance(t, str) and t)
        title = raw.get("title")
        description = raw.get("description")
        bookmarks.append(
            BookmarkRef(
                index=index,
                url=url,
                title=title if isinstance(title, str) else "",
                tags=tags,
                description=description if isinstance(description, str) else "",
            )
        )
    return bookmarks


class BukuCli:
    def __init__(
        self,
        binary: str = "buku",
        runner: Callable[[list[str]], str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.binary = binary
        self._runner = runner
        self.timeout = timeout

    def _exec(self, argv: list[str]) -> str:
        if self._runner is not None:
            return self._runner(argv)
        return _run(argv, timeout=self.timeout)

    def list_all(self) -> tuple[list[BookmarkRef], int]:
        """All bookmarks. Returns (bookmarks, raw_count).

        `buku -j -p` writes the JSON array to stdout, but on a brand-new
        database it also prints a "DB file is being created" notice on
        stdout ahead of the array; strip anything before the first '['.
        Diagnostics ("0 records" etc.) go to stderr and are ignored.
        """
        out = self._exec([self.binary, "--nostdin", "-j", "-p"])
        start = out.find("[")
        if start < 0:
            return [], 0
        try:
            data = json.loads(out[start:])
        except json.JSONDecodeError as exc:
            raise BukuCliError(f"invalid JSON from {self.binary} -j -p") from exc
        bookmarks = parse_bookmarks(data)
        return bookmarks, len(bookmarks)

    def open(self, ref: BookmarkRef) -> None:
        """Open the bookmark's URL in the browser via `buku -o <index>`.

        buku exits 0 even when the index does not exist (it prints
        "[ERROR] No matching index" on stderr), so check stderr for an
        error marker and raise to keep the failure visible.
        """
        if self._runner is not None:
            self._exec([self.binary, "--nostdin", "-o", str(ref.index)])
            return
        try:
            proc = subprocess.run(
                [self.binary, "--nostdin", "-o", str(ref.index)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BukuCliError(f"executable not found: {self.binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise BukuCliError(f"timed out: {self.binary} -o {ref.index}") from exc
        stderr = _strip_ansi(proc.stderr.decode("utf-8", errors="replace"))
        if proc.returncode != 0 or "[ERROR]" in stderr:
            detail = stderr.strip().splitlines()
            raise BukuCliError(detail[-1] if detail else f"could not open index {ref.index}")
