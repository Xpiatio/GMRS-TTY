"""Session journal persistence — save and load from the journals/ directory."""
from __future__ import annotations

import json
import os
from datetime import datetime

JOURNALS_DIR = "journals"


def _ensure_dir() -> None:
    os.makedirs(JOURNALS_DIR, exist_ok=True)


def save_journal(
    title: str,
    summary: str,
    callsigns: list[str],
    transcript: str,
) -> str:
    """Write a journal entry and return its file path."""
    _ensure_dir()
    now = datetime.now()
    filename = now.strftime("%Y%m%d_%H%M%S") + ".json"
    path = os.path.join(JOURNALS_DIR, filename)
    entry = {
        "exported_at": now.isoformat(timespec="seconds"),
        "title": title,
        "callsigns": list(callsigns),
        "transcript": transcript,
        "summary": summary,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2, ensure_ascii=False)
    return path


def load_journals() -> list[dict]:
    """Return all journal entries sorted newest-first."""
    if not os.path.isdir(JOURNALS_DIR):
        return []
    entries = []
    for name in sorted(os.listdir(JOURNALS_DIR), reverse=True):
        if not name.endswith(".json"):
            continue
        path = os.path.join(JOURNALS_DIR, name)
        try:
            with open(path, encoding="utf-8") as fh:
                entries.append(json.load(fh))
        except (OSError, json.JSONDecodeError):
            continue
    return entries
