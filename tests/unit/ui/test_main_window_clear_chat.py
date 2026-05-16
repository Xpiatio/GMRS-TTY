"""Clear-chat button must wipe the conversation log only on explicit confirm.

Chat history is in-memory only, so an accidental clear (stray Ctrl+K, errant
mouse-click) can drop hours of RX context with no recovery path. The button
gates the action behind a Yes/No prompt — these tests pin both paths."""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePTT:
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def close(self):
        pass


@pytest.fixture
def main_window(qapp):
    """Build a MainWindow with file I/O and PTT stubbed so the test focuses on
    the clear-chat flow."""
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSAA111",
        "name": "Operator",
        "location": "Home",
        "filter_profanity": False,
        "voice": "",
        "quick_messages": [],
    }

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()):
        window = mw_mod.MainWindow()
    yield window
    window.close()


class TestClearChat:
    def _seed_chat(self, window):
        window.append_to_chat("<b>[RX 00:00:01]:</b> hello world")
        window.append_to_chat("<b>[TX to All]:</b> radio check")
        assert window.chat_display.toPlainText().strip() != ""

    def test_confirmed_clear_wipes_chat(self, main_window):
        self._seed_chat(main_window)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            main_window.clear_chat()
        assert main_window.chat_display.toPlainText() == ""

    def test_declined_clear_leaves_chat_intact(self, main_window):
        self._seed_chat(main_window)
        before = main_window.chat_display.toPlainText()
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            main_window.clear_chat()
        assert main_window.chat_display.toPlainText() == before

    def test_button_click_routes_through_confirm(self, main_window):
        # The toolbar button must go through the same confirmation as the menu
        # action / Ctrl+K shortcut — bypassing it would defeat the safety net.
        self._seed_chat(main_window)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as q:
            main_window.clear_chat_btn.click()
        assert q.called
        assert main_window.chat_display.toPlainText() != ""
