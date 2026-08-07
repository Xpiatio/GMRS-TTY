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
from PySide6.QtCore import QObject, Signal

from gmrs_tty.audio.playback import AudioPlayerThread
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
    ) -> None:
        """Start TTS synthesis. Emits ``tx_busy_changed(True)`` immediately.

        ``voice_path``  — absolute path to the ``.onnx`` Piper model file.
        ``length_scale`` — Piper synthesis speed (1.0 = native, >1 = slower).
        ``output_device`` — PortAudio device index (or -1 for system default).
        """
        if self._tx_busy:
            return
        tts_text = expand_tty_abbreviations(tts_text)
        self._set_busy(True)
        self._output_device = output_device

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
            parent=self,
        )
        self._tts_thread.ready.connect(self._on_tts_synthesized)
        self._tts_thread.error.connect(self._on_tts_synthesis_error)
        self._tts_thread.start()

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

    def _on_tts_synthesized(self, audio, sample_rate: int) -> None:
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
        self._audio_thread.start()

    def _on_tts_synthesis_error(self, msg: str) -> None:
        _log.exception("TTS synthesis error: %s", msg)
        self.chat_message.emit(f"<i>TTS Error: {msg}</i>", theme.palette().error)
        self.stt_resume_requested.emit()
        self._set_busy(False)

    def _on_audio_finished(self) -> None:
        try:
            self.ptt.unkey()
        except Exception:
            pass
        self.stt_resume_requested.emit()
        self._set_busy(False)

    def _on_audio_error(self, error_msg: str) -> None:
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
