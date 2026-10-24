#!/bin/sh
# DevForge installer.
# Downloads one pinned release archive, checks its SHA256, and copies it into
# place. It does not execute any other remote script.
#
#   curl -fsSL https://raw.githubusercontent.com/mohammadhejazirad/devforge/main/install.sh | bash
set -eu

VERSION="1.3.0"
DEFAULT_URL="https://github.com/mohammadhejazirad/devforge/releases/download/v1.3.0/devforge-1.3.0.tar.gz"
DEFAULT_SHA256="a218865925823eb4677e6762b1a02b4b0a4f287dc6dcc6e4e0a7d0cd551c7a68"

URL="${DEVFORGE_RELEASE_URL:-$DEFAULT_URL}"
SHA256="${DEVFORGE_RELEASE_SHA256:-$DEFAULT_SHA256}"

say() {
    printf '%s\n' "$*"
}

die() {
    printf 'devforge install: %s\n' "$*" >&2
    exit 1
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

python_ok() {
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'
}

run_privileged() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        need_cmd sudo
        sudo "$@"
    fi
}

install_python() {
    say "Python 3.9+ was not found."
    if [ "${DEVFORGE_INSTALL_PYTHON:-}" != "1" ]; then
        if [ ! -r /dev/tty ] || [ ! -t 1 ]; then
            die "Python 3.9+ is required. Install it yourself, or re-run in a terminal to approve the package install"
        fi
        printf 'Install Python 3 with the system package manager? [y/N] ' >/dev/tty
        answer=""
        read -r answer </dev/tty || answer=""
        case "$answer" in
            y | Y | yes | YES) ;;
            *) die "Python 3.9+ is required" ;;
        esac
    fi
    say "Installing Python 3. This changes system packages."
    if command -v apt-get >/dev/null 2>&1; then
        run_privileged apt-get update
        run_privileged apt-get install -y python3 ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        run_privileged dnf install -y python3 ca-certificates
    elif command -v yum >/dev/null 2>&1; then
        run_privileged yum install -y python3 ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        run_privileged pacman -Syu --noconfirm python ca-certificates
    elif command -v zypper >/dev/null 2>&1; then
        run_privileged zypper --non-interactive install python3 ca-certificates
    elif command -v apk >/dev/null 2>&1; then
        run_privileged apk add python3 ca-certificates
    else
        die "no supported package manager found; install Python 3.9+ yourself"
    fi
}

download() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$URL" -o "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$1" "$URL"
    else
        python3 - "$URL" "$1" <<'PY'
import shutil
import sys
import urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=60) as source:
    with open(sys.argv[2], "wb") as target:
        shutil.copyfileobj(source, target)
PY
    fi
}

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk 'NR == 1 { print $1 }'
    elif command -v sha256 >/dev/null 2>&1; then
        sha256 -q "$1"
    else
        python3 - "$1" <<'PY'
import hashlib
import sys
digest = hashlib.sha256()
with open(sys.argv[1], "rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
    fi
}

[ "$(uname -s)" = "Linux" ] || die "DevForge supports Linux only"
case "$URL" in
    https://*) ;;
    http://127.0.0.1/* | http://127.0.0.1:*/* | http://localhost/* | http://localhost:*/*) ;;
    *) die "refusing a download URL that is not HTTPS" ;;
esac
case "$SHA256" in
    *[!0-9a-f]*) die "checksum must be 64 hex characters" ;;
esac
[ "${#SHA256}" -eq 64 ] || die "checksum must be 64 hex characters"

if [ "$(id -u)" -eq 0 ]; then
    PREFIX="${DEVFORGE_PREFIX:-/usr/local}"
else
    PREFIX="${DEVFORGE_PREFIX:-$HOME/.local}"
fi
DEST="${PREFIX}/share/devforge"
BIN_DIR="${PREFIX}/bin"
case "$DEST" in
    /*/share/devforge) ;;
    *) die "refusing install directory $DEST" ;;
esac
case "$DEST" in
    *\'* | *\"* | *\\* | *[[:space:]]*) die "install path contains unsupported characters" ;;
esac

if ! command -v python3 >/dev/null 2>&1 || ! python_ok; then
    install_python
fi
python_ok || die "Python is still older than 3.9 after installation"
# Resolve the bootstrap interpreter so a later project Python pin cannot
# accidentally run DevForge with an incompatible interpreter.
PYTHON=$(python3 -c 'import os, sys; print(os.path.realpath(sys.executable))')

tmpdir=$(mktemp -d)
case "$tmpdir" in
    /tmp/* | /var/tmp/*) ;;
    *) die "unexpected temporary directory" ;;
esac
cleanup() {
    rm -rf "$tmpdir"
}
trap cleanup EXIT INT TERM

archive="$tmpdir/devforge.tar.gz"
download "$archive"
actual=$(checksum "$archive")
[ "$actual" = "$SHA256" ] || die "checksum mismatch (expected $SHA256, got $actual)"

"$PYTHON" - "$archive" "$tmpdir" "$VERSION" <<'PY'
import pathlib
import shutil
import sys
import tarfile
prefix = "devforge-" + sys.argv[3]
with tarfile.open(sys.argv[1], "r:gz") as archive:
    for member in archive.getmembers():
        relative = pathlib.PurePosixPath(member.name)
        if (relative.is_absolute() or not relative.parts or relative.parts[0] != prefix
                or ".." in relative.parts or "\\" in member.name
                or not (member.isdir() or member.isfile())):
            raise SystemExit("devforge install: unexpected member: " + member.name)
    for member in archive.getmembers():
        target = pathlib.Path(sys.argv[2]) / member.name
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)
PY
src="$tmpdir/devforge-${VERSION}"
[ -d "$src/devforge" ] || die "archive is missing the devforge package"
[ -f "$src/devforge/__main__.py" ] || die "archive is missing the program entry point"
[ -f "$src/VERSION" ] || die "archive is missing VERSION"
got_version=$(tr -d '[:space:]' <"$src/VERSION")
[ "$got_version" = "$VERSION" ] || die "archive version is $got_version, expected $VERSION"

if [ -e "$DEST" ]; then
    if [ ! -f "$DEST/.devforge-install" ] && [ ! -d "$DEST/devforge" ]; then
        die "refusing to replace $DEST because it is not a DevForge install"
    fi
fi
mkdir -p "$DEST" "$BIN_DIR"
# Replace the program only. tools/, shims/, and env.sh live in this directory
# and must survive a reinstall.
rm -rf "$DEST/devforge"
cp -a "$src/devforge" "$DEST/devforge"
if [ -f "$src/LICENSE" ]; then
    cp -a "$src/LICENSE" "$DEST/LICENSE"
fi
cp -a "$src/VERSION" "$DEST/VERSION"
printf 'devforge\n' >"$DEST/.devforge-install"

launcher="$BIN_DIR/devforge"
printf '%s\n' \
    '#!/bin/sh' \
    'set -eu' \
    "export PYTHONPATH=\"$DEST\${PYTHONPATH:+:\$PYTHONPATH}\"" \
    "exec \"$PYTHON\" -m devforge \"\$@\"" \
    >"$launcher"
chmod 755 "$launcher"

say "[ok] Installed DevForge ${VERSION} to ${DEST}"
say "Run: ${launcher} --help"
case ":$PATH:" in
    *":${BIN_DIR}:"*) ;;
    *)
        say "[warn] ${BIN_DIR} is not on PATH."
        say "Add it with: export PATH=\"${BIN_DIR}:\$PATH\""
        ;;
esac
