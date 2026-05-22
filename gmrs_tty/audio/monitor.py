import collections
import threading

import numpy as np
import sounddevice as sd


class AudioMonitor:
    """Streams incoming radio audio to the output device in real-time.

    Thread-safe: push() is called from the STT worker thread; the
    sounddevice callback runs on a dedicated audio thread. A bounded
    deque absorbs bursts and drops oldest samples when the buffer would
    exceed ~1 s so playback never lags behind live audio.
    """

    SAMPLE_RATE = 16_000
    CHANNELS = 1
    DTYPE = "float32"
    _MAX_BUFFER_SAMPLES = 16_000  # ~1 s before we start dropping oldest

    def __init__(self):
        self._buf: collections.deque = collections.deque()
        self._buf_lock = threading.Lock()
        self._buf_samples = 0
        self._stream: sd.OutputStream | None = None
        self._stream_lock = threading.Lock()
        self._muted = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        with self._stream_lock:
            return self._stream is not None and self._stream.active

    def start(self, device=None) -> None:
        """Open the output stream. device is a PortAudio index or None/−1 for default."""
        sd_device = device if device not in (None, -1) else None
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
            self._stream = sd.OutputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                device=sd_device,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> None:
        """Close the output stream and drain the buffer."""
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        with self._buf_lock:
            self._buf.clear()
            self._buf_samples = 0

    def push(self, chunk: np.ndarray) -> None:
        """Enqueue a float32 audio chunk from the capture loop."""
        with self._stream_lock:
            if self._stream is None:
                return
        with self._buf_lock:
            # Evict oldest chunks if we'd exceed the latency cap
            while self._buf_samples + len(chunk) > self._MAX_BUFFER_SAMPLES and self._buf:
                dropped = self._buf.popleft()
                self._buf_samples -= len(dropped)
            self._buf.append(chunk.copy())
            self._buf_samples += len(chunk)

    def mute(self, muted: bool) -> None:
        """Suppress output without stopping the stream (called during TX)."""
        self._muted = muted

    # ------------------------------------------------------------------
    # sounddevice callback (audio thread — keep fast, avoid blocking)
    # ------------------------------------------------------------------

    def _callback(self, outdata: np.ndarray, frames: int, time, status) -> None:
        if self._muted:
            outdata[:] = 0
            return
        remaining = frames
        write_pos = 0
        with self._buf_lock:
            while remaining > 0 and self._buf:
                chunk = self._buf[0]
                take = min(len(chunk), remaining)
                outdata[write_pos:write_pos + take, 0] = chunk[:take]
                write_pos += take
                remaining -= take
                if take == len(chunk):
                    self._buf.popleft()
                    self._buf_samples -= take
                else:
                    # Partial consumption: replace head with the leftover slice
                    self._buf[0] = chunk[take:]
                    self._buf_samples -= take
        if remaining > 0:
            outdata[write_pos:, 0] = 0
