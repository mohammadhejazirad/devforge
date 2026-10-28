"""Log file plus secret redaction.

The log lives in the DevForge state directory and never contains secrets: text
is passed through :func:`redact` before it is written.

This module is named ``log`` and not ``logging`` so it can never shadow the
standard library ``logging`` module.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_CREDENTIALS_IN_URL = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*)://[^/\s@:]+:[^/\s@]+@")
_AUTH_HEADER = re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+")
_KEYED_SECRETS = re.compile(
    r"(?i)\b(?P<key>password|passwd|pwd|token|secret|apikey|api_key|"
    r"access_key|secret_key)\b\s*[:=]\s*(?P<value>[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+(?P<value>[A-Za-z0-9._\-]+)")
_GITHUB = re.compile(r"\b(?:ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})\b")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

_REDACTED = "***"


def redact(text: str) -> str:
    """Mask credentials, tokens, and passwords in ``text``."""
    if not text:
        return text
    text = _CREDENTIALS_IN_URL.sub(
        lambda match: f"{match.group('scheme')}://{_REDACTED}:{_REDACTED}@", text
    )
    text = _AUTH_HEADER.sub(rf"\1{_REDACTED}", text)
    text = _KEYED_SECRETS.sub(lambda match: f"{match.group('key')}={_REDACTED}", text)
    text = _BEARER.sub(f"bearer {_REDACTED}", text)
    text = _GITHUB.sub(_REDACTED, text)
    text = _AWS_ACCESS_KEY.sub(_REDACTED, text)
    return text


def _one_line(message: str) -> str:
    return " ".join(part.strip() for part in message.splitlines() if part.strip())


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FileLog:
    """Append-only log file with redaction and a size guard."""

    path: Path
    enabled: bool = True
    max_bytes: int = 2_000_000

    def write(self, level: str, message: str) -> None:
        if not self.enabled:
            return
        line = f"{_timestamp()} {level.upper():<5} {redact(_one_line(message))}\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.parent.chmod(0o700)
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise OSError("refusing nonregular log file")
                os.fchmod(handle.fileno(), 0o600)
                handle.write(line)
        except OSError:
            # Logging must never break the program.
            self.enabled = False

    def debug(self, message: str) -> None:
        self.write("debug", message)

    def info(self, message: str) -> None:
        self.write("info", message)

    def warning(self, message: str) -> None:
        self.write("warn", message)

    def error(self, message: str) -> None:
        self.write("error", message)


def null_log() -> FileLog:
    """A log that discards everything; useful in tests."""
    return FileLog(path=Path("/dev/null"), enabled=False)
