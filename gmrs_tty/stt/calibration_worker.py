"""Background sweep runner for the STT calibration wizard.

Qt port of Radio-TTY's ``_run_calibration_sweep`` server handler: sweeps
gain mode × noise profile × every Whisper model staged on disk against the
captured reading, emitting per-combo progress and the ranked results.
"""
from __future__ import annotations

from PySide6.QtCore import Signal

from gmrs_tty.constants import VALID_WHISPER_MODELS
from gmrs_tty.stt import models as stt_models
from gmrs_tty.stt.calibration import run_sweep
from gmrs_tty.ui.worker_base import WorkerBase


class CalibrationSweepWorker(WorkerBase):
    """Runs the calibration sweep off the GUI thread.

    ``progress`` carries one dict per combo ({index, total, model,
    gain_mode, noise_profile, wer, hypothesis}); ``result`` the ranked
    list, best (lowest WER) first. ``WorkerBase.error`` carries failures,
    including the no-models-staged bootstrap hint.
    """

    progress = Signal(dict)
    result = Signal(list)

    def __init__(self, audio, sample_rate: int, vad_threshold: float, parent=None):
        super().__init__(parent)
        self._audio = audio
        self._sample_rate = sample_rate
        self._vad_threshold = float(vad_threshold)

    def _run(self) -> None:
        # Local imports keep the heavy ML deps off the GUI thread.
        from gmrs_tty.audio.vad import load_vad_model, make_vad_iterator
        from gmrs_tty.stt.transcriber import WhisperTranscriber
        from gmrs_tty.stt.worker import STTWorker

        # Sweep only models staged on disk — faster-whisper treats a missing
        # local path as a Hugging Face repo id and tries to download it, and
        # GMRS-TTY never downloads models at runtime.
        models = stt_models.staged_models(
            VALID_WHISPER_MODELS, models_dir=STTWorker.MODELS_STT_DIR
        )
        if not models:
            raise RuntimeError(
                "No Whisper models found in Models/STT. Run "
                "'python bootstrap_models.py' on an internet-connected "
                "machine, then copy Models/ here."
            )

        vad_model = load_vad_model()

        def transcriber_loader(model: str):
            return WhisperTranscriber.load(
                stt_models.ct2_model_path(model, STTWorker.MODELS_STT_DIR)
            )

        def vad_iterator_factory():
            return make_vad_iterator(
                vad_model,
                sample_rate=self._sample_rate,
                threshold=self._vad_threshold,
            )

        results = run_sweep(
            self._audio,
            models=models,
            transcriber_loader=transcriber_loader,
            vad_iterator_factory=vad_iterator_factory,
            progress_cb=self.progress.emit,  # signal emission is thread-safe
        )
        self.result.emit(results)
