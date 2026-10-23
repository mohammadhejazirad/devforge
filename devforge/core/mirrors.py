"""Mirror profiles loaded from community data.

Profiles are opt-in. The default is always the upstream URL. Applying a
profile rewrites download URLs and can export registry variables. It never
changes a distro repository unless the profile lists a package-repo rewrite
and the user confirms the plan.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

_URL = re.compile(r"^https://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,40}$")


class MirrorError(ValueError):
    """A mirror profile is missing or unsafe."""


@dataclass(frozen=True)
class Rewrite:
    """One upstream-to-mirror prefix, or one environment variable."""

    ecosystem: str
    upstream: str = ""
    mirror: str = ""
    env: str = ""
    value: str = ""


@dataclass(frozen=True)
class MirrorProfile:
    """A named, optional set of mirrors."""

    name: str
    verified: bool
    description: str
    rewrites: tuple[Rewrite, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "verified": self.verified,
            "description": self.description,
            "rewrites": [
                {
                    "ecosystem": item.ecosystem,
                    "upstream": item.upstream,
                    "mirror": item.mirror,
                    "env": item.env,
                    "value": item.value,
                }
                for item in self.rewrites
            ],
        }


def profiles_dir(data_root: Path) -> Path:
    return data_root / "mirrors"


def load_profiles(data_root: Path) -> dict[str, MirrorProfile]:
    """Load every ``*.json`` profile. ``README.md`` is ignored."""
    directory = profiles_dir(data_root)
    found: dict[str, MirrorProfile] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.json")):
        profile = _load_one(path)
        found[profile.name] = profile
    return found


def require_profile(data_root: Path, name: str) -> MirrorProfile:
    profiles = load_profiles(data_root)
    if name not in profiles:
        known = ", ".join(sorted(profiles)) or "(none)"
        raise MirrorError(f"Unknown mirror profile {name!r}. Known profiles: {known}")
    return profiles[name]


def rewrite_urls(url: str, profile: MirrorProfile | None) -> tuple[str, ...]:
    """Return URLs to try, mirror first when a profile rewrites ``url``."""
    if profile is None:
        return (url,)
    extra: list[str] = []
    for item in profile.rewrites:
        if item.upstream and item.mirror and url.startswith(item.upstream):
            extra.append(item.mirror + url[len(item.upstream) :])
    if not extra:
        return (url,)
    return (*extra, url)


def env_assignments(profile: MirrorProfile | None) -> dict[str, str]:
    """Environment variables a profile wants shims to export."""
    if profile is None:
        return {}
    assigned: dict[str, str] = {}
    for item in profile.rewrites:
        if item.env and item.value:
            assigned[item.env] = item.value
    return assigned


def _load_one(path: Path) -> MirrorProfile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MirrorError(f"Could not read mirror profile {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MirrorError(f"Mirror profile {path.name} must be a JSON object")
    data = cast(dict[str, Any], payload)
    name = _token(data.get("name"), path.stem)
    description = data.get("description", "")
    if not isinstance(description, str):
        raise MirrorError(f"Mirror profile {name} has a non-text description")
    verified = bool(data.get("verified", False))
    raw_items = data.get("rewrites", [])
    if not isinstance(raw_items, list):
        raise MirrorError(f"Mirror profile {name} rewrites must be a list")
    rewrites = tuple(_rewrite(name, item) for item in raw_items)
    return MirrorProfile(name=name, verified=verified, description=description, rewrites=rewrites)


def _rewrite(profile: str, item: object) -> Rewrite:
    if not isinstance(item, dict):
        raise MirrorError(f"Mirror profile {profile} has a rewrite that is not an object")
    ecosystem = item.get("ecosystem", "")
    if not isinstance(ecosystem, str) or not ecosystem:
        raise MirrorError(f"Mirror profile {profile} has a rewrite without an ecosystem")
    upstream = _optional_url(item.get("upstream", ""), profile)
    mirror = _optional_url(item.get("mirror", ""), profile)
    env = item.get("env", "")
    value = item.get("value", "")
    if not isinstance(env, str) or (env and _ENV_NAME.fullmatch(env) is None):
        raise MirrorError(f"Mirror profile {profile} has an unsafe environment name")
    if not isinstance(value, str):
        raise MirrorError(f"Mirror profile {profile} has a non-text environment value")
    if value and _URL.fullmatch(value) is None:
        raise MirrorError(f"Mirror profile {profile} environment values must be https URLs")
    if bool(upstream) != bool(mirror):
        raise MirrorError(f"Mirror profile {profile} rewrites need both an upstream and a mirror")
    return Rewrite(ecosystem=ecosystem, upstream=upstream, mirror=mirror, env=env, value=value)


def _optional_url(value: object, profile: str) -> str:
    if value in ("", None):
        return ""
    if not isinstance(value, str) or _URL.fullmatch(value) is None:
        raise MirrorError(f"Mirror profile {profile} has a URL that is not a plain https URL")
    return value.rstrip("/")


def _token(value: object, fallback: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", value):
        return value
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", fallback):
        return fallback
    raise MirrorError(f"unsafe mirror profile name {fallback!r}")
