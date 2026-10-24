"""Load tool definitions and version indexes from package data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from devforge.core.net import Fetcher
from devforge.core.versioning import is_valid_version, sort_versions

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


class CatalogError(ValueError):
    """Shipped data is missing or malformed."""


@dataclass(frozen=True)
class ArchiveSpec:
    """How to download one official build."""

    fmt: str
    url: str
    checksum_url: str
    checksum_format: str
    arch_map: dict[str, str]
    libc_arch_map: dict[str, dict[str, str]]
    filename: str


@dataclass(frozen=True)
class ToolSpec:
    """One managed tool, loaded from ``data/catalog.json``."""

    name: str
    summary: str
    category: str
    strategy: str
    binaries: tuple[str, ...]
    version_args: tuple[str, ...]
    version_regex: str
    shims: tuple[str, ...]
    project_files: tuple[str, ...]
    packages: dict[str, tuple[str, ...]]
    versioned_packages: dict[str, tuple[str, ...]]
    fallback_packages: dict[str, tuple[str, ...]]
    system_bins: tuple[str, ...]
    alternatives: tuple[tuple[str, str], ...]
    archive: ArchiveSpec | None
    coexist_dirs: tuple[str, ...]
    coexist_env: tuple[str, ...]
    linux_group: str
    services: dict[str, tuple[str, ...]]
    extra_checks: tuple[tuple[str, ...], ...]
    desktop_only: bool
    shim_kind: str
    runtime_env: tuple[tuple[str, str], ...]
    notes: str

    @property
    def tool_key(self) -> str:
        return self.name


@dataclass(frozen=True)
class VersionIndex:
    """Known versions and pinned checksums for one tool."""

    tool: str
    versions: tuple[str, ...]
    lts: str
    latest: str
    sha256: dict[str, dict[str, str]]
    refresh_format: str
    refresh_url: str

    def preferred(self) -> str:
        for candidate in (self.lts, self.latest, *self.versions):
            if candidate and is_valid_version(candidate):
                return candidate
        return ""

    def checksum(self, version: str, arch_key: str) -> str:
        found = self.sha256.get(version, {})
        return found.get(arch_key, "") or found.get("any", "")


def data_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data"


def load_catalog(root: Path | None = None) -> dict[str, ToolSpec]:
    path = (root or data_root()) / "catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Could not read the tool catalog: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
        raise CatalogError("catalog.json must contain a tools list")
    found: dict[str, ToolSpec] = {}
    for item in payload["tools"]:
        spec = _tool(item)
        if spec.name in found:
            raise CatalogError(f"duplicate tool {spec.name}")
        found[spec.name] = spec
    return found


def load_index(root: Path, name: str, *, cache: Path | None = None) -> VersionIndex:
    """Load a version index, preferring the user's refreshed cache."""
    candidates = []
    if cache is not None:
        candidates.append(cache / "versions" / f"{name}.json")
    candidates.append(root / "versions" / f"{name}.json")
    for path in candidates:
        if path.is_file():
            return _index(path, name)
    return VersionIndex(name, (), "", "", {}, "", "")


def save_index(cache: Path, index: VersionIndex) -> None:
    path = cache / "versions" / f"{index.tool}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": index.tool,
        "versions": list(index.versions),
        "lts": index.lts,
        "latest": index.latest,
        "sha256": index.sha256,
        "refresh": {"format": index.refresh_format, "url": index.refresh_url},
    }
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def refresh_index(index: VersionIndex, fetcher: Fetcher) -> VersionIndex:
    """Fetch authoritative releases while retaining checksums for older builds."""
    payload = fetcher.get(index.refresh_url, timeout=20)
    versions, lts, latest, checksums = parse_refresh(index.refresh_format, payload)
    if not versions:
        raise CatalogError(f"Upstream returned no usable versions for {index.tool}.")
    merged = {version: dict(arches) for version, arches in index.sha256.items()}
    for version, arches in checksums.items():
        merged.setdefault(version, {}).update(arches)
    return VersionIndex(
        index.tool,
        tuple(sort_versions(versions)),
        lts,
        latest,
        merged,
        index.refresh_format,
        index.refresh_url,
    )


