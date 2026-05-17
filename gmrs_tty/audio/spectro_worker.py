"""Background QThread that turns RX capture chunks into spectrogram rows.

Lives downstream of the STT worker — STT emits raw chunks via the
``audio_chunk`` Qt signal, the spectrogram worker buffers them in a
:class:`ChunkRing`, slides ``frame_size``-sized windows out at every
``hop_size`` boundary, and emits one dB-magnitude row per frame on the
``row_ready`` signal.

The worker is intentionally light on its own thread: it sleeps on a
``threading.Event``, wakes when new audio arrives, and only computes if
there's a full frame waiting. If the GUI is too slow to drain the
``row_ready`` queue, Qt will coalesce queued emissions — but the
upstream ring drops oldest samples first, so the producer (STT capture
loop) is never blocked. That is the load-shed contract the implementation
plan calls out: never starve VAD/STT.
"""
from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QThread, Signal

from gmrs_tty.audio.spectrogram import (
    ChunkRing,
    DEFAULT_FRAME_SIZE,
    DEFAULT_HOP_SIZE,
    DEFAULT_SAMPLE_RATE,
    compute_frame,
    hann_window,
    magnitude_to_db,
)


class SpectrogramWorker(QThread):
    """Consumes audio chunks, emits dB-magnitude rows.

    Single-threaded by design: one row per hop, in capture order, so the
    waterfall scrolls monotonically. Sample-rate and frame parameters are
    fixed at construction; reconfiguring requires a stop/start cycle (the
    rfft plan and window are precomputed against them).
    """

    # numpy ndarray of length frame_size // 2 + 1, dtype float32, in dB.
    row_ready = Signal(object)

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        frame_size: int = DEFAULT_FRAME_SIZE,
        hop_size: int = DEFAULT_HOP_SIZE,
        ring_capacity_frames: int = 16,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sample_rate = int(sample_rate)
        self.frame_size = int(frame_size)
        self.hop_size = int(hop_size)
        self._window = hann_window(self.frame_size)
        self._ring = ChunkRing(
            frame_size=self.frame_size,
            hop_size=self.hop_size,
            capacity_frames=ring_capacity_frames,
        )
        self._wake = threading.Event()
        self._running = True

    # Producer side -------------------------------------------------------
    def push_chunk(self, chunk: np.ndarray) -> None:
        """Hand a captured chunk to the ring. Called from the STT worker
        thread via a Qt signal/slot — must stay allocation-free on the
        hot path beyond what numpy already needs."""
        if chunk is None:
            return
        try:
            data = np.asarray(chunk, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            return
        if data.size == 0:
            return
        self._ring.push(data)
        self._wake.set()

    def stop(self) -> None:
        self._running = False
        self._wake.set()

    # Consumer side -------------------------------------------------------
    def run(self) -> None:
        while self._running:
            self._wake.wait(timeout=0.5)
            self._wake.clear()
            # Drain everything currently bufferable; pop_frame returns
            # None when fewer than frame_size samples are queued.
            while self._running:
                frame = self._ring.pop_frame()
                if frame is None:
                    break
                try:
                    spectrum = compute_frame(frame, self._window)
                    row = magnitude_to_db(spectrum)
                except Exception:
                    # FFT failure shouldn't kill the worker; skip the row
                    # and try again on the next chunk.
                    continue
                self.row_ready.emit(row)

    @property
    def dropped_samples(self) -> int:
        """Cumulative samples evicted by ring overflow. Surfaced for
        the optional performance/health overlay; resets on stop()."""
        return self._ring.dropped_samples
