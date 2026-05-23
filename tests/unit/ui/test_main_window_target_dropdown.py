"""Target-dropdown selection must distinguish family members sharing one
callsign.

GMRS lets a single licensee cover their household, so contacts.json can hold
several rows with the same callsign and different operator names (e.g. three
'WSLZ233' entries for Benjamin, Eliza, and Jennifer). The dropdown row the
operator picks must be the one whose name reaches the FCC preface — picking
'WSLZ233 (Eliza)' must not speak 'Benjamin' just because Benjamin sorts
first.
"""
import datetime
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def main_window(qapp):
    """Build a MainWindow with file I/O and the PTT backend stubbed out so the
    test stays focused on dropdown wiring."""
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSAA111",
        "name": "Operator",
        "location": "Home",
        "filter_profanity": False,
        "voice": "",
        "quick_messages": [],
    }
    contacts = [
        {"callsign": "WSLZ233", "name": "Benjamin", "location": "Jenison"},
        {"callsign": "WSLZ233", "name": "Eliza", "location": "Jenison"},
        {"callsign": "WSLZ233", "name": "Jennifer", "location": "Jenison"},
        {"callsign": "WSEP679", "name": "Steve", "location": "Kentwood"},
    ]

    def fake_load_json(path, default):
        # MainWindow loads config first, then contacts — discriminate by the
        # default's type so we don't have to thread file constants through.
        if isinstance(default, dict):
            return dict(config)
        return [dict(c) for c in contacts]

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()):
        window = mw_mod.MainWindow()
    yield window
    window.close()


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


class TestTargetDropdownPopulation:
    def test_each_row_carries_its_own_name(self, main_window):
        # Index 0 is the hard-coded 'All' broadcast row.
        rows = [
            main_window.target_dropdown.itemData(i)
            for i in range(main_window.target_dropdown.count())
        ]
        assert rows[0] == ("All", "")
        # The three WSLZ233 family members must each carry their own name so
        # selection can't collapse to whichever sorts first.
        wslz_rows = [r for r in rows if r[0] == "WSLZ233"]
        assert sorted(name for _, name in wslz_rows) == ["Benjamin", "Eliza", "Jennifer"]


class TestTransmitUsesSelectedRowName:
    """The bug this test pins down: previously _transmit_text re-resolved the
    target name by callsign via next(...), which always returned the first
    matching contact. Selecting 'WSLZ233 (Eliza)' transmitted 'Benjamin'."""

    def _select_row(self, window, callsign, name):
        for i in range(window.target_dropdown.count()):
            data = window.target_dropdown.itemData(i)
            if data == (callsign, name):
                window.target_dropdown.setCurrentIndex(i)
                return
        raise AssertionError(f"No dropdown row for {callsign} / {name}")

    @pytest.mark.parametrize("selected_name", ["Benjamin", "Eliza", "Jennifer"])
    def test_selected_family_member_name_reaches_preface(self, main_window, selected_name):
        from gmrs_tty.ui import main_window as mw_mod

        self._select_row(main_window, "WSLZ233", selected_name)

        captured = {}

        def fake_format(*, text, target_call, target_name, my_call, my_name,
                        last_id_time, now, service="GMRS"):
            captured["target_call"] = target_call
            captured["target_name"] = target_name
            return ("spoken", now)

        with patch.object(mw_mod, "format_outgoing_message", side_effect=fake_format), \
             patch.object(main_window, "_synthesize_and_play"), \
             patch.object(main_window, "append_to_chat"):
            assert main_window._transmit_text("hello") is True

        assert captured["target_call"] == "WSLZ233"
        assert captured["target_name"] == selected_name

    def test_all_broadcast_clears_target_name(self, main_window):
        from gmrs_tty.ui import main_window as mw_mod

        for i in range(main_window.target_dropdown.count()):
            if main_window.target_dropdown.itemData(i) == ("All", ""):
                main_window.target_dropdown.setCurrentIndex(i)
                break

        captured = {}

        def fake_format(*, text, target_call, target_name, my_call, my_name,
                        last_id_time, now, service="GMRS"):
            captured["target_call"] = target_call
            captured["target_name"] = target_name
            return ("spoken", now)

        with patch.object(mw_mod, "format_outgoing_message", side_effect=fake_format), \
             patch.object(main_window, "_synthesize_and_play"), \
             patch.object(main_window, "append_to_chat"):
            assert main_window._transmit_text("hello") is True

        # Broadcast: no preface, so the target name must be blank regardless
        # of what userData held.
        assert captured["target_name"] == ""

    def test_prefaced_send_resets_dropdown_to_all(self, main_window):
        from gmrs_tty.ui import main_window as mw_mod

        self._select_row(main_window, "WSLZ233", "Eliza")
        with patch.object(mw_mod, "format_outgoing_message",
                          return_value=("spoken", datetime.datetime.now())), \
             patch.object(main_window, "_synthesize_and_play"), \
             patch.object(main_window, "append_to_chat"):
            main_window._transmit_text("hello")
        assert main_window.target_dropdown.currentData() == ("All", "")
