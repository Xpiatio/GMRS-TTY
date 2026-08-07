#!/usr/bin/env bash
# Build a .deb installer for GMRS-TTY.
#
# Output: build/deb/gmrs-tty_<VERSION>_amd64.deb
#
# Constraints baked into the resulting package:
#   * Targets Debian 13 / LMDE 7 (glibc >= 2.41, Python 3.13, x86_64).
#   * Vendors all Python wheels so the postinst is fully offline.
#   * Uses CPU-only torch (drops ~1.6 GB of nvidia CUDA wheels).
#   * Whisper / Piper voice models are NOT bundled — they download on first run.
#
# Usage:
#   ./scripts/build-deb.sh              # version from gmrs_tty/__init__.py
#   ./scripts/build-deb.sh 0.0.2        # override version
#
# Re-running is safe; the build/deb/ tree is wiped first.

set -euo pipefail

ARCH="amd64"
PKG="gmrs-tty"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Version defaults to the canonical gmrs_tty.__version__ stamp.
VERSION="${1:-$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO_ROOT/gmrs_tty/__init__.py")}"
if [[ -z "$VERSION" ]]; then
    echo "ERROR: could not read __version__ from gmrs_tty/__init__.py" >&2
    exit 1
fi
STAGE="$REPO_ROOT/build/deb/${PKG}_${VERSION}_${ARCH}"
DEB_OUT="$REPO_ROOT/build/deb/${PKG}_${VERSION}_${ARCH}.deb"

# Pick a Python interpreter: prefer the project venv, then python3.13, then python3.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PY="$REPO_ROOT/.venv/bin/python"
elif command -v python3.13 >/dev/null 2>&1; then
    PY="$(command -v python3.13)"
else
    PY="$(command -v python3)"
fi

echo ">>> Using Python: $PY ($($PY --version 2>&1))"
echo ">>> Building $PKG $VERSION ($ARCH) into $STAGE"

# ---------------------------------------------------------------------------
# 1. Reset the staging tree.
# ---------------------------------------------------------------------------
rm -rf "$STAGE" "$DEB_OUT"
mkdir -p \
    "$STAGE/DEBIAN" \
    "$STAGE/opt/$PKG" \
    "$STAGE/opt/$PKG/wheels" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications"

# ---------------------------------------------------------------------------
# 2. Copy the source tree into /opt/gmrs-tty/.
# ---------------------------------------------------------------------------
cp -r \
    "$REPO_ROOT/gmrs_tty" \
    "$REPO_ROOT/main.py" \
    "$REPO_ROOT/bootstrap_models.py" \
    "$REPO_ROOT/requirements.txt" \
    "$REPO_ROOT/config.example.json" \
    "$REPO_ROOT/LICENSE" \
    "$REPO_ROOT/NOTICES.md" \
    "$REPO_ROOT/README.md" \
    "$STAGE/opt/$PKG/"

find "$STAGE/opt/$PKG/" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2b. Install helper scripts into package docs.
# ---------------------------------------------------------------------------
mkdir -p "$STAGE/usr/share/doc/$PKG"
cp "$REPO_ROOT/scripts/install.sh" "$STAGE/usr/share/doc/$PKG/install.sh"
chmod 755 "$STAGE/usr/share/doc/$PKG/install.sh"

# ---------------------------------------------------------------------------
# 2c. Bundle offline models.
#     Both STT (Whisper) and Speaker (ECAPA-TDNN) models must be present.
#     Run 'python bootstrap_models.py' on an internet-connected machine first.
# ---------------------------------------------------------------------------
if [ ! -d "$REPO_ROOT/Models/STT" ]; then
    echo "ERROR: Models/STT/ not found."
    echo "       Run 'python bootstrap_models.py' to download Whisper model first."
    exit 1
fi

echo ">>> Bundling offline models ..."
cp -r "$REPO_ROOT/Models" "$STAGE/opt/$PKG/"
# Strip HuggingFace download cache — only the model files are needed at runtime.
find "$STAGE/opt/$PKG/Models" -type d -name ".cache" -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/opt/$PKG/Models" -name ".gitattributes" -delete 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2d. Bundle Piper TTS voice models.
# ---------------------------------------------------------------------------
if [ ! -d "$REPO_ROOT/Voices" ] || [ -z "$(ls -A "$REPO_ROOT/Voices" 2>/dev/null)" ]; then
    echo "ERROR: Voices/ directory not found or empty."
    echo "       Download Piper voice models into Voices/ before building."
    exit 1
fi

echo ">>> Bundling Piper voice models ..."
cp -r "$REPO_ROOT/Voices" "$STAGE/opt/$PKG/"

# A __main__.py so the launcher can `python -m gmrs_tty`.
cat > "$STAGE/opt/$PKG/gmrs_tty/__main__.py" <<'PY'
from gmrs_tty.app import main

if __name__ == "__main__":
    main()
PY

# ---------------------------------------------------------------------------
# 3. Vendor Python wheels for offline install.
#    --extra-index-url pulls the CPU build of torch instead of CUDA.
# ---------------------------------------------------------------------------
echo ">>> Downloading wheels (this can take a few minutes) ..."
"$PY" -m pip download \
    -r "$REPO_ROOT/requirements.txt" \
    -d "$STAGE/opt/$PKG/wheels" \
    --extra-index-url https://download.pytorch.org/whl/cpu
"$PY" -m pip download pip setuptools wheel \
    -d "$STAGE/opt/$PKG/wheels"

# ---------------------------------------------------------------------------
# 4. Launcher script.
# ---------------------------------------------------------------------------
cat > "$STAGE/usr/bin/$PKG" <<'SH'
#!/bin/sh
# GMRS-TTY launcher.
# Prefers a per-user venv if present, otherwise uses the system venv built by
# the package postinst.

