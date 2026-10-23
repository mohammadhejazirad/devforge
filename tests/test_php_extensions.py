"""PHP extensions follow the installed major.minor line."""

from __future__ import annotations

from pathlib import Path

from devforge.core.runner import RunResult, ScriptedRunner
from devforge.tools.managed import load_tool
from devforge.tools.php_extensions import extension_plan, load_php_extensions
from devforge.tui import _php_extensions, _tool_options, menu
from tests.support import machine


def _php(ctx_runner: ScriptedRunner, version: str = "8.3.6") -> None:
    ctx_runner.which_map["php"] = "/usr/bin/php"
    ctx_runner.when_argv(["/usr/bin/php", "-v"], stdout=f"PHP {version} (cli)\n")


def test_debian_packages_use_the_installed_line(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian")
    plan = extension_plan(ctx, "8.5.12", None)
    packages = plan.steps[-1].argv
    assert "php8.5-mysql" in packages
    assert "php8.5-curl" in packages
    assert "php8.5-gd" in packages
    assert "php8.5-mbstring" in packages
    assert "php8.5-redis" in packages
    assert "php8.5-xml" in packages
    assert "php8.5-cli" not in packages
    assert "php8.4-mysql" not in packages
    assert "php-mysql" not in packages
    assert any("installed PHP 8.5.12" in note for note in plan.notes)


def test_alpine_packages_use_the_compact_line(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "alpine", family="alpine")
    plan = extension_plan(ctx, "8.3.6", ("mysql",))
    packages = plan.steps[-1].argv
    assert "php83-mysqli" in packages
    assert "php83-mysqlnd" in packages
    assert "php83-pdo_mysql" in packages
    assert "php8.3-mysql" not in packages


def test_missing_index_packages_are_skipped(tmp_path: Path) -> None:
    ctx, _out, _err = machine(tmp_path, "debian-12", family="debian")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    runner.which_map["apt-cache"] = "/usr/bin/apt-cache"
    runner.when(
        lambda argv: argv[:2] == ("apt-cache", "policy"),
        RunResult(
            ("apt-cache", "policy"),
            0,
            "php8.3-mysql:\n  Installed: (none)\nphp8.3-curl:\n  Installed: 8.3.6-1\n",
            "",
        ),
    )
    catalog = load_php_extensions(ctx, "8.3.6")
    packages = catalog.packages_for(None)
    assert "php8.3-mysql" in packages
    assert "php8.3-curl" in packages
    assert "php8.3-gd" not in packages
    mysql = next(
        item
        for category in catalog.categories
        for item in category.extensions
        if item.name == "mysql"
    )
    curl = next(
        item
        for category in catalog.categories
        for item in category.extensions
        if item.name == "curl"
    )
    assert mysql.installed is False
    assert curl.installed is True


def test_menu_installs_every_extension_when_enter_is_pressed(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    _php(runner, "8.3.6")
    options = _tool_options(load_tool("php").status(ctx))
    number = next(
        index for index, item in enumerate(options, start=1) if item[1] == "php-extensions"
    )
    assert menu(ctx, iter(["1", str(number), "", "", "0"])) == 0
    text = out.getvalue()
    assert "PHP 8.3.6 extensions" in text
    assert "Install all extensions (default)" in text
    assert "php8.3-mysql" in text
    assert "php8.3-xdebug" in text
    assert "php8.4-" not in text


def test_menu_category_default_installs_only_that_category(tmp_path: Path) -> None:
    ctx, out, _err = machine(tmp_path, "debian-12", family="debian")
    runner = ctx.runner
    assert isinstance(runner, ScriptedRunner)
    _php(runner, "8.3.6")
    options = _tool_options(load_tool("php").status(ctx))
    number = next(
        index for index, item in enumerate(options, start=1) if item[1] == "php-extensions"
    )
    assert menu(ctx, iter(["1", str(number), "2", "", "", "0"])) == 0
    text = out.getvalue()
    assert "php8.3-mysql" in text
    assert "php8.3-pgsql" in text
    assert "php8.3-xdebug" not in text


def test_extensions_need_an_installed_php(tmp_path: Path) -> None:
    ctx, _out, err = machine(tmp_path, "debian-12", family="debian")
    assert _php_extensions(ctx, iter([]), load_tool("php")) is False
    assert "Install PHP first" in err.getvalue()
