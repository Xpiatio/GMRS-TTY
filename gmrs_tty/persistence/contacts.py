import re

# Contact-dict fields that hold a callsign. Order matters for tooltip rendering
# (GMRS line before HAM line) but not for indexing.
_CALLSIGN_FIELDS = ("callsign", "gmrs_callsign", "ham_callsign")


def normalize_callsign(value) -> str:
    """Canonical form for any callsign value: strip whitespace, uppercase."""
    return (value or "").strip().upper()


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
            cs = normalize_callsign(c.get(field, ""))
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
            cs = normalize_callsign(c.get(field, ""))
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
    lines = [normalize_callsign(callsign)]
    for c in entries:
        name = (c.get("name", "") or "").strip() or "(no name)"
        loc = (c.get("location", "") or "").strip()
        header = f"  • {name} — {loc}" if loc else f"  • {name}"
        lines.append(header)
        gmrs = normalize_callsign(c.get("gmrs_callsign", ""))
        ham = normalize_callsign(c.get("ham_callsign", ""))
        if gmrs:
            lines.append(f"      GMRS: {gmrs}")
        if ham:
            lines.append(f"      HAM: {ham}")
    return "\n".join(lines)


def deduplicate_ham_cross_references(contacts):
    """Drop HAM-side duplicates of an existing GMRS-primary contact row.

    Detects the case where the same operator is recorded twice — once
    with their GMRS call as the primary (and HAM listed in
    ``ham_callsign``) and again as a standalone row with their HAM call
    as the primary. The FCC verification + auto-add flows can produce
    this naturally: the GMRS-primary row earns a HAM cross-reference,
    then the operator is heard giving their HAM call and a separate
    pending-pill "+ Add" creates the second row.

    A row ``B`` is treated as a duplicate of row ``A`` when:
      * ``A`` and ``B`` have the same operator name (case-insensitive,
        trimmed), and
      * ``A.ham_callsign`` equals ``B.callsign`` (case-insensitive), and
      * ``A.ham_callsign`` is *not* ``A.callsign`` (so ``A`` is the
        GMRS-primary record, not itself a HAM-primary duplicate).

    Family-shared GMRS callsigns are preserved — rows that share a
    primary callsign but differ in operator name don't match each
    other's HAM cross-references and are left in place. Rows with a
    blank name or blank ham field can't be unambiguously matched and
    are also left in place.

    Returns a new list with the duplicates removed, preserving the
    relative order of the survivors.
    """
    if not contacts:
        return list(contacts or [])

    # (operator name, HAM callsign) → first row that owns this cross-reference
    # as a GMRS-primary record. Subsequent rows whose primary callsign matches
    # this HAM under the same name are duplicates.
    canonical_owners = {}
    for c in contacts:
        name = normalize_callsign(c.get("name"))
        primary = normalize_callsign(c.get("callsign"))
        ham = normalize_callsign(c.get("ham_callsign"))
        if not name or not ham:
            continue
        if primary == ham:
            # The row's primary is itself the HAM call — it's a duplicate
            # candidate, not the canonical GMRS-primary record.
            continue
        canonical_owners.setdefault((name, ham), c)

    survivors = []
    for c in contacts:
        name = normalize_callsign(c.get("name"))
        primary = normalize_callsign(c.get("callsign"))
        if name and primary:
            owner = canonical_owners.get((name, primary))
            if owner is not None and owner is not c:
                continue
        survivors.append(c)
    return survivors


def sort_contacts(contacts):
    """Return `contacts` sorted alphabetically by callsign (case-insensitive),
    with the special 'ALL' open-call entry pinned at index 0 and ties broken
    by operator name so shared family callsigns get a stable order."""
    def key(c):
        cs = normalize_callsign(c.get("callsign", ""))
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
        cs = normalize_callsign(c.get("callsign", ""))
        nm = (c.get("name", "") or "").upper()
        if cs == "ALL":
            return (0, "", "", "")
        m = re.search(r'(\d+)$', cs)
        if not m:
            return (2, cs, nm, "")
        last3 = m.group(1)[-3:].zfill(3)
        return (1, last3, cs, nm)

    return sorted(contacts, key=key)
