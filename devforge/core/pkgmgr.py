"""Package-manager command builders.

These functions only build argument lists. They never run them. The plan
engine decides whether a command is shown or executed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from devforge.core.runner import Runner

_VERSION_IN_PKG = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


class PackageManagerError(ValueError):
    """The distro has no supported package manager for this operation."""


def require_manager(name: str) -> str:
    if name not in {"apt", "dnf", "yum", "pacman", "zypper", "apk"}:
        raise PackageManagerError(
            "No supported package manager is available on this system. "
            "Official archive installs can still be used where DevForge publishes one."
        )
    return name


def refresh(manager: str) -> list[str]:
    """Command that refreshes package indexes."""
    require_manager(manager)
    commands = {
        "apt": ["apt-get", "update"],
        "dnf": ["dnf", "-y", "makecache"],
        "yum": ["yum", "-y", "makecache"],
        "pacman": ["pacman", "-Sy", "--noconfirm"],
        "zypper": ["zypper", "--non-interactive", "refresh"],
        "apk": ["apk", "update"],
    }
    return list(commands[manager])


def install(manager: str, packages: Sequence[str]) -> list[str]:
    """Command that installs packages idempotently."""
    require_manager(manager)
    names = _names(packages)
    if manager == "apt":
        return ["apt-get", "install", "-y", *names]
    if manager == "dnf":
        return ["dnf", "install", "-y", *names]
    if manager == "yum":
        return ["yum", "install", "-y", *names]
    if manager == "pacman":
        return ["pacman", "-S", "--noconfirm", "--needed", *names]
    if manager == "zypper":
        return ["zypper", "--non-interactive", "install", *names]
    return ["apk", "add", *names]


def upgrade(manager: str, packages: Sequence[str]) -> list[str]:
    """Command that upgrades already installed packages."""
    require_manager(manager)
    names = _names(packages)
    if manager == "apt":
        return ["apt-get", "install", "-y", "--only-upgrade", *names]
    if manager == "dnf":
        return ["dnf", "upgrade", "-y", *names]
    if manager == "yum":
        return ["yum", "upgrade", "-y", *names]
    if manager == "pacman":
        return ["pacman", "-S", "--noconfirm", "--needed", *names]
    if manager == "zypper":
        return ["zypper", "--non-interactive", "update", *names]
    return ["apk", "upgrade", *names]


def remove(manager: str, packages: Sequence[str], *, purge: bool) -> list[str]:
    """Command that removes packages. ``purge`` also drops their config."""
    require_manager(manager)
    names = _names(packages)
    if manager == "apt":
        return ["apt-get", "purge" if purge else "remove", "-y", *names]
    if manager == "dnf":
        return ["dnf", "remove", "-y", *names]
    if manager == "yum":
        return ["yum", "remove", "-y", *names]
    if manager == "pacman":
        flag = "-Rns" if purge else "-R"
        return ["pacman", flag, "--noconfirm", *names]
    if manager == "zypper":
        return ["zypper", "--non-interactive", "remove", *names]
    if purge:
        return ["apk", "del", "--purge", *names]
    return ["apk", "del", *names]


def query(manager: str, package: str) -> list[str]:
    """Read-only command that reports the installed and candidate versions."""
    require_manager(manager)
    name = _names([package])[0]
    if manager == "apt":
        return ["apt-cache", "policy", name]
    if manager in {"dnf", "yum"}:
        return [manager, "info", "-q", name]
    if manager == "pacman":
        return ["pacman", "-Si", name]
    if manager == "zypper":
        return ["zypper", "--non-interactive", "info", name]
    return ["apk", "policy", name]


def parse_query(manager: str, text: str) -> tuple[str | None, str | None]:
    """Return ``(installed, candidate)`` version strings parsed from ``text``.

    Either value is ``None`` when the package manager did not report it.
    Epochs and distro revisions are retained so backported fixes remain visible.
    """
    if manager == "apt":
        return _parse_apt(text)
    if manager in {"dnf", "yum"}:
        return _parse_rpm_info(text)
    if manager == "pacman":
        return _parse_labeled(text, "Version")
    if manager == "zypper":
        return _parse_labeled(text, "Version")
    if manager == "apk":
        return _parse_apk(text)
    return None, None


def lookup_versions(manager: str, package: str, runner: Runner) -> tuple[str | None, str | None]:
    """Run a read-only query and parse it. Failures become unknown versions."""
    if not manager:
        return None, None
    try:
        name = _names([package])[0]
        argv = query(manager, name)
    except PackageManagerError:
        return None, None
    if manager == "pacman":
        installed_result = runner.run(["pacman", "-Q", name], timeout=20)
        installed = None
        if installed_result.code == 0:
            parts = installed_result.stdout.split()
            if len(parts) >= 2:
                installed = _package_version(parts[1])
        candidate_result = runner.run(argv, timeout=20)
        _, candidate = parse_query(manager, candidate_result.stdout)
        return installed, candidate or installed
    result = runner.run(argv, timeout=20)
    if result.code != 0 and not result.stdout:
        return None, None
    return parse_query(manager, result.stdout)


def comparable(value: str | None) -> str | None:
    """Pull a numeric version out of a package-manager version."""
    if not value or value.lower() in {"none", "(none)", ""}:
        return None
    match = _VERSION_IN_PKG.search(value)
    if match is None:
        return None
    return match.group(1)


def _package_version(value: str | None) -> str | None:
    """Retain epochs and distro revisions, including backported security fixes."""
    if not value or value.lower() in {"none", "(none)"}:
        return None
    token = value.strip().rstrip(":")
    return token if re.fullmatch(r"[0-9][A-Za-z0-9.+:~_-]*", token) else None


def _names(packages: Sequence[str]) -> list[str]:
    names: list[str] = []
    for package in packages:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:_-]{0,80}", package):
            raise PackageManagerError(f"refusing unsafe package name {package!r}")
        names.append(package)
    if not names:
        raise PackageManagerError("no packages were given")
    return names


def _parse_apt(text: str) -> tuple[str | None, str | None]:
    installed = None
    candidate = None
    for line in text.splitlines():
        if "Installed:" in line:
            installed = _package_version(line.split(":", 1)[1].strip())
        elif "Candidate:" in line:
            candidate = _package_version(line.split(":", 1)[1].strip())
    return installed, candidate


def _parse_rpm_info(text: str) -> tuple[str | None, str | None]:
    installed: str | None = None
    candidate: str | None = None
    section = ""
    version: str | None = None
    revision = ""
    epoch = ""

    def flush() -> None:
        nonlocal installed, candidate, version, revision, epoch
        if version is None:
            return
        value = f"{epoch + ':' if epoch else ''}{version}{'-' + revision if revision else ''}"
        parsed = _package_version(value)
        if section.startswith("Installed") and installed is None:
            installed = parsed
        elif section.startswith("Available") and parsed is not None:
            candidate = parsed
        version = None
        revision = ""
        epoch = ""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {"Installed Packages", "Available Packages"}:
            flush()
            section = stripped
            continue
        if stripped.lower().startswith("name") and ":" in stripped:
            flush()
        if stripped.lower().startswith("version") and ":" in stripped:
            version = stripped.split(":", 1)[1].strip()
        elif stripped.lower().startswith("release") and ":" in stripped:
            revision = stripped.split(":", 1)[1].strip()
        elif stripped.lower().startswith("epoch") and ":" in stripped:
            epoch = stripped.split(":", 1)[1].strip()
    flush()
    if candidate is None:
        candidate = installed
    return installed, candidate


def _parse_labeled(text: str, label: str) -> tuple[str | None, str | None]:
    found = None
    prefix = label.lower()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix):
            found = _package_version(stripped.split(":", 1)[1] if ":" in stripped else "")
            if found:
                break
    return None, found


def _parse_apk(text: str) -> tuple[str | None, str | None]:
    installed = None
    candidate = None
    previous = ""
    for line in text.splitlines():
        stripped = line.strip()
        if "installed" in stripped.lower() and previous:
            installed = _package_version(previous)
        version = _package_version(stripped)
        if version:
            previous = stripped
            if candidate is None or version != installed:
                candidate = version
    if candidate is None:
        candidate = installed
    return installed, candidate
