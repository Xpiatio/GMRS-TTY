import datetime

CONFIG_FILE = "config.json"
CONTACTS_FILE = "contacts.json"


def utc_now_iso() -> str:
    """Return the current UTC time as a compact ISO-8601 string (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Radio-service mode. GMRS requires a callsign; FRS doesn't, so when the user
# selects FRS we disable every callsign-dependent feature (preface, ID rule,
# contacts, pill highlighting, detection, online verification). Stored on
# config.json as `radio_service`.
SERVICE_GMRS = "GMRS"
SERVICE_FRS = "FRS"
DEFAULT_SERVICE = SERVICE_GMRS


def normalize_service(value):
    """Coerce whatever's in config.json into a known service constant.
    Anything unrecognized (None, typo, missing key) falls back to GMRS — the
    licensed mode is the safe default because it preserves Part 95 ID-rule
    enforcement until the user explicitly opts into FRS."""
    if not value:
        return DEFAULT_SERVICE
    upper = str(value).strip().upper()
    if upper == SERVICE_FRS:
        return SERVICE_FRS
    return SERVICE_GMRS


# WCAG 2.1 AA color palette. Text colors meet ≥4.5:1 contrast against white;
# UI borders/icons meet ≥3:1. Picked from the Tailwind palette which has
# documented contrast ratios.
COLOR_RX = "#15803D"      # green-700, 5.59:1 on white — incoming transmissions
COLOR_TX = "#1D4ED8"      # blue-700, 7.10:1 on white — outgoing transmissions
COLOR_ERROR = "#B91C1C"   # red-700, 6.45:1 on white — errors
COLOR_WARN = "#92400E"    # amber-800, 8.13:1 on white — warnings / info
PILL_BG = "#FEF3C7"       # amber-100 background for pending-station pills
PILL_TEXT = "#78350F"     # amber-900, ≥10:1 on PILL_BG
PILL_BORDER = "#A16207"   # amber-700, 4.05:1 on white (UI border)

# FCC-verified marker. Used by the Contacts dialog's verified column and by
# the chat display's pill highlighter to flag callsigns whose contact entry
# has a confirmed FCC license match. The color matches COLOR_RX (same
# green-700) so the "verified" semantic reads consistently across surfaces.
VERIFIED_GLYPH = "✓"
VERIFIED_COLOR = COLOR_RX

VOICE_TEST_TEXT = "GMRS-TTY voice test. Radio check, one two three."

# Common Whisper hallucinations on silence/noise — drop these transcripts.
HALLUCINATIONS: frozenset[str] = frozenset({
    "you", "thank you", "thanks", "thanks for watching",
    "thank you for watching", "thanks for watching!", "bye", ".",
    "okay", "ok", "yeah", "mm", "hmm",
})
