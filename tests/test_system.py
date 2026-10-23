"""Distro detection from os-release fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from devforge.core.runner import ScriptedRunner
from devforge.core.system import detect
from tests.support import FIXTURES

EXPECTED = {
    "debian-12": "debian",
    "debian-13": "debian",
    "ubuntu-22.04": "debian",
    "ubuntu-24.04": "debian",
    "ubuntu-26.04": "debian",
    "fedora": "rhel",
    "rocky": "rhel",
    "almalinux": "rhel",
    "centos": "rhel",
    "rhel": "rhel",
    "arch": "arch",
    "manjaro": "arch",
    "opensuse-leap": "suse",
    "opensuse-tumbleweed": "suse",
    "alpine": "alpine",
    "linuxmint": "debian",
    "pop": "debian",
    "unknown": "unknown",
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_family_from_fixture(name: str, tmp_path: Path) -> None:
    root = tmp_path / name
    (root / "etc").mkdir(parents=True)
    (root / "proc").mkdir()
    release = (FIXTURES / name).read_text(encoding="utf-8")
    (root / "etc" / "os-release").write_text(release, encoding="utf-8")
    if name == "alpine":
        (root / "etc" / "alpine-release").write_text("3.22\n", encoding="utf-8")
    runner = ScriptedRunner()
    runner.when_argv(["uname", "-m"], stdout="x86_64\n")
    info = detect(runner, root=root, env={"PATH": "/usr/bin"}, euid=1000)
    assert info.family == EXPECTED[name]
    assert info.arch == "amd64"
    assert info.libc == ("musl" if name == "alpine" else "glibc")
    assert info.privilege == "none"
    if name == "unknown":
        assert any("not in the tested set" in note for note in info.warnings)
    if name == "ubuntu-26.04":
        assert any("new" in note for note in info.warnings)


def test_arm_and_wsl(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "etc").mkdir(parents=True)
    (root / "proc").mkdir()
    release = (FIXTURES / "ubuntu-24.04").read_text(encoding="utf-8")
    (root / "etc" / "os-release").write_text(release, encoding="utf-8")
    (root / "run" / "systemd" / "system").mkdir(parents=True)
    runner = ScriptedRunner()
    runner.when_argv(["uname", "-m"], stdout="aarch64\n")
    runner.which_map["apt-get"] = "/usr/bin/apt-get"
    info = detect(
        runner,
        root=root,
        env={"PATH": "/usr/bin", "WSL_DISTRO_NAME": "Ubuntu", "DISPLAY": ":0"},
        euid=0,
    )
    assert info.arch == "arm64"
    assert info.init == "systemd"
    assert info.virtualization == "wsl"
    assert info.form_factor == "desktop"
    assert info.privilege == "root"
    assert info.package_manager == "apt"
