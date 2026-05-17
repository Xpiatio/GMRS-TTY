"""Listen toggle + live mic-level meter live above the chat, not in the TX dock.

The Listen button and audio_level_meter used to share the leftmost column of
the Transmit dock. That placement wedged RX controls into a TX surface and
squeezed the message-input width on a 720-px window. They now live in the
central widget, above the chat display, in a single horizontal strip that
also hosts Clear-chat on the right.

These tests pin the new location so an accidental regression (someone
re-adds them to the Transmit dock) is caught before it ships.
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QProgressBar, QPushButton,
)


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
    from gmrs_tty.ui import main_window as mw_mod

    config = {
        "callsign": "WSLZ233",
        "name": "Ben",
        "location": "Jenison",
        "filter_profanity": False,
        "voice": "",
        "quick_messages": [],
    }

    def fake_load_json(path, default):
        if isinstance(default, dict):
            return dict(config)
        return []

    with patch.object(mw_mod, "load_json", side_effect=fake_load_json), \
         patch.object(mw_mod, "save_json"), \
         patch.object(mw_mod, "make_ptt", return_value=_FakePTT()), \
         patch.object(mw_mod, "is_online", return_value=True):
        window = mw_mod.MainWindow()
    yield window
    window.close()


class TestListenStripParentage:
    def test_listen_btn_lives_in_central_widget(self, main_window):
        # The whole point of the relocation: keyboard / mouse / a11y reach
        # to the Listen toggle can no longer depend on the Transmit dock's
        # visibility or position.
        central = main_window.centralWidget()
        assert main_window.listen_btn.parentWidget() is central, (
            "listen_btn must be parented to the central widget so it is "
            "always reachable independent of dock state"
        )

    def test_audio_level_meter_lives_in_central_widget(self, main_window):
        central = main_window.centralWidget()
        assert main_window.audio_level_meter.parentWidget() is central

    def test_listen_btn_is_not_inside_transmit_dock(self, main_window):
        # Belt-and-braces: even if a future refactor accidentally re-creates
        # a Listen button inside the Transmit dock, this test will fail.
        dock_content = main_window.transmit_dock.widget()
        push_buttons = dock_content.findChildren(QPushButton)
        assert main_window.listen_btn not in push_buttons, (
            "listen_btn must not be hosted inside the Transmit dock"
        )

    def test_audio_level_meter_is_not_inside_transmit_dock(self, main_window):
        dock_content = main_window.transmit_dock.widget()
        meters = dock_content.findChildren(QProgressBar)
        assert main_window.audio_level_meter not in meters


class TestListenStripLayout:
    def test_listen_strip_sits_above_chat_display(self, main_window):
        # Visually the strip must precede the chat. We assert this through
        # the central widget's QVBoxLayout — the Listen QHBoxLayout's item
        # index must be less than the chat-display widget's index.
        central = main_window.centralWidget()
        layout = central.layout()
        chat_index = None
        listen_index = None
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            if widget is main_window.chat_display:
                chat_index = i
                continue
            child_layout = item.layout()
            if child_layout is not None and main_window.listen_btn in (
                child_layout.itemAt(j).widget() for j in range(child_layout.count())
            ):
                listen_index = i
        assert listen_index is not None, "listen strip not found in central layout"
        assert chat_index is not None, "chat display not found in central layout"
        assert listen_index < chat_index, (
            "listen strip must render above the chat display"
        )

    def test_level_meter_stretches_between_buttons(self, main_window):
        # The meter is the only widget in the strip that should grow with
        # the window — the buttons should keep their natural width.
        central = main_window.centralWidget()
        layout = central.layout()
        strip = None
        for i in range(layout.count()):
            child = layout.itemAt(i).layout()
            if child is None:
                continue
            widgets = [child.itemAt(j).widget() for j in range(child.count())]
            if main_window.listen_btn in widgets:
                strip = child
                break
        assert strip is not None, "expected a horizontal strip hosting Listen"
        # Find the meter's stretch factor in the strip.
        for j in range(strip.count()):
            if strip.itemAt(j).widget() is main_window.audio_level_meter:
                assert strip.stretch(j) >= 1, (
                    "audio_level_meter must have a positive stretch so it "
                    "fills the space between Listen and Clear-chat"
                )
                return
        pytest.fail("audio_level_meter was not found in the listen strip")


class TestListenStripBehaviorUnchanged:
    def test_ctrl_l_still_toggles_listen(self, main_window):
        # The Ctrl+L global shortcut existed before the move; its handler
        # references self.listen_btn directly so the relocation must not
        # break the binding.
        from PySide6.QtGui import QShortcut

        shortcuts = main_window.findChildren(QShortcut)
        ctrl_l = [s for s in shortcuts if s.key() == QKeySequence("Ctrl+L")]
        assert ctrl_l, "Ctrl+L shortcut must remain installed on the window"

    def test_listen_btn_still_checkable(self, main_window):
        # The button is the toggle surface for STT — losing checkable
        # behaviour would silently break Listen/Listening… state cycling.
        assert main_window.listen_btn.isCheckable() is True

    def test_listen_btn_keeps_mnemonic(self, main_window):
        # Alt+L should still land focus / activate the toggle.
        assert "&" in main_window.listen_btn.text()
        assert "Listen" in main_window.listen_btn.text()

    def test_accessible_metadata_preserved(self, main_window):
        # Screen readers rely on these strings; moving the widget shouldn't
        # have stripped its a11y annotations.
        assert main_window.listen_btn.accessibleName() == "Listen toggle"
        assert "transcribing" in main_window.listen_btn.accessibleDescription().lower()
        assert main_window.audio_level_meter.accessibleName() == "Microphone input level"


class TestTransmitDockUnaffected:
    def test_transmit_dock_still_hosts_tx_widgets(self, main_window):
        # The TX-only widgets must still live inside the Transmit dock so
        # the operator's TX path is intact (Closable is off — losing TX
        # would strand them).
        dock_content = main_window.transmit_dock.widget()
        descendants = dock_content.findChildren(object)
        assert main_window.target_dropdown in descendants
        assert main_window.message_input in descendants
        assert main_window.transmit_btn in descendants
        assert main_window.id_btn in descendants
