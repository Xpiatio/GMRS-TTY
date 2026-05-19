"""TX pipeline controller.

Owns the Piper TTS → AudioPlayerThread → PTT state machine and the
voice model cache. MainWindow keeps the entry points that read UI state
(_transmit_text, transmit_id_only) and delegates the synthesis leg here.

Signals drive all callbacks into MainWindow so the controller has no
import-time dependency on the window or its widgets.
"""
from __future__ import annotations

import os
import traceback

from piper.voice import PiperVoice
from PySide6.QtCore import QObject, Signal

from gmrs_tty.audio.playback import AudioPlayerThread
from gmrs_tty.text.shorthand import expand_tty_abbreviations
from gmrs_tty.tts.synthesizer import TTSSynthesisThread
from gmrs_tty.ui import theme


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
        self._voice_cache: dict = {}
        self._tx_busy = False
        self._tts_thread: TTSSynthesisThread | None = None
        self._audio_thread: AudioPlayerThread | None = None
        self._output_device = -1  # captured from config at synthesize time

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

        if not voice_path or not os.path.exists(voice_path):
            self.chat_message.emit(
                "<i>Error: No valid Piper voice selected. "
                "Please select one in Settings → Configuration.</i>",
                theme.palette().error,
            )
            self._set_busy(False)
            return

        if voice_path not in self._voice_cache:
            try:
                self._voice_cache[voice_path] = PiperVoice.load(voice_path)
            except Exception as exc:
                self.chat_message.emit(
                    f"<i>Failed to load voice model: {exc}</i>",
                    theme.palette().error,
                )
                self._set_busy(False)
                return

        voice = self._voice_cache[voice_path]
        self._tts_thread = TTSSynthesisThread(
            voice, tts_text,
            self.ptt.lead_in_seconds, self.ptt.tail_seconds,
            length_scale=length_scale,
            parent=self,
        )
        self._tts_thread.ready.connect(self._on_tts_synthesized)
        self._tts_thread.error.connect(self._on_tts_synthesis_error)
        self._tts_thread.start()

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
        traceback.print_exc()
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
