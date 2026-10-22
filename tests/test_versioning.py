"""Strict version strings and ordering."""

from __future__ import annotations

import pytest

from devforge.core.versioning import Version, is_valid_version, require_version, sort_versions


@pytest.mark.parametrize(
    "value",
    ["24", "24.11.1", "3.12.7", "1.0.0-rc.1", "1.0+build", "8_1"],
)
def test_accepts_plain_versions(value: str) -> None:
    assert is_valid_version(value)
    assert require_version(value) == value
    assert str(Version(value)) == value


@pytest.mark.parametrize(
    "value",
    ["", " 1.0", "1.0;rm", "1.0 && true", "../1", "-1", "1/2", "a.b", "1" * 65],
)
def test_rejects_unsafe_versions(value: str) -> None:
    assert not is_valid_version(value)
    with pytest.raises(ValueError):
        require_version(value)
    with pytest.raises(ValueError):
        Version(value)


def test_release_sorts_after_prerelease_and_newer_first() -> None:
    assert Version("1.0") > Version("1.0-rc1")
    assert Version("26") > Version("24.11.0")
    assert Version("v1.2.3") == Version("1.2.3")
    ordered = sort_versions(["1.0-rc1", "1.0", "0.9", "not a version"])
    assert ordered == ["1.0", "1.0-rc1", "0.9"]
