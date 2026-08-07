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


def _start_synthesis(ctrl, **kwargs):
    """Drive synthesize_and_play with a cached fake voice and a stubbed
    synthesis thread; returns the mock TTSSynthesisThread instance."""
    fake_voice = MagicMock()
    ctrl._voice_cache = ("/fake/voice.onnx", fake_voice)
    mock_thread = MagicMock()
    with patch("gmrs_tty.ui.tx_controller.TTSSynthesisThread",
               return_value=mock_thread), \
         patch("gmrs_tty.ui.tx_controller.validate_voice_path",
               return_value=True):
        ctrl.synthesize_and_play(
            "hello", voice_path="/fake/voice.onnx", length_scale=1.0,
            output_device=-1, **kwargs,
        )
    return mock_thread


class TestSynthesisTimeout:
    def test_timeout_aborts_without_keying_ptt(self, qapp):
        ctrl = _make_controller(qapp)
        messages = []
        ctrl.chat_message.connect(lambda html, color: messages.append(html))
        _start_synthesis(ctrl, synthesis_timeout_s=5.0)
        assert ctrl.is_busy
        assert ctrl._synth_timer.isActive()

        ctrl._on_synthesis_timeout()

        assert not ctrl.is_busy
        ctrl.ptt.key.assert_not_called()
        assert any("aborted" in m for m in messages)

    def test_stale_result_after_timeout_is_discarded(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl, synthesis_timeout_s=5.0)
        generation = ctrl._synth_generation
        ctrl._on_synthesis_timeout()

        import numpy as np
        with patch("gmrs_tty.ui.tx_controller.AudioPlayerThread") as player:
            ctrl._on_tts_synthesized(np.ones(16, dtype="int16"), 22050, generation)
        player.assert_not_called()
        ctrl.ptt.key.assert_not_called()
        assert not ctrl.is_busy

    def test_zero_timeout_disables_timer(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl, synthesis_timeout_s=0.0)
        assert not ctrl._synth_timer.isActive()


class TestMaxTxWatchdog:
    def _deliver_audio(self, ctrl):
        import numpy as np
        mock_player = MagicMock()
        mock_player.isRunning.return_value = True
        with patch("gmrs_tty.ui.tx_controller.AudioPlayerThread",
                   return_value=mock_player):
            ctrl._on_tts_synthesized(
                np.ones(16, dtype="int16"), 22050, ctrl._synth_generation
            )
        return mock_player

    def test_watchdog_armed_at_key_and_stops_playback(self, qapp):
        ctrl = _make_controller(qapp)
        messages = []
        ctrl.chat_message.connect(lambda html, color: messages.append(html))
        _start_synthesis(ctrl, max_tx_s=5.0)
        self._deliver_audio(ctrl)
        assert ctrl._watchdog_timer.isActive()

        with patch("sounddevice.stop") as sd_stop:
            ctrl._on_watchdog_fired()
        sd_stop.assert_called_once()
        assert any("exceeded" in m for m in messages)

        # sd.stop() unblocks sd.wait(); the finished path unkeys PTT.
        ctrl._on_audio_finished()
        ctrl.ptt.unkey.assert_called()
        assert not ctrl.is_busy
        assert not ctrl._watchdog_timer.isActive()

    def test_watchdog_cancelled_on_normal_finish(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl, max_tx_s=5.0)
        self._deliver_audio(ctrl)
        assert ctrl._watchdog_timer.isActive()
        ctrl._on_audio_finished()
        assert not ctrl._watchdog_timer.isActive()

    def test_zero_cap_never_arms_watchdog(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl, max_tx_s=0.0)
        self._deliver_audio(ctrl)
        assert not ctrl._watchdog_timer.isActive()


