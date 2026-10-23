"""Distro, architecture, init, and desktop/server detection.

Reads an os-release file and optional command output. Both are injectable, so
tests never depend on the host distribution.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from devforge.core.runner import Runner

_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("alpine", ("alpine",)),
    ("arch", ("arch", "manjaro", "endeavouros")),
    ("suse", ("opensuse", "sles", "suse")),
    ("rhel", ("rhel", "fedora", "centos", "rocky", "almalinux", "ol", "amzn")),
    ("debian", ("debian", "ubuntu", "linuxmint", "pop", "raspbian", "kali", "elementary")),
)

_ARCH_MAP = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "i686": "386",
    "i386": "386",
}

_OS_RELEASE_LINE = re.compile(r"^(?P<key>[A-Z0-9_]+)=(?P<value>.*)$")


@dataclass(frozen=True)
class SystemInfo:
    """Facts DevForge detected about this machine."""

    os_id: str
    id_like: str
    version_id: str
    codename: str
    pretty_name: str
    family: str
    arch: str
    libc: str
    init: str
    virtualization: str
    form_factor: str
    package_manager: str
    privilege: str
    disk_free_bytes: int
    memory_bytes: int
    proxies: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "os_id": self.os_id,
            "id_like": self.id_like,
            "version_id": self.version_id,
            "codename": self.codename,
            "pretty_name": self.pretty_name,
            "family": self.family,
            "arch": self.arch,
            "libc": self.libc,
            "init": self.init,
            "virtualization": self.virtualization,
            "form_factor": self.form_factor,
            "package_manager": self.package_manager,
            "privilege": self.privilege,
            "disk_free_bytes": self.disk_free_bytes,
            "memory_bytes": self.memory_bytes,
            "proxies": list(self.proxies),
            "warnings": list(self.warnings),
        }


def parse_os_release(text: str) -> dict[str, str]:
    """Parse an ``/etc/os-release`` document. Quotes are removed."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _OS_RELEASE_LINE.match(line)
        if match is None:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[match.group("key")] = value
    return values


def family_for(os_id: str, id_like: str) -> str:
    """Map an os-release identity onto a package-manager family."""
    raw = f"{os_id} {id_like}".lower().replace(",", " ")
    tokens = {part for part in raw.split() if part}
    expanded = set(tokens)
    for token in tokens:
        for prefix in ("opensuse", "sles"):
            if token.startswith(prefix):
                expanded.add(prefix)
    for family, names in _FAMILY_RULES:
        if expanded & set(names):
            return family
    return "unknown"


def normalize_arch(machine: str) -> str:
    """Return a Debian-style architecture name, or the raw machine string."""
    return _ARCH_MAP.get(machine.strip().lower(), machine.strip().lower() or "unknown")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _libc(root: Path, family: str) -> str:
    if family == "alpine" or (root / "etc" / "alpine-release").is_file():
        return "musl"
    lib = root / "lib"
    try:
        if lib.is_dir() and any(child.name.startswith("ld-musl") for child in lib.iterdir()):
            return "musl"
    except OSError:
        return "glibc"
    return "glibc"


def _init(root: Path) -> str:
    if (root / "run" / "systemd" / "system").is_dir():
        return "systemd"
    for candidate in (root / "sbin" / "openrc", root / "usr" / "sbin" / "openrc"):
        if candidate.exists():
            return "openrc"
    return "other"


def _virtualization(root: Path, runner: Runner, env: Mapping[str, str]) -> str:
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return "wsl"
    proc = _read_text(root / "proc" / "version").lower()
    if "microsoft" in proc or "wsl" in proc:
        return "wsl"
    if (root / ".dockerenv").exists() or (root / "run" / ".containerenv").exists():
        return "container"
    if env.get("container"):
        return "container"
    if runner.which("systemd-detect-virt"):
        result = runner.run(["systemd-detect-virt"], timeout=5)
        name = result.stdout.strip().lower()
        if result.code == 0 and name and name not in {"none", "n/a"}:
            if name in {"docker", "podman", "lxc", "container", "systemd-nspawn"}:
                return "container"
            if name == "wsl":
                return "wsl"
            return "vm"
    return "baremetal"


