#!/usr/bin/env bash
# install.sh — GMRS-TTY installer helper for Debian / Ubuntu-family Linux.
#
# Usage:
#   sudo bash install.sh                           # auto-finds .deb in CWD
#   sudo bash install.sh path/to/gmrs-tty_*.deb   # explicit path
#
# What it does:
#   1. Detects your distro and version.
#   2. Adds the deadsnakes PPA and installs python3.13 + python3.13-venv on
#      Ubuntu 22.04/24.04 (and derivatives) where Python 3.13 isn't native.
#   3. Installs the required system libraries (libportaudio2, Qt xcb libs, …).
#   4. Installs the .deb with `apt install`, which runs the postinst that
#      creates the virtualenv and installs all bundled Python wheels offline.
#
# Supported platforms:
#   Ubuntu 22.04 (jammy)   — python3.13 via deadsnakes PPA
#   Ubuntu 24.04 (noble)   — python3.13 via deadsnakes PPA
#   Ubuntu 24.10+ (oracular, plucky, …) — python3.13 native
#   Linux Mint 21 / 22     — ubuntu jammy / noble base
#   Pop!_OS 22.04 / 24.04  — ubuntu jammy / noble base
#   Debian 13 (trixie)     — python3.13 native (direct apt also works)
#   LMDE 7 (gigi / trixie) — python3.13 native (direct apt also works)
#
# Unsupported (no Python 3.13 path available via apt):
#   Debian 12 (bookworm)   — install from source instead
#   Ubuntu 20.04 (focal)   — glibc 2.31 is too old for PySide6 6.x (needs ≥2.34)

set -euo pipefail

REQUIRED_PY="python3.13"
DEADSNAKES_PPA="ppa:deadsnakes/ppa"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_bold='\033[1m'
_blue='\033[1;34m'
_green='\033[1;32m'
_yellow='\033[1;33m'
_red='\033[1;31m'
_reset='\033[0m'

info()  { printf "${_blue}[gmrs-tty]${_reset} %s\n" "$*"; }
ok()    { printf "${_green}[gmrs-tty]${_reset} %s\n" "$*"; }
warn()  { printf "${_yellow}[gmrs-tty] WARNING:${_reset} %s\n" "$*" >&2; }
die()   { printf "${_red}[gmrs-tty] ERROR:${_reset} %s\n" "$*" >&2; exit 1; }

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        die "This script must be run as root.\n\nRe-run with: sudo bash $0 ${1:-}"
    fi
}

# ---------------------------------------------------------------------------
# 1. Find the .deb
# ---------------------------------------------------------------------------
find_deb() {
    local explicit="${1:-}"
    if [ -n "$explicit" ]; then
        [ -f "$explicit" ] || die "File not found: $explicit"
        echo "$explicit"
        return
    fi
    local found
    found=$(ls gmrs-tty_*_amd64.deb 2>/dev/null | sort -V | tail -1 || true)
    if [ -z "$found" ]; then
        die "No gmrs-tty_*_amd64.deb found in the current directory.\n\nUsage: sudo bash install.sh path/to/gmrs-tty_VERSION_amd64.deb"
    fi
    echo "$found"
}

