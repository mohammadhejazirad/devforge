"""Terminal output and prompting.

Plain ASCII markers, optional color, and no escape codes when the stream is not
a TTY or when color is disabled via ``NO_COLOR``, ``TERM=dumb``, or
``--no-color``.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import IO

from devforge import strings as s

_RESET = "\x1b[0m"
_CODES = {
    "ok": "\x1b[32m",
    "warn": "\x1b[33m",
    "err": "\x1b[31m",
    "info": "\x1b[38;5;75m",
    "step": "\x1b[1;38;5;141m",
    "detail": "\x1b[2m",
    "emphasis": "\x1b[1m",
}


def color_enabled(
    stream: IO[str],
    *,
    no_color_flag: bool = False,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Decide whether ANSI color should be used for ``stream``."""
    if no_color_flag:
        return False
    environ = os.environ if env is None else env
    if "NO_COLOR" in environ:
        return False
    if environ.get("TERM", "") == "dumb":
        return False
    if environ.get("FORCE_COLOR"):
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


@dataclass
class Printer:
    """Writes DevForge output with consistent markers and optional color."""

    stream: IO[str]
    error_stream: IO[str]
    color: bool = False
    quiet: bool = False
    verbose: int = 0
    assume_yes: bool = False
    dry_run: bool = False

    @classmethod
    def create(
        cls,
        *,
        no_color: bool = False,
        quiet: bool = False,
        verbose: int = 0,
        assume_yes: bool = False,
        dry_run: bool = False,
        out: IO[str] | None = None,
        err: IO[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Printer:
        out = out if out is not None else sys.stdout
        err = err if err is not None else sys.stderr
        return cls(
            stream=out,
            error_stream=err,
            color=color_enabled(out, no_color_flag=no_color, env=env),
            quiet=quiet,
            verbose=verbose,
            assume_yes=assume_yes,
            dry_run=dry_run,
        )

    def _emit(self, text: str, *, style: str = "", stream: IO[str] | None = None) -> None:
        target = stream if stream is not None else self.stream
        if self.color and style in _CODES:
            target.write(f"{_CODES[style]}{text}{_RESET}\n")
        else:
            target.write(f"{text}\n")
        with contextlib.suppress(AttributeError, ValueError):
            target.flush()

    def raw(self, text: str = "") -> None:
        if not self.quiet:
            self._emit(text)

    def heading(self, title: str, subtitle: str = "") -> None:
        if not self.quiet:
            self._emit("+" + "-" * 66 + "+", style="detail")
            self._emit("  " + title, style="step")
            if subtitle:
                self._emit("  " + subtitle, style="detail")
            self._emit("+" + "-" * 66 + "+", style="detail")

    def info(self, text: str) -> None:
        if not self.quiet:
            self._emit(f"{s.MARK_INFO} {text}", style="info")

    def ok(self, text: str) -> None:
        if not self.quiet:
            self._emit(f"{s.MARK_OK} {text}", style="ok")

    def warn(self, text: str) -> None:
        self._emit(f"{s.MARK_WARN} {text}", style="warn", stream=self.error_stream)

    def error(self, text: str) -> None:
        self._emit(f"{s.MARK_ERR} {text}", style="err", stream=self.error_stream)

    def step(self, text: str) -> None:
        if not self.quiet:
            self._emit(f"{s.MARK_STEP} {text}", style="step")

    def detail(self, text: str) -> None:
        if self.verbose >= 1 and not self.quiet:
            self._emit(f"    {text}", style="detail")

    def plan_line(self, index: int, text: str) -> None:
        if not self.quiet:
            self._emit(f"  {index}. {text}")

    def command_line(self, argv: Sequence[str]) -> None:
        if self.verbose >= 1:
            self.detail("$ " + " ".join(argv))

    def confirm(self, question: str = s.PROMPT_CONFIRM, *, default: bool = False) -> bool:
        """Ask a yes/no question. Returns the default when confirmation is skipped."""
        if self.assume_yes:
            return True
        try:
            interactive = self.stream.isatty()
        except (AttributeError, ValueError):
            interactive = False
        if not interactive:
            self.warn(s.WARN_NO_TTY)
            return False
        suffix = " [Y/n] " if default else " [y/N] "
        self.stream.write(question + suffix)
        self.stream.flush()
        try:
            answer = input().strip().lower()
        except EOFError:
            return False
        if not answer:
            return default
        return answer in {"y", "yes"}

    def pause(self, prompt: str = s.PROMPT_PRESS_ENTER) -> None:
        if self.assume_yes or not self.stream.isatty():
            return
        self.stream.write(prompt + " ")
        self.stream.flush()
        with contextlib.suppress(EOFError):
            input()
