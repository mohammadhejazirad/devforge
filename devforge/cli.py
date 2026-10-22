"""Argument parsing for the DevForge command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import TextIO

from devforge import __version__
from devforge import strings as s
from devforge.ui import Printer


def build_parser() -> argparse.ArgumentParser:
    """Return the top-level parser. Subcommands are added as they land."""
    parser = argparse.ArgumentParser(
        prog="devforge",
        description=s.DESCRIPTION,
        epilog=s.HELP_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Python 3.14 colors help from the process TTY, not from the stream
    # help is written to. Keep help plain so it matches 3.9 and NO_COLOR.
    if hasattr(parser, "color"):
        parser.color = False
    parser.add_argument(
        "--version",
        action="version",
        version=s.VERSION_TEMPLATE.format(version=__version__),
    )
    parser.add_argument("--dry-run", action="store_true", help=s.HELP_DRY_RUN)
    parser.add_argument("-y", "--yes", action="store_true", help=s.HELP_YES)
    parser.add_argument("--json", action="store_true", help=s.HELP_JSON)
    parser.add_argument("--no-color", action="store_true", help=s.HELP_NO_COLOR)
    parser.add_argument("-q", "--quiet", action="store_true", help=s.HELP_QUIET)
    parser.add_argument("-v", "--verbose", action="count", default=0, help=s.HELP_VERBOSE)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run DevForge. Returns a process status code."""
    parser = build_parser()
    args = parser.parse_args(None if argv is None else list(argv))
    printer = Printer.create(
        no_color=args.no_color,
        quiet=args.quiet,
        verbose=args.verbose,
        assume_yes=args.yes,
        dry_run=args.dry_run,
        out=out,
        err=err,
    )
    # Parsed so help can document them. No command consumes these yet.
    del args.json
    printer.error(s.ERR_NO_COMMAND)
    parser.print_help(printer.error_stream)
    return 2


def entrypoint() -> None:
    """Console-script entry. Propagates the status code."""
    sys.exit(main())
