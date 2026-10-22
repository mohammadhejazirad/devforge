"""Secret redaction and the state-directory log file."""

from __future__ import annotations

from pathlib import Path

from devforge.core.log import FileLog, redact

_SECRET = "hunter2-secret"


def test_redact_key_value_and_headers() -> None:
    message = (
        f"password={_SECRET} token: {_SECRET} api_key={_SECRET} "
        f"Authorization: Bearer {_SECRET} Authorization: Basic {_SECRET}"
    )
    cleaned = redact(message)
    assert _SECRET not in cleaned
    assert "password=***" in cleaned
    assert "token=***" in cleaned
    assert "api_key=***" in cleaned
    assert "Authorization: Bearer ***" in cleaned
    assert "Authorization: Basic ***" in cleaned


def test_redact_known_token_shapes_and_url_userinfo() -> None:
    github = "ghp_" + "a" * 20
    pat = "github_pat_" + "b" * 20
    aws = "AKIA" + "0" * 16
    message = f"clone https://git:{_SECRET}@example.com keys {github} {pat} {aws}"
    cleaned = redact(message)
    assert _SECRET not in cleaned
    assert github not in cleaned
    assert pat not in cleaned
    assert aws not in cleaned
    assert "https://***:***@example.com" in cleaned


def test_redact_leaves_ordinary_text() -> None:
    message = "token bucket on port 443 for the archive mirror"
    assert redact(message) == message


def test_redact_is_idempotent() -> None:
    once = redact(f"password={_SECRET}")
    assert redact(once) == once


def test_logger_redacts_and_appends(tmp_path: Path) -> None:
    log = FileLog(tmp_path / "devforge.log")
    log.info(f"saving password={_SECRET}")
    log.warning("second line\nwith a break")
    log.error("third")
    text = log.path.read_text(encoding="utf-8")
    assert _SECRET not in text
    assert "password=***" in text
    assert "second line with a break" in text
    lines = text.splitlines()
    assert len(lines) == 3
    assert " INFO " in lines[0]
    assert " WARN " in lines[1]
    assert " ERROR " in lines[2]
    assert log.path.stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700
