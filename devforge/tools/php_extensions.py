"""PHP extension packages for the PHP version that is already installed.

Package names keep the installed major.minor line. PHP 8.5.12 selects
``php8.5-*`` on Debian, never ``php8.4-*`` or the unversioned ``php-*`` names.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from devforge.context import Context
from devforge.core.pkgmgr import PackageManagerError, install, refresh
from devforge.core.plan import Plan, Step
from devforge.core.versioning import is_valid_version

_SUFFIX = re.compile(r"^[a-z0-9][a-z0-9+._-]{0,40}$")
_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+._-]{0,80}$")


class PhpExtensionError(ValueError):
    """The extension catalog or the installed PHP version cannot be used."""


@dataclass(frozen=True)
class PhpExtension:
    """One extension and the packages that implement it on this machine."""

    name: str
    summary: str
    packages: tuple[str, ...]
    installed: bool


@dataclass(frozen=True)
class PhpExtensionCategory:
    """A menu group such as Databases or Cache."""

    label: str
    extensions: tuple[PhpExtension, ...]


@dataclass(frozen=True)
class PhpExtensionCatalog:
    """Every extension DevForge can install for one PHP line."""

    version: str
    line: str
    family: str
    categories: tuple[PhpExtensionCategory, ...]

    def packages_for(self, names: tuple[str, ...] | None) -> tuple[str, ...]:
        """Packages for ``names``, or every extension when ``names`` is None."""
        wanted = None if names is None else set(names)
        found: list[str] = []
        seen: set[str] = set()
        for category in self.categories:
            for extension in category.extensions:
                if wanted is not None and extension.name not in wanted:
                    continue
                for package in extension.packages:
                    if package not in seen:
                        seen.add(package)
                        found.append(package)
        return tuple(found)


def load_php_extensions(ctx: Context, version: str) -> PhpExtensionCatalog:
    """Build the menu for the installed PHP version."""
    if not is_valid_version(version):
        raise PhpExtensionError(f"Installed PHP version {version!r} is not usable.")
    line = _line(version)
    family = ctx.system().family
    payload = _read_catalog(ctx.data_root / "php-extensions.json")
    prefixes = payload.get("prefix")
    categories = payload.get("categories")
    if not isinstance(prefixes, dict) or not isinstance(categories, list):
        raise PhpExtensionError("PHP extension catalog is malformed.")
    raw_prefix = prefixes.get(family)
    if not isinstance(raw_prefix, str) or not raw_prefix:
        raise PhpExtensionError(f"PHP extensions have no packages for the {family} family.")
    expanded = _expand_prefix(raw_prefix, version)
    indexed = _query(ctx, _candidate_packages(categories, family, expanded))
    built: list[PhpExtensionCategory] = []
    for category in categories:
        if not isinstance(category, dict):
            raise PhpExtensionError("PHP extension catalog is malformed.")
        item = cast(dict[str, object], category)
        label = item.get("label")
        rows = item.get("extensions")
        if not isinstance(label, str) or not isinstance(rows, list):
            raise PhpExtensionError("PHP extension catalog is malformed.")
        extensions: list[PhpExtension] = []
        for row in rows:
            parsed = _extension(row, family, expanded, indexed)
            if parsed is not None and parsed.packages:
                extensions.append(parsed)
        if extensions:
            built.append(PhpExtensionCategory(label, tuple(extensions)))
    if not built:
        raise PhpExtensionError(f"No PHP {line} extension packages were found for this system.")
    return PhpExtensionCatalog(version, line, family, tuple(built))


def extension_plan(
    ctx: Context,
    version: str,
    names: tuple[str, ...] | None,
    *,
    catalog: PhpExtensionCatalog | None = None,
) -> Plan:
    """Plan an install of one PHP line's extensions. ``names`` None installs all."""
    try:
        listing = catalog if catalog is not None else load_php_extensions(ctx, version)
    except PhpExtensionError as exc:
        return Plan(title="PHP extensions", blocked=str(exc))
    if listing.version != version:
        return Plan(title="PHP extensions", blocked="The extension list does not match this PHP.")
    packages = listing.packages_for(names)
    if names is not None:
        known = {item.name for category in listing.categories for item in category.extensions}
        missing = [name for name in names if name not in known]
        if missing:
            return Plan(
                title="PHP extensions",
                blocked=f"Unknown PHP extension {missing[0]!r} for PHP {listing.line}.",
            )
    if not packages:
        return Plan(
            title="PHP extensions",
            blocked=f"No packages are available for those PHP {listing.line} extensions.",
        )
    manager = ctx.system().package_manager
    if not manager:
        return Plan(title="PHP extensions", blocked="No supported package manager is available.")
    try:
        refresh_argv = tuple(refresh(manager))
        install_argv = tuple(install(manager, packages))
    except PackageManagerError as exc:
        return Plan(title="PHP extensions", blocked=str(exc))
    title = f"Install PHP {listing.line} extensions"
    plan = Plan(title=title)
    reason = f"Installing PHP {listing.line} extensions uses the system package manager."
    plan.add(
        Step(
            title="Refresh package indexes",
            kind="command",
            argv=refresh_argv,
            sudo=True,
            reason=reason,
        )
    )
    plan.add(
        Step(
            title=f"Install {len(packages)} PHP {listing.line} extension packages",
            kind="command",
            argv=install_argv,
            sudo=True,
            reason=reason,
        )
    )
    plan.notes.append(
        f"These packages match the installed PHP {version} (the {listing.line} line)."
    )
    return plan


