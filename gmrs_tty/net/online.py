"""Online-status probe for features that require internet (callsign verification).

The probe targets the crossref API itself rather than a generic host: a working
LAN with a broken upstream still means our feature can't run, and we'd rather
report that honestly than light up a green dot the user can't act on. A short
TTL prevents UI redraws from hammering the network.
"""
import time
import urllib.error
import urllib.request

# The API root we depend on; HEAD against the bare host returns 404 from the
# nginx layer, which is fine — any HTTP response (including 4xx) proves the
# socket round-tripped, so we treat "got a response" as online.
PROBE_URL = "https://api.ke8rxnwx.net/crossref/"
PROBE_TIMEOUT_SECONDS = 2.5
PROBE_TTL_SECONDS = 60.0

_cache = {"value": None, "checked_at": 0.0}


def _probe(url, timeout):
    """One-shot HTTP probe. Returns True if the host responded with any HTTP
    status (including 4xx); returns False / raises on socket-level failure."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status is not None
    except urllib.error.HTTPError:
        # HTTPError means the server *did* answer — connection works.
        return True


def is_online():
    """Return True iff the crossref API host is reachable. Cached for
    PROBE_TTL_SECONDS so chatty UI code doesn't burn DNS lookups."""
    now = time.monotonic()
    cached = _cache["value"]
    if cached is not None and (now - _cache["checked_at"]) < PROBE_TTL_SECONDS:
        return cached
    try:
        result = bool(_probe(PROBE_URL, PROBE_TIMEOUT_SECONDS))
    except (OSError, urllib.error.URLError, TimeoutError):
        result = False
    _cache["value"] = result
    _cache["checked_at"] = now
    return result


def invalidate():
    """Forget the cached online state so the next is_online() re-probes.
    Call this after a verification HTTP call fails — a stale True can outlive
    the actual connection by up to PROBE_TTL_SECONDS otherwise."""
    _cache["value"] = None
    _cache["checked_at"] = 0.0


def reset_cache():
    """Test hook: drop the cache without semantic meaning."""
    invalidate()
