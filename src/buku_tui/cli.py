from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from .app import App
from .bukucli import BukuCli, BukuCliError
from .cache import CACHE_NAME, Cache
from .clipboard import Clipboard
from .config import Config


def _debug_log(cache_dir: Path, message: str) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        log = cache_dir / "debug.log"
        if log.exists() and log.stat().st_size > 200_000:
            log.write_text("", encoding="utf-8")
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%F %T')} {message}\n")
    except OSError:
        pass


def _verbose(config: Config, cache_dir: Path, message: str) -> None:
    if not config.verbose:
        return
    print(f"buku-tui: {message}", file=sys.stderr)
    _debug_log(cache_dir, f"verbose: {message}")


def _spawn_rebuild(config: Config) -> None:
    env = dict(os.environ)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "buku_tui.cli", "--rebuild"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except OSError:
        pass


def build_app(
    config: Config,
    client: BukuCli | None = None,
    clipboard: Clipboard | None = None,
) -> App:
    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = client or BukuCli(config.buku_bin)
    cache = Cache(cache_dir / CACHE_NAME, client, ttl=config.cache_ttl)
    clipboard = clipboard or Clipboard(
        log=(lambda msg: _verbose(config, cache_dir, msg)) if config.verbose else None
    )

    def log(message: str) -> None:
        _verbose(config, cache_dir, message)

    return App(config, cache, client, clipboard, log=log)


def run_tui(config: Config | None = None, env=None) -> int:
    config = config or Config.from_env(env or os.environ)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "buku-tui: interactive terminal required (run it from a terminal)",
            file=sys.stderr,
        )
        return 2
    from .tui import run

    app = build_app(config)
    app.cache.ensure_fresh_async(lambda _cache: _spawn_rebuild(config))
    try:
        run(app)
    except KeyboardInterrupt:
        return 0
    return 0


def run_rebuild(config: Config | None = None, env=None) -> int:
    config = config or Config.from_env(env or os.environ)
    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = Cache(cache_dir / CACHE_NAME, BukuCli(config.buku_bin), ttl=config.cache_ttl)
    _verbose(config, cache_dir, "rebuild: start")
    try:
        refs, raw_count = cache.rebuild()
        _verbose(
            config,
            cache_dir,
            f"rebuild: ok, {len(refs)} bookmarks from {raw_count} raw entries",
        )
    except BukuCliError as exc:
        _verbose(config, cache_dir, f"rebuild failed: {exc}")
        _debug_log(cache_dir, f"background rebuild failed: {exc}")
    try:
        (cache_dir / "rebuild.lock").unlink()
    except OSError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="buku-tui",
        description="Terminal TUI for buku bookmarks.",
    )
    parser.add_argument("--rebuild", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log decision points to stderr and the debug log",
    )
    args = parser.parse_args(argv)
    env = os.environ
    if args.verbose:
        env = dict(env)
        env["BUKU_TUI_VERBOSE"] = "1"
    if args.rebuild:
        return run_rebuild(env=env)
    return run_tui(env=env)


if __name__ == "__main__":
    raise SystemExit(main())
