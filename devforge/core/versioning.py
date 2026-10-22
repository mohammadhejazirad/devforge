"""Version string validation and ordering.

Version strings are the main piece of untrusted data that reaches command
arguments, so they are validated against a strict allowlist before use.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import total_ordering

# A version must start with a digit, contain only digits, letters, dots, dashes,
# underscores, and plus signs, and be reasonably short. Anything else (spaces,
# quotes, semicolons, pipes, slashes, leading dashes) is rejected, so a version
# can never be interpreted as a flag or a shell fragment.
_VERSION_RE = re.compile(r"^v?[0-9][0-9A-Za-z._+-]{0,63}$")

_LEADING_V = re.compile(r"^v(?=\d)")
_SPLIT_RE = re.compile(r"[._+-]")


def is_valid_version(value: object) -> bool:
    """Return True when ``value`` is a safe, well-formed version string."""
    if not isinstance(value, str):
        return False
    return bool(_VERSION_RE.match(value))


def require_version(value: str, field: str = "version") -> str:
    """Return ``value`` unchanged, or raise ``ValueError`` if it is unsafe."""
    if not is_valid_version(value):
        raise ValueError(
            f"invalid {field} {value!r}: expected something like '24.04.1' or '3.12.7'"
        )
    return value


def _parts(value: str) -> tuple[tuple[int, object], ...]:
    text = _LEADING_V.sub("", value.strip(), count=1)
    parts: list[tuple[int, object]] = []
    for chunk in _SPLIT_RE.split(text):
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        elif chunk:
            parts.append((1, chunk.lower()))
    return tuple(parts)


def _compare(left: str, right: str) -> int:
    """Return -1, 0, or 1. A final release sorts after its pre-release."""
    a = _parts(left)
    b = _parts(right)
    for index in range(max(len(a), len(b))):
        if index == len(a):
            return -1 if b[index][0] == 0 else 1
        if index == len(b):
            return 1 if a[index][0] == 0 else -1
        if a[index] != b[index]:
            return -1 if a[index] < b[index] else 1
    return 0


@total_ordering
@dataclass(frozen=True)
class Version:
    """A validated version string with ordering support."""

    value: str

    def __post_init__(self) -> None:
        if not is_valid_version(self.value):
            raise ValueError(f"invalid version {self.value!r}")

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Version):
            return _compare(self.value, other.value) == 0
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Version):
            return _compare(self.value, other.value) < 0
        return NotImplemented

    def __hash__(self) -> int:
        return hash(_parts(self.value))

    @property
    def major(self) -> int:
        match = re.match(r"^(\d+)", self.value)
        return int(match.group(1)) if match else 0

    @property
    def major_minor(self) -> str:
        parts = re.findall(r"\d+", self.value)
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return parts[0] if parts else self.value


def sort_versions(values: Iterable[str], *, reverse: bool = True) -> list[str]:
    """Sort version strings newest-first (or oldest-first) by semantic order."""
    versions = [Version(item) for item in values if is_valid_version(item)]
    return [item.value for item in sorted(versions, reverse=reverse)]
