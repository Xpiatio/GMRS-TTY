import numpy as np
import pytest

from gmrs_tty.audio.dsp import normalize_rms


class TestNormalizeRms:
    def test_normalizes_to_target_level(self):
        # Sine at known RMS = 1/sqrt(2) ≈ 0.707
        t = np.linspace(0, 1, 16000, dtype=np.float32)
        audio = np.sin(2 * np.pi * 1000 * t)
        result = normalize_rms(audio, target_dbfs=-20.0)
        target_rms = 10 ** (-20.0 / 20.0)
        actual_rms = float(np.sqrt(np.mean(result ** 2)))
        assert actual_rms == pytest.approx(target_rms, rel=1e-3)

    def test_modifies_in_place(self):
        audio = np.ones(1024, dtype=np.float32) * 0.5
        original_id = id(audio)
        result = normalize_rms(audio)
        assert id(result) == original_id

    def test_silence_is_unchanged(self):
        audio = np.zeros(1024, dtype=np.float32)
        result = normalize_rms(audio)
        assert np.all(result == 0.0)

    def test_near_silence_is_unchanged(self):
        audio = np.full(1024, 1e-8, dtype=np.float32)
        original = audio.copy()
        normalize_rms(audio)
        np.testing.assert_array_equal(audio, original)

    def test_clips_to_unit_range(self):
        # Very quiet signal → large gain → clamp to [-1, 1]
        audio = np.full(1024, 1e-4, dtype=np.float32)
        result = normalize_rms(audio, target_dbfs=0.0)
        assert np.all(np.abs(result) <= 1.0)

    def test_default_target_is_minus20_dbfs(self):
        audio = np.ones(1024, dtype=np.float32) * 0.1
        result = normalize_rms(audio.copy())
        target_rms = 10 ** (-20.0 / 20.0)
        assert float(np.sqrt(np.mean(result ** 2))) == pytest.approx(target_rms, rel=1e-3)
