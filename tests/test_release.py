"""Release parsing, the update cache, and a program update that keeps tools."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_release import build_archive

from devforge import __version__
from devforge.commands.release import cmd_self_update
from devforge.core.net import MemoryFetcher
from devforge.core.release import (
    API_URL,
    ReleaseNotice,
    check_newer,
    is_release_install,
    parse_latest,
    program_root,
    release_asset_url,
)
from devforge.tui import menu
from tests.support import machine

ROOT = Path(__file__).resolve().parents[1]


def _notice(version: str = "9.9.9") -> tuple[ReleaseNotice, dict[str, object]]:
    archive_name = f"devforge-{version}.tar.gz"
    notice = ReleaseNotice(
        version,
        release_asset_url(version, archive_name),
        release_asset_url(version, "SHA256SUMS"),
    )
    payload: dict[str, object] = {
        "tag_name": f"v{version}",
        "assets": [
            {"name": archive_name, "browser_download_url": notice.archive_url},
            {"name": "SHA256SUMS", "browser_download_url": notice.sums_url},
        ],
    }
    return notice, payload


def test_parse_latest_accepts_the_github_asset_url() -> None:
    notice, payload = _notice()
    parsed = parse_latest(json.dumps(payload).encode("utf-8"))
    assert parsed == notice


def test_parse_latest_rejects_a_foreign_url() -> None:
    _notice_obj, payload = _notice()
    assets = payload["assets"]
    assert isinstance(assets, list)
    assets[0] = {
        "name": "devforge-9.9.9.tar.gz",
        "browser_download_url": "https://example.com/devforge-9.9.9.tar.gz",
    }
    try:
        parse_latest(json.dumps(payload).encode("utf-8"))
    except ValueError as exc:
        assert "refusing" in str(exc)
    else:
        raise AssertionError("a foreign archive URL was accepted")


def test_check_newer_is_quiet_when_offline(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian")
    _notice_obj, payload = _notice()
    ctx.fetcher = MemoryFetcher({API_URL: json.dumps(payload).encode("utf-8")})
    assert check_newer(ctx) is None
    assert ctx.fetcher.urls == []


def test_check_newer_caches_the_release(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian")
    ctx.offline = False
    _notice_obj, payload = _notice()
    ctx.fetcher = MemoryFetcher({API_URL: json.dumps(payload).encode("utf-8")})
    found = check_newer(ctx)
    assert found is not None
    assert found.version == "9.9.9"
    ctx.fetcher.urls.clear()
    again = check_newer(ctx)
    assert again is not None and again.version == "9.9.9"
    assert ctx.fetcher.urls == []


def test_checkout_is_not_overwritten(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    ctx.offline = False
    ctx.fetcher = MemoryFetcher({})
    assert is_release_install(program_root()) is False
    assert cmd_self_update(ctx, root=tmp_path / "checkout") == 0
    assert "source checkout" in out.getvalue()
    assert ctx.fetcher.urls == []


def test_self_update_dry_run_does_not_replace_files(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    ctx.offline = False
    install = _install_tree(tmp_path)
    _notice_obj, payload = _notice()
    sums = "ab" * 32 + "  devforge-9.9.9.tar.gz\n"
    ctx.fetcher = MemoryFetcher(
        {
            API_URL: json.dumps(payload).encode("utf-8"),
            _notice_obj.sums_url: sums.encode("utf-8"),
        }
    )
    assert cmd_self_update(ctx, root=install) == 0
    text = out.getvalue()
    assert "Dry run" in text
    assert "leave tools, shims, and shell config in place" in text
    assert (install / "tools" / "keep").read_text(encoding="utf-8") == "safe\n"
    assert "old" in (install / "devforge" / "__main__.py").read_text(encoding="utf-8")
    assert _notice_obj.archive_url not in ctx.fetcher.urls


def test_self_update_replaces_the_program_and_keeps_tools(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian", dry_run=False)
    ctx.dry_run = False
    ctx.offline = False
    install = _install_tree(tmp_path)
    version = "9.9.9"
    archive = tmp_path / f"devforge-{version}.tar.gz"
    digest = build_archive(ROOT, archive, version)
    notice, payload = _notice(version)
    ctx.fetcher = MemoryFetcher(
        {
            API_URL: json.dumps(payload).encode("utf-8"),
            notice.sums_url: f"{digest}  devforge-{version}.tar.gz\n".encode(),
            notice.archive_url: archive.read_bytes(),
        }
    )
    assert cmd_self_update(ctx, root=install) == 0
    assert f"Updated DevForge to {version}" in out.getvalue()
    assert (install / "tools" / "keep").read_text(encoding="utf-8") == "safe\n"
    assert (install / "shims" / "node").is_file()
    assert (install / "env.sh").read_text(encoding="utf-8") == "# env\n"
    assert (install / "VERSION").read_text(encoding="utf-8").strip() == version
    assert (install / "devforge" / "__main__.py").is_file()
    launcher = install.parent.parent / "bin" / "devforge"
    script = launcher.read_text(encoding="utf-8")
    assert "python3 -m devforge" in script
    assert str(install) in script
    assert __version__ == "1.1.0"


def test_menu_update_refuses_a_checkout(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    assert menu(ctx, iter(["g", "", "0"])) == 0
    assert "source checkout" in out.getvalue()


def _install_tree(tmp: Path) -> Path:
    prefix = tmp / "prefix"
    root = prefix / "share" / "devforge"
    package = root / "devforge"
    package.mkdir(parents=True)
    (package / "__main__.py").write_text("print('old')\n", encoding="utf-8")
    (root / ".devforge-install").write_text("devforge\n", encoding="utf-8")
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools" / "keep").write_text("safe\n", encoding="utf-8")
    (root / "shims").mkdir()
    (root / "shims" / "node").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "env.sh").write_text("# env\n", encoding="utf-8")
    launcher = prefix / "bin" / "devforge"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        '#!/bin/sh\nset -eu\nexport PYTHONPATH="old"\nexec python3 -m devforge "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return root
