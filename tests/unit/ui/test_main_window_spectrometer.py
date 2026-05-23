"""MainWindow integration for the rolling-RX spectrometer.

Covers the operator-visible contract:
  * The View menu carries a checkable "Show waterfall" entry plus
    color-map / frequency-range / time-window submenus.
  * Toggling persists ``spectrometer.enabled`` to config.json.
  * Settings setters keep the widget, the menu radio state, and the
    persisted config in sync.
  * The widget starts hidden by default but visible when the operator's
    last-saved choice was enabled=True.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.ui import theme  # noqa: E402
from gmrs_tty.ui.spectrogram_widget import (  # noqa: E402
    FREQ_RANGE_FULL, FREQ_RANGE_VOICE,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


def _make_window(qapp, spectrometer_cfg=None, save_capture=None):
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233", "name": "Ben", "location": "Jenison",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }
    if spectrometer_cfg is not None:
        config["spectrometer"] = dict(spectrometer_cfg)

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    def fake_save_json(path, data):
        if save_capture is not None:
            save_capture.append((path, dict(data) if isinstance(data, dict) else data))

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "save_json", side_effect=fake_save_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        return mw_mod.MainWindow()


@pytest.fixture(autouse=True)
def reset_theme():
    yield
    theme.set_dark(False)
    app = QApplication.instance()
    if app is not None:
        theme.apply_theme(app, False)


class TestDefaultsHidden:
    def test_widget_hidden_by_default(self, qapp):
        win = _make_window(qapp)
        try:
            assert win.spectro_manager.widget is not None
            assert win.spectro_manager.widget.isVisible() is False
        finally:
            win.close()

    def test_toggle_action_unchecked_by_default(self, qapp):
        win = _make_window(qapp)
        try:
            assert win._spectro_toggle_action.isChecked() is False
        finally:
            win.close()

    def test_visible_when_config_enables(self, qapp):
        win = _make_window(qapp, spectrometer_cfg={"enabled": True})
        try:
            # We never call show() so the widget itself is hidden by Qt
            # because its parent isn't shown — but the *intent* (the
            # toggle action checked, the visibility flag set) must match
            # the persisted preference.
            assert win._spectro_toggle_action.isChecked() is True
            assert win.spectro_manager.settings.enabled is True
        finally:
            win.close()


class TestToggleAction:
    def test_toggle_persists_enabled(self, qapp):
        import gmrs_tty.ui.spectro_manager as sm_mod
        win = _make_window(qapp)
        saves = []

        def capture(_path, data):
            saves.append(dict(data) if isinstance(data, dict) else data)
        try:
            with patch.object(sm_mod, "save_json", side_effect=capture):
                win.spectro_manager.toggle(True)
            spec_saves = [s for s in saves if isinstance(s, dict) and "spectrometer" in s]
            assert spec_saves, "toggle must persist a spectrometer section"
            assert spec_saves[-1]["spectrometer"]["enabled"] is True
        finally:
            win.close()

    def test_toggle_off_persists_disabled(self, qapp):
        import gmrs_tty.ui.spectro_manager as sm_mod
        win = _make_window(qapp, spectrometer_cfg={"enabled": True})
        saves = []

        def capture(_path, data):
            saves.append(dict(data) if isinstance(data, dict) else data)
        try:
            with patch.object(sm_mod, "save_json", side_effect=capture):
                win.spectro_manager.toggle(False)
            spec_saves = [s for s in saves if isinstance(s, dict) and "spectrometer" in s]
            assert spec_saves and spec_saves[-1]["spectrometer"]["enabled"] is False
        finally:
            win.close()


class TestSettersSync:
    def test_set_colormap_updates_menu_and_widget(self, qapp):
        win = _make_window(qapp)
        try:
            win.spectro_manager.set_colormap("grayscale")
            assert win.spectro_manager.settings.colormap == "grayscale"
            assert win.spectro_manager._cmap_actions["grayscale"].isChecked() is True
            assert win.spectro_manager._cmap_actions["viridis"].isChecked() is False
        finally:
            win.close()

    def test_set_freq_range_updates_widget(self, qapp):
        win = _make_window(qapp)
        try:
            win.spectro_manager.set_freq_range(FREQ_RANGE_FULL)
            assert win.spectro_manager.settings.freq_range == FREQ_RANGE_FULL
            assert win.spectro_manager._freq_actions[FREQ_RANGE_FULL].isChecked() is True
            assert win.spectro_manager._freq_actions[FREQ_RANGE_VOICE].isChecked() is False
        finally:
            win.close()

    def test_set_time_window_updates_widget(self, qapp):
        win = _make_window(qapp)
        try:
            win.spectro_manager.set_time_window(60)
            assert win.spectro_manager.settings.time_window_s == 60
            assert win.spectro_manager._window_actions[60].isChecked() is True
            assert win.spectro_manager._window_actions[30].isChecked() is False
        finally:
            win.close()

    def test_unknown_colormap_is_no_op(self, qapp):
        win = _make_window(qapp)
        try:
            before = win.spectro_manager.settings.colormap
            win.spectro_manager.set_colormap("ultraviolet")
            assert win.spectro_manager.settings.colormap == before
        finally:
            win.close()


class TestActivityTextToStatusBar:
    def test_status_bar_skipped_when_disabled(self, qapp):
        win = _make_window(qapp)
        try:
            # Spectrometer disabled — activity text shouldn't burn the
            # status bar with waterfall chatter.
            win.statusBar().clearMessage()
            win.spectro_manager._on_activity("Strong signal at 1.2 kHz")
            assert "Waterfall" not in win.statusBar().currentMessage()
        finally:
            win.close()

    def test_status_bar_set_when_enabled(self, qapp):
        win = _make_window(qapp, spectrometer_cfg={"enabled": True})
        try:
            win.spectro_manager._on_activity("Strong signal at 1.2 kHz")
            assert "Waterfall" in win.statusBar().currentMessage()
        finally:
            win.close()
