"""Session journal persistence — save and load from the journals/ directory."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

JOURNALS_DIR = "journals"


def _ensure_dir() -> None:
    os.makedirs(JOURNALS_DIR, exist_ok=True)


def save_journal(
    title: str,
    summary: str,
    callsigns_with_locations: list[dict],
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
        "callsigns": [c.get("callsign", "") for c in callsigns_with_locations],
        "callsigns_locations": list(callsigns_with_locations),
        "transcript": transcript,
        "summary": summary,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2, ensure_ascii=False)
    return path


def load_journals() -> list[dict]:
    """Return all journal entries sorted newest-first.

    Each entry contains a ``_file`` key with the absolute path to its source
    file so callers can pass it to ``delete_journal`` without reconstructing it.
    """
    if not os.path.isdir(JOURNALS_DIR):
        return []
    entries = []
    for name in sorted(os.listdir(JOURNALS_DIR), reverse=True):
        if not name.endswith(".json"):
            continue
        path = os.path.join(JOURNALS_DIR, name)
        try:
            with open(path, encoding="utf-8") as fh:
                entry = json.load(fh)
            entry["_file"] = path
            entries.append(entry)
        except (OSError, json.JSONDecodeError):
            continue
    return entries


def delete_journal(file_path: str) -> None:
    """Delete the journal entry at *file_path*."""
    journals_dir = Path(JOURNALS_DIR).resolve()
    target = Path(file_path).resolve()
    if not target.is_relative_to(journals_dir):
        raise ValueError(f"Refusing to delete file outside journals directory: {file_path}")
    os.remove(target)
