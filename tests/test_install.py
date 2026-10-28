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
RELEASE = __version__


def _pinned_sha() -> str:
    for line in INSTALLER.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEFAULT_SHA256="):
            return line.split('"', 2)[1]
    raise AssertionError("install.sh is missing DEFAULT_SHA256")


def test_release_build_is_deterministic_and_installer_pin_matches(tmp_path: Path) -> None:
    """The release installer must pin the exact deterministic archive being published."""
    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
    digest = build_archive(ROOT, archive, RELEASE)
    again = build_archive(ROOT, tmp_path / "again.tar.gz", RELEASE)
    text = INSTALLER.read_text(encoding="utf-8")
    pinned = _pinned_sha()
    assert len(pinned) == 64
    assert all(char in "0123456789abcdef" for char in pinned)
    assert f'VERSION="{RELEASE}"' in text
    assert f"releases/download/v{RELEASE}/devforge-{RELEASE}.tar.gz" in text
    assert digest == again == pinned


def test_installer_installs_into_a_prefix(tmp_path: Path) -> None:
    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
    digest = build_archive(ROOT, archive, RELEASE)
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
    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
    build_archive(ROOT, archive, RELEASE)
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    result = _run_installer(prefix, port, "a" * 64)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (prefix / "share/devforge").exists()


def test_installer_rejects_an_escaping_archive(tmp_path: Path) -> None:
    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
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
    env["DEVFORGE_INSTALL_TUI"] = "0"
    env["DEVFORGE_PREFIX"] = str(prefix)
    env["DEVFORGE_RELEASE_URL"] = f"http://127.0.0.1:{port}/devforge-{RELEASE}.tar.gz"
    env["DEVFORGE_RELEASE_SHA256"] = digest
    env["HOME"] = str(prefix / "home")
    return subprocess.run(
        ["sh", str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_reinstall_keeps_managed_tools(tmp_path: Path) -> None:
    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
    digest = build_archive(ROOT, archive, RELEASE)
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    first = _run_installer(prefix, port, digest)
    assert first.returncode == 0, first.stderr
    kept = prefix / "share/devforge/tools/keep"
    kept.parent.mkdir()
    kept.write_text("safe\n", encoding="utf-8")
    shim = prefix / "share/devforge/shims/node"
    shim.parent.mkdir()
    shim.write_text("#!/bin/sh\n", encoding="utf-8")
    second = _run_installer(prefix, port, digest)
    assert second.returncode == 0, second.stderr
    assert kept.read_text(encoding="utf-8") == "safe\n"
    assert shim.is_file()
    assert (prefix / "share/devforge/devforge/__main__.py").is_file()


def test_old_python_does_not_install_packages(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "python3"
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
    digest = build_archive(ROOT, archive, RELEASE)
    port = _serve(tmp_path)
    prefix = tmp_path / "opt"
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    env["DEVFORGE_INSTALL_TUI"] = "0"
    env["DEVFORGE_PREFIX"] = str(prefix)
    env["DEVFORGE_RELEASE_URL"] = f"http://127.0.0.1:{port}/devforge-{RELEASE}.tar.gz"
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


def test_installer_bootstraps_without_download_hash_or_archive_utilities(tmp_path: Path) -> None:
    import shutil
    import sys

    archive = tmp_path / f"devforge-{RELEASE}.tar.gz"
    digest = build_archive(ROOT, archive, RELEASE)
    port = _serve(tmp_path)
    bindir = tmp_path / "minimal-bin"
    bindir.mkdir()
    for name in ("uname", "id", "mktemp", "rm", "mkdir", "cp", "tr", "chmod"):
        source = shutil.which(name)
        assert source
        (bindir / name).symlink_to(source)
    (bindir / "python3").symlink_to(sys.executable)
    prefix = tmp_path / "minimal-install"
    env = dict(
        os.environ,
        PATH=str(bindir),
        DEVFORGE_INSTALL_TUI="0",
        DEVFORGE_PREFIX=str(prefix),
        DEVFORGE_RELEASE_URL=f"http://127.0.0.1:{port}/devforge-{RELEASE}.tar.gz",
        DEVFORGE_RELEASE_SHA256=digest,
    )
    result = subprocess.run(["/bin/sh", str(INSTALLER)], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # A subsequent PATH change must not replace the bootstrap interpreter.
    (bindir / "python3").unlink()
    (bindir / "python3").write_text("#!/bin/sh\nexit 99\n")
    (bindir / "python3").chmod(0o755)
    result = subprocess.run(
        [str(prefix / "bin/devforge"), "--version"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
