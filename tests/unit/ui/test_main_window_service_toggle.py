"""GMRS / FRS service toggle behavior on MainWindow.

In FRS mode every callsign-dependent feature has to go dark: header replaces
the callsign segment, target dropdown hides, 'This is' button disables,
station-ID shortcut becomes a no-op, contacts menu disables, pending bar
clears, chat-display highlighting stops, and TX output drops the preface +
trailing ID. The toggle has to be persistent across restarts (lives in
config.json) and the radio buttons must reflect the saved state on startup.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.constants import SERVICE_FRS, SERVICE_GMRS  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


def _make_window(qapp, *, service=None, contacts=None, save_capture=None):
    """Build a MainWindow with file I/O and PTT stubbed. `save_capture`, when
    provided, receives a list of (path, data) tuples for every save_json call
    so tests can pin config persistence on toggle."""
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233", "name": "Ben", "location": "Jenison",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }
    if service is not None:
        config["radio_service"] = service

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return [dict(c) for c in (contacts or [])]

    def fake_save_json(path, data):
        if save_capture is not None:
            save_capture.append((path, dict(data) if isinstance(data, dict) else data))

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "save_json", side_effect=fake_save_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        window = mw_mod.MainWindow()
    return window


class TestStartupReflectsSavedService:
    def test_default_is_gmrs(self, qapp):
        w = _make_window(qapp)
        try:
            assert w.gmrs_radio.isChecked() is True
            assert w.frs_radio.isChecked() is False
            assert "Station: WSLZ233" in w.header_label.text()
        finally:
            w.close()

    def test_frs_persists_into_startup(self, qapp):
        w = _make_window(qapp, service=SERVICE_FRS)
        try:
            assert w.frs_radio.isChecked() is True
            assert w.gmrs_radio.isChecked() is False
            assert "FRS Mode" in w.header_label.text()
            assert "Station:" not in w.header_label.text()
        finally:
            w.close()

    def test_unknown_service_falls_back_to_gmrs(self, qapp):
        w = _make_window(qapp, service="not-a-mode")
        try:
            assert w.gmrs_radio.isChecked() is True
        finally:
            w.close()


class TestToggleHidesCallsignSurfaces:
    def test_frs_hides_target_dropdown_and_disables_id_button(self, qapp):
        w = _make_window(qapp)
        try:
            assert w.target_dropdown.isVisibleTo(w) or w.target_dropdown.isVisible()
            assert w.id_btn.isEnabled() is True
            w.frs_radio.setChecked(True)
            assert w.target_dropdown.isVisible() is False
            assert w.id_btn.isEnabled() is False
            assert "FRS" in w.id_btn.toolTip() or "GMRS" in w.id_btn.toolTip()
        finally:
            w.close()

    def test_frs_hides_online_indicator(self, qapp):
        w = _make_window(qapp)
        try:
            w.show()  # status-bar visibility requires the window to be shown
            assert w.online_indicator.isVisible() is True
            w.frs_radio.setChecked(True)
            assert w.online_indicator.isVisible() is False
        finally:
            w.close()

    def test_frs_disables_contacts_menu_action(self, qapp):
        w = _make_window(qapp)
        try:
            assert w._contacts_action.isEnabled() is True
            w.frs_radio.setChecked(True)
            assert w._contacts_action.isEnabled() is False
        finally:
            w.close()

    def test_frs_disables_contacts_icon_button(self, qapp):
        # The quick-access contacts icon on the service row must follow the
        # same enable rule as the menu action — both lead to the same dialog,
        # both are GMRS-only.
        w = _make_window(qapp)
        try:
            assert w.contacts_icon_btn.isEnabled() is True
            w.frs_radio.setChecked(True)
            assert w.contacts_icon_btn.isEnabled() is False
            # Tooltip swaps to an explanation so the operator can recover.
            assert "FRS" in w.contacts_icon_btn.toolTip() \
                or "GMRS" in w.contacts_icon_btn.toolTip()
            w.gmrs_radio.setChecked(True)
            assert w.contacts_icon_btn.isEnabled() is True
        finally:
            w.close()

    def test_frs_clears_callsign_index_so_highlights_stop(self, qapp):
        w = _make_window(qapp, contacts=[
            {"callsign": "WSAC909", "name": "Tim"},
        ])
        try:
            # Indirectly probe via the chat_display's stored index.
            assert w.chat_display._callsign_index, "GMRS should populate the index"
            w.frs_radio.setChecked(True)
            assert w.chat_display._callsign_index == {}
        finally:
            w.close()

    def test_frs_clears_existing_pending_pills(self, qapp):
        w = _make_window(qapp)
        try:
            w.add_pending_station("WSLZ501", "Stranger", "")
            assert "WSLZ501" in w.pending_buttons
            w.frs_radio.setChecked(True)
            assert w.pending_buttons == {}
            assert w.pending_scroll.isVisible() is False
        finally:
            w.close()


class TestToggleGatesDetectionAndTx:
    def test_frs_scan_skips_pending_pill_creation(self, qapp):
        w = _make_window(qapp, service=SERVICE_FRS)
        try:
            # Even though this transcription contains a recognizable
            # callsign, FRS mode must not generate a pill.
            w.scan_for_unknown_stations("just heard WSLZ501 calling")
            assert "WSLZ501" not in w.pending_buttons
        finally:
            w.close()

    def test_gmrs_scan_still_works_after_toggle_back(self, qapp):
        w = _make_window(qapp)
        try:
            w.frs_radio.setChecked(True)
            w.gmrs_radio.setChecked(True)
            w.scan_for_unknown_stations("just heard WSLZ501 calling")
            assert "WSLZ501" in w.pending_buttons
        finally:
            w.close()

    def test_frs_transmit_drops_preface_and_id(self, qapp):
        from gmrs_tty.ui import main_window as mw_mod

        w = _make_window(qapp, service=SERVICE_FRS)
        try:
            captured = {}

            def fake_format(*, text, target_call, target_name, my_call, my_name,
                            last_id_time, now, service=SERVICE_GMRS):
                captured["service"] = service
                captured["target_call"] = target_call
                captured["target_name"] = target_name
                # Echo what id_rule actually does in FRS.
                if service == SERVICE_FRS:
                    return text, last_id_time
                return f"{my_call} {my_name} calling … {text}", now

            with patch.object(mw_mod, "format_outgoing_message", side_effect=fake_format), \
                 patch.object(w, "_synthesize_and_play"):
                assert w._transmit_text("hello channel") is True

            assert captured["service"] == SERVICE_FRS
            assert captured["target_call"] == ""
            assert captured["target_name"] == ""
            # Chat label drops the "to <CALL>" segment in FRS.
            assert "TX]:" in w.chat_display.toPlainText()
            assert "TX to" not in w.chat_display.toPlainText()
        finally:
            w.close()

    def test_frs_id_button_press_is_a_noop(self, qapp):
        # Belt-and-suspenders: the Ctrl+I shortcut bypasses button-enabled
        # state, so transmit_id_only must hard-guard.
        w = _make_window(qapp, service=SERVICE_FRS)
        try:
            with patch.object(w, "_synthesize_and_play") as synth:
                w.transmit_id_only()
                synth.assert_not_called()
        finally:
            w.close()


class TestTogglePersistsToConfig:
    def test_clicking_frs_writes_radio_service_to_config(self, qapp):
        from gmrs_tty.ui import main_window as mw_mod

        save_capture = []
        w = _make_window(qapp, save_capture=save_capture)
        try:
            # Re-patch save_json for the duration of the toggle — the fixture
            # only kept it patched during construction.
            def fake_save_json(path, data):
                save_capture.append((path, dict(data) if isinstance(data, dict) else data))
            with patch.object(mw_mod, "save_json", side_effect=fake_save_json):
                w.frs_radio.setChecked(True)
            assert any(
                isinstance(data, dict) and data.get("radio_service") == SERVICE_FRS
                for _path, data in save_capture
            )
        finally:
            w.close()
