# Architecture notes

This document records decisions that are not obvious from the code.

## Layering

```
cli.py            parses arguments, builds a Printer, dispatches to a command
commands/         thin adapters: parse options, call core, return an exit code
core/             pure-ish logic: detection, package managers, state, plan, net
tools/            one module per managed tool, implementing the Tool interface
```

Nothing in `core/` or `tools/` writes to the terminal directly. They return
plans and data; `commands/` and the TUI render them. This keeps every mutating
path testable in `--dry-run` without root.

## Side effects are injectable

Detection reads `/etc/os-release` and runs commands. Both are injectable:

- the os-release path is a parameter, so tests read fixtures;
- system commands go through a runner object, so tests record commands instead
  of executing them.

## State directories

All DevForge paths follow the XDG base directory spec, with fallbacks:

- data: `$XDG_DATA_HOME/devforge` or `~/.local/share/devforge`
- state and logs: `$XDG_STATE_HOME/devforge` or `~/.local/state/devforge`
- config: `$XDG_CONFIG_HOME/devforge` or `~/.config/devforge`
- cache: `$XDG_CACHE_HOME/devforge` or `~/.cache/devforge`

`core/paths.py` owns these paths and provides the deletion guard used before any
`rm -rf`, so destructive operations can only touch DevForge-owned directories.

## Terminal output

Text is centralized in `devforge/strings.py`. Markers are plain ASCII
(`[ok]`, `[warn]`, `[err]`, `[info]`) and color is added only when the stream is
a TTY, `NO_COLOR` is unset, `TERM` is not `dumb`, and `--no-color` was not
passed. Non-TTY output never contains escape codes.

## Logging module name

The logging helper is `core/log.py`, not `core/logging.py`, so it can never
shadow the standard library `logging` module.
