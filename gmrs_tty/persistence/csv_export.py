"""CSV rendering for net sessions and attendance stats.

Python port of Hearthwave's frontend/src/netsessions/csv.ts, using the
stdlib ``csv`` module so quoting (embedded quotes, commas, newlines) is
handled correctly rather than hand-rolled.
"""
from __future__ import annotations

import csv
import io

_SESSION_HEADER = ["callsign", "name", "location", "gmrs", "ham"]
_ALL_HEADER = ["net_id", "net_date", "callsign", "name"]
_STATS_HEADER = [
    "callsign", "name", "total_nets", "attended_of_recent",
    "recent_window", "current_streak", "last_seen",
]

# Excel and LibreOffice evaluate a cell that opens with one of these as a
# formula. Names and locations come from the operator's own contacts, so this
# is defence in depth rather than a live hole — but exports get mailed around,
# and a leading apostrophe costs nothing. No exported field is ever a negative
# number, so escaping "-" loses no legitimate value.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _render(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(header)
    writer.writerows([_sanitize(cell) for cell in row] for row in rows)
    return buf.getvalue().rstrip("\n")


def session_to_csv(session: dict) -> str:
    """One session's roster: header plus one row per station heard."""
    return _render(_SESSION_HEADER, [
        [r.get(field, "") for field in _SESSION_HEADER]
        for r in session.get("roster") or []
    ])


def all_sessions_to_csv(summaries: list[dict]) -> str:
    """Every session: header plus one row per station per session."""
    rows = []
    for s in summaries:
        date = (s.get("started_at") or "")[:10]
        for station in s.get("stations") or []:
            rows.append([
                s.get("id", ""), date,
                station.get("callsign", ""), station.get("name", ""),
            ])
    return _render(_ALL_HEADER, rows)


def stats_to_csv(stats: list[dict]) -> str:
    """Aggregate attendance stats: one row per station."""
    return _render(_STATS_HEADER, [
        [r.get(field, "") for field in _STATS_HEADER] for r in stats
    ])
