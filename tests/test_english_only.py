"""The program package stays ASCII English."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "devforge"


def test_program_sources_are_ascii() -> None:
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if any(ord(char) > 127 for char in line):
                relative = path.relative_to(ROOT)
                offenders.append(f"{relative}:{number}")
    assert offenders == []
