#!/usr/bin/env bash
# Download the Piper voice models listed in scripts/voices.txt into Voices/.
#
# Voices/ is gitignored, so a fresh clone (and every CI runner) starts without
# it while scripts/build-deb.sh hard-requires it. This script closes that gap.
#
# Usage:
#   ./scripts/fetch-voices.sh                    # into <repo>/Voices
#   VOICES_DIR=/tmp/voices ./scripts/fetch-voices.sh
#
# Re-running is safe: files already present are left alone.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/scripts/voices.txt"
VOICES_DIR="${VOICES_DIR:-$REPO_ROOT/Voices}"
BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main"

if [[ ! -f "$MANIFEST" ]]; then
    echo "ERROR: manifest not found: $MANIFEST" >&2
    exit 1
fi

mkdir -p "$VOICES_DIR"
echo ">>> Fetching Piper voices into $VOICES_DIR"

fetch() {
    local url="$1" dest="$2"
    if [[ -s "$dest" ]]; then
        echo "    skip $(basename "$dest") (already present)"
        return
    fi
    echo "    get  $(basename "$dest")"
    # Download to a temp name so an interrupted run cannot leave a truncated
    # file that the next run would happily skip.
    curl --fail --location --silent --show-error --output "$dest.part" "$url"
    if [[ ! -s "$dest.part" ]]; then
        rm -f "$dest.part"
        echo "ERROR: downloaded an empty file from $url" >&2
        exit 1
    fi
    mv "$dest.part" "$dest"
}

count=0
while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"
    line="$(echo "$line" | xargs)"
    [[ -z "$line" ]] && continue

    name="$(basename "$line")"
    fetch "$BASE_URL/$line.onnx" "$VOICES_DIR/$name.onnx"
    fetch "$BASE_URL/$line.onnx.json" "$VOICES_DIR/$name.onnx.json"
    count=$((count + 1))
done < "$MANIFEST"

if [[ "$count" -eq 0 ]]; then
    echo "ERROR: no voices listed in $MANIFEST" >&2
    exit 1
fi

echo ">>> Done — $count voice(s) in $VOICES_DIR"