# ---------------------------------------------------------------------------
# 2. Detect distro
# ---------------------------------------------------------------------------
detect_distro() {
    [ -f /etc/os-release ] || die "/etc/os-release not found. This installer requires a modern Debian/Ubuntu-family Linux."

    # shellcheck disable=SC1091
    . /etc/os-release

    DISTRO_ID="${ID:-unknown}"
    DISTRO_VERSION="${VERSION_ID:-}"
    DISTRO_CODENAME="${VERSION_CODENAME:-}"
    DISTRO_ID_LIKE="${ID_LIKE:-}"

    IS_UBUNTU_BASED=false
    IS_DEBIAN_BASED=false
    UBUNTU_CODENAME=""

    if [ "$DISTRO_ID" = "ubuntu" ]; then
        IS_UBUNTU_BASED=true
        UBUNTU_CODENAME="$DISTRO_CODENAME"
    elif echo "${DISTRO_ID_LIKE}" | grep -qw "ubuntu"; then
        IS_UBUNTU_BASED=true
        # Linux Mint stores the upstream Ubuntu codename here:
        if [ -f /etc/upstream-release/lsb-release ]; then
            UBUNTU_CODENAME=$(grep DISTRIB_CODENAME /etc/upstream-release/lsb-release \
                | cut -d= -f2 | tr -d '"' || true)
        fi
        # Pop!_OS and others expose UBUNTU_CODENAME directly in os-release:
        if [ -z "$UBUNTU_CODENAME" ] && [ -n "${UBUNTU_CODENAME:-}" ]; then
            : # already set by the sourced os-release
        fi
        # Fallback: the distro's own codename usually matches Ubuntu's:
        if [ -z "$UBUNTU_CODENAME" ]; then
            UBUNTU_CODENAME="$DISTRO_CODENAME"
        fi
    fi

    if [ "$DISTRO_ID" = "debian" ] || echo "${DISTRO_ID_LIKE}" | grep -qw "debian"; then
        IS_DEBIAN_BASED=true
    fi
}

# ---------------------------------------------------------------------------
# 3. Decide how to get python3.13
#    Sets: PYTHON_METHOD (native | deadsnakes | unsupported)
#          PYTHON_PKGS   (space-separated apt package names)
# ---------------------------------------------------------------------------
plan_python() {
    PYTHON_METHOD="unsupported"
    PYTHON_PKGS=""

    # Already present — nothing to do regardless of distro:
    if command -v python3.13 >/dev/null 2>&1; then
        PYTHON_METHOD="native"
        PYTHON_PKGS="python3.13-venv"
        return
    fi

    if $IS_UBUNTU_BASED; then
        case "$UBUNTU_CODENAME" in
            focal)
                # Ubuntu 20.04 — glibc 2.31, PySide6 6.x needs glibc ≥ 2.34.
                PYTHON_METHOD="unsupported"
                return
                ;;
            jammy|noble)
                # Ubuntu 22.04 / 24.04 — python3.13 via deadsnakes PPA.
                PYTHON_METHOD="deadsnakes"
                PYTHON_PKGS="python3.13 python3.13-venv python3.13-distutils"
                return
                ;;
            *)
                # Ubuntu 24.10+ or unknown Ubuntu derivative — try deadsnakes
                # as a fallback; it supports all active Ubuntu LTS/non-LTS.
                PYTHON_METHOD="deadsnakes"
                PYTHON_PKGS="python3.13 python3.13-venv"
                return
                ;;
        esac
    fi

    if $IS_DEBIAN_BASED; then
        case "$DISTRO_CODENAME" in
            trixie|gigi)
                # Debian 13 / LMDE 7 — python3.13 in main repos.
                PYTHON_METHOD="apt"
                PYTHON_PKGS="python3.13 python3.13-venv"
                return
                ;;
            bookworm|bullseye|buster)
                # Debian 12 / 11 / 10 — no python3.13 available via apt.
                PYTHON_METHOD="unsupported"
                return
                ;;
            *)
                # Unknown Debian derivative — try apt, may work on sid/testing.
                PYTHON_METHOD="apt"
                PYTHON_PKGS="python3.13 python3.13-venv"
                return
                ;;
        esac
    fi

    # Unknown distro — try anyway.
    PYTHON_METHOD="apt"
    PYTHON_PKGS="python3.13 python3.13-venv"
}

# ---------------------------------------------------------------------------
# 4. Add deadsnakes PPA (Ubuntu only)
# ---------------------------------------------------------------------------
add_deadsnakes() {
    info "Adding deadsnakes PPA (provides python3.13 for Ubuntu ${UBUNTU_CODENAME}) ..."
    if ! command -v add-apt-repository >/dev/null 2>&1; then
        apt-get install -y --no-install-recommends software-properties-common
    fi
    add-apt-repository -y "$DEADSNAKES_PPA"
    apt-get update -q
    ok "deadsnakes PPA added."
}

