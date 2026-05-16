"""Verified column + Verify-all wiring on ContactsDialog.

Verification is the one online feature so far: when the network probe says
we're offline, the Verify-all button has to disable so users don't sit on
multi-second timeouts per contact.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.fcc import crossref  # noqa: E402
from gmrs_tty.ui.contacts_dialog import ContactsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_dialog(qapp, contacts, online=True):
    """Construct a ContactsDialog with the online probe forced to a known
    value. Callers patch crossref.verify_callsign on top of this if they need
    to drive the verify flow."""
    with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=online):
        dlg = ContactsDialog(contacts)
    return dlg


class TestColumnLayout:
    """Six columns: Callsign | Name | Location | GMRS | HAM | Verified.
    GMRS / HAM appear after the personal fields so the operator-identifying
    cluster stays leftmost; Verified remains the rightmost status column."""

    def test_has_six_columns(self, qapp):
        dlg = _make_dialog(qapp, [])
        assert dlg.table.columnCount() == 6
        headers = [dlg.table.horizontalHeaderItem(i).text()
                   for i in range(dlg.table.columnCount())]
        assert headers == ["Callsign", "Name", "Location", "GMRS", "HAM", "Verified"]


class TestVerifiedColumn:
    def test_verified_cell_shows_check_for_verified_contact(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin", "verified": True},
        ])
        cell = dlg.table.item(0, 5)
        assert cell is not None
        # Whatever glyph we render, a verified row's accessible/tool-tip text
        # has to include "verified" so screen readers don't see a bare check.
        text = (cell.toolTip() + " " + (cell.text() or "")).lower()
        assert "verified" in text

    def test_verified_cell_blank_for_unverified_contact(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
        ])
        cell = dlg.table.item(0, 5)
        # No verification yet: cell exists (so the column is well-formed) but
        # should not display a check glyph.
        if cell is not None:
            assert "✓" not in (cell.text() or "")


class TestGmrsAndHamColumns:
    """The GMRS and HAM columns surface the FCC cross-references next to the
    primary callsign so the operator can see all three forms at a glance —
    and edit them by hand when a row hasn't been verified yet."""

    def test_columns_render_existing_cross_reference_values(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "KE8RXN", "name": "Collin", "location": "Grand Rapids",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ])
        assert dlg.table.item(0, 3).text() == "WRPN553"
        assert dlg.table.item(0, 4).text() == "KE8RXN"

    def test_blank_cells_for_unverified_contact(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSAC909", "name": "Tim"},
        ])
        assert (dlg.table.item(0, 3).text() or "") == ""
        assert (dlg.table.item(0, 4).text() or "") == ""

    def test_manual_edit_round_trips_through_get_contacts(self, qapp):
        """Operator types a HAM callsign into the grid for an unverified
        row — that value must survive save (get_contacts) without needing
        a verification round trip."""
        dlg = _make_dialog(qapp, [
            {"callsign": "WSAC909", "name": "Tim"},
        ], online=False)
        dlg.table.item(0, 4).setText("KE8ABC")
        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=False):
            rows = dlg.get_contacts()
        assert rows[0]["ham_callsign"] == "KE8ABC"

    def test_cells_uppercased_on_save_like_primary_callsign(self, qapp):
        # Callsigns are conventionally upper-case; the primary field already
        # uppercases on save, so GMRS / HAM should match for consistency.
        dlg = _make_dialog(qapp, [
            {"callsign": "WSAC909", "name": "Tim"},
        ], online=False)
        dlg.table.item(0, 3).setText("wrpn553")
        dlg.table.item(0, 4).setText("ke8abc")
        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=False):
            rows = dlg.get_contacts()
        assert rows[0]["gmrs_callsign"] == "WRPN553"
        assert rows[0]["ham_callsign"] == "KE8ABC"

    def test_blank_grid_cell_drops_field(self, qapp):
        """Blanking out a cell should remove the field from the saved dict
        (don't persist '' as a value that looks like manual data)."""
        dlg = _make_dialog(qapp, [
            {"callsign": "KE8RXN", "name": "Collin",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ], online=False)
        dlg.table.item(0, 3).setText("")
        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=False):
            rows = dlg.get_contacts()
        # Either absent or empty string is acceptable — both signal 'no value'.
        assert not rows[0].get("gmrs_callsign")


