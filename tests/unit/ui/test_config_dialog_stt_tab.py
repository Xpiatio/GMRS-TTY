"""ConfigDialog STT tab — widget wiring and get_config round-trip."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock, patch  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.ui.config_dialog import ConfigDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_dialog(qapp, config=None):
    # DeviceQueryThread probes PortAudio; stub it so the test never touches
    # audio hardware and OK-button gating stays deterministic.
    with patch("gmrs_tty.ui.config_dialog.DeviceQueryThread") as thread_cls:
        thread_cls.return_value = MagicMock()
        dlg = ConfigDialog(config or {})
    return dlg


class TestSttTabDefaults:
    def test_defaults_render(self, qapp):
        dlg = _make_dialog(qapp)
        assert dlg.gain_mode_input.currentData() == "agc"
        assert dlg.noise_profile_input.isChecked() is False
        assert dlg.saved_phrases_input.toPlainText() == ""
        assert dlg.vocab_max_callsigns_input.value() == 15
        assert dlg.debug_capture_input.isChecked() is False
        assert dlg.debug_dir_input.text() == "debug/stt"
        # Debug dir is only editable when capture is on.
        assert dlg.debug_dir_input.isEnabled() is False

    def test_saved_values_render(self, qapp):
        dlg = _make_dialog(qapp, {
            "stt_gain_mode": "rms",
            "stt_noise_profile": True,
            "saved_phrases": ["Kent County ARES", "repeater"],
            "stt_vocab_max_callsigns": 7,
            "stt_debug_capture": True,
            "stt_debug_dir": "captures",
        })
        assert dlg.gain_mode_input.currentData() == "rms"
        assert dlg.noise_profile_input.isChecked() is True
        assert dlg.saved_phrases_input.toPlainText() == "Kent County ARES\nrepeater"
        assert dlg.vocab_max_callsigns_input.value() == 7
        assert dlg.debug_capture_input.isChecked() is True
        assert dlg.debug_dir_input.text() == "captures"
        assert dlg.debug_dir_input.isEnabled() is True


class TestSttTabGetConfig:
    def test_round_trip(self, qapp):
        dlg = _make_dialog(qapp)
        dlg.gain_mode_input.setCurrentIndex(dlg.gain_mode_input.findData("off"))
        dlg.noise_profile_input.setChecked(True)
        dlg.saved_phrases_input.setPlainText("  Ada Township \n\n net control ")
        dlg.vocab_max_callsigns_input.setValue(3)
        dlg.debug_capture_input.setChecked(True)
        dlg.debug_dir_input.setText("  ")
        cfg = dlg.get_config()
        assert cfg["stt_gain_mode"] == "off"
        assert cfg["stt_noise_profile"] is True
        assert cfg["saved_phrases"] == ["Ada Township", "net control"]
        assert cfg["stt_vocab_max_callsigns"] == 3
        assert cfg["stt_debug_capture"] is True
        # Blank dir falls back to the default rather than saving "".
        assert cfg["stt_debug_dir"] == "debug/stt"

    def test_whisper_model_in_config(self, qapp):
        dlg = _make_dialog(qapp, {"whisper_model": "small.en"})
        assert dlg.get_config()["whisper_model"] == "small.en"


class TestSttTabAccessibility:
    def test_widgets_have_accessible_names(self, qapp):
        dlg = _make_dialog(qapp)
        for widget in (
            dlg.whisper_model_input, dlg.gain_mode_input, dlg.noise_profile_input,
            dlg.saved_phrases_input, dlg.vocab_max_callsigns_input,
            dlg.debug_capture_input, dlg.debug_dir_input,
        ):
            assert widget.accessibleName(), widget
            assert widget.accessibleDescription(), widget
            assert widget.toolTip(), widget