# ---------------------------------------------------------------------------
# 5. Install system libraries + Python
# ---------------------------------------------------------------------------
install_dependencies() {
    if [ "$PYTHON_METHOD" = "unsupported" ]; then
        case "$DISTRO_CODENAME" in
            focal|bionic)
                die "Ubuntu ${DISTRO_VERSION} (${DISTRO_CODENAME}) is not supported.\n" \
                    "glibc $(ldd --version 2>/dev/null | head -1 | grep -oP '\d+\.\d+' | head -1 || echo '?') is too old; PySide6 6.x requires glibc ≥ 2.34 (Ubuntu 22.04+).\n\n" \
                    "Upgrade to Ubuntu 22.04 or later, or install GMRS-TTY from source:\n" \
                    "  https://github.com/Xpiatio/GMRS-TTY#from-source"
                ;;
            bookworm|bullseye|buster)
                die "Debian ${DISTRO_VERSION} (${DISTRO_CODENAME}) does not have python3.13 in its repos.\n\n" \
                    "Options:\n" \
                    "  1. Upgrade to Debian 13 (trixie) or LMDE 7.\n" \
                    "  2. Install GMRS-TTY from source:\n" \
                    "       https://github.com/Xpiatio/GMRS-TTY#from-source"
                ;;
            *)
                die "Unsupported distribution: ${DISTRO_ID} ${DISTRO_VERSION} (${DISTRO_CODENAME}).\n\n" \
                    "Supported: Ubuntu 22.04/24.04/24.10+, Linux Mint 21/22,\n" \
                    "           Pop!_OS 22.04/24.04, Debian 13 (trixie), LMDE 7.\n\n" \
                    "Install from source instead:\n" \
                    "  https://github.com/Xpiatio/GMRS-TTY#from-source"
                ;;
        esac
    fi

    info "Installing system libraries ..."
    apt-get install -y --no-install-recommends \
        libportaudio2 libxcb-cursor0 libegl1 libgl1 espeak-ng

    case "$PYTHON_METHOD" in
        deadsnakes)
            add_deadsnakes
            info "Installing python3.13 from deadsnakes ..."
            # shellcheck disable=SC2086
            apt-get install -y --no-install-recommends $PYTHON_PKGS
            ;;
        apt)
            info "Installing python3.13 from system repositories ..."
            # shellcheck disable=SC2086
            apt-get install -y --no-install-recommends $PYTHON_PKGS
            ;;
        native)
            # python3.13 already present; just add venv package if needed.
            if ! dpkg -l python3.13-venv >/dev/null 2>&1; then
                # shellcheck disable=SC2086
                apt-get install -y --no-install-recommends $PYTHON_PKGS
            fi
            ;;
    esac

    command -v python3.13 >/dev/null 2>&1 \
        || die "python3.13 still not found after installation. Check apt output above."
    ok "python3.13 is available: $(python3.13 --version)"
}

# ---------------------------------------------------------------------------
# 6. Install the .deb
# ---------------------------------------------------------------------------
install_deb() {
    local deb="$1"
    info "Installing ${deb} ..."
    # apt handles Depends resolution and runs postinst.
    apt install -y "$deb" || {
        echo ""
        die "Installation failed.\n\n" \
            "Common causes:\n" \
            "  • A dependency could not be installed — check the apt output above.\n" \
            "  • The .deb was built for a different architecture.\n" \
            "  • Run 'sudo apt-get install -f' to attempt automatic repair.\n\n" \
            "Report issues at: https://github.com/Xpiatio/GMRS-TTY/issues"
    }
    ok "GMRS-TTY installed successfully."
    echo ""
    echo "  Run:  gmrs-tty"
    echo "  Then: Settings → Configuration to set your callsign and voice."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    require_root "${1:-}"

    local deb_path
    deb_path=$(find_deb "${1:-}")

    echo ""
    info "GMRS-TTY installer"
    info "Package : ${deb_path}"

    detect_distro
    info "Detected: ${DISTRO_ID} ${DISTRO_VERSION} (${DISTRO_CODENAME})"
    if $IS_UBUNTU_BASED && [ -n "$UBUNTU_CODENAME" ]; then
        info "Ubuntu base codename: ${UBUNTU_CODENAME}"
    fi

    plan_python
    info "Python 3.13 install method: ${PYTHON_METHOD}"

    install_dependencies
    install_deb "$deb_path"
}

main "$@"
