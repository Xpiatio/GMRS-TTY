"""Net session history — structured records of completed Listen sessions.

One JSON file per session in ``sessions_dir`` (``net_sessions/`` beside
``journals/``). Distinct from journals: journals are narrative text, these
are structured attendance rosters kept for history and CSV export. The
roster rows are the attendance-grid shape from
``gmrs_tty.persistence.attendance.build_attendance_rows``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from gmrs_tty.persistence.json_store import save_json

_log = logging.getLogger(__name__)

NET_SESSIONS_DIR = "net_sessions"


def _iso(value: object) -> str:
    """Coerce a unix timestamp or ISO string to one canonical ISO-8601 UTC
    encoding. Blank/unparsable input is passed through unchanged rather than
    raised on, since a session save must never fail on a timestamp quirk."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds")
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def normalize_roster(rows: list[dict]) -> list[dict]:
    """Normalize attendance-grid rows into the stored shape."""
    return [
        {
            "callsign": (row.get("callsign") or "").upper(),
            "name": (row.get("name") or "").strip(),
            "location": (row.get("location") or "").strip(),
            "gmrs": (row.get("gmrs") or "").strip().upper(),
            "ham": (row.get("ham") or "").strip().upper(),
        }
        for row in rows
    ]


def save_session(
    started_at: "str | float | int",
    ended_at: "str | float | int",
    duration_seconds: int,
    roster: list[dict],
    sessions_dir: "Path | str" = NET_SESSIONS_DIR,
) -> str:
    """Write one completed Listen session and return its file path."""
    sessions_dir = Path(sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    session_id = stamp
    path = sessions_dir / f"{session_id}.json"
    save_json(str(path), {
        "id": session_id,
        "started_at": _iso(started_at),
        "ended_at": _iso(ended_at),
        "duration_seconds": int(duration_seconds),
        "roster": normalize_roster(roster),
    })
    return str(path)


def load_session_summaries(sessions_dir: "Path | str" = NET_SESSIONS_DIR) -> list[dict]:
    """Return every session newest-first.

    Summaries carry each roster row's identity (``stations``) because both
    the list UI and the attendance stats need it.
    """
    sessions_dir = Path(sessions_dir)
    if not sessions_dir.is_dir():
        return []
    summaries = []
    for name in sorted(os.listdir(sessions_dir), reverse=True):
        if not name.endswith(".json"):
            continue
        try:
            with open(sessions_dir / name, encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("Skipping unreadable net session file %s: %s", name, exc)
            continue
        roster = entry.get("roster") or []
        summaries.append({
            "id": entry.get("id") or name[:-5],
            "started_at": entry.get("started_at", ""),
            "ended_at": entry.get("ended_at", ""),
            "duration_seconds": entry.get("duration_seconds", 0),
            "checkin_count": len(roster),
            "stations": [
                {"callsign": r.get("callsign", ""), "name": r.get("name", "")}
                for r in roster
            ],
        })
    return summaries


def load_session(session_id: str, sessions_dir: "Path | str" = NET_SESSIONS_DIR) -> "dict | None":
    """Return one full session, or None if unreadable."""
    path = _resolve(session_id, Path(sessions_dir))
    if path is None or not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("Failed to read net session %s: %s", path, exc)
        return None


def delete_session(session_id: str, sessions_dir: "Path | str" = NET_SESSIONS_DIR) -> None:
    """Delete one session. Raises ValueError for an id outside sessions_dir."""
    path = _resolve(session_id, Path(sessions_dir))
    if path is None:
        raise ValueError(f"Invalid session id: {session_id}")
    os.remove(path)


def _resolve(session_id: str, sessions_dir: Path) -> "Path | None":
    """Map a session id to its file path, or None if it escapes sessions_dir."""
    if not session_id or "/" in session_id or "\\" in session_id:
        return None
    target = (sessions_dir / f"{session_id}.json").resolve()
    if not target.is_relative_to(sessions_dir.resolve()):
        return None
    return target
