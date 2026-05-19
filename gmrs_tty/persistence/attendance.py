"""Listening-session attendance tracking.

Pure data model for the attendance grid: an ordered set of callsigns
heard during the current Listen session, plus a resolver that joins
those callsigns against the saved contact list so the UI can show
Name / Location / GMRS / HAM the moment a callsign is added to (or
already in) contacts.

Kept separate from the Qt panel so the dedup + ordering + contact-join
logic is testable without a display server.
"""
from __future__ import annotations

from typing import Iterable

from gmrs_tty.persistence.contacts import index_contacts_by_callsign, normalize_callsign


class AttendanceTracker:
    """Ordered, deduplicated set of callsigns heard this session.

    Insertion order is preserved so the grid reads chronologically: the
    first station heard sits at the top, regardless of any later
    alphabetical or contact-aware sort the panel might layer on.
    """

    def __init__(self) -> None:
        self._order: list[str] = []
        self._seen: set[str] = set()

    def record(self, callsign: str) -> bool:
        cs = normalize_callsign(callsign)
        if not cs:
            return False
        if cs in self._seen:
            return False
        self._seen.add(cs)
        self._order.append(cs)
        return True

    def remove(self, callsign: str) -> bool:
        """Remove *callsign* from the session. Returns True if it was present."""
        cs = normalize_callsign(callsign)
        if cs not in self._seen:
            return False
        self._seen.discard(cs)
        self._order.remove(cs)
        return True

    def clear(self) -> None:
        self._order.clear()
        self._seen.clear()

    def callsigns(self) -> list[str]:
        return list(self._order)

    def __contains__(self, callsign: str) -> bool:
        return normalize_callsign(callsign) in self._seen

    def __len__(self) -> int:
        return len(self._order)


def build_attendance_rows(callsigns: Iterable[str], contacts) -> list[dict]:
    """Join `callsigns` against `contacts` and return one row per call.

    Each row carries five string fields (``callsign``, ``name``,
    ``location``, ``gmrs``, ``ham``); unknown callsigns get blank
    name / location / GMRS / HAM so the grid still records "we heard
    this station" with no contact match.

    Matching considers every callsign field on a contact (primary,
    ``gmrs_callsign``, ``ham_callsign``) so a contact whose primary is
    their HAM call still resolves when their GMRS call is heard. When
    multiple contacts share a callsign (family-shared GMRS case), the
    first one wins — the rest are documented via the chat tooltip and
    Contacts dialog rather than fanning out into the attendance grid.
    """
    index = index_contacts_by_callsign(contacts)
    rows = []
    for cs in callsigns:
        cs = normalize_callsign(cs)
        if not cs:
            continue
        entries = index.get(cs, [])
        if entries:
            c = entries[0]
            rows.append({
                "callsign": cs,
                "name": (c.get("name", "") or "").strip(),
                "location": (c.get("location", "") or "").strip(),
                "gmrs": normalize_callsign(c.get("gmrs_callsign", "")),
                "ham": normalize_callsign(c.get("ham_callsign", "")),
            })
        else:
            rows.append({
                "callsign": cs,
                "name": "",
                "location": "",
                "gmrs": "",
                "ham": "",
            })
    return rows
