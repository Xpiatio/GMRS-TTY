import datetime
import shutil
import subprocess

import numpy as np
import sounddevice as sd


def _yt_dlp_auth_flags(cookies_from_browser: str = "", cookies_file: str = "") -> list:
    """Return yt-dlp auth flags for the given cookie source (at most one)."""
    if cookies_from_browser:
        return ["--cookies-from-browser", cookies_from_browser]
    if cookies_file:
        return ["--cookies", cookies_file]
    return []


def fetch_youtube_upload_date(
    url: str,
    cookies_from_browser: str = "",
    cookies_file: str = "",
) -> str | None:
    """Return the YouTube upload date as 'YYYY-MM-DD', or None on failure."""
    if not shutil.which("yt-dlp"):
        return None
    try:
        auth = _yt_dlp_auth_flags(cookies_from_browser, cookies_file)
        result = subprocess.run(
            ["yt-dlp", "--print", "%(upload_date)s", "--no-playlist", *auth, url],
            capture_output=True, text=True, timeout=30,
        )
        raw = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if len(raw) == 8 and raw.isdigit():
            return datetime.datetime.strptime(raw, "%Y%m%d").strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


class YouTubeSource:
    """Stream audio from a YouTube URL via yt-dlp + ffmpeg, with auto-loop.

    Audio is decoded in-process to 16 kHz mono float32 PCM; no audio output
    device is touched so nothing plays through speakers. Intended for STT/VAD
    testing without physical microphone access.

    Each time the video ends the stream restarts from the beginning. The
    YouTube CDN URL is re-resolved on every restart because yt-dlp URLs are
    time-limited and would expire on long loops.
    """

    def __init__(
        self,
        url: str,
        sample_rate: int,
        chunk_samples: int,
        cookies_from_browser: str = "",
        cookies_file: str = "",
    ):
        if not shutil.which("yt-dlp"):
            raise FileNotFoundError("yt-dlp binary not on PATH")
        if not shutil.which("ffmpeg"):
            raise FileNotFoundError("ffmpeg binary not on PATH")
        self._url = url
        self._sample_rate = sample_rate
        self._chunk_samples = chunk_samples
        self._bytes_per_chunk = chunk_samples * 4  # float32 = 4 bytes/sample
        self._auth = _yt_dlp_auth_flags(cookies_from_browser, cookies_file)
        self._proc = None
        self._start()

    def _resolve_audio_url(self) -> str:
        result = None
        for fmt in ("bestaudio", "bestaudio/best"):
            result = subprocess.run(
                ["yt-dlp", "-f", fmt, "--get-url", *self._auth, self._url],
                capture_output=True, text=True, timeout=30,
            )
            line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
            if line:
                return line
        stderr = result.stderr.strip() if result else ""
        detail = f": {stderr}" if stderr else ""
        raise IOError(f"yt-dlp returned no audio URL for {self._url!r}{detail}")

    def _start(self):
        audio_url = self._resolve_audio_url()
        self._proc = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", audio_url,
                "-f", "f32le", "-ar", str(self._sample_rate), "-ac", "1",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _read_bytes(self, n: int):
        buf = b""
        while len(buf) < n:
            more = self._proc.stdout.read(n - len(buf))
            if not more:
                return None
            buf += more
        return buf

    def read(self) -> np.ndarray:
        while True:
            raw = self._read_bytes(self._bytes_per_chunk)
            if raw is not None:
                return np.frombuffer(raw, dtype=np.float32).copy()
            try:
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._start()

    def close(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


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


def open_input_source(
    sample_rate,
    chunk_samples,
    input_device=None,
    youtube_url=None,
    youtube_cookies_from_browser="",
    youtube_cookies_file="",
):
    """Open an InputSource for the active capture path.

    Prefers `parec` over PortAudio when the operator has not selected a
    specific input device — PortAudio's PipeWire-via-ALSA bridge can
    silently deliver flat-zero buffers on PipeWire 1.4. Falls back to
    PortAudio if parec isn't on PATH, or when a specific input device
    is configured.

    When input_device is ``"youtube"``, streams audio from youtube_url via
    yt-dlp + ffmpeg without touching any audio output device.
    """
    if input_device == "youtube":
        if not youtube_url:
            raise ValueError("input_device='youtube' requires a youtube_url")
        return YouTubeSource(
            youtube_url,
            sample_rate,
            chunk_samples,
            cookies_from_browser=youtube_cookies_from_browser,
            cookies_file=youtube_cookies_file,
        )
    if input_device is None:
        try:
            return ParecSource(sample_rate, chunk_samples)
        except FileNotFoundError:
            pass
    return PortAudioSource(sample_rate, chunk_samples, device=input_device)