class TestOverLengthRefusedBeforeKeying:
    """A message longer than the cap is refused up front rather than keyed and
    then chopped off mid-word by the watchdog."""

    def _deliver(self, ctrl, seconds, sample_rate=22050):
        import numpy as np
        mock_player = MagicMock()
        with patch("gmrs_tty.ui.tx_controller.AudioPlayerThread",
                   return_value=mock_player) as player_cls:
            ctrl._on_tts_synthesized(
                np.ones(int(sample_rate * seconds), dtype="int16"),
                sample_rate, ctrl._synth_generation,
            )
        return player_cls

    def test_over_length_message_never_keys_ptt(self, qapp):
        ctrl = _make_controller(qapp)
        messages = []
        ctrl.chat_message.connect(lambda html, color: messages.append(html))
        _start_synthesis(ctrl, max_tx_s=5.0)
        player_cls = self._deliver(ctrl, seconds=6.0)

        player_cls.assert_not_called()
        ctrl.ptt.key.assert_not_called()
        assert not ctrl.is_busy
        assert not ctrl._watchdog_timer.isActive()
        assert any("cancelled" in m and "6s" in m for m in messages)

    def test_message_inside_the_cap_transmits_normally(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl, max_tx_s=5.0)
        self._deliver(ctrl, seconds=4.0)
        ctrl.ptt.key.assert_called_once()
        assert ctrl._watchdog_timer.isActive()

    def test_no_cap_means_no_length_check(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl, max_tx_s=0.0)
        self._deliver(ctrl, seconds=120.0)
        ctrl.ptt.key.assert_called_once()


class TestOperatorAbort:
    def test_abort_during_playback_stops_device(self, qapp):
        ctrl = _make_controller(qapp)
        messages = []
        ctrl.chat_message.connect(lambda html, color: messages.append(html))
        _start_synthesis(ctrl, max_tx_s=60.0)
        import numpy as np
        mock_player = MagicMock()
        mock_player.isRunning.return_value = True
        with patch("gmrs_tty.ui.tx_controller.AudioPlayerThread",
                   return_value=mock_player):
            ctrl._on_tts_synthesized(
                np.ones(16, dtype="int16"), 22050, ctrl._synth_generation
            )
        with patch("sounddevice.stop") as sd_stop:
            ctrl.abort_tx()
        sd_stop.assert_called_once()
        assert any("operator" in m for m in messages)

    def test_abort_during_synthesis_discards_result(self, qapp):
        ctrl = _make_controller(qapp)
        _start_synthesis(ctrl)
        generation = ctrl._synth_generation
        ctrl.abort_tx()
        assert not ctrl.is_busy
        import numpy as np
        with patch("gmrs_tty.ui.tx_controller.AudioPlayerThread") as player:
            ctrl._on_tts_synthesized(np.ones(16, dtype="int16"), 22050, generation)
        player.assert_not_called()
        ctrl.ptt.key.assert_not_called()

    def test_abort_when_idle_is_noop(self, qapp):
        ctrl = _make_controller(qapp)
        messages = []
        ctrl.chat_message.connect(lambda html, color: messages.append(html))
        ctrl.abort_tx()
        assert messages == []


class TestPrimerWordPrepend:
    def test_primer_word_prefixed_to_text(self, qapp):
        ctrl = _make_controller(qapp)
        fake_voice = MagicMock()
        ctrl._voice_cache = ("/fake/voice.onnx", fake_voice)
        with patch("gmrs_tty.ui.tx_controller.TTSSynthesisThread") as mock_tts, \
             patch("gmrs_tty.ui.tx_controller.validate_voice_path",
                   return_value=True):
            mock_tts.return_value = MagicMock()
            ctrl.synthesize_and_play(
                "hello", voice_path="/fake/voice.onnx", length_scale=1.0,
                output_device=-1, vox_primer_word="transmit",
            )
        text_arg = mock_tts.call_args.args[1]
        assert text_arg.startswith("transmit. ")

    def test_conditioning_and_primer_forwarded_to_thread(self, qapp):
        ctrl = _make_controller(qapp)
        fake_voice = MagicMock()
        ctrl._voice_cache = ("/fake/voice.onnx", fake_voice)
        with patch("gmrs_tty.ui.tx_controller.TTSSynthesisThread") as mock_tts, \
             patch("gmrs_tty.ui.tx_controller.validate_voice_path",
                   return_value=True):
            mock_tts.return_value = MagicMock()
            ctrl.synthesize_and_play(
                "hello", voice_path="/fake/voice.onnx", length_scale=1.0,
                output_device=-1, tx_conditioning=True, vox_primer_ms=300,
            )
        kwargs = mock_tts.call_args.kwargs
        assert kwargs["condition"] is True
        assert kwargs["vox_primer_ms"] == 300
