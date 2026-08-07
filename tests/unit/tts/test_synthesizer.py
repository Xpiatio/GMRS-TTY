"""TTSSynthesisThread splice geometry — primer tone and TX conditioning."""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.tts.synthesizer import TTSSynthesisThread, make_vox_primer  # noqa: E402

SR = 16000


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _fake_voice(speech: np.ndarray):
    """A stand-in Piper voice producing one chunk of the given int16 speech."""
    voice = MagicMock()
    voice.config.num_speakers = 1
    voice.config.sample_rate = SR
    voice.synthesize.return_value = iter(
        [SimpleNamespace(audio_int16_array=speech)]
    )
    return voice


def _run(thread):
    """Run the QThread body synchronously and capture the emitted buffer."""
    result = {}
    thread.ready.connect(lambda audio, sr: result.update(audio=audio, sr=sr))
    thread.error.connect(lambda msg: result.update(error=msg))
    thread.run()
    return result


class TestMakeVoxPrimer:
    def test_tone_plus_gap_length(self):
        primer = make_vox_primer(SR, 300, gap_ms=80.0)
        assert len(primer) == int(0.3 * SR) + int(0.08 * SR)
        assert primer.dtype == np.int16

    def test_gap_is_silent_and_tone_is_not(self):
        primer = make_vox_primer(SR, 100, gap_ms=50.0)
        tone_n = int(0.1 * SR)
        assert np.abs(primer[:tone_n]).max() > 0
        assert np.abs(primer[tone_n:]).max() == 0


class TestSpliceGeometry:
    def test_primer_sits_between_lead_in_and_speech(self, qapp):
        speech = np.full(SR, 1000, dtype=np.int16)  # 1 s of constant level
        thread = TTSSynthesisThread(
            _fake_voice(speech), "hi", lead_seconds=0.5, tail_seconds=0.25,
            vox_primer_ms=300,
        )
        result = _run(thread)
        audio = result["audio"]
        lead_n = int(0.5 * SR)
        primer_n = len(make_vox_primer(SR, 300))
        tail_n = int(0.25 * SR)
        assert len(audio) == lead_n + primer_n + len(speech) + tail_n
        # Lead-in and tail are true zeros; speech lands after the primer.
        assert np.abs(audio[:lead_n]).max() == 0
        assert np.abs(audio[-tail_n:]).max() == 0
        assert (audio[lead_n + primer_n:lead_n + primer_n + len(speech)] == speech).all()

    def test_no_primer_by_default(self, qapp):
        speech = np.full(SR, 1000, dtype=np.int16)
        thread = TTSSynthesisThread(
            _fake_voice(speech), "hi", lead_seconds=0.0, tail_seconds=0.0,
        )
        result = _run(thread)
        assert (result["audio"] == speech).all()

    def test_conditioning_applied_before_padding(self, qapp):
        speech = np.full(SR, 1000, dtype=np.int16)
        conditioned = np.full(SR, 42, dtype=np.int16)
        thread = TTSSynthesisThread(
            _fake_voice(speech), "hi", lead_seconds=0.5, tail_seconds=0.5,
            condition=True,
        )
        with patch(
            "gmrs_tty.audio.tx_conditioning.condition_tx_audio",
            return_value=conditioned,
        ) as cond:
            result = _run(thread)
        cond.assert_called_once()
        audio = result["audio"]
        lead_n = int(0.5 * SR)
        # Padding regions stay exact zeros even with conditioning on.
        assert np.abs(audio[:lead_n]).max() == 0
        assert np.abs(audio[-lead_n:]).max() == 0
        assert (audio[lead_n:lead_n + SR] == conditioned).all()

    def test_conditioning_off_leaves_speech_untouched(self, qapp):
        speech = np.full(SR, 1000, dtype=np.int16)
        thread = TTSSynthesisThread(
            _fake_voice(speech), "hi", lead_seconds=0.0, tail_seconds=0.0,
            condition=False,
        )
        with patch(
            "gmrs_tty.audio.tx_conditioning.condition_tx_audio"
        ) as cond:
            result = _run(thread)
        cond.assert_not_called()
        assert (result["audio"] == speech).all()
