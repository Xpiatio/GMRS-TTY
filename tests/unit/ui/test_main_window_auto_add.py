"""scan_for_unknown_stations should auto-add a detected callsign to the
contact list when:

* we're online, AND
* the transcript surfaced a plausible operator name, AND
* the FCC crossref API confirms the callsign-and-name pair (status=verified).

Any other condition (offline, blank name extracted, known call, name mismatch,
HTTP error) must fall back to the legacy '+ Add' pending-pill flow so the
operator can still review the row manually.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.fcc.crossref import VerificationResult  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


def _make_window(qapp, contacts, online=True):
    """Build a MainWindow with a controlled contact list and a stubbed PTT.

    ``is_online`` is patched so the test controls whether scan_for_unknown
    treats the runtime as connected without touching the cached probe state.
    """
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSAA111", "name": "Operator", "location": "Home",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return [dict(c) for c in contacts]

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=online):
        window = mw_mod.MainWindow()
    return window


def _patch_save():
    """Stop the test from touching ``contacts.json`` on disk."""
    import gmrs_tty.ui.pending_station_manager as psm_mod
    return patch.object(psm_mod, "save_json", return_value=None)


class _SyncWorker:
    """Stand-in for ``CallsignLookupWorker`` that runs synchronously inside
    ``start()``. Lets us assert the full auto-add flow without spinning up a
    real QThread (and without needing the test to pump the Qt event loop)."""

    def __init__(self, result):
        self.result = result
        self.factory_calls = []

    def __call__(self, callsign, name, location, parent=None):
        self.factory_calls.append((callsign, name, location))
        worker = _SyncWorkerInstance(callsign, name, location, self.result)
        return worker


class _SyncWorkerInstance:
    def __init__(self, callsign, name, location, result):
        self.callsign = callsign
        self.name = name
        self.location = location
        self.result = result
        self._handlers = []
        self._finished_handlers = []

    class _Signal:
        def __init__(self, parent, kind):
            self.parent = parent
            self.kind = kind

        def connect(self, fn):
            if self.kind == "result":
                self.parent._handlers.append(fn)
            else:
                self.parent._finished_handlers.append(fn)

        def disconnect(self, *args, **kwargs):
            if self.kind == "result":
                self.parent._handlers.clear()

    @property
    def result_ready(self):
        return self._Signal(self, "result")

    @property
    def finished(self):
        return self._Signal(self, "finished")

    def start(self):
        for fn in list(self._handlers):
            fn(self.callsign, self.name, self.location, self.result)
        for fn in list(self._finished_handlers):
            fn()

    def isRunning(self):
        return False

    def wait(self, *_args):
        return True

    def deleteLater(self):
        pass


def _install_sync_worker(result):
    """Replace ``auto_add.CallsignLookupWorker`` with a synchronous stand-in
    for the duration of the test. The import inside MainWindow happens lazily,
    so we patch the module attribute after import to keep things simple."""
    from gmrs_tty.fcc import auto_add
    factory = _SyncWorker(result)
    return patch.object(auto_add, "CallsignLookupWorker", side_effect=factory), factory


def _verified_result(license_name="Zomberg, Benjamin J", city="JENISON",
                     gmrs="WSLZ233", ham="KE8RXN"):
    return VerificationResult(
        status="verified",
        license_name=license_name,
        license_location=f"{city.title()}, MI",
        license_city=city,
        license_active=True,
        gmrs_callsign=gmrs,
        ham_callsign=ham,
    )


class TestAutoAddVerified:
    def test_verified_lookup_appends_contact_and_removes_pill(self, qapp):
        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            ctx, factory = _install_sync_worker(_verified_result())
            with ctx, _patch_save():
                w.pending_manager.scan_for_unknown_stations("This is WSLZ233 Benjamin from Jenison")
            # The synchronous worker fired the verified result inline, so the
            # pending pill should have been replaced by a real contact row.
            assert "WSLZ233" not in w.pending_manager.buttons
            added = [c for c in w.contacts if c.get("callsign") == "WSLZ233"]
            assert len(added) == 1, "Verified lookup must add exactly one row"
            row = added[0]
            assert row["name"] == "Benjamin"
            assert row["verified"] is True
            assert row["gmrs_callsign"] == "WSLZ233"
            assert row["ham_callsign"] == "KE8RXN"
            # Lookup was issued with the transcript-derived name; suffix
            # arguments captured by the stub prove the wiring carries through.
            assert factory.factory_calls == [("WSLZ233", "Benjamin", "Jenison")]
        finally:
            w.close()

    def test_verified_lookup_backfills_location_when_blank(self, qapp):
        """When the transcript didn't include a 'from <city>' clause, the
        FCC city should win the location field — same backfill rule as the
        manual-add path."""
        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            ctx, _factory = _install_sync_worker(_verified_result())
            with ctx, _patch_save():
                # No 'from <city>' clause — extract_name_location returns ''
                # for location, so the FCC city is the only source.
                w.pending_manager.scan_for_unknown_stations("This is WSLZ233 Benjamin here")
            row = [c for c in w.contacts if c.get("callsign") == "WSLZ233"][0]
            assert row["location"] == "Jenison"
        finally:
            w.close()


class TestAutoAddNoOp:
    def test_offline_does_not_trigger_lookup(self, qapp):
        import gmrs_tty.ui.pending_station_manager as psm_mod
        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            ctx, factory = _install_sync_worker(_verified_result())
            with patch.object(psm_mod, "is_online", return_value=False), ctx:
                w.pending_manager.scan_for_unknown_stations("This is WSLZ233 Benjamin here")
            # Pending pill exists (legacy flow), lookup was NOT issued.
            assert "WSLZ233" in w.pending_manager.buttons
            assert factory.factory_calls == []
            assert not any(c.get("callsign") == "WSLZ233" for c in w.contacts)
        finally:
            w.close()

    def test_no_extracted_name_does_not_trigger_lookup(self, qapp):
        """A transcript with a bare callsign and no operator name should
        not waste an API call — the FCC name match would never succeed."""
        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            ctx, factory = _install_sync_worker(_verified_result())
            with ctx, _patch_save():
                # Just the callsign, no capitalized word after it.
                w.pending_manager.scan_for_unknown_stations("WSLZ233 ten four")
            assert "WSLZ233" in w.pending_manager.buttons
            assert factory.factory_calls == []
        finally:
            w.close()

    def test_name_mismatch_leaves_pending_pill(self, qapp):
        """status=callsign_only means the FCC licensee name didn't match.
        We must not auto-add — but the pending pill should remain so the
        operator can decide manually (family-member-on-shared-call case)."""
        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            mismatch = VerificationResult(
                status="callsign_only",
                license_name="Zomberg, Benjamin J",
                license_active=True,
            )
            ctx, _factory = _install_sync_worker(mismatch)
            with ctx, _patch_save():
                w.pending_manager.scan_for_unknown_stations("This is WSLZ233 Eliza here")
            assert "WSLZ233" in w.pending_manager.buttons
            assert not any(c.get("callsign") == "WSLZ233" for c in w.contacts)
        finally:
            w.close()

    def test_known_callsign_does_not_trigger_lookup(self, qapp):
        w = _make_window(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
        ])
        try:
            ctx, factory = _install_sync_worker(_verified_result())
            with ctx, _patch_save():
                w.pending_manager.scan_for_unknown_stations("This is WSLZ233 Benjamin here")
            assert factory.factory_calls == []
        finally:
            w.close()

    def test_repeat_detection_during_lookup_deduped(self, qapp):
        """Two scans of the same callsign in quick succession must result
        in at most one API call. The first scan already creates the pending
        pill, so the duplicate-suppression in scan_for_unknown_stations
        (``cs in self.pending_buttons``) handles the common case; this guards
        the regression."""
        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            # Use a callsign-only result so the pill stays up between scans.
            mismatch = VerificationResult(
                status="callsign_only",
                license_name="Zomberg, Benjamin J",
                license_active=True,
            )
            ctx, factory = _install_sync_worker(mismatch)
            with ctx, _patch_save():
                w.pending_manager.scan_for_unknown_stations("This is WSLZ233 Benjamin here")
                w.pending_manager.scan_for_unknown_stations("WSLZ233 Benjamin again")
            assert len(factory.factory_calls) == 1
        finally:
            w.close()


class TestPendingLookupCap:
    def test_lookup_skipped_when_cap_reached(self, qapp):
        from gmrs_tty.ui.pending_station_manager import _MAX_PENDING_LOOKUPS

        w = _make_window(qapp, [{"callsign": "All", "name": "Everyone"}])
        try:
            # Pre-fill _lookups to the cap with worker stubs that satisfy
            # disconnect_workers (needs result_ready.disconnect and isRunning).
            w.pending_manager._lookups = {
                f"FAKE{i:03d}": _SyncWorkerInstance(f"FAKE{i:03d}", "", "", None)
                for i in range(_MAX_PENDING_LOOKUPS)
            }

            ctx, factory = _install_sync_worker(_verified_result())
            with ctx, _patch_save():
                w.pending_manager._start_callsign_lookup("WSLZ233", "Benjamin", "Jenison")

            assert factory.factory_calls == [], (
                "No worker should be created when _lookups is at capacity"
            )
        finally:
            w.pending_manager._lookups.clear()
            w.close()
