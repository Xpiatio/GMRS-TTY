"""Attendance statistics across stored net sessions.

Pure aggregation — callers pass in the summaries from
``net_sessions.load_session_summaries`` (newest-first) and the contact list.
"""
from __future__ import annotations

from gmrs_tty.persistence.contacts import index_contacts_by_callsign, normalize_callsign

# How many of the most recent nets the "attended N of last M" figure covers.
_RECENT_WINDOW = 10


def compute_attendance_stats(
    summaries: list[dict], contacts: list[dict] | None = None
) -> list[dict]:
    """Aggregate per-station attendance, busiest station first.

    A station is ``(callsign, name)``, not callsign alone: on GMRS a whole
    family shares one licensed callsign, so keying on callsign would collapse
    the whole household into one row — the opposite of what a family net wants.

    ``summaries`` must be newest-first, which is what the store returns —
    ``current_streak`` and ``last_seen`` both depend on that ordering.
    """
    index = index_contacts_by_callsign(contacts or [])
    # One pass over the sessions records each station's session positions
    # (0 = newest). Totals, the recent-window count and the streak all read
    # from that list, so nothing re-scans the session history per station.
    per_session = [_station_names(s) for s in summaries]
    recent_window = min(len(per_session), _RECENT_WINDOW)

    appearances: dict[tuple[str, str], list[int]] = {}
    display: dict[tuple[str, str], str] = {}
    last_seen: dict[tuple[str, str], str] = {}

    for position, (session, stations) in enumerate(zip(summaries, per_session)):
        for key, name in stations.items():
            appearances.setdefault(key, []).append(position)
            # Newest-first means the first sighting is the most recent one, so
            # both the timestamp and the name spelling come from the newest net.
            last_seen.setdefault(key, session.get("started_at", ""))
            if name:
                display.setdefault(key, name)

    rows = [
        {
            "callsign": key[0],
            "name": display.get(key) or _contact_name(index, key[0]),
            "total_nets": len(positions),
            "attended_of_recent": sum(1 for p in positions if p < recent_window),
            "recent_window": recent_window,
            "current_streak": _streak(positions),
            "last_seen": last_seen.get(key, ""),
        }
        for key, positions in appearances.items()
    ]
    rows.sort(key=lambda r: (-r["total_nets"], r["callsign"], r["name"]))
    return rows


def _station_names(session: dict) -> dict[tuple[str, str], str]:
    """Stations in one session summary, keyed ``(callsign, folded name)``.

    The value is the name as it was typed; the key folds case and surrounding
    whitespace so "Maria" and "maria " are the same person across nets.
    """
    stations: dict[tuple[str, str], str] = {}
    for station in session.get("stations") or []:
        cs = normalize_callsign(station.get("callsign", ""))
        if not cs:
            continue
        name = (station.get("name") or "").strip()
        stations.setdefault((cs, name.casefold()), name)
    return stations


def _streak(positions: list[int]) -> int:
    """Consecutive most-recent sessions containing this station.

    ``positions`` are the station's session positions in ascending order with
    0 the newest net, so the streak is the length of the leading run
    0, 1, 2, ... — the first gap ends it.
    """
    streak = 0
    for position in positions:
        if position != streak:
            break
        streak += 1
    return streak


def _contact_name(index: dict, callsign: str) -> str:
    entries = index.get(callsign) or []
    return (entries[0].get("name") or "").strip() if entries else ""
