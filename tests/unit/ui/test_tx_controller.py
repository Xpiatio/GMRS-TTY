"""TXController unit tests."""
import os
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.ui.tx_controller import TXController  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_controller(qapp):
    ptt = MagicMock()
    ptt.lead_in_seconds = 0.0
    ptt.tail_seconds = 0.0
    return TXController(ptt)


class TestTestVoiceTxBusyGuard:
    def test_done_cb_called_immediately_when_tx_busy(self, qapp):
        ctrl = _make_controller(qapp)
        ctrl._tx_busy = True

        done_cb = MagicMock()
        with patch("gmrs_tty.ui.tx_controller.TTSSynthesisThread") as mock_tts:
            ctrl.test_voice("/fake/voice.onnx", 1.0, -1, done_cb)

        done_cb.assert_called_once()
        mock_tts.assert_not_called()

    def test_test_voice_proceeds_when_not_busy(self, qapp):
        ctrl = _make_controller(qapp)
        ctrl._tx_busy = False

        fake_voice = MagicMock()
        ctrl._voice_cache = ("/fake/voice.onnx", fake_voice)

        done_cb = MagicMock()
        mock_thread = MagicMock()
        with patch("gmrs_tty.ui.tx_controller.TTSSynthesisThread",
                   return_value=mock_thread) as mock_tts:
            ctrl.test_voice("/fake/voice.onnx", 1.0, -1, done_cb)

        mock_tts.assert_called_once()
        mock_thread.start.assert_called_once()
        done_cb.assert_not_called()
