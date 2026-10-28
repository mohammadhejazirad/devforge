"""CLI help, version, and exit codes."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from devforge import __version__
from devforge.cli import main

ROOT = Path(__file__).resolve().parents[1]


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert "Examples:" in captured.out
    assert "devforge --version" in captured.out
    assert "--dry-run" in captured.out
    assert captured.err == ""


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == f"devforge {__version__}"
    assert captured.err == ""


def test_no_command_exits_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    err = io.StringIO()
    code = main([], out=io.StringIO(), err=err)
    text = err.getvalue()
    assert code == 2
    assert "[err] No command was given." in text
    assert "Examples:" in text
    assert "\033" not in text


def test_flags_alone_are_not_a_command() -> None:
    err = io.StringIO()
    code = main(
        ["--dry-run", "--yes", "--json", "--no-color", "-q", "-vv"],
        out=io.StringIO(),
        err=err,
    )
    assert code == 2
    assert "[err]" in err.getvalue()


def test_no_color_flag_disables_marker_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    err = _Tty()
    code = main(["--no-color"], out=_Tty(), err=err)
    assert code == 2
    assert "\033" not in err.getvalue()
    assert "[err]" in err.getvalue()


def test_auto_color_on_tty_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    err = _Tty()
    code = main([], out=_Tty(), err=err)
    assert code == 2
    assert "\x1b[31m[err]" in err.getvalue()


def test_bare_command_on_a_tty_opens_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen: dict[str, bool] = {}

    def fake(ctx: object, force: bool = False) -> int:
        del ctx
        seen["force"] = force
        return 0

    monkeypatch.setattr("devforge.cli.cmd_tui", fake)
    code = main([], out=_Tty(), err=_Tty())
    assert code == 0
    assert seen["force"] is True


def test_flags_on_a_tty_do_not_open_the_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    err = _Tty()
    code = main(["--dry-run"], out=_Tty(), err=err)
    assert code == 2
    assert "[err] No command was given." in err.getvalue()


def test_help_does_not_write_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    with pytest.raises(SystemExit):
        main(["--help"])
    assert list(tmp_path.rglob("*")) == []


def test_module_help_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "devforge", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Examples:" in result.stdout
    assert result.stderr == ""


def test_version_matches_pyproject() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"textual>=8.2,<9"' in pyproject
    assert f'version = "{__version__}"' in pyproject