def _line(version: str) -> str:
    numbers = re.findall(r"\d+", version)
    if len(numbers) < 2:
        raise PhpExtensionError(f"Installed PHP version {version!r} has no major.minor line.")
    return f"{int(numbers[0])}.{int(numbers[1])}"


def _expand_prefix(prefix: str, version: str) -> str:
    numbers = re.findall(r"\d+", version)
    major = str(int(numbers[0])) if numbers else "0"
    minor = str(int(numbers[1])) if len(numbers) > 1 else "0"
    expanded = prefix.replace("{major}", major).replace("{minor}", minor)
    if "{" in expanded or not expanded:
        raise PhpExtensionError("PHP extension package prefix is malformed.")
    return expanded


def _read_catalog(path: Path) -> dict[str, object]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhpExtensionError(f"Could not read PHP extensions: {exc}") from exc
    if not isinstance(payload, dict):
        raise PhpExtensionError("PHP extension catalog must be a JSON object.")
    return cast(dict[str, object], payload)


def _candidate_packages(categories: list[object], family: str, prefix: str) -> tuple[str, ...]:
    names: list[str] = []
    for category in categories:
        if not isinstance(category, dict):
            continue
        rows = category.get("extensions")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = cast(dict[str, object], row)
            for key in ("all", "one"):
                names.extend(_suffix_packages(record.get(key), family, prefix))
    return tuple(dict.fromkeys(names))


def _suffix_packages(block: object, family: str, prefix: str) -> list[str]:
    if not isinstance(block, dict) or family not in block:
        return []
    suffixes = block[family]
    if not isinstance(suffixes, list):
        raise PhpExtensionError("PHP extension catalog is malformed.")
    packages: list[str] = []
    for suffix in suffixes:
        if not isinstance(suffix, str) or not _SUFFIX.match(suffix):
            raise PhpExtensionError(f"Unsafe PHP extension suffix {suffix!r}.")
        package = prefix + suffix
        if not _PACKAGE.match(package):
            raise PhpExtensionError(f"Unsafe PHP package name {package!r}.")
        packages.append(package)
    return packages


def _extension(
    row: object,
    family: str,
    prefix: str,
    indexed: dict[str, bool] | None,
) -> PhpExtension | None:
    if not isinstance(row, dict):
        raise PhpExtensionError("PHP extension catalog is malformed.")
    record = cast(dict[str, object], row)
    name = record.get("name")
    summary = record.get("summary")
    if not isinstance(name, str) or not isinstance(summary, str):
        raise PhpExtensionError("PHP extension catalog is malformed.")
    required = _suffix_packages(record.get("all"), family, prefix)
    alternatives = _suffix_packages(record.get("one"), family, prefix)
    if not required and not alternatives:
        return None
    selected = _select(required, alternatives, indexed)
    installed = False
    if selected and indexed is not None:
        installed = all(indexed.get(item) for item in selected)
    return PhpExtension(name, summary, tuple(selected), installed)


def _select(
    required: list[str],
    alternatives: list[str],
    indexed: dict[str, bool] | None,
) -> list[str]:
    if indexed is None:
        chosen = list(required)
        if alternatives:
            chosen.append(alternatives[0])
        return chosen
    chosen = [name for name in required if name in indexed]
    for name in alternatives:
        if name in indexed:
            chosen.append(name)
            break
    return chosen


def _query(ctx: Context, packages: tuple[str, ...]) -> dict[str, bool] | None:
    """Map package name to whether it is installed.

    None means the package index could not be read, so every catalog package
    stays in the plan.
    """
    if not packages:
        return {}
    manager = ctx.system().package_manager
    if manager == "apt":
        if ctx.runner.which("apt-cache") is None:
            return None
        result = ctx.runner.run(("apt-cache", "policy", *packages), timeout=60)
        if result.code != 0 and not result.stdout:
            return None
        return _parse_apt_policy(result.stdout, set(packages))
    return None


def _parse_apt_policy(text: str, requested: set[str]) -> dict[str, bool]:
    found: dict[str, bool] = {}
    current = ""
    for line in text.splitlines():
        if line and not line.startswith((" ", "\t")) and line.endswith(":"):
            name = line[:-1]
            current = name if name in requested else ""
            if current:
                found[current] = False
            continue
        if current and line.strip().startswith("Installed:"):
            value = line.split(":", 1)[1].strip()
            found[current] = bool(value) and value != "(none)"
    return found
