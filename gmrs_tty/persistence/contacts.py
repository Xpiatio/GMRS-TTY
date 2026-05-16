import re

# Contact-dict fields that hold a callsign. Order matters for tooltip rendering
# (GMRS line before HAM line) but not for indexing.
_CALLSIGN_FIELDS = ("callsign", "gmrs_callsign", "ham_callsign")


def known_callsigns(contacts):
    """Return the set of UPPERCASED callsigns this contact list 'knows about',
    pulled from every populated callsign field (primary `callsign`,
    `gmrs_callsign`, `ham_callsign`) across every contact. Skips the 'ALL'
    open-call shortcut and blank values.

    Powers the unknown-station detection — a detected callsign is unknown
    only if it's not in this set, so a HAM call over the air doesn't trigger
    a redundant '+ Add' pill when that operator's GMRS call is already
    saved (or vice versa)."""
    known = set()
    for c in contacts or []:
        for field in _CALLSIGN_FIELDS:
            cs = (c.get(field, "") or "").upper()
            if not cs or cs == "ALL":
                continue
            known.add(cs)
    return known


def index_contacts_by_callsign(contacts):
    """Return {UPPERCASED_CALLSIGN: [contact, …]} for use as a fast lookup.

    A single contact is indexed under each of its callsign fields (primary
    `callsign`, `gmrs_callsign`, `ham_callsign`) so the chat-display
    highlighter finds the contact whichever form a remote operator speaks —
    a HAM addressing the contact by their amateur call hits the same bucket
    as a GMRS user addressing them by their family GMRS call.

    Skips empty callsigns and the 'ALL' open-call shortcut. Preserves input
    order within each bucket so duplicates render in the order they're
    stored. A contact is added to a bucket only once even when two of its
    fields resolve to the same value (common case: primary callsign equals
    the HAM cross-reference)."""
    index = {}
    for c in contacts or []:
        seen_keys = set()
        for field in _CALLSIGN_FIELDS:
            cs = (c.get(field, "") or "").upper()
            if not cs or cs == "ALL" or cs in seen_keys:
                continue
            seen_keys.add(cs)
            index.setdefault(cs, []).append(c)
    return index


def format_callsign_tooltip(callsign, contacts):
    """Render a multi-line tooltip body listing every entry that shares
    `callsign` (under any of its callsign fields). Each entry shows name,
    location, and — when known — its GMRS / HAM cross-references. Returns ''
    when no entries are supplied so callers can treat it as falsy."""
    entries = list(contacts or [])
    if not entries:
        return ""
    lines = [callsign.upper()]
    for c in entries:
        name = (c.get("name", "") or "").strip() or "(no name)"
        loc = (c.get("location", "") or "").strip()
        header = f"  • {name} — {loc}" if loc else f"  • {name}"
        lines.append(header)
        gmrs = (c.get("gmrs_callsign", "") or "").strip().upper()
        ham = (c.get("ham_callsign", "") or "").strip().upper()
        if gmrs:
            lines.append(f"      GMRS: {gmrs}")
        if ham:
            lines.append(f"      HAM: {ham}")
    return "\n".join(lines)


def sort_contacts(contacts):
    """Return `contacts` sorted alphabetically by callsign (case-insensitive),
    with the special 'ALL' open-call entry pinned at index 0 and ties broken
    by operator name so shared family callsigns get a stable order."""
    def key(c):
        cs = (c.get("callsign", "") or "").upper()
        nm = (c.get("name", "") or "").upper()
        # ALL is the open-call shortcut, not a real station; keep it first
        # regardless of where it would sort alphabetically.
        if cs == "ALL":
            return (0, "", "")
        return (1, cs, nm)

    return sorted(contacts, key=key)


def sort_contacts_by_suffix(contacts):
    """Return `contacts` sorted by the trailing digits of each callsign — the
    last 3 numbers of a GMRS callsign. 'ALL' stays pinned at index 0; entries
    without trailing digits sort to the end. The trailing-digit key is taken
    as the last 3 digits left-padded to 3 chars, so legacy 4-digit and modern
    3-digit suffixes interleave consistently."""
    def key(c):
        cs = (c.get("callsign", "") or "").upper()
        nm = (c.get("name", "") or "").upper()
        if cs == "ALL":
            return (0, "", "", "")
        m = re.search(r'(\d+)$', cs)
        if not m:
            return (2, cs, nm, "")
        last3 = m.group(1)[-3:].zfill(3)
        return (1, last3, cs, nm)

    return sorted(contacts, key=key)
