"""The bootstrap installer downloads a pinned archive and verifies it."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.build_release import build_archive

from devforge import __version__

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
PINNED_SHA = "0edf8516776568e607898ba573cb8272a841589d1296a4cdfe97fc5affd654c9"


def test_pinned_checksum_matches_the_release_archive(tmp_path: Path) -> None:
    """The public installer stays pinned to the published 1.0.0 archive.

    A rebuild of the current tree is a newer revision, so its digest is not the
    published pin. The pin must still be a real SHA256 and the archive build
    must be deterministic.
    """
    archive = tmp_path / "devforge-1.0.0.tar.gz"
    digest = build_archive(ROOT, archive, "1.0.0")
    again = build_archive(ROOT, tmp_path / "again.tar.gz", "1.0.0")
    text = INSTALLER.read_text(encoding="utf-8")
    assert len(PINNED_SHA) == 64
    assert all(char in "0123456789abcdef" for char in PINNED_SHA)
    assert PINNED_SHA in text
    assert "releases/download/v1.0.0/devforge-1.0.0.tar.gz" in text
    assert digest == again
    assert digest != PINNED_SHA


def test_installer_installs_into_a_prefix(tmp_path: Path) -> None:
    archive = tmp_path / "devforge-1.0.0.tar.gz"
    digest = build_archive(ROOT, archive, "1.0.0")
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    result = _run_installer(prefix, port, digest)
    assert result.returncode == 0, result.stderr
    launcher = prefix / "bin" / "devforge"
    assert launcher.is_file()
    assert (prefix / "share/devforge/.devforge-install").is_file()
    version = subprocess.run(
        [str(launcher), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert version.returncode == 0
    assert version.stdout.strip() == f"devforge {__version__}"


def test_installer_rejects_a_bad_checksum(tmp_path: Path) -> None:
    archive = tmp_path / "devforge-1.0.0.tar.gz"
    build_archive(ROOT, archive, "1.0.0")
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    result = _run_installer(prefix, port, "a" * 64)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (prefix / "share/devforge").exists()


def test_installer_rejects_an_escaping_archive(tmp_path: Path) -> None:
    archive = tmp_path / "devforge-1.0.0.tar.gz"
    with tarfile.open(archive, "w:gz") as packed:
        info = tarfile.TarInfo("../escape")
        payload = b"nope\n"
        info.size = len(payload)
        packed.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    result = _run_installer(prefix, port, digest)
    assert result.returncode != 0
    assert "unexpected member" in result.stderr
    assert not (prefix / "share/devforge").exists()


def _serve(directory: Path) -> int:
    handler = SimpleHTTPRequestHandler
    previous = os.getcwd()
    os.chdir(directory)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    finally:
        os.chdir(previous)

    def serve() -> None:
        os.chdir(directory)
        server.serve_forever()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return int(server.server_address[1])


def _run_installer(prefix: Path, port: int, digest: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DEVFORGE_PREFIX"] = str(prefix)
    env["DEVFORGE_RELEASE_URL"] = f"http://127.0.0.1:{port}/devforge-1.0.0.tar.gz"
    env["DEVFORGE_RELEASE_SHA256"] = digest
    env["HOME"] = str(prefix / "home")
    return subprocess.run(
        ["sh", str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_old_python_does_not_install_packages(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "python3"
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    archive = tmp_path / "devforge-1.0.0.tar.gz"
    digest = build_archive(ROOT, archive, "1.0.0")
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    env["DEVFORGE_PREFIX"] = str(prefix)
    env["DEVFORGE_RELEASE_URL"] = f"http://127.0.0.1:{port}/devforge-1.0.0.tar.gz"
    env["DEVFORGE_RELEASE_SHA256"] = digest
    env["HOME"] = str(tmp_path / "home")
    result = subprocess.run(
        ["sh", str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode != 0
    assert "Python 3.9+" in result.stderr
    assert not (prefix / "share/devforge").exists()
