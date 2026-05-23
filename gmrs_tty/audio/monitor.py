import collections
import threading

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly, sosfilt, sosfilt_zi

from gmrs_tty.audio.dsp import make_bandpass_sos


class AudioMonitor:
    """Streams incoming radio audio to the output device in real-time.

    Thread-safe: push() is called from the STT worker thread; the
    sounddevice callback runs on a dedicated audio thread. A bounded
    deque absorbs bursts and drops oldest samples when the buffer would
    exceed ~1 s so playback never lags behind live audio.

    Audio processing in push():
      1. Bandpass 300–3000 Hz (causal sosfilt with persistent state —
         seamless across chunk boundaries, matches the narrowband-FM voice band)
      2. Upsample 16 kHz → 48 kHz via polyphase resampler so the output
         device receives its native rate rather than leaving resampling to
         the driver (which may use low-quality linear interpolation).
    """

    INPUT_RATE = 16_000
    OUTPUT_RATE = 48_000
    _UPSAMPLE_RATIO = OUTPUT_RATE // INPUT_RATE  # 3
    CHANNELS = 1
    DTYPE = "float32"
    _MAX_BUFFER_SAMPLES = OUTPUT_RATE  # ~1 s at output rate before dropping oldest

    def __init__(self):
        self._buf: collections.deque = collections.deque()
        self._buf_lock = threading.Lock()
        self._buf_samples = 0
        self._stream: sd.OutputStream | None = None
        self._stream_lock = threading.Lock()
        self._muted = threading.Event()

        self._sos = make_bandpass_sos(self.INPUT_RATE, 300, 3000)
        self._zi = sosfilt_zi(self._sos)  # persistent filter state across chunks

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
        self._zi = sosfilt_zi(self._sos)  # reset filter state on each new session
        with self._stream_lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
            self._stream = sd.OutputStream(
                samplerate=self.OUTPUT_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                device=sd_device,
                blocksize=512,
                latency="low",
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
        # Bandpass 300–3000 Hz; sosfilt carries state across calls so there
        # are no edge transients at chunk boundaries.
        filtered, self._zi = sosfilt(self._sos, chunk, zi=self._zi)
        # Upsample 16 kHz → 48 kHz with polyphase sinc resampler.
        upsampled = resample_poly(filtered, self._UPSAMPLE_RATIO, 1).astype(np.float32)
        with self._buf_lock:
            while self._buf_samples + len(upsampled) > self._MAX_BUFFER_SAMPLES and self._buf:
                dropped = self._buf.popleft()
                self._buf_samples -= len(dropped)
            self._buf.append(upsampled)
            self._buf_samples += len(upsampled)

    def mute(self, muted: bool) -> None:
        """Suppress output without stopping the stream (called during TX)."""
        if muted:
            self._muted.set()
        else:
            self._muted.clear()

    # ------------------------------------------------------------------
    # sounddevice callback (audio thread — keep fast, avoid blocking)
    # ------------------------------------------------------------------

    def _callback(self, outdata: np.ndarray, frames: int, time, status) -> None:
        if self._muted.is_set():
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