set -e

APP_DIR=/opt/gmrs-tty
SYS_VENV="$APP_DIR/.venv"
USER_STATE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/gmrs-tty"
USER_VENV="$USER_STATE_DIR/.venv"

if [ -x "$USER_VENV/bin/python" ]; then
    PY="$USER_VENV/bin/python"
elif [ -x "$SYS_VENV/bin/python" ]; then
    PY="$SYS_VENV/bin/python"
else
    echo "gmrs-tty: no venv found at $USER_VENV or $SYS_VENV" >&2
    echo "Reinstall the package to recreate it." >&2
    exit 1
fi

cd "$APP_DIR"
exec "$PY" -m gmrs_tty "$@"
SH
chmod 755 "$STAGE/usr/bin/$PKG"

# ---------------------------------------------------------------------------
# 5. Desktop entry.
# ---------------------------------------------------------------------------
cat > "$STAGE/usr/share/applications/${PKG}.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=GMRS-TTY
GenericName=GMRS Text-To-Talk
Comment=Speech-to-text and text-to-speech for GMRS/FRS radios
Exec=gmrs-tty
Icon=utilities-terminal
Terminal=false
Categories=AudioVideo;Audio;HamRadio;Network;
Keywords=GMRS;FRS;radio;TTS;STT;ham;
StartupNotify=true
DESKTOP
chmod 644 "$STAGE/usr/share/applications/${PKG}.desktop"

# ---------------------------------------------------------------------------
# 6. DEBIAN control + maintainer scripts.
# ---------------------------------------------------------------------------
SIZE_KB=$(du -sk "$STAGE/opt" "$STAGE/usr" | awk '{s+=$1} END {print s}')

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: hamradio
Priority: optional
Architecture: $ARCH
Depends: python3.13, python3.13-venv, libportaudio2, libxcb-cursor0, libegl1, libgl1
Recommends: espeak-ng, pulseaudio-utils
Installed-Size: $SIZE_KB
Maintainer: Xpiatio <xpiatio@users.noreply.github.com>
Homepage: https://github.com/Xpiatio/GMRS-TTY
Description: GMRS/FRS speech-to-text and text-to-speech assistant
 GMRS-TTY is a Qt desktop application that lets you talk over GMRS/FRS
 radios using your computer: live speech-to-text on receive (Whisper)
 and text-to-speech on transmit (Piper), with PTT keying and noise
 reduction.
 .
 Whisper STT and speaker identification models are bundled offline.
 Piper TTS voice models are bundled offline.
CONTROL

cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
# Create /opt/gmrs-tty/.venv and install vendored wheels offline.

set -e

APP_DIR=/opt/gmrs-tty
VENV="$APP_DIR/.venv"
WHEELS="$APP_DIR/wheels"

case "$1" in
    configure)
        if ! command -v python3.13 >/dev/null 2>&1; then
            echo "gmrs-tty ERROR: python3.13 not found." >&2
            echo "  On Ubuntu 22.04/24.04: sudo bash /usr/share/doc/gmrs-tty/install.sh" >&2
            exit 1
        fi

        if [ ! -d "$VENV" ]; then
            echo "gmrs-tty: creating Python venv at $VENV ..."
            python3.13 -m venv --without-pip "$VENV"
            "$VENV/bin/python" -m ensurepip --upgrade 2>/dev/null || true
        fi

        echo "gmrs-tty: installing bundled wheels (offline) ..."
        "$VENV/bin/python" -m pip install --quiet --no-index --find-links "$WHEELS" \
            --upgrade pip setuptools wheel || true
        "$VENV/bin/python" -m pip install --quiet --no-index --find-links "$WHEELS" \
            -r "$APP_DIR/requirements.txt"

        # Allow all users to write config.json / contacts.json in-place.
        # The app resolves these files relative to APP_DIR, so the directory
        # must be writable by whoever runs gmrs-tty.
        chmod a+w "$APP_DIR"

        # Seed an initial config.json from the example so first launch works.
        if [ ! -f "$APP_DIR/config.json" ]; then
            cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
            chmod a+rw "$APP_DIR/config.json"
        fi

        if [ -x /usr/bin/update-desktop-database ]; then
            update-desktop-database -q /usr/share/applications || true
        fi

        echo "gmrs-tty: install complete. Run 'gmrs-tty' to launch."
        echo "gmrs-tty: open Settings → Configuration to set your callsign and Piper TTS voice."
        ;;
    abort-upgrade|abort-remove|abort-deconfigure)
        ;;
esac

exit 0
POSTINST

cat > "$STAGE/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
# Tear down the venv so dpkg can purge cleanly.

set -e

APP_DIR=/opt/gmrs-tty
VENV="$APP_DIR/.venv"

case "$1" in
    remove|upgrade|deconfigure)
        if [ -d "$VENV" ]; then
            rm -rf "$VENV"
        fi
        find "$APP_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        ;;
    failed-upgrade)
        ;;
esac

exit 0
PRERM

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
# Refresh the desktop database after our .desktop file disappears.

set -e

case "$1" in
    remove|purge)
        if [ -x /usr/bin/update-desktop-database ]; then
            update-desktop-database -q /usr/share/applications || true
        fi
        ;;
esac

exit 0
POSTRM

chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"
chmod 644 "$STAGE/DEBIAN/control"

# ---------------------------------------------------------------------------
# 7. Build.
# ---------------------------------------------------------------------------
echo ">>> Building $DEB_OUT ..."
dpkg-deb --root-owner-group --build "$STAGE" "$DEB_OUT"

echo
echo ">>> Done."
dpkg-deb -I "$DEB_OUT"
echo
ls -lh "$DEB_OUT"
