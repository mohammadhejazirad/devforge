"""Shared fixtures for command and tool tests."""

from __future__ import annotations

import io
from pathlib import Path

from devforge.context import Context, isolated
from devforge.core.runner import ScriptedRunner
from devforge.ui import Printer

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "os-release"

MANAGERS = {
    "debian": "apt-get",
    "rhel": "dnf",
    "arch": "pacman",
    "suse": "zypper",
    "alpine": "apk",
    "unknown": "",
}


def printer(
    *,
    dry_run: bool = True,
    assume_yes: bool = True,
) -> tuple[Printer, io.StringIO, io.StringIO]:
    out = io.StringIO()
    err = io.StringIO()
    made = Printer.create(out=out, err=err, dry_run=dry_run, assume_yes=assume_yes, no_color=True)
    return made, out, err


def machine(
    tmp: Path,
    fixture: str,
    *,
    family: str,
    dry_run: bool = True,
    arch_machine: str = "x86_64",
) -> tuple[Context, io.StringIO, io.StringIO]:
    """A context whose os-release comes from a fixture and whose commands are scripted."""
    root = tmp / "os"
    (root / "etc").mkdir(parents=True)
    (root / "proc").mkdir()
    release = FIXTURES.joinpath(fixture).read_text(encoding="utf-8")
    (root / "etc" / "os-release").write_text(release, encoding="utf-8")
    if family == "alpine":
        (root / "etc" / "alpine-release").write_text("3.22\n", encoding="utf-8")
    runner = ScriptedRunner()
    runner.when_argv(["uname", "-m"], stdout=arch_machine + "\n")
    binary = MANAGERS[family]
    if binary:
        runner.which_map[binary] = f"/usr/bin/{binary}"
    made, out, err = printer(dry_run=dry_run)
    ctx = isolated(tmp, made, runner=runner, fs_root=root, dry_run=dry_run, assume_yes=True)
    return ctx, out, err
