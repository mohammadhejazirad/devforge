"""Presets, machine files, export, and shell integration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from devforge.commands.common import emit_json, run_plan
from devforge.context import Context
from devforge.core.plan import Plan
from devforge.core.versioning import is_valid_version
from devforge.tools.engine import ToolError, merge_plans, shell_remove_steps, shell_steps
from devforge.tools.managed import all_tools, load_tool

_SECTION = re.compile(r"^\[tool\.([a-z0-9][a-z0-9-]{0,40})\]\s*(?:#.*)?$")
_STRING = re.compile(r'^([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"\s*(?:#.*)?$')
_BOOL = re.compile(r"^([A-Za-z0-9_-]+)\s*=\s*(true|false)\s*(?:#.*)?$")


def cmd_preset_list(ctx: Context) -> int:
    """List the shipped presets."""
    presets = _load_presets(ctx.data_root / "presets")
    if isinstance(presets, str):
        ctx.printer.error(presets)
        return 1
    if ctx.as_json:
        emit_json(ctx, {"presets": presets})
        return 0
    for preset in presets:
        tools = ", ".join(str(name) for name in preset["tools"])
        ctx.printer.raw(f"{preset['name']}: {preset['summary']} ({tools})")
    return 0


def cmd_preset_apply(ctx: Context, name: str) -> int:
    """Install every tool in a preset. One blocked tool blocks the whole preset."""
    presets = _load_presets(ctx.data_root / "presets")
    if isinstance(presets, str):
        ctx.printer.error(presets)
        return 1
    match = next((item for item in presets if item["name"] == name), None)
    if match is None:
        known = ", ".join(str(item["name"]) for item in presets) or "(none)"
        ctx.printer.error(f"Unknown preset {name!r}. Known presets: {known}")
        return 2
    return _install_requests(ctx, _requests_from_names(match["tools"]), f"Apply preset {name}")


def cmd_apply(ctx: Context, path: Path) -> int:
    """Install the tools described by a JSON file or a small TOML subset."""
    try:
        requests = parse_manifest(path)
    except ValueError as exc:
        ctx.printer.error(str(exc))
        return 2
    return _install_requests(ctx, requests, f"Apply {path.name}")


def cmd_export(ctx: Context) -> int:
    """Print a manifest of the tools that are already installed."""
    tools: dict[str, dict[str, object]] = {}
    for tool in all_tools():
        info = tool.detect(ctx)
        if info.current is None and not info.versions:
            continue
        entry: dict[str, object] = {"default": True}
        if info.current:
            entry["version"] = info.current
        tools[tool.name] = entry
    emit_json(ctx, {"tools": tools})
    return 0


def cmd_shell(ctx: Context, action: str) -> int:
    """Install or remove the managed shell block."""
    if action == "install":
        steps = shell_steps(ctx)
        title = "Install shell integration"
    elif action == "remove":
        steps = shell_remove_steps(ctx)
        title = "Remove shell integration"
    else:
        ctx.printer.error(f"Unknown shell action {action!r}.")
        return 2
    plan = Plan(title=title, steps=list(steps))
    if not plan.steps:
        plan.empty_message = "Shell integration is already in the requested state."
    else:
        plan.notes.append("Open a new shell after this change.")
    return run_plan(ctx, plan)


def parse_manifest(path: Path) -> list[tuple[str, str | None, bool]]:
    """Read a tool manifest. JSON is preferred. A small TOML subset also works."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if path.suffix == ".toml" or (
        text.lstrip().startswith("[") and not text.lstrip().startswith("{")
    ):
        data = _parse_toml_subset(text, path)
    else:
        data = _parse_json_manifest(text, path)
    return _requests(data, path)


def _install_requests(
    ctx: Context, requests: list[tuple[str, str | None, bool]], title: str
) -> int:
    plans: list[Plan] = []
    for name, version, make_default in requests:
        try:
            tool = load_tool(name)
            plans.append(tool.install(ctx, version, make_default=make_default, use_package=False))
        except (ToolError, ValueError) as exc:
            plans.append(Plan(title=name, blocked=str(exc)))
    if not plans:
        plan = Plan(title=title, empty_message="The manifest lists no tools.")
        return run_plan(ctx, plan)
    return run_plan(ctx, merge_plans(title, plans))


def _requests_from_names(names: object) -> list[tuple[str, str | None, bool]]:
    if not isinstance(names, list):
        return []
    return [(str(name), None, True) for name in names]


def _load_presets(directory: Path) -> list[dict[str, Any]] | str:
    if not directory.is_dir():
        return f"Preset directory is missing: {directory}"
    found: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return f"Could not read preset {path.name}: {exc}"
        if not isinstance(payload, dict):
            return f"Preset {path.name} must be a JSON object"
        data = cast(dict[str, Any], payload)
        name = data.get("name")
        tools = data.get("tools")
        summary = data.get("summary", "")
        if not isinstance(name, str) or not isinstance(tools, list) or not isinstance(summary, str):
            return f"Preset {path.name} needs a name, a summary, and a tools list"
        found.append({"name": name, "summary": summary, "tools": tools})
    return found


def _parse_json_manifest(text: str, path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(dict[str, Any], payload)


def _parse_toml_subset(text: str, path: Path) -> dict[str, Any]:
    """Parse ``[tool.name]`` tables with string and boolean keys."""
    tools: dict[str, dict[str, object]] = {}
    current: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        section = _SECTION.fullmatch(line)
        if section:
            current = section.group(1)
            tools.setdefault(current, {})
            continue
        if current is None:
            raise ValueError(f"{path}:{number}: expected a [tool.name] section")
        string_match = _STRING.fullmatch(line)
        bool_match = _BOOL.fullmatch(line)
        if string_match is not None:
            key = string_match.group(1)
            value: object = string_match.group(2)
        elif bool_match is not None:
            key = bool_match.group(1)
            value = bool_match.group(2) == "true"
        else:
            raise ValueError(f"{path}:{number}: unsupported line")
        if key not in {"version", "default"}:
            raise ValueError(f"{path}:{number}: unknown key {key!r}")
        tools[current][key] = value
    return {"tools": tools}


def _requests(data: dict[str, Any], path: Path) -> list[tuple[str, str | None, bool]]:
    raw = data.get("tools")
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a tools object")
    requests: list[tuple[str, str | None, bool]] = []
    for name, body in raw.items():
        if not isinstance(name, str):
            raise ValueError(f"{path} has a tool name that is not text")
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise ValueError(f"{path} tool {name} must be an object")
        version = body.get("version")
        if version is not None and (not isinstance(version, str) or not is_valid_version(version)):
            raise ValueError(f"{path} tool {name} has an invalid version")
        default = body.get("default", True)
        if not isinstance(default, bool):
            raise ValueError(f"{path} tool {name} default must be true or false")
        requests.append((name, version if isinstance(version, str) else None, default))
    return requests
