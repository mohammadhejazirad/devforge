"""Shared types for every managed tool."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Scope(enum.Enum):
    """Where a version selection applies."""

    GLOBAL = "global"
    PROJECT = "project"
    SHELL = "shell"


@dataclass(frozen=True)
class InstalledInfo:
    """What is already on the machine for one tool."""

    name: str
    versions: tuple[str, ...]
    current: str | None
    source: str
    path: str | None
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "versions": list(self.versions),
            "current": self.current,
            "source": self.source,
            "path": self.path,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Check:
    """One doctor result."""

    name: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "message": self.message}


@dataclass(frozen=True)
class ToolStatus:
    """The view `devforge status` prints for one tool."""

    name: str
    summary: str
    category: str
    installed_version: str | None
    installed_versions: tuple[str, ...]
    source: str
    latest: str | None
    update_available: bool | None
    update_kind: str
    path: str | None
    notes: tuple[str, ...]
    can_install: bool
    can_update: bool
    can_switch: bool
    can_uninstall: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "summary": self.summary,
            "category": self.category,
            "installed_version": self.installed_version,
            "installed_versions": list(self.installed_versions),
            "source": self.source,
            "latest": self.latest,
            "update_available": self.update_available,
            "update_kind": self.update_kind,
            "path": self.path,
            "notes": list(self.notes),
            "can_install": self.can_install,
            "can_update": self.can_update,
            "can_switch": self.can_switch,
            "can_uninstall": self.can_uninstall,
        }
