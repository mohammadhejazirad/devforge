"""XDG paths and the owned-directory guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from devforge.core.paths import Paths


def test_defaults_follow_xdg_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    paths = Paths.resolve(home)
    assert paths.data == home / ".local/share/devforge"
    assert paths.state == home / ".local/state/devforge"
    assert paths.logs == paths.state / "logs"
    assert paths.config == home / ".config/devforge"
    assert paths.cache == home / ".cache/devforge"
    assert paths.install_root == paths.data / "tools"


def test_absolute_xdg_overrides_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_DATA_HOME", "relative/ignored")
    paths = Paths.resolve(tmp_path / "home")
    assert paths.logs == tmp_path / "state/devforge/logs"
    assert paths.data == tmp_path / "home/.local/share/devforge"


def test_contains_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    paths = Paths.resolve(tmp_path / "home")
    paths.ensure()
    inside = paths.data / "tools" / "node"
    inside.mkdir(parents=True)
    outside = tmp_path / "etc"
    outside.mkdir()
    assert paths.contains(inside)
    assert paths.contains(inside / ".." / "tools" / "node")
    assert not paths.contains(outside)
    assert not paths.contains(paths.data / ".." / ".." / "etc")
    assert not paths.contains(paths.data)
