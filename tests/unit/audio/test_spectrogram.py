"""Unit tests for the Qt-free spectrogram helpers.

These cover the math that the rolling-RX waterfall depends on:
  * Hann window correctness (endpoints zero, mid peak, symmetric)
  * compute_frame produces a peak at the right bin for a known sine
  * magnitude_to_db floors at MIN_DB instead of -inf for silence
  * ChunkRing emits hop-aligned frames and drops on overflow
  * bin_range_for_band clips to Nyquist and always returns >=1 bin
"""
import numpy as np
import pytest

from gmrs_tty.audio.spectrogram import (
    ChunkRing,
    DEFAULT_FRAME_SIZE,
    DEFAULT_HOP_SIZE,
    DEFAULT_SAMPLE_RATE,
    MIN_DB,
    bin_range_for_band,
    compute_frame,
    frequency_bins,
    hann_window,
    magnitude_to_db,
)


class TestHannWindow:
    def test_endpoints_are_zero(self):
        w = hann_window(64)
        assert w[0] == pytest.approx(0.0, abs=1e-6)
        assert w[-1] == pytest.approx(0.0, abs=1e-6)

    def test_midpoint_peaks_at_one(self):
        w = hann_window(65)  # odd length so there's a true center sample
        assert w[len(w) // 2] == pytest.approx(1.0, abs=1e-6)

    def test_window_is_symmetric(self):
        w = hann_window(128)
        assert np.allclose(w, w[::-1], atol=1e-6)

    def test_dtype_is_float32(self):
        # rfft has a fast path on float32; the worker reuses this window so
        # locking the dtype here protects the hot path.
        assert hann_window(32).dtype == np.float32

    def test_zero_length_raises(self):
        with pytest.raises(ValueError):
            hann_window(0)

    def test_length_one_is_unit(self):
        # Degenerate single-sample window — exists so callers don't have to
        # special-case frame_size == 1.
        assert np.allclose(hann_window(1), [1.0])


class TestComputeFrame:
    def test_peak_at_known_sine_bin(self):
        # A 1 kHz sine into a 1024-point FFT at 16 kHz should peak at bin 64
        # (1000 / (16000 / 1024) == 64). Hann widens the peak slightly, but
        # the maximum bin is still correct.
        sr = 16000
        n = 1024
        freq = 1000.0
        t = np.arange(n) / sr
        samples = np.sin(2 * np.pi * freq * t).astype(np.float32)
        window = hann_window(n)
        spectrum = compute_frame(samples, window)
        peak_bin = int(np.argmax(spectrum))
        expected_bin = int(round(freq * n / sr))
        assert abs(peak_bin - expected_bin) <= 1

    def test_silence_produces_zero_magnitude(self):
        samples = np.zeros(1024, dtype=np.float32)
        spectrum = compute_frame(samples, hann_window(1024))
        assert np.max(spectrum) == pytest.approx(0.0, abs=1e-6)

    def test_returns_float32(self):
        spectrum = compute_frame(np.zeros(64, dtype=np.float32), hann_window(64))
        assert spectrum.dtype == np.float32

    def test_output_length_is_half_plus_one(self):
        # rfft of N real samples is N//2 + 1 bins.
        spectrum = compute_frame(np.zeros(512, dtype=np.float32), hann_window(512))
        assert spectrum.shape[0] == 512 // 2 + 1

    def test_window_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            compute_frame(np.zeros(64, dtype=np.float32), hann_window(32))


class TestMagnitudeToDb:
    def test_silence_clamps_to_floor(self):
        # log10(0) would be -inf; we want MIN_DB instead so a silent frame
        # doesn't poison the displayed dB range.
        db = magnitude_to_db(np.zeros(8, dtype=np.float32))
        assert np.all(db >= MIN_DB - 1e-3)
        assert np.all(np.isfinite(db))

    def test_unit_magnitude_is_zero_db(self):
        db = magnitude_to_db(np.array([1.0], dtype=np.float32))
        assert db[0] == pytest.approx(0.0, abs=1e-4)

    def test_factor_of_ten_is_twenty_db(self):
        db = magnitude_to_db(np.array([10.0], dtype=np.float32))
        assert db[0] == pytest.approx(20.0, abs=1e-4)

    def test_empty_input_returns_empty(self):
        db = magnitude_to_db(np.zeros(0, dtype=np.float32))
        assert db.size == 0


class TestChunkRing:
    def test_pop_returns_none_until_full_frame(self):
        ring = ChunkRing(frame_size=16, hop_size=8, capacity_frames=4)
        ring.push(np.zeros(8, dtype=np.float32))
        assert ring.pop_frame() is None
        ring.push(np.zeros(8, dtype=np.float32))
        assert ring.pop_frame() is not None

    def test_pop_advances_by_hop_size(self):
        ring = ChunkRing(frame_size=8, hop_size=4, capacity_frames=4)
        ring.push(np.arange(16, dtype=np.float32))
        first = ring.pop_frame()
        second = ring.pop_frame()
        assert first is not None and second is not None
        # First frame covers indices 0..7, second is 4..11 (hop=4).
        assert np.allclose(first, np.arange(0, 8))
        assert np.allclose(second, np.arange(4, 12))

    def test_overflow_drops_oldest(self):
        # Capacity = frame_size + hop_size * capacity_frames = 16 + 4*2 = 24.
        # Pushing 40 samples means the ring evicts 16 samples (rounded up to
        # the nearest hop boundary), leaving samples 16..39 in the buffer.
        # The newest value (39) must surface after enough pops to walk past
        # the surviving prefix.
        ring = ChunkRing(frame_size=16, hop_size=4, capacity_frames=2)
        ring.push(np.arange(40, dtype=np.float32))
        assert ring.dropped_samples >= 16
        seen_newest = False
        while True:
            frame = ring.pop_frame()
            if frame is None:
                break
            if 39.0 in frame.tolist():
                seen_newest = True
        assert seen_newest, "newest sample must survive overflow"

    def test_overflow_keeps_buffer_hop_aligned(self):
        # After an overflow, the next frame popped should still be 16 samples
        # wide and the difference between consecutive pops should equal the
        # hop size — i.e. eviction didn't desync the producer/consumer grid.
        ring = ChunkRing(frame_size=16, hop_size=4, capacity_frames=2)
        ring.push(np.arange(40, dtype=np.float32))
        first = ring.pop_frame()
        second = ring.pop_frame()
        assert first is not None and second is not None
        assert first.size == 16 and second.size == 16
        assert second[0] - first[0] == pytest.approx(4.0)

    def test_clear_empties_buffer(self):
        ring = ChunkRing(frame_size=8, hop_size=4, capacity_frames=4)
        ring.push(np.zeros(20, dtype=np.float32))
        ring.clear()
        assert ring.pop_frame() is None

    def test_push_handles_empty_chunk(self):
        ring = ChunkRing(frame_size=8, hop_size=4, capacity_frames=4)
        ring.push(np.zeros(0, dtype=np.float32))
        ring.push(None)
        assert ring.pop_frame() is None

    def test_invalid_hop_raises(self):
        with pytest.raises(ValueError):
            ChunkRing(frame_size=8, hop_size=16, capacity_frames=2)
        with pytest.raises(ValueError):
            ChunkRing(frame_size=8, hop_size=0, capacity_frames=2)

    def test_invalid_capacity_raises(self):
        with pytest.raises(ValueError):
            ChunkRing(frame_size=8, hop_size=4, capacity_frames=0)


class TestFrequencyBins:
    def test_first_bin_is_zero_hz(self):
        bins = frequency_bins(1024, 16000)
        assert bins[0] == pytest.approx(0.0)

    def test_last_bin_is_nyquist(self):
        bins = frequency_bins(1024, 16000)
        assert bins[-1] == pytest.approx(8000.0, abs=1e-3)

    def test_bin_count_is_half_plus_one(self):
        assert frequency_bins(512, 16000).shape[0] == 512 // 2 + 1


class TestBinRangeForBand:
    def test_voice_band_clipped_to_voice(self):
        lo, hi = bin_range_for_band(1024, 16000, 300.0, 3400.0)
        bins = frequency_bins(1024, 16000)
        assert bins[lo] >= 300.0 - 16.0 and bins[lo] <= 320.0
        # hi is exclusive; the last included bin is bins[hi-1].
        assert bins[hi - 1] <= 3400.0 + 16.0

    def test_above_nyquist_clipped(self):
        lo, hi = bin_range_for_band(1024, 16000, 0.0, 99999.0)
        assert hi == frequency_bins(1024, 16000).size

    def test_inverted_inputs_safe(self):
        lo, hi = bin_range_for_band(1024, 16000, 9000.0, 300.0)
        # Clipped band collapses to a single safe bin.
        assert hi - lo >= 1

    def test_zero_width_band_returns_at_least_one_bin(self):
        lo, hi = bin_range_for_band(1024, 16000, 1000.0, 1000.0)
        assert hi - lo >= 1


class TestDefaultsAreSane:
    def test_defaults_imply_overlap(self):
        # Hop size below frame size is the whole point of streaming FFT
        # frames — assert the defaults preserve that contract.
        assert DEFAULT_HOP_SIZE < DEFAULT_FRAME_SIZE
        assert DEFAULT_HOP_SIZE > 0
        assert DEFAULT_SAMPLE_RATE == 16000
