import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "scripts" / "voices.txt"
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch-voices.sh"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-deb.sh"

# en/en_US/ryan/high/en_US-ryan-high — the tail must restate locale, name and
# quality, because fetch-voices.sh flattens each entry to its basename.
ENTRY = re.compile(
    r"(?P<lang>[a-z]{2})/(?P<locale>[a-z]{2}_[A-Z]{2})/(?P<name>[a-z0-9_]+)/"
    r"(?P<quality>x_low|low|medium|high)/"
    r"(?P=locale)-(?P=name)-(?P=quality)"
)


def manifest_entries() -> list[str]:
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    return [
        stripped
        for stripped in (line.split("#", 1)[0].strip() for line in lines)
        if stripped
    ]


def test_manifest_is_not_empty():
    assert manifest_entries()


def test_every_entry_is_a_wellformed_voice_path():
    for entry in manifest_entries():
        assert ENTRY.fullmatch(entry), entry


def test_no_duplicate_voice_basenames():
    names = [entry.rsplit("/", 1)[-1] for entry in manifest_entries()]
    assert len(names) == len(set(names)), names


def test_fetch_script_is_executable_and_reads_the_manifest():
    assert os.access(FETCH_SCRIPT, os.X_OK)
    assert "voices.txt" in FETCH_SCRIPT.read_text(encoding="utf-8")


def test_build_script_does_not_claim_models_are_unbundled():
    # The deb has bundled both since 2c/2d were added; the header comment and
    # the control Description drifted behind that for several releases.
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "NOT bundled" not in text
    assert "speaker identification" not in text