def parse_refresh(
    fmt: str, payload: bytes
) -> tuple[list[str], str, str, dict[str, dict[str, str]]]:
    """Parse an upstream index. Returns versions, lts, latest, and checksums."""
    text = payload.decode("utf-8", errors="replace").strip()
    if fmt == "plain":
        version = text.splitlines()[0].strip() if text else ""
        if version.startswith("v"):
            version = version[1:]
        if not is_valid_version(version):
            raise CatalogError(f"upstream did not return a version: {text[:80]!r}")
        return [version], "", version, {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"upstream index was not JSON: {exc}") from exc
    if fmt == "node-index":
        return _node_index(data)
    if fmt == "go-index":
        return _go_index(data)
    if fmt == "github":
        return _github_index(data)
    if fmt == "composer":
        return _composer_index(data)
    raise CatalogError(f"unknown version index format {fmt}")


def _tool(item: object) -> ToolSpec:
    if not isinstance(item, dict):
        raise CatalogError("a tool entry must be an object")
    data = cast(dict[str, Any], item)
    name = _require_name(data.get("name"))
    strategy = str(data.get("strategy", ""))
    if strategy not in {"archive", "package", "external", "npm", "rustup"}:
        raise CatalogError(f"{name} has an unknown strategy")
    summary = _text(data.get("summary"), f"{name} summary")
    archive = _archive(name, data.get("archive"))
    return ToolSpec(
        name=name,
        summary=summary,
        category=_text(data.get("category", "other"), f"{name} category"),
        strategy=strategy,
        binaries=_strings(data.get("binaries", [])),
        version_args=_strings(data.get("version_args", [])),
        version_regex=_text(data.get("version_regex", r"(\d+\.\d+\.\d+)"), f"{name} regex"),
        shims=_strings(data.get("shims", [])),
        project_files=_strings(data.get("project_files", [])),
        packages=_package_map(data.get("packages", {})),
        versioned_packages=_package_map(data.get("versioned_packages", {})),
        fallback_packages=_package_map(data.get("fallback_packages", {})),
        system_bins=_strings(data.get("system_bins", [])),
        alternatives=_pairs(data.get("alternatives", [])),
        archive=archive,
        coexist_dirs=_strings(data.get("coexist_dirs", [])),
        coexist_env=_strings(data.get("coexist_env", [])),
        linux_group=_text(data.get("linux_group", ""), f"{name} group"),
        services=_services(data.get("services", {})),
        extra_checks=tuple(tuple(_strings(row)) for row in data.get("extra_checks", [])),
        desktop_only=bool(data.get("desktop_only", False)),
        shim_kind=_text(data.get("shim_kind", "exec"), f"{name} shim"),
        runtime_env=_pairs(data.get("runtime_env", [])),
        notes=_text(data.get("notes", ""), f"{name} notes"),
    )


def _archive(name: str, value: object) -> ArchiveSpec | None:
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise CatalogError(f"{name} archive must be an object")
    data = cast(dict[str, Any], value)
    libc_raw = data.get("libc_arch_map", {})
    libc: dict[str, dict[str, str]] = {}
    if isinstance(libc_raw, dict):
        for key, mapping in libc_raw.items():
            if isinstance(key, str) and isinstance(mapping, dict):
                libc[key] = {str(arch): str(token) for arch, token in mapping.items()}
    arch_raw = data.get("arch_map", {})
    arch_map = (
        {str(key): str(val) for key, val in arch_raw.items()} if isinstance(arch_raw, dict) else {}
    )
    return ArchiveSpec(
        fmt=_text(data.get("format"), f"{name} archive format"),
        url=_text(data.get("url"), f"{name} url"),
        checksum_url=_text(data.get("checksum_url", ""), f"{name} checksum url"),
        checksum_format=_text(data.get("checksum_format", "pinned"), f"{name} checksum format"),
        arch_map=arch_map,
        libc_arch_map=libc,
        filename=_text(data.get("filename", ""), f"{name} filename"),
    )


def _index(path: Path, name: str) -> VersionIndex:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"Could not read versions for {name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError(f"versions for {name} must be an object")
    data = cast(dict[str, Any], payload)
    versions = tuple(item for item in _strings(data.get("versions", [])) if is_valid_version(item))
    sha_raw = data.get("sha256", {})
    sha: dict[str, dict[str, str]] = {}
    if isinstance(sha_raw, dict):
        for version, arches in sha_raw.items():
            if isinstance(version, str) and isinstance(arches, dict):
                sha[version] = {
                    str(arch): str(digest)
                    for arch, digest in arches.items()
                    if isinstance(digest, str)
                }
    refresh = data.get("refresh", {})
    fmt = ""
    url = ""
    if isinstance(refresh, dict):
        fmt = str(refresh.get("format", ""))
        url = str(refresh.get("url", ""))
    lts = str(data.get("lts", ""))
    latest = str(data.get("latest", ""))
    return VersionIndex(
        tool=name,
        versions=tuple(sort_versions(versions)),
        lts=lts if is_valid_version(lts) else "",
        latest=latest if is_valid_version(latest) else "",
        sha256=sha,
        refresh_format=fmt,
        refresh_url=url,
    )


