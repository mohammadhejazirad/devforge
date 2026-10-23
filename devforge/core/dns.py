"""DNS inspection, presets, and reversible changes.

Presets are chosen by the user. DevForge detects which resolver is in use and
backs up ``resolv.conf`` before writing it. ``dns restore`` puts the backup back.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from devforge.core.runner import Runner

_PRESET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


class DnsError(ValueError):
    """A DNS preset or resolver change cannot be applied safely."""


@dataclass(frozen=True)
class DnsPreset:
    """A named resolver list."""

    name: str
    verified: bool
    description: str
    servers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "verified": self.verified,
            "description": self.description,
            "servers": list(self.servers),
        }


@dataclass(frozen=True)
class Resolver:
    """How this machine applies DNS."""

    kind: str
    detail: str


def load_presets(path: Path) -> dict[str, DnsPreset]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DnsError(f"Could not read DNS presets: {exc}") from exc
    if not isinstance(payload, list):
        raise DnsError("DNS presets must be a JSON list")
    found: dict[str, DnsPreset] = {}
    for item in payload:
        preset = _preset(item)
        found[preset.name] = preset
    return found


def require_preset(path: Path, name: str) -> DnsPreset:
    presets = load_presets(path)
    if name not in presets:
        known = ", ".join(sorted(presets)) or "(none)"
        raise DnsError(f"Unknown DNS preset {name!r}. Known presets: {known}")
    return presets[name]


def detect_resolver(root: Path, runner: Runner) -> Resolver:
    """Decide which mechanism owns DNS. The filesystem root is injectable."""
    resolv = root / "etc" / "resolv.conf"
    try:
        link = os.readlink(resolv) if resolv.is_symlink() else ""
    except OSError:
        link = ""
    resolved = "systemd" in link or (root / "run" / "systemd" / "resolve").exists()
    if resolved and runner.which("resolvectl"):
        return Resolver("systemd-resolved", "resolvectl")
    if runner.which("nmcli"):
        return Resolver("networkmanager", "nmcli")
    if runner.which("resolvconf"):
        return Resolver("resolvconf", "resolvconf")
    return Resolver("static", str(resolv))


def resolv_conf_text(servers: tuple[str, ...]) -> str:
    lines = [
        "# Written by DevForge. Restore the previous file with: devforge dns restore",
        *(f"nameserver {server}" for server in servers),
        "",
    ]
    return "\n".join(lines)


def validate_servers(servers: tuple[str, ...]) -> tuple[str, ...]:
    if not servers:
        raise DnsError("at least one DNS server is required")
    checked: list[str] = []
    for server in servers:
        if _IPV4.fullmatch(server) is None or any(int(part) > 255 for part in server.split(".")):
            raise DnsError(f"refusing DNS server {server!r}; expected an IPv4 address")
        checked.append(server)
    return tuple(checked)


def _preset(item: object) -> DnsPreset:
    if not isinstance(item, dict):
        raise DnsError("a DNS preset must be a JSON object")
    data = cast(dict[str, Any], item)
    name = data.get("name", "")
    if not isinstance(name, str) or _PRESET_NAME.fullmatch(name) is None:
        raise DnsError("a DNS preset has an unsafe name")
    description = data.get("description", "")
    if not isinstance(description, str):
        raise DnsError(f"DNS preset {name} has a non-text description")
    raw_servers = data.get("servers", [])
    if not isinstance(raw_servers, list):
        raise DnsError(f"DNS preset {name} servers must be a list")
    servers = validate_servers(tuple(str(server) for server in raw_servers))
    return DnsPreset(
        name=name,
        verified=bool(data.get("verified", False)),
        description=description,
        servers=servers,
    )
