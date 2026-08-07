import re
import subprocess
import sys
from pathlib import Path

import gmrs_tty

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", gmrs_tty.__version__)


def test_version_sync_check_passes_on_tree():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_version_sync.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
