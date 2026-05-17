"""Pure FFT + ring-buffer helpers for the rolling RX spectrometer.

Kept Qt-free so the STT worker tap and the unit tests can both lean on it
without dragging PySide6 into the audio layer.

The spectrometer pipeline is:

    capture chunk (512 samples @ 16 kHz)
        └─► ChunkRing  ─►  build_frame(...)  ─►  rfft + Hann + dB  ─►  row

The ring concatenates chunks until enough samples are available for one
FFT frame (``frame_size`` samples), then slides forward by ``hop_size``
samples per frame. Defaults pin a 1024-sample frame with 50 % overlap at
16 kHz, i.e. a hop every ~32 ms — fast enough to see voice formants
without dominating CPU on a Raspberry Pi 4.
"""
from __future__ import annotations

import threading

import numpy as np


DEFAULT_FRAME_SIZE = 1024
DEFAULT_HOP_SIZE = 512
DEFAULT_SAMPLE_RATE = 16000
# Floor for log conversion. Anything below this is clamped to MIN_DB so a
# silent input doesn't produce -inf rows that corrupt the colormap range.
MIN_DB = -120.0


def hann_window(n: int) -> np.ndarray:
    """Symmetric Hann window of length ``n``.

    We hand-roll the formula rather than calling ``scipy.signal.windows``
    so the spectrometer hot path stays free of scipy import overhead on a
    cold start (scipy is already loaded for the bandpass, but the
    spectrometer can run in tests / smoke tests without it).
    """
    if n <= 0:
        raise ValueError("hann_window length must be positive")
    if n == 1:
        return np.ones(1, dtype=np.float32)
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)


def magnitude_to_db(magnitudes: np.ndarray, ref: float = 1.0) -> np.ndarray:
    """Convert linear magnitude spectra to dB with a stable floor.

    ``ref`` is the reference amplitude. With float32 PCM in [-1.0, 1.0]
    and a Hann-windowed rfft, the peak magnitude for a full-scale sine
    sits well under N/2; we leave ``ref=1.0`` so the dB scale is
    self-relative ("how far below 0 dBFS" rather than absolute SPL).
    """
    if magnitudes.size == 0:
        return magnitudes.astype(np.float32)
    safe = np.maximum(magnitudes, 1e-12)
    db = 20.0 * np.log10(safe / max(ref, 1e-12))
    return np.maximum(db, MIN_DB).astype(np.float32)


def compute_frame(
    samples: np.ndarray,
    window: np.ndarray,
) -> np.ndarray:
    """Hann-window + rfft a single time-domain frame.

    Returns the linear magnitude spectrum (length ``frame_size // 2 + 1``).
    The caller converts to dB if it wants a log scale.
    """
    if samples.shape[0] != window.shape[0]:
        raise ValueError(
            f"frame length {samples.shape[0]} != window length {window.shape[0]}"
        )
    windowed = samples.astype(np.float32) * window
    spectrum = np.fft.rfft(windowed)
    return np.abs(spectrum).astype(np.float32)


class ChunkRing:
    """Thread-safe sample accumulator that emits fixed-size FFT frames.

    The producer (audio capture loop) calls :meth:`push` with whatever
    chunk size it has on hand; the consumer (FFT worker) calls
    :meth:`pop_frame` repeatedly until it returns ``None``. Each frame
    overlaps the previous by ``frame_size - hop_size`` samples.

    Capacity is fixed at construction time. When the ring fills past
    capacity, the oldest samples are dropped — the spectrometer must
    never back-pressure the capture loop or it would starve VAD/STT.
    """

    def __init__(
        self,
        frame_size: int = DEFAULT_FRAME_SIZE,
        hop_size: int = DEFAULT_HOP_SIZE,
        capacity_frames: int = 16,
    ) -> None:
        if frame_size <= 0:
            raise ValueError("frame_size must be positive")
        if hop_size <= 0 or hop_size > frame_size:
            raise ValueError("hop_size must be in (0, frame_size]")
        if capacity_frames < 1:
            raise ValueError("capacity_frames must be >= 1")
        self.frame_size = int(frame_size)
        self.hop_size = int(hop_size)
        self.capacity_samples = self.frame_size + self.hop_size * int(capacity_frames)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self.dropped_samples = 0

    def push(self, chunk: np.ndarray) -> None:
        """Append a chunk. Older samples are evicted when capacity is reached."""
        if chunk is None or chunk.size == 0:
            return
        data = np.asarray(chunk, dtype=np.float32).reshape(-1)
        with self._lock:
            self._buffer = np.concatenate((self._buffer, data))
            if self._buffer.size > self.capacity_samples:
                overflow = self._buffer.size - self.capacity_samples
                # Snap overflow to a multiple of hop_size so the next pop
                # lands on the same hop grid as the producer expected. If
                # we just chopped raw samples, the consumer would see a
                # ragged frame on the very next call after a drop.
                overflow = ((overflow + self.hop_size - 1) // self.hop_size) * self.hop_size
                overflow = min(overflow, self._buffer.size)
                self._buffer = self._buffer[overflow:]
                self.dropped_samples += overflow

    def pop_frame(self) -> np.ndarray | None:
        """Return one frame_size window and advance by hop_size, or None
        if not enough samples are buffered yet."""
        with self._lock:
            if self._buffer.size < self.frame_size:
                return None
            frame = self._buffer[: self.frame_size].copy()
            self._buffer = self._buffer[self.hop_size:]
            return frame

    def clear(self) -> None:
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)


def frequency_bins(frame_size: int, sample_rate: int) -> np.ndarray:
    """Return the center frequency (Hz) of every rfft bin for ``frame_size``."""
    return np.fft.rfftfreq(frame_size, d=1.0 / sample_rate).astype(np.float32)


def bin_range_for_band(
    frame_size: int, sample_rate: int, low_hz: float, high_hz: float
) -> tuple[int, int]:
    """Return ``(lo_bin, hi_bin_exclusive)`` for a frequency band.

    Inputs outside [0, Nyquist] are clipped. Always returns at least one
    bin so callers can slice unconditionally.
    """
    nyquist = sample_rate / 2.0
    low = max(0.0, min(low_hz, nyquist))
    high = max(low, min(high_hz, nyquist))
    bins = frequency_bins(frame_size, sample_rate)
    lo = int(np.searchsorted(bins, low, side="left"))
    hi = int(np.searchsorted(bins, high, side="right"))
    if hi <= lo:
        hi = min(lo + 1, bins.size)
    return lo, hi
