"""Status markers, color, NO_COLOR, and non-TTY streams."""

from __future__ import annotations

import io

import pytest

from devforge.ui import Printer, color_enabled


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_markers_on_a_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    out = io.StringIO()
    err = io.StringIO()
    printer = Printer.create(out=out, err=err)
    printer.ok("installed")
    printer.warn("skipped")
    printer.error("failed")
    assert out.getvalue() == "[ok] installed\n"
    assert err.getvalue() == "[warn] skipped\n[err] failed\n"
    assert "\x1b" not in out.getvalue()
    assert "\x1b" not in err.getvalue()


def test_color_when_stdout_is_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    out = _Tty()
    err = io.StringIO()
    printer = Printer.create(out=out, err=err)
    printer.ok("ready")
    printer.error("failed")
    assert out.getvalue() == "\x1b[32m[ok] ready\x1b[0m\n"
    assert err.getvalue() == "\x1b[31m[err] failed\x1b[0m\n"


def test_no_color_disables_tty_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    stream = _Tty()
    assert color_enabled(stream) is False
    printer = Printer.create(out=stream, err=stream)
    printer.warn("check")
    assert stream.getvalue() == "[warn] check\n"


def test_dumb_terminal_disables_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    stream = _Tty()
    assert color_enabled(stream) is False


def test_force_color_overrides_a_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    stream = io.StringIO()
    printer = Printer.create(out=stream, err=stream)
    printer.ok("ready")
    assert stream.getvalue() == "\x1b[32m[ok] ready\x1b[0m\n"
