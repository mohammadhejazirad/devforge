"""The objects a command is allowed to use.

Tests build a context with a temporary home, a scripted runner, and a memory
fetcher. The real CLI uses the process environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from devforge.core.log import FileLog, null_log
from devforge.core.net import Fetcher, UrllibFetcher
from devforge.core.paths import Paths
from devforge.core.plan import ApplyContext
from devforge.core.runner import Runner, SubprocessRunner
from devforge.core.system import SystemInfo, detect
from devforge.ui import Printer

DATA_ROOT = Path(__file__).resolve().parent / "data"


@dataclass
class Context:
    """Runtime dependencies for one DevForge invocation."""

    printer: Printer
    paths: Paths
    runner: Runner
    fetcher: Fetcher
    log: FileLog
    fs_root: Path
    cwd: Path
    env: Mapping[str, str]
    dry_run: bool
    assume_yes: bool
    as_json: bool
    offline: bool
    euid: int
    data_root: Path = DATA_ROOT
    _system: SystemInfo | None = field(default=None, repr=False)

    def system(self) -> SystemInfo:
        if self._system is None:
            self._system = detect(self.runner, root=self.fs_root, env=self.env, euid=self.euid)
        return self._system

    def apply(self) -> ApplyContext:
        return ApplyContext(
            printer=self.printer,
            paths=self.paths,
            runner=self.runner,
            fetcher=self.fetcher,
            dry_run=self.dry_run,
            assume_yes=self.assume_yes,
            as_json=self.as_json,
            euid=self.euid,
            fs_root=self.fs_root,
            cwd=self.cwd,
            home=self.paths.home,
            env=self.env,
        )


def make_context(
    printer: Printer,
    *,
    paths: Paths | None = None,
    runner: Runner | None = None,
    fetcher: Fetcher | None = None,
    fs_root: Path | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    as_json: bool = False,
    offline: bool = False,
    euid: int | None = None,
    log: FileLog | None = None,
) -> Context:
    """Build a context. Omitted pieces use the real machine."""
    resolved = paths if paths is not None else Paths.resolve()
    file_log = log if log is not None else FileLog(resolved.logs / "devforge.log")
    return Context(
        printer=printer,
        paths=resolved,
        runner=runner if runner is not None else SubprocessRunner(),
        fetcher=fetcher if fetcher is not None else UrllibFetcher(),
        log=file_log,
        fs_root=fs_root if fs_root is not None else Path("/"),
        cwd=cwd if cwd is not None else Path.cwd(),
        env=dict(os.environ if env is None else env),
        dry_run=dry_run,
        assume_yes=assume_yes,
        as_json=as_json,
        offline=offline,
        euid=os.geteuid() if euid is None else euid,
    )


def isolated(
    tmp: Path,
    printer: Printer,
    *,
    runner: Runner | None = None,
    fetcher: Fetcher | None = None,
    fs_root: Path | None = None,
    dry_run: bool = True,
    assume_yes: bool = True,
    euid: int = 1000,
) -> Context:
    """A context whose DevForge directories live under ``tmp``."""
    home = tmp / "home"
    home.mkdir(parents=True, exist_ok=True)
    paths = Paths(
        home=home,
        data=home / ".local" / "share" / "devforge",
        state=home / ".local" / "state" / "devforge",
        config=home / ".config" / "devforge",
        cache=home / ".cache" / "devforge",
    )
    root = fs_root if fs_root is not None else tmp / "root"
    root.mkdir(parents=True, exist_ok=True)
    (root / "etc").mkdir(exist_ok=True)
    (root / "proc").mkdir(exist_ok=True)
    (tmp / "project").mkdir(parents=True, exist_ok=True)
    return Context(
        printer=printer,
        paths=paths,
        runner=runner if runner is not None else SubprocessRunner(),
        fetcher=fetcher if fetcher is not None else UrllibFetcher(),
        log=null_log(),
        fs_root=root,
        cwd=tmp / "project",
        env={"HOME": str(home), "USER": "dev", "SHELL": "/bin/bash", "PATH": "/usr/bin"},
        dry_run=dry_run,
        assume_yes=assume_yes,
        as_json=False,
        offline=True,
        euid=euid,
    )