class TestVerifyButtonOfflineGating:
    def test_button_disabled_when_offline(self, qapp):
        dlg = _make_dialog(qapp, [], online=False)
        assert dlg.verify_all_btn.isEnabled() is False
        # Tooltip must explain *why* it's disabled — invisible disabled
        # buttons are an accessibility trap.
        assert "offline" in dlg.verify_all_btn.toolTip().lower()

    def test_button_enabled_when_online(self, qapp):
        dlg = _make_dialog(qapp, [], online=True)
        assert dlg.verify_all_btn.isEnabled() is True


class TestVerifyAll:
    def test_verify_all_updates_contacts(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
            {"callsign": "WSAC909", "name": "Tim"},
        ])

        def fake_verify(callsign, name):
            return crossref.VerificationResult(
                status="verified",
                license_name=f"{name} License",
                license_location="Somewhere",
                license_active=True,
            )

        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=True), \
             patch("gmrs_tty.ui.contacts_dialog.verify_callsign",
                   side_effect=fake_verify):
            dlg.verify_all()
            rows = dlg.get_contacts()

        assert all(r.get("verified") for r in rows)
        # Verified-at must be populated so subsequent sessions can show
        # "verified 3 days ago" if we ever want to surface it.
        assert all(r.get("verified_at") for r in rows)

    def test_callsign_only_result_marks_unverified(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Eliza"},
        ])

        def fake_verify(callsign, name):
            return crossref.VerificationResult(
                status="callsign_only",
                license_name="Zomberg, Benjamin J",
                license_location="Jenison, MI",
                license_active=True,
            )

        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=True), \
             patch("gmrs_tty.ui.contacts_dialog.verify_callsign",
                   side_effect=fake_verify):
            dlg.verify_all()
            row = dlg.get_contacts()[0]

        assert row.get("verified") is False
        # We still want the license-holder name persisted so the tooltip can
        # explain why the row didn't earn a green check.
        assert row.get("license_name") == "Zomberg, Benjamin J"

    def test_offline_results_leave_existing_verified_alone(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin",
             "verified": True, "verified_at": "2026-05-10T00:00:00Z"},
        ])

        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=True), \
             patch("gmrs_tty.ui.contacts_dialog.verify_callsign",
                   return_value=crossref.VerificationResult(status="offline")):
            dlg.verify_all()
            row = dlg.get_contacts()[0]

        assert row.get("verified") is True
        assert row.get("verified_at") == "2026-05-10T00:00:00Z"


class TestVerifyOnSave:
    def test_get_contacts_runs_verify_when_online(self, qapp):
        """get_contacts is the persistence hand-off. New / edited rows should
        be verified before being handed back so save → reload shows the green
        check without the user having to click 'Verify all'."""
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
        ])

        # The user edits the name in row 0 → row is now 'dirty'.
        dlg.table.item(0, 1).setText("Ben")

        calls = []

        def fake_verify(callsign, name):
            calls.append((callsign, name))
            return crossref.VerificationResult(
                status="verified", license_name="Zomberg, Benjamin J",
                license_location="Jenison, MI", license_active=True,
            )

        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=True), \
             patch("gmrs_tty.ui.contacts_dialog.verify_callsign",
                   side_effect=fake_verify):
            rows = dlg.get_contacts()

        assert ("WSLZ233", "Ben") in calls
        assert rows[0]["verified"] is True

    def test_get_contacts_persists_gmrs_and_ham_callsigns(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
        ])

        def fake_verify(callsign, name):
            return crossref.VerificationResult(
                status="verified",
                license_name="Zomberg, Benjamin J",
                license_location="Jenison, MI",
                license_active=True,
                gmrs_callsign="WSLZ233",
                ham_callsign="KE8RXN",
            )

        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=True), \
             patch("gmrs_tty.ui.contacts_dialog.verify_callsign",
                   side_effect=fake_verify):
            rows = dlg.get_contacts()

        assert rows[0]["gmrs_callsign"] == "WSLZ233"
        assert rows[0]["ham_callsign"] == "KE8RXN"

    def test_verified_cell_tooltip_includes_cross_references(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin",
             "verified": True, "license_name": "Zomberg, Benjamin J",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KE8RXN"},
        ])
        tip = dlg.table.item(0, 5).toolTip()
        assert "GMRS: WSLZ233" in tip
        assert "HAM: KE8RXN" in tip

    def test_get_contacts_skips_verify_when_offline(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
        ], online=False)
        dlg.table.item(0, 1).setText("Ben")

        with patch("gmrs_tty.ui.contacts_dialog.is_online", return_value=False), \
             patch("gmrs_tty.ui.contacts_dialog.verify_callsign") as verify:
            rows = dlg.get_contacts()
            verify.assert_not_called()
        # Edited rows survive even though we can't verify them.
        assert rows[0]["name"] == "Ben"
