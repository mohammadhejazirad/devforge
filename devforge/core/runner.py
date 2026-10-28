"""Injectable command execution.

System commands go through a runner so tests can record them instead of
executing them. Arguments are always a list. ``shell=True`` is never used.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import BinaryIO, Protocol


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

    def stream(self, argv: Sequence[str], output: BinaryIO, *, timeout: float = 3600) -> RunResult:
        """Stream binary stdout to a private backup file."""

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
        if not isinstance(arg, str) or "\0" in arg:
            raise RunnerError("command arguments must be strings without NUL bytes")
        if not checked and not arg:
            raise RunnerError("command executable must not be empty")
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
        command_env = dict(os.environ if env is None else env)
        command_env["LC_ALL"] = "C"
        try:
            completed = subprocess.run(
                checked,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=command_env,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(checked, 124, _text(exc.stdout), _text(exc.stderr) or "timed out")
        except OSError as exc:
            return RunResult(checked, 127, "", str(exc))
        return RunResult(checked, completed.returncode, completed.stdout, completed.stderr)

    def stream(self, argv: Sequence[str], output: BinaryIO, *, timeout: float = 3600) -> RunResult:
        import tempfile

        checked = _check_argv(argv)
        # stderr also goes to disk: a large database must not fill process memory.
        with tempfile.TemporaryFile() as errors:
            try:
                result = subprocess.run(
                    checked,
                    stdout=output,
                    stderr=errors,
                    stdin=subprocess.DEVNULL,
                    timeout=timeout,
                    check=False,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
            except OSError as exc:
                return RunResult(checked, 127, "", str(exc))
            errors.seek(0)
            detail = errors.read(65536).decode("utf-8", errors="replace")
        return RunResult(checked, code, "", detail or ("timed out" if code == 124 else ""))

    def which(self, name: str) -> str | None:
        if not name or "/" in name:
            return None
        found = shutil.which(name)
        if found:
            return found
        # Administrative binaries are often outside a desktop user's PATH.
        return shutil.which(name, path="/usr/local/sbin:/usr/sbin:/sbin")


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

    def stream(self, argv: Sequence[str], output: BinaryIO, *, timeout: float = 3600) -> RunResult:
        result = self.run(argv, timeout=timeout)
        output.write(result.stdout.encode())
        return result

    def which(self, name: str) -> str | None:
        return self.which_map.get(name)
