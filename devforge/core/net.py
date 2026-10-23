"""Downloads with retries, checksums, and a test double.

The default fetcher uses the standard library and honors proxy variables.
Tests pass a fetcher that never opens a socket.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

USER_AGENT = "devforge"


class DownloadError(RuntimeError):
    """A download failed or did not match its checksum."""


class Fetcher:
    """Reads a URL and returns the body."""

    def get(self, url: str, timeout: float = 30) -> bytes:
        raise NotImplementedError


class UrllibFetcher(Fetcher):
    """HTTP(S) fetcher. Proxy environment variables are honored by urllib."""

    def get(self, url: str, timeout: float = 30) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return bytes(response.read())
        except urllib.error.URLError as exc:
            raise DownloadError(f"could not download {url}: {exc.reason}") from exc


class MemoryFetcher(Fetcher):
    """Maps URLs to bodies. Used by tests and by the local checksum fixtures."""

    def __init__(self, bodies: dict[str, bytes] | None = None) -> None:
        self.bodies = {} if bodies is None else dict(bodies)
        self.urls: list[str] = []
        self.fail_times = 0

    def get(self, url: str, timeout: float = 30) -> bytes:
        del timeout
        self.urls.append(url)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise DownloadError(f"temporary failure for {url}")
        if url not in self.bodies:
            raise DownloadError(f"no fixture for {url}")
        return self.bodies[url]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def download(
    urls: Sequence[str],
    dest: Path,
    *,
    sha256: str,
    fetcher: Fetcher,
    retries: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Download the first URL that matches ``sha256``.

    A partial file is replaced only after the checksum matches, so a failed
    attempt never leaves a trusted-looking archive behind. ``sha256`` is
    required: DevForge does not install an archive it cannot verify.
    """
    digest = sha256.strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise DownloadError("a SHA256 checksum is required before downloading")
    if not urls:
        raise DownloadError("no download URL was provided")
    pause = time.sleep if sleep is None else sleep
    errors: list[str] = []
    for url in urls:
        for attempt in range(retries):
            try:
                payload = fetcher.get(url)
            except DownloadError as exc:
                errors.append(str(exc))
                pause(min(0.2 * (2**attempt), 1.0))
                continue
            actual = sha256_bytes(payload)
            if actual != digest:
                errors.append(f"checksum mismatch for {url}")
                break
            dest.parent.mkdir(parents=True, exist_ok=True)
            temporary = dest.with_name(dest.name + ".partial")
            temporary.write_bytes(payload)
            temporary.replace(dest)
            return
    detail = errors[-1] if errors else "unknown error"
    raise DownloadError(
        "Download failed. If the network is filtered, choose a mirror with "
        f"`devforge mirror list` and retry. Last error: {detail}"
    )


def parse_checksum_text(text: str, filename: str) -> str | None:
    """Find the SHA256 of ``filename`` in a BSD or GNU checksum file."""
    wanted = filename.strip()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        digest = parts[0].lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            continue
        name = parts[-1].lstrip("*")
        if name.startswith("./"):
            name = name[2:]
        if name == wanted or name.endswith("/" + wanted):
            return digest
    return None