def _node_index(data: object) -> tuple[list[str], str, str, dict[str, dict[str, str]]]:
    if not isinstance(data, list):
        raise CatalogError("Node index was not a list")
    stable: list[str] = []
    lts_versions: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        version = str(item.get("version", "")).removeprefix("v")
        if not is_valid_version(version) or not re.fullmatch(r"\d+(?:\.\d+)*", version):
            continue
        stable.append(version)
        if item.get("lts") not in (False, None, ""):
            lts_versions.append(version)
    ordered = sort_versions(stable)
    return (
        ordered,
        sort_versions(lts_versions)[0] if lts_versions else "",
        ordered[0] if ordered else "",
        {},
    )


def _go_index(data: object) -> tuple[list[str], str, str, dict[str, dict[str, str]]]:
    if not isinstance(data, list):
        raise CatalogError("Go index was not a list")
    versions: list[str] = []
    checksums: dict[str, dict[str, str]] = {}
    latest = ""
    for item in data:
        if not isinstance(item, dict) or not item.get("stable", False):
            continue
        raw = str(item.get("version", ""))
        version = raw[2:] if raw.startswith("go") else raw
        if not is_valid_version(version):
            continue
        versions.append(version)
        if not latest:
            latest = version
        arches: dict[str, str] = {}
        files = item.get("files", [])
        if isinstance(files, list):
            for entry in files:
                if not isinstance(entry, dict):
                    continue
                if entry.get("os") == "linux" and entry.get("kind") == "archive":
                    arch = str(entry.get("arch", ""))
                    digest = str(entry.get("sha256", ""))
                    filename = str(entry.get("filename", ""))
                    if arch in {"amd64", "arm64"} and filename.endswith(".tar.gz") and digest:
                        arches[arch] = digest
        if arches:
            checksums[version] = arches
    return versions, "", latest, checksums


def _github_index(data: object) -> tuple[list[str], str, str, dict[str, dict[str, str]]]:
    if not isinstance(data, dict):
        raise CatalogError("GitHub release was not an object")
    raw = str(data.get("tag_name", ""))
    for prefix in ("refs/tags/", "v", "bun-v"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    if not is_valid_version(raw):
        raise CatalogError(f"GitHub release tag is not a version: {raw!r}")
    return [raw], "", raw, {}


def _composer_index(data: object) -> tuple[list[str], str, str, dict[str, dict[str, str]]]:
    if not isinstance(data, dict):
        raise CatalogError("Composer index was not an object")
    stable = data.get("stable", [])
    if not isinstance(stable, list) or not stable or not isinstance(stable[0], dict):
        raise CatalogError("Composer index has no stable release")
    version = str(stable[0].get("version", ""))
    if not is_valid_version(version):
        raise CatalogError(f"Composer version is not usable: {version!r}")
    return [version], version, version, {}


def _require_name(value: object) -> str:
    if not isinstance(value, str) or _NAME.fullmatch(value) is None:
        raise CatalogError(f"unsafe tool name {value!r}")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise CatalogError(f"{label} must be text")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogError("expected a list of strings")
    return tuple(value)


def _package_map(value: object) -> dict[str, tuple[str, ...]]:
    if value in ({}, None):
        return {}
    if not isinstance(value, dict):
        raise CatalogError("package map must be an object")
    found: dict[str, tuple[str, ...]] = {}
    for key, packages in value.items():
        if not isinstance(key, str) or not isinstance(packages, list):
            raise CatalogError("package map entries are lists of names")
        found[key] = tuple(str(item) for item in packages)
    return found


def _pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise CatalogError("expected a list of pairs")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise CatalogError("expected pairs of two strings")
        pairs.append((str(item[0]), str(item[1])))
    return tuple(pairs)


def _services(value: object) -> dict[str, tuple[str, ...]]:
    if isinstance(value, list):
        return {"default": _strings(value)}
    if isinstance(value, dict):
        return {str(key): _strings(item) for key, item in value.items()}
    if value in ({}, None):
        return {}
    raise CatalogError("services must be a list or an object")
