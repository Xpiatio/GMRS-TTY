"""Touch-screen mode toggle on MainWindow.

A ⊞/⊟ QToolButton on the service toolbar switches the central widget
between the normal desktop layout (QStackedWidget index 0) and the
large-button touch-optimised view (index 1). Entering touch mode hides all
QDockWidgets; exiting restores their previous visibility. The preference
persists to config.json and is honored on startup.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDockWidget, QStackedWidget, QToolBar  # noqa: E402

from gmrs_tty.ui.touch_view import TouchView  # noqa: E402


def _service_toolbar_widgets(window):
    toolbar = window.findChild(QToolBar, "toolbar.service")
    if toolbar is None:
        return []
    return [a.defaultWidget() for a in toolbar.actions()]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


def _make_window(qapp, *, touch_mode=None, save_capture=None):
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233", "name": "Ben", "location": "Jenison",
        "filter_profanity": False, "voice": "", "quick_messages": [],
    }
    if touch_mode is not None:
        config["touch_mode"] = touch_mode

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    def fake_save_json(path, data):
        if save_capture is not None:
            save_capture.append((path, dict(data) if isinstance(data, dict) else data))

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch("gmrs_tty.config.save_json", side_effect=fake_save_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        return mw_mod.MainWindow()


class TestTouchToggleButtonExists:
    def test_button_lives_on_service_toolbar(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_toggle_btn in _service_toolbar_widgets(window), (
                "touch toggle must be hosted by the service toolbar"
            )
        finally:
            window.close()

    def test_touch_button_is_left_of_theme_button(self, qapp):
        window = _make_window(qapp)
        try:
            widgets = _service_toolbar_widgets(window)
            assert window.touch_toggle_btn in widgets
            assert window.theme_toggle_btn in widgets
            assert (
                widgets.index(window.touch_toggle_btn)
                < widgets.index(window.theme_toggle_btn)
            ), "touch toggle must appear left of the theme toggle"
        finally:
            window.close()

    def test_button_has_accessible_label(self, qapp):
        window = _make_window(qapp)
        try:
            name = window.touch_toggle_btn.accessibleName().lower()
            assert "touch" in name, name
        finally:
            window.close()


class TestTouchToggleInitialState:
    def test_default_state_is_normal_view(self, qapp):
        window = _make_window(qapp)
        try:
            assert window._central_stack.currentIndex() == 0
        finally:
            window.close()

    def test_central_stack_is_stacked_widget(self, qapp):
        window = _make_window(qapp)
        try:
            assert isinstance(window._central_stack, QStackedWidget)
        finally:
            window.close()

    def test_touch_view_is_page_1(self, qapp):
        window = _make_window(qapp)
        try:
            assert window._central_stack.widget(1) is window.touch_view
            assert isinstance(window.touch_view, TouchView)
        finally:
            window.close()

    def test_startup_with_touch_mode_true_activates_touch_view(self, qapp):
        window = _make_window(qapp, touch_mode=True)
        try:
            assert window._central_stack.currentIndex() == 1
        finally:
            window.close()

    def test_startup_with_touch_mode_missing_defaults_to_normal(self, qapp):
        window = _make_window(qapp)
        try:
            assert window._central_stack.currentIndex() == 0
        finally:
            window.close()


class TestTouchToggleSwitch:
    def test_click_enters_touch_mode(self, qapp):
        window = _make_window(qapp)
        try:
            with patch("gmrs_tty.config.save_json"):
                window.touch_toggle_btn.click()
            assert window._central_stack.currentIndex() == 1
        finally:
            window.close()

    def test_second_click_exits_touch_mode(self, qapp):
        window = _make_window(qapp)
        try:
            with patch("gmrs_tty.config.save_json"):
                window.touch_toggle_btn.click()
                window.touch_toggle_btn.click()
            assert window._central_stack.currentIndex() == 0
        finally:
            window.close()

    def test_entering_touch_mode_hides_docks(self, qapp):
        window = _make_window(qapp)
        try:
            docks = window.findChildren(QDockWidget)
            assert docks, "expected at least one dock to be present"
            with patch("gmrs_tty.config.save_json"):
                window.touch_toggle_btn.click()
            assert all(not d.isVisible() for d in docks), (
                "all docks must be hidden in touch mode"
            )
        finally:
            window.close()

    def test_exiting_touch_mode_restores_dock_visibility(self, qapp):
        window = _make_window(qapp)
        try:
            # Record which docks were visible before entering touch mode.
            docks = window.findChildren(QDockWidget)
            before = {d.objectName(): d.isVisible() for d in docks}
            with patch("gmrs_tty.config.save_json"):
                window.touch_toggle_btn.click()   # enter
                window.touch_toggle_btn.click()   # exit
            after = {d.objectName(): d.isVisible() for d in docks}
            assert before == after, (
                "dock visibility must be restored after exiting touch mode"
            )
        finally:
            window.close()


class TestTouchTogglePersistence:
    def test_click_writes_touch_mode_true_to_config(self, qapp):
        saved = []
        window = _make_window(qapp, save_capture=saved)
        try:
            def capture(path, data):
                saved.append((path, dict(data) if isinstance(data, dict) else data))

            with patch("gmrs_tty.config.save_json", side_effect=capture):
                window.touch_toggle_btn.click()
            payloads = [d for _, d in saved if isinstance(d, dict)]
            assert payloads, "expected save_json to be called with the config dict"
            assert payloads[-1].get("touch_mode") is True
        finally:
            window.close()

    def test_second_click_writes_touch_mode_false(self, qapp):
        saved = []
        window = _make_window(qapp, save_capture=saved)
        try:
            def capture(path, data):
                saved.append((path, dict(data) if isinstance(data, dict) else data))

            with patch("gmrs_tty.config.save_json", side_effect=capture):
                window.touch_toggle_btn.click()
                window.touch_toggle_btn.click()
            payloads = [d for _, d in saved if isinstance(d, dict)]
            assert payloads[-1].get("touch_mode") is False
        finally:
            window.close()


class TestTouchToggleGlyph:
    def test_normal_mode_shows_enter_glyph(self, qapp):
        from gmrs_tty.ui.main_window import TOUCH_GLYPH_ENTER
        window = _make_window(qapp, touch_mode=False)
        try:
            assert TOUCH_GLYPH_ENTER in window.touch_toggle_btn.text()
        finally:
            window.close()

    def test_touch_mode_shows_exit_glyph(self, qapp):
        from gmrs_tty.ui.main_window import TOUCH_GLYPH_EXIT
        window = _make_window(qapp, touch_mode=True)
        try:
            assert TOUCH_GLYPH_EXIT in window.touch_toggle_btn.text()
        finally:
            window.close()

    def test_glyph_flips_after_toggle(self, qapp):
        window = _make_window(qapp, touch_mode=False)
        try:
            before = window.touch_toggle_btn.text()
            with patch("gmrs_tty.config.save_json"):
                window.touch_toggle_btn.click()
            after = window.touch_toggle_btn.text()
            assert before != after, "glyph must flip on toggle"
        finally:
            window.close()


class TestTouchViewContents:
    def test_touch_view_has_listen_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_view.listen_btn is not None
            assert window.touch_view.listen_btn.isCheckable()
        finally:
            window.close()

    def test_touch_view_has_no_transmit_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert not hasattr(window.touch_view, "transmit_btn"), (
                "transmit button must not exist on the touch view"
            )
        finally:
            window.close()

    def test_touch_view_has_listen_only_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_view.listen_only_btn.isCheckable()
        finally:
            window.close()

    def test_touch_view_has_monitor_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_view.monitor_btn.isCheckable()
            assert not window.touch_view.monitor_btn.isEnabled()
        finally:
            window.close()

    def test_touch_view_has_theme_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_view.theme_btn is not None
        finally:
            window.close()

    def test_touch_view_has_callsigns_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_view.attendance_btn is not None
        finally:
            window.close()

    def test_touch_view_has_journals_button(self, qapp):
        window = _make_window(qapp)
        try:
            assert window.touch_view.journals_btn is not None
        finally:
            window.close()

    def test_generate_log_hidden_without_api_key(self, qapp):
        window = _make_window(qapp)
        try:
            assert not window.touch_view.generate_btn.isVisible()
        finally:
            window.close()

    def test_touch_view_has_chat_display(self, qapp):
        window = _make_window(qapp)
        try:
            from gmrs_tty.ui.chat_display import ChatDisplay
            assert isinstance(window.touch_view.chat_display, ChatDisplay)
        finally:
            window.close()

    def test_append_to_chat_writes_to_touch_display(self, qapp):
        window = _make_window(qapp)
        try:
            window.append_to_chat("Hello touch", color="#000000")
            normal_html = window.chat_display.toHtml()
            touch_html = window.touch_view.chat_display.toHtml()
            assert "Hello touch" in normal_html
            assert "Hello touch" in touch_html
        finally:
            window.close()

    def test_listen_only_sync_on_toggle(self, qapp):
        window = _make_window(qapp)
        try:
            assert not window.touch_view.listen_only_btn.isChecked()
            with patch("gmrs_tty.config.save_json"):
                window.listen_only_btn.setChecked(True)
            assert window.touch_view.listen_only_btn.isChecked()
        finally:
            window.close()
