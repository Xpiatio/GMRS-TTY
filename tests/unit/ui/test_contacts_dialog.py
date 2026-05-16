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


class TestVerifiedColumn:
    def test_has_four_columns_including_verified(self, qapp):
        dlg = _make_dialog(qapp, [])
        assert dlg.table.columnCount() == 4
        headers = [dlg.table.horizontalHeaderItem(i).text()
                   for i in range(dlg.table.columnCount())]
        assert "Verified" in headers

    def test_verified_cell_shows_check_for_verified_contact(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin", "verified": True},
        ])
        cell = dlg.table.item(0, 3)
        assert cell is not None
        # Whatever glyph we render, a verified row's accessible/tool-tip text
        # has to include "verified" so screen readers don't see a bare check.
        text = (cell.toolTip() + " " + (cell.text() or "")).lower()
        assert "verified" in text

    def test_verified_cell_blank_for_unverified_contact(self, qapp):
        dlg = _make_dialog(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin"},
        ])
        cell = dlg.table.item(0, 3)
        # No verification yet: cell exists (so the column is well-formed) but
        # should not display a check glyph.
        if cell is not None:
            assert "✓" not in (cell.text() or "")


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
        tip = dlg.table.item(0, 3).toolTip()
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
