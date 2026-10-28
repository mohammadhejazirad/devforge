"""DevForge-owned paths, following the XDG base directory spec.

Every path DevForge writes to is derived here. Destructive code must call
:meth:`Paths.contains` before removing anything, so a computed path can never
escape the DevForge-owned directories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "devforge"


def _home(home: Path | None) -> Path:
    if home is not None:
        return home.expanduser()
    env_home = os.environ.get("HOME")
    if env_home:
        return Path(env_home).expanduser()
    return Path.home()


def _xdg_root(env_var: str, fallback: Path) -> Path:
    value = os.environ.get(env_var, "").strip()
    if value and os.path.isabs(value):
        return Path(value)
    return fallback


@dataclass(frozen=True)
class Paths:
    """Resolved DevForge directories.

    Construct with :func:`Paths.resolve`, or build one directly in tests with a
    temporary home directory.
    """

    home: Path
    data: Path
    state: Path
    config: Path
    cache: Path

    @classmethod
    def resolve(cls, home: Path | None = None) -> Paths:
        base = _home(home)
        data = _xdg_root("XDG_DATA_HOME", base / ".local" / "share") / APP_NAME
        state = _xdg_root("XDG_STATE_HOME", base / ".local" / "state") / APP_NAME
        config = _xdg_root("XDG_CONFIG_HOME", base / ".config") / APP_NAME
        cache = _xdg_root("XDG_CACHE_HOME", base / ".cache") / APP_NAME
        return cls(home=base, data=data, state=state, config=config, cache=cache)

    @property
    def logs(self) -> Path:
        return self.state / "logs"

    @property
    def state_db(self) -> Path:
        return self.state / "state.json"

    @property
    def config_file(self) -> Path:
        return self.config / "config.json"

    @property
    def install_root(self) -> Path:
        """Where DevForge keeps the toolchains it manages."""
        return self.data / "tools"

    @property
    def shims(self) -> Path:
        """Directory prepended to PATH. One executable shim per tool."""
        return self.data / "shims"

    @property
    def env_file(self) -> Path:
        """Shell fragment sourced by shims (mirrors, GOPROXY, and similar)."""
        return self.data / "env.sh"

    def owned_roots(self) -> tuple[Path, ...]:
        return (self.data, self.state, self.config, self.cache)

    def contains(self, candidate: Path) -> bool:
        """Return True when ``candidate`` is inside a DevForge-owned directory.

        Paths are resolved first, so ``..`` segments and symlinked parents
        cannot be used to escape the owned roots.
        """
        try:
            target = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError):
            return False
        for root in self.owned_roots():
            try:
                resolved_root = root.expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            if target != resolved_root and resolved_root in target.parents:
                return True
        return False

    def ensure(self, *directories: Path) -> None:
        """Create the given directories (defaults to every owned root)."""
        targets = directories or self.owned_roots()
        for directory in targets:
            directory.mkdir(parents=True, exist_ok=True)
