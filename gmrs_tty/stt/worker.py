import collections
import os
import queue
import threading

import numpy as np
from PySide6.QtCore import QThread, Signal

from gmrs_tty.audio.capture import open_input_source
from gmrs_tty.audio.dsp import bandpass, denoise, make_bandpass_sos
from gmrs_tty.audio.segmentation import pick_cut_index
from gmrs_tty.audio.silence_watchdog import SilenceWatchdog
from gmrs_tty.audio.squelch import SquelchDetector
from gmrs_tty.audio.vad import load_vad_model, make_vad_iterator, reset_vad_state
from gmrs_tty.stt.transcriber import WhisperTranscriber


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

    MODELS_STT_DIR = os.path.join("Models", "STT")

    def __init__(self, input_device=None, whisper_model="small.en", vad_threshold=0.5,
                 whisper=None, vad_model=None, parent=None):
        super().__init__(parent)
        self.input_device = input_device if input_device not in (None, -1) else None
        self.whisper_model_name = whisper_model
        self.whisper_model_path = os.path.join(self.MODELS_STT_DIR, whisper_model)
        self.vad_threshold = float(vad_threshold)
        self._running = True
        self._paused = False
        # Public so MainWindow can hoist them out after the worker stops and
        # hand them back to the next worker — avoids re-loading on every
        # Listen toggle. Either both are None (need to load) or both are set.
        self.whisper = whisper
        self.vad_model = vad_model

    def stop(self):
        self._running = False

    def pause(self):
        """Suspend transcription (e.g., while the app is transmitting) without
        tearing down the Whisper/VAD models or audio stream."""
        self._paused = True

    def resume(self):
        self._paused = False

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
            if self.whisper is None or self.vad_model is None:
                self.status.emit(f"Loading Whisper model from {self.whisper_model_path}...")
                self.whisper = WhisperTranscriber.load(self.whisper_model_path)
                self.vad_model = load_vad_model()
            transcriber = self.whisper
            vad_iter = make_vad_iterator(
                self.vad_model,
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

        if not self._running:
            return

        try:
            source = open_input_source(
                sample_rate=self.SAMPLE_RATE,
                chunk_samples=self.CHUNK_SAMPLES,
                input_device=self.input_device,
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
        rolling = collections.deque(maxlen=self.PRE_BUFFER_CHUNKS)
        collected = []
        in_speech = False
        was_paused = False
        utterance_id = 0
        current_uid = -1
        partials_emitted = 0
        silence_watchdog = SilenceWatchdog(
            int(self.SILENCE_RESET_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES)
        )
        squelch = SquelchDetector(
            open_threshold=self.SQUELCH_OPEN_THRESHOLD,
            open_hold_chunks=self.SQUELCH_OPEN_HOLD_CHUNKS,
            close_hold_chunks=self.SQUELCH_CLOSE_HOLD_CHUNKS,
        )
        squelch_buffer = collections.deque(maxlen=self.SQUELCH_BUFFER_MAX_CHUNKS)
        rolling_target_chunks = int(self.ROLLING_SEGMENT_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES)
        cut_window_chunks = int(self.CUT_WINDOW_S * self.SAMPLE_RATE / self.CHUNK_SAMPLES)
        slice_trigger_chunks = rolling_target_chunks + cut_window_chunks

        try:
            while self._running:
                try:
                    chunk = source.read()
                except Exception as e:
                    self.error.emit(f"Audio read error: {e}")
                    break

                # Emit input level before any pause/VAD gating so a stuck or
                # disconnected mic shows up as a flat-zero meter regardless
                # of transmit state. Peak (not RMS) matches what users expect
                # from a VU-style indicator and reacts fast to short syllables.
                peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
                self.audio_level.emit(min(100, int(peak * 100)))

                if self._paused:
                    if not was_paused:
                        collected = []
                        in_speech = False
                        rolling.clear()
                        squelch_buffer.clear()
                        squelch.reset()
                        reset_vad_state(vad_iter)
                        silence_watchdog.reset()
                        self.status.emit("Paused (transmitting)")
                        was_paused = True
                    continue

                if was_paused:
                    squelch.reset()
                    squelch_buffer.clear()
                    reset_vad_state(vad_iter)
                    silence_watchdog.reset()
                    self.status.emit("Listening...")
                    was_paused = False

                squelch_event = squelch.update(peak)
                if squelch_event == 'opened':
                    squelch_buffer.clear()
                elif squelch_event == 'closed' and not in_speech:
                    # Carrier dropped without VAD ever firing — kerchunk or
                    # noise burst with no human voice. Drop the buffer so it
                    # never reaches the transcriber.
                    squelch_buffer.clear()

                try:
                    speech_dict = vad_iter(chunk, return_seconds=False)
                except Exception as e:
                    print(f"VAD error on chunk: {e}")
                    speech_dict = None

                if speech_dict and 'start' in speech_dict:
                    in_speech = True
                    utterance_id += 1
                    current_uid = utterance_id
                    partials_emitted = 0
                    if squelch.is_open and squelch_buffer:
                        collected = list(squelch_buffer) + [chunk]
                    else:
                        collected = list(rolling) + [chunk]
                    squelch_buffer.clear()
                    silence_watchdog.note_speech()
                elif speech_dict and 'end' in speech_dict:
                    collected.append(chunk)
                    audio = np.concatenate(collected)
                    in_speech = False
                    collected = []
                    silence_watchdog.note_speech()
                    # Drop the trailing piece only when we never emitted any
                    # partial for this utterance — a long monologue's tail can
                    # be much shorter than the kerchunk threshold yet still
                    # carry meaningful last syllables.
                    if partials_emitted > 0 or len(audio) / self.SAMPLE_RATE >= self.MIN_SPEECH_DURATION_S:
                        transcribe_queue.put((current_uid, audio, True))
                elif in_speech:
                    collected.append(chunk)
                    silence_watchdog.note_speech()
                    if len(collected) >= slice_trigger_chunks:
                        cut_idx = pick_cut_index(
                            [float(np.max(np.abs(c))) for c in collected],
                            rolling_target_chunks,
                            rolling_target_chunks + cut_window_chunks,
                        )
                        if cut_idx is None:
                            cut_idx = slice_trigger_chunks - 1
                        slice_chunks = collected[: cut_idx + 1]
                        collected = collected[cut_idx + 1:]
                        audio = np.concatenate(slice_chunks)
                        transcribe_queue.put((current_uid, audio, False))
                        partials_emitted += 1
                elif silence_watchdog.note_silence():
                    # Silero's RNN state drifts after long silence; re-baseline so
                    # the next speech onset still clears the threshold.
                    reset_vad_state(vad_iter)
                    silence_watchdog.reset()

                rolling.append(chunk)
                # Buffer pre-VAD audio while carrier is open so the leading
                # syllables of a transmission survive VAD onset latency. The
                # buffer is consumed (and cleared) the moment VAD fires, and
                # discarded if the carrier drops without VAD ever firing.
                if squelch.is_open and not in_speech:
                    squelch_buffer.append(chunk)
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
        loop never blocks on Whisper. Items are (utterance_id, audio, is_final);
        a None sentinel signals shutdown. Single-threaded by design so
        partials emit in capture order.
        """
        while True:
            job = transcribe_queue.get()
            if job is None:
                break
            uid, audio, is_final = job
            try:
                filtered = bandpass(audio, bandpass_sos)
                denoised = denoise(filtered, self.SAMPLE_RATE, prop_decrease=0.7)
                text = transcriber.transcribe(denoised)
                if text:
                    self.transcribed_segment.emit(uid, text, is_final)
            except Exception as e:
                self.error.emit(f"Transcription error: {e}")
