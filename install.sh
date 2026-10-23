#!/bin/sh
# DevForge installer.
# Downloads one pinned release archive, checks its SHA256, and copies it into
# place. It does not execute any other remote script.
#
#   curl -fsSL https://raw.githubusercontent.com/mohammadhejazirad/devforge/main/install.sh | bash
set -eu

VERSION="1.2.0"
DEFAULT_URL="https://github.com/mohammadhejazirad/devforge/releases/download/v1.2.0/devforge-1.2.0.tar.gz"
DEFAULT_SHA256="25805006fb08e87a4f9e771aa93c73a18141429cc625bcfa8d9a724dedd0393c"

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
        run_privileged apt-get install -y python3
    elif command -v dnf >/dev/null 2>&1; then
        run_privileged dnf install -y python3
    elif command -v yum >/dev/null 2>&1; then
        run_privileged yum install -y python3
    elif command -v pacman >/dev/null 2>&1; then
        run_privileged pacman -Sy --noconfirm python
    elif command -v zypper >/dev/null 2>&1; then
        run_privileged zypper --non-interactive install python3
    elif command -v apk >/dev/null 2>&1; then
        run_privileged apk add python3
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
        die "curl or wget is required"
    fi
}

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk 'NR == 1 { print $1 }'
    elif command -v sha256 >/dev/null 2>&1; then
        sha256 -q "$1"
    else
        die "sha256sum is required to verify the download"
    fi
}

assert_safe_member() {
    member="$1"
    case "$member" in
        "devforge-${VERSION}" | "devforge-${VERSION}"/*) ;;
        *) die "archive contains an unexpected member: $member" ;;
    esac
    case "$member" in
        *..* | *\\*) die "archive contains an unsafe path: $member" ;;
    esac
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
need_cmd tar

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

tar -tzf "$archive" >"$tmpdir/members"
while IFS= read -r member; do
    assert_safe_member "$member"
done <"$tmpdir/members"
tar -xzf "$archive" -C "$tmpdir"
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
    'exec python3 -m devforge "$@"' \
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
