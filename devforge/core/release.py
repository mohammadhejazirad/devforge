"""GitHub release lookup and a safe in-place program update.

The installer copies DevForge to ``<prefix>/share/devforge``. That directory is
also the XDG data directory, so it holds ``tools/``, ``shims/``, and ``env.sh``.
An update replaces the Python package, ``VERSION``, and ``LICENSE`` only.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from devforge import __version__
from devforge.context import Context
from devforge.core.archive import ArchiveError, safe_extract
from devforge.core.net import DownloadError, download, parse_checksum_text
from devforge.core.state import save_json
from devforge.core.versioning import Version, is_valid_version

REPO = "mohammadhejazirad/devforge"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE_NAME = "release-check.json"
CACHE_SECONDS = 6 * 60 * 60
CHECK_TIMEOUT = 2.0


class ReleaseError(ValueError):
    """A release could not be read or applied safely."""


@dataclass(frozen=True)
class ReleaseNotice:
    """One published GitHub release that passed the URL allowlist."""

    version: str
    archive_url: str
    sums_url: str


def program_root() -> Path:
    """Directory that contains the ``devforge`` package."""
    return Path(__file__).resolve().parents[2]


def is_release_install(root: Path | None = None) -> bool:
    """True when ``root`` was created by ``install.sh`` or ``self-update``."""
    base = program_root() if root is None else root
    marker = base / ".devforge-install"
    if not marker.is_file() or marker.is_symlink():
        return False
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return False
    return "devforge" in text.split()


def release_asset_url(version: str, name: str) -> str:
    """The only download URL DevForge will request for a release file."""
    return f"https://github.com/{REPO}/releases/download/v{version}/{name}"


def parse_latest(payload: bytes) -> ReleaseNotice:
    """Read the GitHub releases API body. Rejects any other download host."""
    try:
        parsed: object = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"release response is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("release response must be a JSON object")
    data = cast(dict[str, object], parsed)
    tag = data.get("tag_name")
    assets = data.get("assets")
    if not isinstance(tag, str) or not isinstance(assets, list):
        raise ValueError("release response is missing tag_name or assets")
    version = tag[1:] if tag.startswith("v") else tag
    if not is_valid_version(version):
        raise ValueError(f"release tag {tag!r} is not a version")
    found: dict[str, str] = {}
    for item in assets:
        if not isinstance(item, dict):
            continue
        record = cast(dict[str, object], item)
        name = record.get("name")
        url = record.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            found[name] = url
    archive_name = f"devforge-{version}.tar.gz"
    sums_name = "SHA256SUMS"
    archive_url = found.get(archive_name, "")
    sums_url = found.get(sums_name, "")
    if archive_url != release_asset_url(version, archive_name):
        raise ValueError("refusing an archive URL that is not the GitHub release asset")
    if sums_url != release_asset_url(version, sums_name):
        raise ValueError("refusing a checksum URL that is not the GitHub release asset")
    return ReleaseNotice(version=version, archive_url=archive_url, sums_url=sums_url)


def is_newer(version: str, current: str | None = None) -> bool:
    """True when ``version`` sorts after the running program."""
    baseline = __version__ if current is None else current
    if not is_valid_version(version) or not is_valid_version(baseline):
        return False
    return Version(version) > Version(baseline)


def check_newer(ctx: Context) -> ReleaseNotice | None:
    """Return a newer release, or None.

    Offline mode, a timeout, and a malformed response stay quiet. A successful
    check is cached for six hours so opening the menu stays fast.
    """
    if ctx.offline:
        return None
    cached = _read_cache(ctx)
    now = time.time()
    if cached is not None and now - cached[0] < CACHE_SECONDS:
        return cached[1] if is_newer(cached[1].version) else None
    try:
        notice = parse_latest(ctx.fetcher.get(API_URL, timeout=CHECK_TIMEOUT))
    except (DownloadError, OSError, ValueError, TimeoutError):
        if cached is None:
            return None
        return cached[1] if is_newer(cached[1].version) else None
    _write_cache(ctx, notice)
    return notice if is_newer(notice.version) else None


def fetch_latest(ctx: Context, *, timeout: float = 20) -> ReleaseNotice:
    """Download and parse the latest-release document."""
    try:
        payload = ctx.fetcher.get(API_URL, timeout=timeout)
    except DownloadError as exc:
        raise ReleaseError(f"Could not read the GitHub release: {exc}") from exc
    try:
        return parse_latest(payload)
    except ValueError as exc:
        raise ReleaseError(str(exc)) from exc


def fetch_digest(ctx: Context, notice: ReleaseNotice) -> str:
    """Read ``SHA256SUMS`` and return the archive digest."""
    try:
        payload = ctx.fetcher.get(notice.sums_url, timeout=20)
    except DownloadError as exc:
        raise ReleaseError(f"Could not read the release checksum: {exc}") from exc
    digest = parse_checksum_text(payload.decode("utf-8", "replace"), _archive_name(notice))
    if digest is None:
        raise ReleaseError("The release is missing a SHA256 line for the archive.")
    return digest


def launcher_path(root: Path) -> Path | None:
    """Return the install.sh launcher when it is safe to rewrite, else None."""
    if root.name != "devforge" or root.parent.name != "share":
        return None
    candidate = root.parent.parent / "bin" / "devforge"
    if not candidate.is_file() or candidate.is_symlink():
        return None
    if not _plain_path(candidate) or not _plain_path(root):
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    if "python3 -m devforge" not in text:
        return None
    return candidate


def describe_update(root: Path, notice: ReleaseNotice, digest: str) -> list[str]:
    """Lines that tell the user exactly what an update will change."""
    lines = [
        f"download {notice.archive_url}",
        f"verify SHA256 {digest}",
        f"replace {root / 'devforge'}",
        f"replace {root / 'VERSION'}",
        f"replace {root / 'LICENSE'}",
    ]
    launcher = launcher_path(root)
    if launcher is not None:
        lines.append(f"rewrite {launcher}")
    else:
        lines.append("leave the command launcher unchanged")
    lines.append("leave tools, shims, and shell config in place")
    return lines


def apply_release(ctx: Context, notice: ReleaseNotice, digest: str, root: Path) -> None:
    """Download the archive and replace the program files inside ``root``."""
    if not is_release_install(root):
        raise ReleaseError("refusing to update a directory that is not a DevForge install")
    if not ctx.paths.contains(ctx.paths.cache / "self-update" / "probe"):
        raise ReleaseError("the cache directory is not a DevForge-owned path")
    archive_name = _archive_name(notice)
    archive = ctx.paths.cache / "self-update" / archive_name
    extracted = ctx.paths.cache / "self-update" / notice.version
    try:
        download(
            [notice.archive_url],
            archive,
            sha256=digest,
            fetcher=ctx.fetcher,
            sleep=lambda _seconds: None,
        )
        if extracted.exists() or extracted.is_symlink():
            shutil.rmtree(extracted)
        safe_extract(archive, extracted, fmt="tar.gz")
    except (DownloadError, ArchiveError, OSError) as exc:
        raise ReleaseError(str(exc)) from exc
    package = extracted / "devforge"
    version_file = extracted / "VERSION"
    if not (package / "__main__.py").is_file():
        raise ReleaseError("The archive is missing the program.")
    try:
        got = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ReleaseError(f"The archive is missing VERSION: {exc}") from exc
    if got != notice.version:
        raise ReleaseError(f"archive version is {got}, expected {notice.version}")
    try:
        _swap_package(package, root / "devforge")
        _replace_file(version_file, root / "VERSION")
        license_file = extracted / "LICENSE"
        if license_file.is_file():
            _replace_file(license_file, root / "LICENSE")
        launcher = launcher_path(root)
        if launcher is not None:
            _write_launcher(launcher, root)
    except OSError as exc:
        raise ReleaseError(f"Could not replace the program files: {exc}") from exc


def _archive_name(notice: ReleaseNotice) -> str:
    return f"devforge-{notice.version}.tar.gz"


def _plain_path(path: Path) -> bool:
    text = str(path)
    return not any(char in text for char in ("'", '"', "\\", "\n", " "))


def _swap_package(source: Path, dest: Path) -> None:
    if dest.name != "devforge":
        raise ReleaseError("refusing to replace a directory that is not the devforge package")
    if source.is_symlink() or not source.is_dir():
        raise ReleaseError("release package is not a directory")
    if dest.is_symlink():
        raise ReleaseError("refusing to replace a symlinked package directory")
    parent = dest.parent
    staging = parent / "devforge.new"
    backup = parent / "devforge.old"
    if staging.exists() or staging.is_symlink():
        _remove_owned(staging)
    moved = False
    try:
        shutil.copytree(source, staging)
        if backup.exists() or backup.is_symlink():
            _remove_owned(backup)
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or not dest.is_dir():
                raise ReleaseError("installed package is not a directory")
            dest.rename(backup)
            moved = True
        staging.rename(dest)
    except (OSError, ReleaseError, shutil.Error):
        if moved and not (dest.exists() or dest.is_symlink()) and backup.exists():
            backup.rename(dest)
        if staging.exists() or staging.is_symlink():
            _remove_owned(staging)
        raise
    if backup.exists() or backup.is_symlink():
        _remove_owned(backup)


def _remove_owned(path: Path) -> None:
    if path.name not in {"devforge.new", "devforge.old"}:
        raise ReleaseError(f"refusing to remove {path.name}")
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def _replace_file(source: Path, dest: Path) -> None:
    if dest.name not in {"VERSION", "LICENSE"}:
        raise ReleaseError(f"refusing to replace {dest.name}")
    temporary = dest.with_name(dest.name + ".tmp")
    temporary.write_bytes(source.read_bytes())
    os.replace(temporary, dest)


def _write_launcher(launcher: Path, root: Path) -> None:
    if launcher.name != "devforge":
        raise ReleaseError("refusing to rewrite an unexpected launcher")
    text = (
        "#!/bin/sh\n"
        "set -eu\n"
        f'export PYTHONPATH="{root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
        'exec python3 -m devforge "$@"\n'
    )
    temporary = launcher.with_name(launcher.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o755)
    os.replace(temporary, launcher)


def _read_cache(ctx: Context) -> tuple[float, ReleaseNotice] | None:
    path = ctx.paths.state / CACHE_NAME
    if not path.is_file():
        return None
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    data = cast(dict[str, object], parsed)
    checked = data.get("checked_at")
    version = data.get("version")
    archive_url = data.get("archive_url")
    sums_url = data.get("sums_url")
    if not isinstance(checked, (int, float)):
        return None
    if (
        not isinstance(version, str)
        or not isinstance(archive_url, str)
        or not isinstance(sums_url, str)
    ):
        return None
    if not is_valid_version(version):
        return None
    if archive_url != release_asset_url(version, f"devforge-{version}.tar.gz"):
        return None
    if sums_url != release_asset_url(version, "SHA256SUMS"):
        return None
    return float(checked), ReleaseNotice(version, archive_url, sums_url)


def _write_cache(ctx: Context, notice: ReleaseNotice) -> None:
    try:
        save_json(
            ctx.paths.state / CACHE_NAME,
            {
                "archive_url": notice.archive_url,
                "checked_at": int(time.time()),
                "sums_url": notice.sums_url,
                "version": notice.version,
            },
        )
    except OSError:
        return
