import shutil
import subprocess

import numpy as np
import sounddevice as sd


class ParecSource:
    """PulseAudio/PipeWire `parec` capture.

    Reliable on PipeWire 1.4 where PortAudio's ALSA bridge can silently
    deliver flat-zero buffers — only the first stream after PortAudio init
    returns audio, and long-lived streams degenerate to silence with no
    error. parec speaks PipeWire's PulseAudio protocol directly and is
    stable across stream restarts.
    """

    def __init__(self, sample_rate, chunk_samples):
        parec_bin = shutil.which("parec")
        if not parec_bin:
            raise FileNotFoundError("parec binary not on PATH")
        self.sample_rate = sample_rate
        self.chunk_samples = chunk_samples
        self.bytes_per_chunk = chunk_samples * 2  # int16 little-endian
        self.proc = subprocess.Popen(
            [parec_bin, "--raw", "--format=s16le",
             f"--rate={sample_rate}", "--channels=1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def read(self):
        buf = self.proc.stdout.read(self.bytes_per_chunk)
        while len(buf) < self.bytes_per_chunk:
            more = self.proc.stdout.read(self.bytes_per_chunk - len(buf))
            if not more:
                raise IOError("parec stdout closed unexpectedly")
            buf = buf + more
        return np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class PortAudioSource:
    """sounddevice/PortAudio capture for a specific input device.

    Used when the operator has selected an explicit input device (e.g., a
    USB sound card / Signalink / Digirig), or when parec isn't available
    on the host (Windows, headless Linux without PulseAudio/PipeWire).
    """

    def __init__(self, sample_rate, chunk_samples, device=None):
        self.sample_rate = sample_rate
        self.chunk_samples = chunk_samples
        self.stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            device=device,
        )
        self.stream.start()

    def read(self):
        data, _ = self.stream.read(self.chunk_samples)
        return data[:, 0].copy()

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass


def open_input_source(sample_rate, chunk_samples, input_device=None):
    """Open an InputSource for the active capture path.

    Prefers `parec` over PortAudio when the operator has not selected a
    specific input device — PortAudio's PipeWire-via-ALSA bridge can
    silently deliver flat-zero buffers on PipeWire 1.4. Falls back to
    PortAudio if parec isn't on PATH, or when a specific input device
    is configured.
    """
    if input_device is None:
        try:
            return ParecSource(sample_rate, chunk_samples)
        except FileNotFoundError:
            pass
    return PortAudioSource(sample_rate, chunk_samples, device=input_device)
