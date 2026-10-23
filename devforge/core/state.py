"""JSON state, atomic writes, and config backups.

The state file records defaults DevForge itself selected. Detection of tools
that were already on the machine does not depend on this file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, cast


class StateError(ValueError):
    """The state file exists but cannot be read safely."""


def load_json(path: Path) -> dict[str, Any]:
    """Return the object in ``path``, or an empty object when it is missing."""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"Could not read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StateError(f"Expected a JSON object in {path}")
    return cast(dict[str, Any], payload)


def save_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace ``path``. The previous file is left in place on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def backup_file(path: Path) -> Path | None:
    """Copy ``path`` to ``path.devforge.bak`` once. Later backups are kept.

    Symlinks are backed up as symlinks so a restore puts the original link back.
    Returns the backup path, or ``None`` when ``path`` does not exist.
    """
    if not path.exists() and not path.is_symlink():
        return None
    destination = Path(str(path) + ".devforge.bak")
    if destination.exists() or destination.is_symlink():
        return destination
    if path.is_symlink():
        destination.symlink_to(os.readlink(path))
        return destination
    shutil.copy2(path, destination)
    return destination


def restore_backup(path: Path) -> bool:
    """Restore ``path`` from its ``.devforge.bak`` copy. Returns whether it did."""
    backup = Path(str(path) + ".devforge.bak")
    if not backup.exists() and not backup.is_symlink():
        return False
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            raise StateError(f"refusing to restore over directory {path}")
        path.unlink()
    if backup.is_symlink():
        path.symlink_to(os.readlink(backup))
    else:
        shutil.copy2(backup, path)
    return True
