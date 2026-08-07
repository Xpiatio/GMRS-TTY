import logging
import os
import queue
import threading
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QThread, Signal

from gmrs_tty.audio.capture import open_input_source
from gmrs_tty.audio.dsp import lowpass, make_bandpass_sos, make_lowpass_sos
from gmrs_tty.audio.squelch import SquelchDetector
from gmrs_tty.audio.vad import load_vad_model, make_vad_iterator
from gmrs_tty.constants import GAIN_MODES
from gmrs_tty.stt.preprocess import preprocess_segment
from gmrs_tty.stt.segmenter import SpeechSegmenter
from gmrs_tty.stt.transcriber import WhisperTranscriber

_log = logging.getLogger(__name__)


@dataclass
class ModelCache:
    """Loaded Whisper and VAD objects hoisted out of a stopped STTWorker.

    Passed back into the next STTWorker so the multi-second model load is
    skipped on every Listen toggle.  None means the models have not been
    loaded yet or the model name changed.
    """
    whisper: object
    vad_model: object
    model_name: str


class STTWorker(QThread):
    """Captures mic audio, gates on Silero VAD, transcribes speech with faster-whisper.

    Orchestrates four single-purpose collaborators (capture / VAD / DSP /
    transcriber). Owns the run-loop state machine and the Qt signals that
    feed the main UI. The collaborators are lazy-imported (the heavy ML
    deps don't load until Listen is pressed).

    Long utterances are streamed: every ~5 s of continuous speech, the
    capture loop slices off the buffer at a quiet point (so cuts land
    between words, not mid-syllable) and hands the segment to a background
    transcription thread. Partial transcripts emit in order under a shared
    `utterance_id` so the UI can grow a single chat line as the
    transmission progresses, instead of waiting for the operator to unkey.
    """
    # (utterance_id, text, is_final). Partial segments emit with is_final=False
    # so the UI can grow a single chat line; the last segment of an utterance
    # emits with is_final=True so consumers can close the line and run any
    # full-text passes (callsign scan, etc.).
    transcribed_segment = Signal(int, str, bool)
    error = Signal(str)
    status = Signal(str)
    # Peak amplitude per captured chunk on a 0-100 scale, emitted live so
    # the UI can show a level meter — useful for confirming the mic / radio
    # audio is actually reaching the app during hardware setup.
    audio_level = Signal(int)
    # Read-only fan-out of the raw float32 capture chunk for downstream
    # consumers that want the time-domain signal (e.g. the rolling
    # spectrometer). Emitted on every captured chunk, including while
    # paused — pause is for VAD/STT correctness, not visualization. The
    # receiver MUST treat the array as read-only and copy if it needs to
    # retain it; a slow consumer must drop frames rather than backpressure
    # this loop or VAD/STT will starve.
    audio_chunk = Signal(object)
    # Capture-loop events the spectrometer overlays as vertical markers:
    # 'vad_start' / 'vad_end' / 'squelch_opened' / 'squelch_closed'.
    capture_event = Signal(str)

    SAMPLE_RATE = 16000
    CHUNK_SAMPLES = 512   # required by Silero VAD at 16kHz
    PRE_BUFFER_CHUNKS = 10  # ~320ms of pre-speech context (fallback when no squelch open)
    MIN_SPEECH_DURATION_S = 0.4  # drops kerchunks / blips on the *first* segment of an utterance
    BANDPASS_LOW_HZ = 300   # narrowband-FM voice floor
    BANDPASS_HIGH_HZ = 3000  # narrowband-FM voice ceiling
    SILENCE_RESET_S = 30.0  # re-baseline VAD after this much continuous silence
    # Squelch-open pre-trigger: captures audio from carrier-open until VAD
    # fires, so leading syllables clipped by VAD onset latency survive into
    # transcription. Buffer is discarded if the carrier drops without voice.
    SQUELCH_OPEN_THRESHOLD = 0.05  # peak amplitude (0..1) on raw int16-normalized chunks
    SQUELCH_OPEN_HOLD_CHUNKS = 2   # ~64ms above threshold = carrier open
    SQUELCH_CLOSE_HOLD_CHUNKS = 16  # ~500ms below threshold = carrier dropped
    SQUELCH_BUFFER_MAX_CHUNKS = 64  # ~2s cap on pre-VAD capture
    # Streaming-transcription cut points: slice when the in-speech buffer
    # passes ROLLING_SEGMENT_S, choosing the lowest-peak chunk in the next
    # CUT_WINDOW_S so cuts land in a natural pause between words.
    ROLLING_SEGMENT_S = 5.0
    CUT_WINDOW_S = 0.5
    # Squelch-derived noise profile: while the squelch is closed the channel
    # is pure noise floor. Quiet chunks are buffered and snapshotted at each
    # utterance start as the denoise stage's stationary noise estimate. The
    # buffer/minimum sizes give >= ~31 STFT frames for a stable threshold.
    NOISE_BUFFER_S = 2.0
    NOISE_MIN_S = 0.5

    MODELS_STT_DIR = os.path.join("Models", "STT")

    def __init__(self, input_device=None, whisper_model="small.en", vad_threshold=0.5,
                 model_cache: "ModelCache | None" = None, system_monitor_sink="",
                 saved_phrases=(), debug_capture=False, debug_dir="",
                 gain_mode="agc", noise_profile=False,
                 parent=None):
        super().__init__(parent)
        self.input_device = input_device if input_device not in (None, -1) else None
        self.system_monitor_sink = system_monitor_sink or ""
        self.whisper_model_name = whisper_model
        self.whisper_model_path = os.path.join(self.MODELS_STT_DIR, whisper_model)
        self.vad_threshold = float(vad_threshold)
        self.saved_phrases: "list[str]" = list(saved_phrases)
        self.debug_capture = bool(debug_capture)
        self.debug_dir = debug_dir or ""
        self._debug_recorder = None
        self.gain_mode = gain_mode if gain_mode in GAIN_MODES else "agc"
        self.noise_profile = bool(noise_profile)
        self._running = True
        self._paused = False
        self._model_cache: ModelCache | None = model_cache

    @property
    def model_cache(self) -> "ModelCache | None":
        return self._model_cache

    def stop(self):
        self._running = False

    def pause(self):
        """Suspend transcription (e.g., while the app is transmitting) without
        tearing down the Whisper/VAD models or audio stream."""
        self._paused = True

    def resume(self):
        self._paused = False

    def update_phrases(self, phrases: "list[str]") -> None:
        """Update the Whisper initial_prompt without restarting the worker.

        Safe to call from any thread — the GIL protects the string assignment
        inside WhisperTranscriber.update_prompt().
        """
        self.saved_phrases = list(phrases)
        if self._model_cache is not None:
            self._model_cache.whisper.update_prompt(self.saved_phrases)

    def run(self):
        if not self._running:
            return

        if not os.path.isdir(self.whisper_model_path):
            self.error.emit(
                f"Whisper model not found at '{self.whisper_model_path}'. "
                f"Run 'python bootstrap_models.py --model {self.whisper_model_name}' on an "
                f"internet-connected machine, then copy Models/ here. "
                f"GMRS-TTY does not download models at runtime."
            )
            return

        try:
            if self._model_cache is None or self._model_cache.model_name != self.whisper_model_name:
                self.status.emit(f"Loading Whisper model from {self.whisper_model_path}...")
                whisper = WhisperTranscriber.load(
                    self.whisper_model_path, saved_phrases=self.saved_phrases,
                )
                vad_model = load_vad_model()
                self._model_cache = ModelCache(
                    whisper=whisper,
                    vad_model=vad_model,
                    model_name=self.whisper_model_name,
                )
            transcriber = self._model_cache.whisper
            # The cached transcriber may carry a stale prompt from the
            # previous Listen session; contacts/phrases can change between.
            transcriber.update_prompt(self.saved_phrases)
            vad_iter = make_vad_iterator(
                self._model_cache.vad_model,
                sample_rate=self.SAMPLE_RATE,
                threshold=self.vad_threshold,
            )
            bandpass_sos = make_bandpass_sos(
                self.SAMPLE_RATE,
                self.BANDPASS_LOW_HZ,
                self.BANDPASS_HIGH_HZ,
            )
        except Exception as e:
            self.error.emit(f"Failed to initialize STT models: {e}")
            return

        # Construct once; failure is non-fatal (fall back to unfiltered path).
        try:
            lowpass_sos = make_lowpass_sos(self.SAMPLE_RATE, cutoff_hz=2700)
        except Exception as e:
            _log.error("Failed to construct lowpass filter: %s — proceeding without LPF", e)
            lowpass_sos = None

        if not self._running:
            return

        try:
            source = open_input_source(
                sample_rate=self.SAMPLE_RATE,
                chunk_samples=self.CHUNK_SAMPLES,
                input_device=self.input_device,
                system_monitor_sink=self.system_monitor_sink,
            )
        except Exception as e:
            self.error.emit(f"Failed to open input device: {e}")
            return

        transcribe_queue = queue.Queue()
        transcribe_thread = threading.Thread(
            target=self._transcription_loop,
            args=(transcribe_queue, transcriber, bandpass_sos),
            daemon=True,
        )
        transcribe_thread.start()

        self.status.emit("Listening...")
        squelch = SquelchDetector(
            open_threshold=self.SQUELCH_OPEN_THRESHOLD,
            open_hold_chunks=self.SQUELCH_OPEN_HOLD_CHUNKS,
            close_hold_chunks=self.SQUELCH_CLOSE_HOLD_CHUNKS,
        )
        segmenter = SpeechSegmenter(
            vad_iter, squelch,
            sample_rate=self.SAMPLE_RATE,
            rolling_target_chunks=int(self.ROLLING_SEGMENT_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES),
            cut_window_chunks=int(self.CUT_WINDOW_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES),
            pre_buffer_chunks=self.PRE_BUFFER_CHUNKS,
            squelch_buffer_max_chunks=self.SQUELCH_BUFFER_MAX_CHUNKS,
            min_speech_duration_s=self.MIN_SPEECH_DURATION_S,
            silence_reset_chunks=int(self.SILENCE_RESET_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES),
            noise_profile_chunks=(
                int(self.NOISE_BUFFER_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES)
                if self.noise_profile else 0
            ),
            noise_min_samples=int(self.NOISE_MIN_S * self.SAMPLE_RATE),
        )
        was_paused = False

        if self.debug_capture and self.debug_dir:
            try:
                from gmrs_tty.stt.debug_capture import UtteranceDebugRecorder
                self._debug_recorder = UtteranceDebugRecorder(
                    self.debug_dir,
                    sample_rate=self.SAMPLE_RATE,
                    pre_roll_chunks=self.PRE_BUFFER_CHUNKS,
                    meta={
                        "whisper_model": self.whisper_model_name,
                        "vad_threshold": self.vad_threshold,
                        "squelch_open_threshold": self.SQUELCH_OPEN_THRESHOLD,
                    },
                )
            except Exception as e:
                _log.warning("Debug capture disabled (init failed): %s", e)
                self._debug_recorder = None
        recorder = self._debug_recorder

        try:
            while self._running:
                try:
                    chunk = source.read()
                except Exception as e:
                    self.error.emit(f"Audio read error: {e}")
                    break

                # Low-pass the chunk for squelch/VAD processing; the raw chunk
                # is kept for the level meter fan-out and waterfall so the
                # operator sees the true unfiltered signal.
                chunk_for_vad = (
                    lowpass(np.asarray(chunk, dtype=np.float32), lowpass_sos)
                    if lowpass_sos is not None else chunk
                )
                # Emit input level before any pause/VAD gating so a stuck or
                # disconnected mic shows up as a flat-zero meter regardless
                # of transmit state. Peak (not RMS) matches what users expect
                # from a VU-style indicator and reacts fast to short syllables.
                peak = float(np.max(np.abs(chunk_for_vad))) if chunk_for_vad.size else 0.0
                self.audio_level.emit(min(100, int(peak * 100)))
                # Fan the raw chunk out to any spectrometer consumer. Done
                # before the pause / VAD branches so the waterfall keeps
                # scrolling during TX (the operator wants to see their own
                # carrier and any breakthrough RX while transmitting).
                # Receivers are responsible for dropping frames if they
                # can't keep up — this emit must stay non-blocking.
                self.audio_chunk.emit(chunk)

                if self._paused:
                    if not was_paused:
                        segmenter.reset()
                        self.status.emit("Paused (transmitting)")
                        was_paused = True
                    continue

                if was_paused:
                    segmenter.reset()
                    self.status.emit("Listening...")
                    was_paused = False

                if recorder is not None:
                    recorder.feed_raw(np.asarray(chunk, dtype=np.float32))
                segments, events = segmenter.feed(chunk_for_vad, peak)
                for event in events:
                    self.capture_event.emit(event)
                    if recorder is not None:
                        recorder.on_capture_event(event)
                for uid, audio, is_final in segments:
                    noise_clip = segmenter.utterance_noise_clip if self.noise_profile else None
                    if recorder is not None:
                        recorder.on_segment(uid, audio, is_final)
                        if noise_clip is not None:
                            recorder.on_noise_clip(uid, noise_clip)
                    transcribe_queue.put((uid, audio, is_final, noise_clip))
        finally:
            try:
                source.close()
            except Exception:
                pass
            transcribe_queue.put(None)
            transcribe_thread.join(timeout=15)
            self.status.emit("Stopped listening")

    def _transcription_loop(self, transcribe_queue, transcriber, bandpass_sos):
        """Drain the segmentation queue on a background thread so the capture
        loop never blocks on Whisper. Items are (utterance_id, audio,
        is_final, noise_clip); a None sentinel signals shutdown.
        Single-threaded by design so partials emit in capture order.
        """
        while True:
            job = transcribe_queue.get()
            if job is None:
                break
            uid, audio, is_final, noise_clip = job
            recorder = self._debug_recorder
            try:
                processed = preprocess_segment(
                    audio, self.SAMPLE_RATE, bandpass_sos, gain_mode=self.gain_mode,
                    noise_clip=noise_clip,
                )
                if recorder is not None:
                    recorder.on_processed(uid, processed)
                text = transcriber.transcribe(processed)
                if text:
                    if recorder is not None:
                        recorder.on_transcript(uid, text, partial=not is_final)
                    self.transcribed_segment.emit(uid, text, is_final)
            except Exception as e:
                self.error.emit(f"Transcription error: {e}")
            finally:
                if recorder is not None and is_final:
                    recorder.finalize(uid)
