from __future__ import annotations

import os
from dataclasses import dataclass


def _env(env, key: str, default: str | None = None) -> str | None:
    value = env.get(key)
    if value:
        return value
    return default


@dataclass(frozen=True)
class Config:
    buku_bin: str = "buku"
    cache_dir: str = ""
    cache_ttl: int = 600
    lock_seconds: int = 300
    debug: bool = False
    verbose: bool = False

    @classmethod
    def from_env(cls, env=None) -> "Config":
        if env is None:
            env = os.environ
        cache_home = env.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache"
        )
        cache_dir = _env(env, "BUKU_TUI_CACHE_DIR")
        if not cache_dir:
            cache_dir = os.path.join(cache_home, "buku-tui")
        return cls(
            buku_bin=_env(env, "BUKU_TUI_BUKU", "buku"),
            cache_dir=cache_dir,
            cache_ttl=int(_env(env, "BUKU_TUI_CACHE_TTL", "600")),
            lock_seconds=int(_env(env, "BUKU_TUI_LOCK_SECONDS", "300")),
            debug=_env(env, "BUKU_TUI_DEBUG", "") == "1",
            verbose=_env(env, "BUKU_TUI_VERBOSE", "") == "1",
        )
