"""Online/offline indicator on MainWindow.

The user only opted into online features (FCC callsign verification) with the
caveat that they get disabled when the app loses internet. The status-bar
indicator is the user-visible part of that contract — it has to flip
correctly so the operator knows why the Verify button is grayed out.
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


def _make_window(qapp, *, online=True):
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSAA111", "name": "Operator", "location": "Home",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=online):
        window = mw_mod.MainWindow()
    return window


class TestOnlineIndicator:
    def test_indicator_shows_online_at_startup(self, qapp):
        w = _make_window(qapp, online=True)
        try:
            text = w.online_indicator.text().lower()
            assert "online" in text
        finally:
            w.close()

    def test_indicator_shows_offline_at_startup(self, qapp):
        w = _make_window(qapp, online=False)
        try:
            text = w.online_indicator.text().lower()
            assert "offline" in text
        finally:
            w.close()

    def test_refresh_flips_indicator_when_state_changes(self, qapp):
        from gmrs_tty.ui import main_window as mw_mod

        w = _make_window(qapp, online=True)
        try:
            assert "online" in w.online_indicator.text().lower()
            with patch.object(mw_mod, "is_online", return_value=False):
                w._refresh_online_indicator()
            assert "offline" in w.online_indicator.text().lower()
        finally:
            w.close()