def _form_factor(env: Mapping[str, str], runner: Runner) -> str:
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY") or env.get("XDG_CURRENT_DESKTOP"):
        return "desktop"
    if runner.which("systemctl"):
        result = runner.run(["systemctl", "get-default"], timeout=5)
        if result.code == 0 and "graphical" in result.stdout:
            return "desktop"
    return "server"


def _privilege(euid: int, runner: Runner) -> str:
    if euid == 0:
        return "root"
    if runner.which("sudo") is None:
        return "none"
    result = runner.run(["sudo", "-n", "true"], timeout=5)
    if result.code == 0:
        return "sudo"
    return "sudo-password"


def _package_manager(family: str, runner: Runner) -> str:
    if family == "debian":
        return "apt" if runner.which("apt-get") else ""
    if family == "rhel":
        if runner.which("dnf"):
            return "dnf"
        if runner.which("yum"):
            return "yum"
        return ""
    if family == "arch":
        return "pacman" if runner.which("pacman") else ""
    if family == "suse":
        return "zypper" if runner.which("zypper") else ""
    if family == "alpine":
        return "apk" if runner.which("apk") else ""
    return ""


def _memory_bytes(root: Path) -> int:
    text = _read_text(root / "proc" / "meminfo")
    for line in text.splitlines():
        if line.lower().startswith("memtotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return 0


def _disk_free(root: Path) -> int:
    try:
        target = root if root.exists() else Path("/")
        return int(shutil.disk_usage(target).free)
    except OSError:
        return 0


def _proxies(env: Mapping[str, str]) -> tuple[str, ...]:
    found: list[str] = []
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
        value = env.get(key, "").strip()
        if value:
            found.append(f"{key}={value}")
    return tuple(found)


def _warnings(
    info_family: str, version_id: str, package_manager: str, disk_free: int
) -> tuple[str, ...]:
    notes: list[str] = []
    if info_family == "unknown":
        notes.append(
            "This distribution is not in the tested set. "
            "Package installs are disabled. Official archives still work."
        )
    elif not package_manager:
        notes.append("The distro family was recognized, but its package manager was not found.")
    if version_id.startswith("26") or version_id.startswith("27"):
        notes.append(
            "This OS release is new. If a distro package is missing, "
            "DevForge falls back to the official archive when one exists."
        )
    if 0 < disk_free < 2 * 1024 * 1024 * 1024:
        notes.append("Less than 2 GiB of free disk space is available.")
    return tuple(notes)


def detect(
    runner: Runner,
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
    euid: int | None = None,
) -> SystemInfo:
    """Detect the machine. ``root`` replaces ``/`` in tests."""
    fs = root if root is not None else Path("/")
    environ = os.environ if env is None else env
    identity = parse_os_release(_read_text(fs / "etc" / "os-release"))
    os_id = identity.get("ID", "")
    id_like = identity.get("ID_LIKE", "")
    version_id = identity.get("VERSION_ID", "")
    pretty = identity.get("PRETTY_NAME", os_id or "unknown")
    family = family_for(os_id, id_like) if os_id or id_like else "unknown"
    codename = identity.get("VERSION_CODENAME", "")
    uname = runner.run(["uname", "-m"], timeout=5)
    machine = (
        uname.stdout.strip() if uname.code == 0 and uname.stdout.strip() else platform.machine()
    )
    arch = normalize_arch(machine)
    libc = _libc(fs, family)
    init = _init(fs)
    virt = _virtualization(fs, runner, environ)
    form = _form_factor(environ, runner)
    manager = _package_manager(family, runner)
    privilege = _privilege(os.geteuid() if euid is None else euid, runner)
    disk_free = _disk_free(fs)
    memory = _memory_bytes(fs)
    warnings = _warnings(family, version_id, manager, disk_free)
    return SystemInfo(
        os_id=os_id or "unknown",
        id_like=id_like,
        version_id=version_id,
        codename=codename,
        pretty_name=pretty,
        family=family,
        arch=arch,
        libc=libc,
        init=init,
        virtualization=virt,
        form_factor=form,
        package_manager=manager,
        privilege=privilege,
        disk_free_bytes=disk_free,
        memory_bytes=memory,
        proxies=_proxies(environ),
        warnings=warnings,
    )
