"""scan_for_unknown_stations must consider all three callsign fields on a
contact when deciding whether to add a '+ Add' pill. A detected HAM call must
not generate a pill when that operator's GMRS call is already saved (because
verification cross-referenced the HAM call into ham_callsign), and vice versa.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


def _make_window(qapp, contacts, extra_config=None):
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSAA111", "name": "Operator", "location": "Home",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }
    if extra_config:
        config.update(extra_config)

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return [dict(c) for c in contacts]

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        window = mw_mod.MainWindow()
    return window


class TestScanRespectsCrossReferences:
    def test_ham_call_suppressed_when_gmrs_known(self, qapp):
        """Operator detected by HAM call should NOT pill when their GMRS call
        is already saved as a contact (with the HAM in ham_callsign)."""
        w = _make_window(qapp, [
            {"callsign": "WRPN553", "name": "Collin", "location": "Grand Rapids",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ])
        try:
            w.scan_for_unknown_stations("hello KE8RXN here")
            assert "KE8RXN" not in w.pending_buttons
        finally:
            w.close()

    def test_gmrs_call_suppressed_when_ham_known(self, qapp):
        """Symmetric: operator detected by GMRS call should NOT pill when
        their HAM call is the primary on file."""
        w = _make_window(qapp, [
            {"callsign": "KE8RXN", "name": "Collin", "location": "Grand Rapids",
             "gmrs_callsign": "WRPN553", "ham_callsign": "KE8RXN"},
        ])
        try:
            w.scan_for_unknown_stations("hello WRPN553 here")
            assert "WRPN553" not in w.pending_buttons
        finally:
            w.close()

    def test_truly_unknown_call_still_pills(self, qapp):
        # Regression guard: widening the 'known' set must not suppress
        # genuinely new callsigns.
        w = _make_window(qapp, [
            {"callsign": "WSLZ233", "name": "Benjamin",
             "gmrs_callsign": "WSLZ233", "ham_callsign": "KD8AAA"},
        ])
        try:
            w.scan_for_unknown_stations("hello KE8NEW here")
            assert "KE8NEW" in w.pending_buttons
        finally:
            w.close()


class TestScanRespectsFuzzyToggle:
    """With the fuzzy_callsign toggle on, a detected callsign that differs from
    a known one by exactly one character is treated as a hit — no '+ Add' pill
    is created for it. With the toggle off, off-by-one detections still pill
    as new stations (preserving the historical behavior for users who want
    every near-miss surfaced for manual review)."""

    def test_off_by_one_suppressed_when_fuzzy_on(self, qapp):
        w = _make_window(
            qapp,
            [{"callsign": "WSLZ233", "name": "Benjamin"}],
            extra_config={"fuzzy_callsign": True},
        )
        try:
            w.scan_for_unknown_stations("hello WSLZ234 here")
            assert "WSLZ234" not in w.pending_buttons
        finally:
            w.close()

    def test_off_by_one_still_pills_when_fuzzy_off(self, qapp):
        w = _make_window(
            qapp,
            [{"callsign": "WSLZ233", "name": "Benjamin"}],
            extra_config={"fuzzy_callsign": False},
        )
        try:
            w.scan_for_unknown_stations("hello WSLZ234 here")
            assert "WSLZ234" in w.pending_buttons
        finally:
            w.close()

    def test_two_off_still_pills_when_fuzzy_on(self, qapp):
        # Two-character difference is beyond fuzzy reach: this is a new call.
        w = _make_window(
            qapp,
            [{"callsign": "WSLZ233", "name": "Benjamin"}],
            extra_config={"fuzzy_callsign": True},
        )
        try:
            w.scan_for_unknown_stations("hello WSLZ244 here")
            assert "WSLZ244" in w.pending_buttons
        finally:
            w.close()
