"""The tool interface used by every language, service, and utility."""

from __future__ import annotations

from functools import lru_cache

from devforge.context import Context
from devforge.core.plan import Plan
from devforge.tools.base import Check, InstalledInfo, Scope, ToolStatus
from devforge.tools.catalog import ToolSpec, load_catalog
from devforge.tools.engine import (
    ToolError,
    detect,
    doctor_tool,
    install_tool,
    status_of,
    uninstall_tool,
    update_tool,
    use_tool,
)


class ManagedTool:
    """One catalog entry. Adding a tool is a catalog record plus a thin module."""

    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self.name = spec.name

    def detect(self, ctx: Context) -> InstalledInfo:
        return detect(self.spec, ctx)

    def available_versions(self, ctx: Context) -> list[str]:
        from devforge.tools.engine import _index

        return list(_index(self.spec, ctx).versions)

    def install(
        self,
        ctx: Context,
        version: str | None,
        *,
        make_default: bool,
        use_package: bool = False,
    ) -> Plan:
        return install_tool(
            self.spec,
            ctx,
            version,
            make_default=make_default,
            use_package=use_package,
        )

    def update(self, ctx: Context, version: str | None = None) -> Plan:
        del version
        return update_tool(self.spec, ctx)

    def use(self, ctx: Context, version: str, *, scope: Scope) -> Plan:
        return use_tool(self.spec, ctx, version, scope)

    def uninstall(self, ctx: Context, version: str | None, *, purge: bool) -> Plan:
        return uninstall_tool(self.spec, ctx, version, purge=purge)

    def doctor(self, ctx: Context) -> list[Check]:
        return doctor_tool(self.spec, ctx)

    def status(self, ctx: Context) -> ToolStatus:
        return status_of(self.spec, ctx)


@lru_cache(maxsize=1)
def catalog() -> dict[str, ToolSpec]:
    return load_catalog()


def load_tool(name: str) -> ManagedTool:
    try:
        return ManagedTool(catalog()[name])
    except KeyError as exc:
        known = ", ".join(catalog())
        raise ToolError(f"Unknown tool {name!r}. Known tools: {known}") from exc


def all_tools() -> list[ManagedTool]:
    return [load_tool(name) for name in catalog()]
