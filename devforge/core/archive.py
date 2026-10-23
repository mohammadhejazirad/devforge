"""Safe archive extraction.

Members that are absolute, or that climb out of the destination with ``..``,
are refused. A single top-level directory can be stripped so official
tarballs land as ``bin/<tool>`` or ``<tool>``.
"""

from __future__ import annotations

import stat
import tarfile
import zipfile
from pathlib import Path


class ArchiveError(ValueError):
    """The archive is not safe to extract."""


def safe_extract(archive: Path, dest: Path, *, fmt: str) -> None:
    """Extract ``archive`` into ``dest``, which must already be the final directory."""
    dest.mkdir(parents=True, exist_ok=True)
    if fmt == "zip" or archive.name.endswith(".zip"):
        _extract_zip(archive, dest)
        return
    if fmt in {"tar.gz", "tar.xz", "tar"} or archive.name.endswith(
        (".tar.gz", ".tgz", ".tar.xz", ".tar")
    ):
        _extract_tar(archive, dest)
        return
    raise ArchiveError(f"unsupported archive format {fmt}")


def _safe_relative(name: str) -> Path:
    if not name or name.startswith("/") or name.startswith("\\"):
        raise ArchiveError(f"refusing absolute archive member {name!r}")
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ArchiveError(f"refusing escaping archive member {name!r}")
    return relative


def _strip_root(names: list[str]) -> str:
    """Return the single top-level directory, or an empty string to keep names."""
    tops: set[str] = set()
    for name in names:
        if not name or name.endswith("/"):
            continue
        parts = Path(name).parts
        if not parts:
            continue
        tops.add(parts[0])
        if len(parts) == 1:
            return ""
    if len(tops) == 1:
        return next(iter(tops))
    return ""


def _extract_tar(archive: Path, dest: Path) -> None:
    try:
        with tarfile.open(archive, mode="r:*") as handle:
            _extract_tar_members(handle, dest)
    except ArchiveError:
        raise
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveError(f"could not open archive {archive.name}: {exc}") from exc


def _extract_tar_members(handle: tarfile.TarFile, dest: Path) -> None:
    members = [item for item in handle.getmembers() if item.name]
    root = _strip_root([item.name for item in members])
    for item in members:
        relative = _safe_relative(item.name)
        if root and (relative == Path(root) or root in relative.parts[:1]):
            if relative == Path(root):
                continue
            relative = Path(*relative.parts[1:])
        if not relative.parts:
            continue
        target = dest / relative
        if item.issym() or item.islnk():
            raise ArchiveError(f"refusing link in archive: {item.name}")
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not item.isfile():
            raise ArchiveError(f"refusing special file in archive: {item.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = handle.extractfile(item)
        if source is None:
            raise ArchiveError(f"missing member {item.name}")
        with source:
            target.write_bytes(source.read())
        mode = item.mode & 0o777
        if mode & stat.S_IXUSR:
            target.chmod(0o755)
        else:
            target.chmod(0o644)


def _extract_zip(archive: Path, dest: Path) -> None:
    try:
        handle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveError(f"could not open archive {archive.name}: {exc}") from exc
    with handle:
        names = [info.filename for info in handle.infolist()]
        root = _strip_root(names)
        for info in handle.infolist():
            relative = _safe_relative(info.filename)
            if root and relative.parts and relative.parts[0] == root:
                relative = Path(*relative.parts[1:])
            if not relative.parts:
                continue
            target = dest / relative
            if info.is_dir() or info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(handle.read(info))
            unix_mode = (info.external_attr >> 16) & 0o777
            target.chmod(0o755 if unix_mode & stat.S_IXUSR else 0o644)
