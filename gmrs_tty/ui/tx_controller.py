"""TX pipeline controller.

Owns the Piper TTS → AudioPlayerThread → PTT state machine and the
voice model cache. MainWindow keeps the entry points that read UI state
(_transmit_text, transmit_id_only) and delegates the synthesis leg here.

Signals drive all callbacks into MainWindow so the controller has no
import-time dependency on the window or its widgets.
"""
from __future__ import annotations

import logging

from piper.voice import PiperVoice
from PySide6.QtCore import QObject, QTimer, Signal

from gmrs_tty.audio.playback import AudioPlayerThread
from gmrs_tty.text.primer import prepend_primer_word
from gmrs_tty.text.shorthand import expand_tty_abbreviations
from gmrs_tty.tts.synthesizer import TTSSynthesisThread
from gmrs_tty.constants import VOICE_TEST_TEXT, validate_voice_path
from gmrs_tty.ui import theme

_log = logging.getLogger(__name__)


class TXController(QObject):
    """Manages the synthesis → playback → PTT sequence for a single transmission.

    One instance lives for the lifetime of MainWindow. Call
    ``synthesize_and_play`` to start a TX; it is a no-op if a TX is already
    in progress (callers should gate on ``is_busy``).
    """

    # Emitted when the busy state changes. True = TX in progress, False = idle.
    tx_busy_changed = Signal(bool)
    # Errors and warnings that should appear in the chat log.
    chat_message = Signal(str, str)   # (html, color)
    # Ask MainWindow to pause/resume the STT worker around audio playback.
    stt_pause_requested = Signal()
    stt_resume_requested = Signal()

    def __init__(self, ptt, parent=None):
        super().__init__(parent)
        self.ptt = ptt
        self._voice_cache: tuple[str, PiperVoice] | None = None  # (path, model)
        self._tx_busy = False
        self._tts_thread: TTSSynthesisThread | None = None
        self._audio_thread: AudioPlayerThread | None = None
        self._output_device = -1  # captured from config at synthesize time
        self._test_tts_thread: TTSSynthesisThread | None = None
        self._test_audio_thread: AudioPlayerThread | None = None
        # Generation counter guards against a timed-out synthesis delivering
        # late: a QThread running Piper can't be safely killed, so on timeout
        # the generation is bumped and the stale ready/error result discarded.
        self._synth_generation = 0
        # Synthesis timeout — fires only while waiting on Piper; PTT is
        # never keyed on this path.
        self._synth_timer = QTimer(self)
        self._synth_timer.setSingleShot(True)
        self._synth_timer.timeout.connect(self._on_synthesis_timeout)
        self._synth_timeout_s = 0.0
        # Max-TX watchdog — armed at PTT key, hard-stops playback so a
        # runaway transmission can't hold the channel (or violate the
        # radio's own TX timer) indefinitely.
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setSingleShot(True)
        self._watchdog_timer.timeout.connect(self._on_watchdog_fired)
        self._max_tx_s = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def is_busy(self) -> bool:
        return self._tx_busy

    def synthesize_and_play(
        self,
        tts_text: str,
        *,
        voice_path: str,
        length_scale: float,
        output_device,
        tx_conditioning: bool = False,
        vox_primer_ms: float = 0.0,
        vox_primer_word: str = "",
        synthesis_timeout_s: float = 0.0,
        max_tx_s: float = 0.0,
    ) -> None:
        """Start TTS synthesis. Emits ``tx_busy_changed(True)`` immediately.

        ``voice_path``  — absolute path to the ``.onnx`` Piper model file.
        ``length_scale`` — Piper synthesis speed (1.0 = native, >1 = slower).
        ``output_device`` — PortAudio device index (or -1 for system default).
        ``tx_conditioning`` — band-limit/compress/normalize speech for radio.
        ``vox_primer_ms`` — VOX priming tone length (0 disables).
        ``vox_primer_word`` — spoken priming word prefixed to the text ("" disables).
        ``synthesis_timeout_s`` — abort if Piper takes longer (0 disables);
        PTT is never keyed on this path.
        ``max_tx_s`` — hard cap on keyed transmission length (0 disables).
        """
        if self._tx_busy:
            return
        tts_text = expand_tty_abbreviations(tts_text)
        tts_text = prepend_primer_word(tts_text, vox_primer_word)
        self._set_busy(True)
        self._output_device = output_device
        self._synth_timeout_s = float(synthesis_timeout_s)
        self._max_tx_s = float(max_tx_s)

        if not validate_voice_path(voice_path):
            self.chat_message.emit(
                "<i>Error: No valid Piper voice selected. "
                "Please select one in Settings → Configuration.</i>",
                theme.palette().error,
            )
            self._set_busy(False)
            return

        if self._voice_cache is None or self._voice_cache[0] != voice_path:
            try:
                self._voice_cache = (voice_path, PiperVoice.load(voice_path))
            except Exception as exc:
                self.chat_message.emit(
                    f"<i>Failed to load voice model: {exc}</i>",
                    theme.palette().error,
                )
                self._set_busy(False)
                return

        voice = self._voice_cache[1]
        self._tts_thread = TTSSynthesisThread(
            voice, tts_text,
            self.ptt.lead_in_seconds, self.ptt.tail_seconds,
            length_scale=length_scale,
            condition=tx_conditioning,
            vox_primer_ms=vox_primer_ms,
            parent=self,
        )
        generation = self._synth_generation
        self._tts_thread.ready.connect(
            lambda audio, sr: self._on_tts_synthesized(audio, sr, generation)
        )
        self._tts_thread.error.connect(
            lambda msg: self._on_tts_synthesis_error(msg, generation)
        )
        if self._synth_timeout_s > 0:
            self._synth_timer.start(int(self._synth_timeout_s * 1000))
        self._tts_thread.start()

    def abort_tx(self) -> None:
        """Operator kill switch. Hard-stops an in-progress transmission:
        during playback the audio device is stopped (PTT unkeys via the
        normal finished path); during synthesis the pending result is
        discarded and PTT is never keyed. No-op when idle."""
        if not self._tx_busy:
            return
        if self._audio_thread is not None and self._audio_thread.isRunning():
            self.chat_message.emit(
                "<i>TX aborted by operator.</i>", theme.palette().error,
            )
            self._stop_playback()
        else:
            self._abandon_synthesis("<i>TX aborted by operator.</i>")

    def test_voice(self, voice_path: str, length_scale: float, output_device: int, done_cb) -> None:
        """Synthesize a short test sample and play it back (no PTT keying).

        Reuses the voice cache so the dialog test is free if the same voice
        is already loaded. Calls ``done_cb()`` on completion or error.
        """
        if self._tx_busy:
            _log.warning("test_voice called while TX is in progress; ignoring.")
            done_cb()
            return
        if self._voice_cache is None or self._voice_cache[0] != voice_path:
            try:
                self._voice_cache = (voice_path, PiperVoice.load(voice_path))
            except Exception as exc:
                self.chat_message.emit(
                    f"<i>Failed to load voice model: {exc}</i>",
                    theme.palette().error,
                )
                done_cb()
                return

        voice = self._voice_cache[1]
        self._test_tts_thread = TTSSynthesisThread(
            voice, VOICE_TEST_TEXT, 0.0, 0.0,
            length_scale=length_scale, parent=self,
        )

        def on_ready(audio, sample_rate: int) -> None:
            if audio is None or len(audio) == 0:
                done_cb()
                return
            self._test_audio_thread = AudioPlayerThread(audio, sample_rate, device=output_device)
            self._test_audio_thread.finished.connect(done_cb)
            self._test_audio_thread.error.connect(lambda _: done_cb())
            self._test_audio_thread.start()

        self._test_tts_thread.ready.connect(on_ready)
        self._test_tts_thread.error.connect(lambda _: done_cb())
        self._test_tts_thread.start()

    def close_ptt(self) -> None:
        """Release the PTT device. Call from MainWindow.closeEvent."""
        try:
            self.ptt.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Private callbacks
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._tx_busy = busy
        self.tx_busy_changed.emit(busy)

    def _abandon_synthesis(self, chat_html: str) -> None:
        """Discard the in-flight synthesis: bump the generation so its late
        ready/error is ignored, and release the busy state. The Piper thread
        can't be killed safely, so it is left to finish and be discarded."""
        self._synth_generation += 1
        self._synth_timer.stop()
        self.chat_message.emit(chat_html, theme.palette().error)
        self._set_busy(False)

    def _on_synthesis_timeout(self) -> None:
        if not self._tx_busy:
            return
        if self._audio_thread is not None and self._audio_thread.isRunning():
            return  # synthesis already delivered; the watchdog owns playback
        _log.warning("TTS synthesis exceeded %.0fs — aborting TX", self._synth_timeout_s)
        self._abandon_synthesis(
            f"<i>TX aborted: TTS synthesis exceeded {self._synth_timeout_s:.0f}s.</i>"
        )

    def _stop_playback(self) -> None:
        """Stop the audio device; sd.stop() unblocks sd.wait() inside
        AudioPlayerThread.run so the normal finished path unkeys PTT.
        sd.stop() is process-global, but TX is serialized through this
        controller and callers gate on _tx_busy, so only our stream dies."""
        import sounddevice as sd
        sd.stop()

    def _on_watchdog_fired(self) -> None:
        if not self._tx_busy:
            return
        _log.warning("TX exceeded max duration (%.0fs) — forcing PTT unkey", self._max_tx_s)
        self.chat_message.emit(
            f"<i>TX aborted: exceeded {self._max_tx_s:.0f}s limit.</i>",
            theme.palette().error,
        )
        self._stop_playback()

    def _on_tts_synthesized(self, audio, sample_rate: int, generation: int) -> None:
        if generation != self._synth_generation:
            return  # abandoned by timeout or operator abort
        self._synth_timer.stop()
        if audio is None or len(audio) == 0:
            self.chat_message.emit(
                "<i>Warning: Piper generated no audio.</i>",
                theme.palette().error,
            )
            self._set_busy(False)
            return

        self._audio_thread = AudioPlayerThread(
            audio, sample_rate, device=self._output_device
        )
        self._audio_thread.finished.connect(self._on_audio_finished)
        self._audio_thread.error.connect(self._on_audio_error)
        self.stt_pause_requested.emit()
        try:
            self.ptt.key()
        except Exception as exc:
            self.chat_message.emit(
                f"<i>PTT key failed: {exc}</i>",
                theme.palette().error,
            )
        if self._max_tx_s > 0:
            self._watchdog_timer.start(int(self._max_tx_s * 1000))
        self._audio_thread.start()

    def _on_tts_synthesis_error(self, msg: str, generation: int) -> None:
        if generation != self._synth_generation:
            return  # abandoned by timeout or operator abort
        self._synth_timer.stop()
        _log.exception("TTS synthesis error: %s", msg)
        self.chat_message.emit(f"<i>TTS Error: {msg}</i>", theme.palette().error)
        self.stt_resume_requested.emit()
        self._set_busy(False)

    def _on_audio_finished(self) -> None:
        self._watchdog_timer.stop()
        try:
            self.ptt.unkey()
        except Exception:
            pass
        self.stt_resume_requested.emit()
        self._set_busy(False)

    def _on_audio_error(self, error_msg: str) -> None:
        self._watchdog_timer.stop()
        try:
            self.ptt.unkey()
        except Exception:
            pass
        self.stt_resume_requested.emit()
        self.chat_message.emit(
            f"<i>TTS Error: {error_msg}</i>",
            theme.palette().error,
        )
        self._set_busy(False)
