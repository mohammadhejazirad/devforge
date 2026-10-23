# Version indexes

Shipped version indexes live here as JSON, one file per tool that publishes a
selectable version. `devforge versions <tool> --refresh` downloads the upstream
index and writes the result to the user cache (`$XDG_CACHE_HOME/devforge`).
The shipped file remains the fallback. Deleting a cache file is safe.

A download still requires a SHA256. Pins in these files cover the builds that
were current when they were added. A later version can use the publisher's
checksum file at apply time when `catalog.json` names one. DevForge does not
install an archive with no checksum.

The word `stable` is not stored as a Rust version. Rustup's stable toolchain
is a fixed argument, not a version string.

