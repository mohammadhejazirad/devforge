"""Build the deterministic release tarball.

The installer pins the SHA256 of this archive. Rebuild it only when the
packaged files change, then update the checksum in install.sh.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _files(source: Path) -> list[Path]:
    selected: list[Path] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        selected.append(path)
    return selected


def build_archive(source: Path, dest: Path, version: str) -> str:
    """Write ``dest`` and return its SHA256 hex digest."""
    package = source / "devforge"
    license_file = source / "LICENSE"
    if not (package / "__main__.py").is_file():
        raise SystemExit("devforge/__main__.py is missing")
    if not license_file.is_file():
        raise SystemExit("LICENSE is missing")

    prefix = f"devforge-{version}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as raw:  # noqa: SIM117 - nested so this stays valid on Python 3.9
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                _add_bytes(archive, f"{prefix}/VERSION", version.encode("ascii") + b"\n")
                _add_path(archive, f"{prefix}/LICENSE", license_file)
                for path in _files(package):
                    relative = path.relative_to(package).as_posix()
                    _add_path(archive, f"{prefix}/devforge/{relative}", path)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    return digest


def _add_path(archive: tarfile.TarFile, arcname: str, path: Path) -> None:
    info = archive.gettarinfo(str(path), arcname=arcname)
    _normalize(info)
    with path.open("rb") as handle:
        archive.addfile(info, handle)


def _add_bytes(archive: tarfile.TarFile, arcname: str, payload: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(payload)
    _normalize(info)
    archive.addfile(info, io.BytesIO(payload))


def _normalize(info: tarfile.TarInfo) -> None:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = 0o644 if info.isfile() else 0o755


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the DevForge release archive.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    digest = build_archive(args.source, args.output, args.version)
    print(f"{digest}  {args.output}")


if __name__ == "__main__":
    main()
