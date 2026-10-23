"""Injectable command execution.

System commands go through a runner so tests can record them instead of
executing them. Arguments are always a list. ``shell=True`` is never used.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RunResult:
    """One finished command."""

    argv: tuple[str, ...]
    code: int
    stdout: str
    stderr: str


class RunnerError(RuntimeError):
    """The runner refused a command before starting it."""


class Runner(Protocol):
    """The command interface used by detection, plans, and tests."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> RunResult:
        """Run one command and return its result."""

    def which(self, name: str) -> str | None:
        """Return an executable path, or None when the name is not available."""


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _check_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv:
        raise RunnerError("refusing to run an empty command")
    checked: list[str] = []
    for arg in argv:
        if not isinstance(arg, str) or arg == "":
            raise RunnerError("command arguments must be non-empty strings")
        checked.append(arg)
    return tuple(checked)


class SubprocessRunner:
    """Run commands on the real system, without a shell."""

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> RunResult:
        checked = _check_argv(argv)
        try:
            completed = subprocess.run(
                checked,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=None if env is None else dict(env),
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(checked, 124, _text(exc.stdout), _text(exc.stderr) or "timed out")
        except OSError as exc:
            return RunResult(checked, 127, "", str(exc))
        return RunResult(checked, completed.returncode, completed.stdout, completed.stderr)

    def which(self, name: str) -> str | None:
        if not name or "/" in name:
            return None
        return shutil.which(name)


class ScriptedRunner:
    """Runner used by tests. It never touches the host."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.which_map: dict[str, str | None] = {}
        self._rules: list[tuple[Callable[[tuple[str, ...]], bool], RunResult]] = []
        self.default_code = 0

    def when(self, predicate: Callable[[tuple[str, ...]], bool], result: RunResult) -> None:
        self._rules.append((predicate, result))

    def when_argv(
        self, argv: Sequence[str], *, code: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        expected = tuple(argv)
        self.when(lambda got: got == expected, RunResult(expected, code, stdout, stderr))

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float = 60,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> RunResult:
        del timeout, env, cwd
        checked = _check_argv(argv)
        self.calls.append(checked)
        for predicate, result in self._rules:
            if predicate(checked):
                return result
        return RunResult(checked, self.default_code, "", "")

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)
