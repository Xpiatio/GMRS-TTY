import re


def index_contacts_by_callsign(contacts):
    """Return {UPPERCASED_CALLSIGN: [contact, …]} for use as a fast lookup.
    Skips empty callsigns and the 'ALL' open-call shortcut. Preserves input
    order within each bucket so duplicates render in the order they're stored."""
    index = {}
    for c in contacts or []:
        cs = (c.get("callsign", "") or "").upper()
        if not cs or cs == "ALL":
            continue
        index.setdefault(cs, []).append(c)
    return index


def format_callsign_tooltip(callsign, contacts):
    """Render a multi-line tooltip body listing every name/location entry that
    shares `callsign`. Returns '' when no entries are supplied so callers can
    treat it as falsy."""
    entries = list(contacts or [])
    if not entries:
        return ""
    lines = [callsign.upper()]
    for c in entries:
        name = (c.get("name", "") or "").strip() or "(no name)"
        loc = (c.get("location", "") or "").strip()
        lines.append(f"  • {name} — {loc}" if loc else f"  • {name}")
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
