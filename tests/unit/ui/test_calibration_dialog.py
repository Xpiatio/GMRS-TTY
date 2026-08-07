"""CalibrationDialog — step flow, progress rendering, apply semantics."""
import os
from unittest.mock import MagicMock

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.config import AppConfig  # noqa: E402
from gmrs_tty.ui.calibration_dialog import CalibrationDialog  # noqa: E402

SR = 16000


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeWorker(QObject):
    """Stands in for STTWorker: just the audio_chunk fan-out + SAMPLE_RATE."""
    audio_chunk = Signal(object)
    SAMPLE_RATE = SR


def _make_dialog(qapp, config=None):
    cfg = AppConfig(config or {})
    cfg.save = MagicMock()
    return CalibrationDialog(_FakeWorker(), cfg)


class TestStepFlow:
    def test_starts_on_intro(self, qapp):
        dlg = _make_dialog(qapp)
        assert dlg._stack.currentIndex() == 0

    def test_start_recording_advances_and_buffers_audio(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._start_recording()
        assert dlg._stack.currentIndex() == 1
        dlg._worker.audio_chunk.emit(np.zeros(512, dtype=np.float32))
        assert dlg._capture._samples == 512

    def test_too_short_capture_returns_to_intro(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._start_recording()
        dlg._worker.audio_chunk.emit(np.zeros(512, dtype=np.float32))
        dlg._stop_and_analyze()
        assert dlg._stack.currentIndex() == 0
        assert "No audio captured" in dlg._elapsed_label.text()
        assert dlg._sweep is None

    def test_enough_audio_starts_sweep_and_advances(self, qapp, monkeypatch):
        started = []
        import gmrs_tty.ui.calibration_dialog as mod

        class _FakeSweep(QObject):
            progress = Signal(dict)
            result = Signal(list)
            error = Signal(str)
            finished = Signal()

            def __init__(self, audio, sr, vad):
                super().__init__()
                started.append(len(audio))

            def start(self):
                pass

            def deleteLater(self):
                pass

        monkeypatch.setattr(mod, "CalibrationSweepWorker", _FakeSweep)
        dlg = _make_dialog(qapp)
        dlg._start_recording()
        for _ in range(100):  # > 2 s at 16 kHz in 512-sample chunks
            dlg._worker.audio_chunk.emit(np.zeros(512, dtype=np.float32))
        dlg._stop_and_analyze()
        assert dlg._stack.currentIndex() == 2
        assert started == [100 * 512]


class TestProgressAndResults:
    def test_progress_updates_bar_and_text(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._on_progress({
            "index": 3, "total": 12, "model": "small.en",
            "gain_mode": "agc", "noise_profile": True, "wer": 0.25,
        })
        assert dlg._progress_bar.value() == 3
        assert dlg._progress_bar.maximum() == 12
        assert "Combination 3 of 12" in dlg._progress_label.text()

    def test_results_populate_table_with_best_row_selected(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._on_result([
            {"model": "small.en", "gain_mode": "agc",
             "noise_profile": False, "wer": 0.10},
            {"model": "tiny.en", "gain_mode": "off",
             "noise_profile": True, "wer": 0.42},
        ])
        assert dlg._stack.currentIndex() == 3
        assert dlg._results_table.rowCount() == 2
        assert dlg._results_table.currentRow() == 0
        assert dlg._results_table.item(0, 0).text() == "small.en"
        assert dlg._results_table.item(1, 3).text() == "42.0%"

    def test_sweep_error_shown(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._on_sweep_error("No Whisper models found in Models/STT.")
        assert "Calibration failed" in dlg._progress_label.text()


class _FakeSweep:
    """Stand-in for CalibrationSweepWorker: real Qt signals, no thread."""
    def __init__(self, running=True):
        from PySide6.QtCore import QObject, Signal

        class _Sweep(QObject):
            progress = Signal(dict)
            result = Signal(list)
            error = Signal(str)
            finished = Signal()

        self._obj = _Sweep()
        self._running = running
        # The dialog subscribes to all three before starting the thread; mirror
        # that so _detach_sweep's disconnect has something to remove.
        self.seen = []
        for signal in (self._obj.progress, self._obj.result, self._obj.error):
            signal.connect(self.seen.append)

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def isRunning(self):
        return self._running


class TestSweepDetach:
    """A running QThread must never lose its last reference — the sweep object
    has no Qt parent, so both the cancel and the error path have to park it."""

    def test_error_path_parks_a_still_running_sweep(self, qapp):
        from gmrs_tty.ui import calibration_dialog as mod

        dlg = _make_dialog(qapp)
        sweep = _FakeSweep(running=True)
        dlg._sweep = sweep
        try:
            dlg._on_sweep_error("boom")
            assert dlg._sweep is None
            assert sweep in mod._ORPHANED_SWEEPS
            # Reaped once the thread reports it is done.
            sweep.finished.emit()
            assert sweep not in mod._ORPHANED_SWEEPS
        finally:
            if sweep in mod._ORPHANED_SWEEPS:
                mod._ORPHANED_SWEEPS.remove(sweep)

    def test_finished_sweep_is_not_parked(self, qapp):
        from gmrs_tty.ui import calibration_dialog as mod

        dlg = _make_dialog(qapp)
        sweep = _FakeSweep(running=False)
        dlg._sweep = sweep
        dlg._on_sweep_error("boom")
        assert dlg._sweep is None
        assert sweep not in mod._ORPHANED_SWEEPS

    def test_reject_parks_a_running_sweep_and_disconnects_it(self, qapp):
        from gmrs_tty.ui import calibration_dialog as mod

        dlg = _make_dialog(qapp)
        sweep = _FakeSweep(running=True)
        seen = []
        sweep.result.connect(seen.append)
        dlg._sweep = sweep
        try:
            dlg.reject()
            assert dlg._sweep is None
            assert sweep in mod._ORPHANED_SWEEPS
            sweep.result.emit([{"model": "small.en"}])
            assert seen == []   # disconnected, so a late result is dropped
        finally:
            if sweep in mod._ORPHANED_SWEEPS:
                mod._ORPHANED_SWEEPS.remove(sweep)

    def test_double_release_is_safe(self, qapp):
        from gmrs_tty.ui import calibration_dialog as mod

        sweep = _FakeSweep(running=True)
        mod._ORPHANED_SWEEPS.append(sweep)
        mod._release_sweep(sweep)
        mod._release_sweep(sweep)   # must not raise ValueError
        assert sweep not in mod._ORPHANED_SWEEPS

    def test_detach_with_no_sweep_is_noop(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._sweep = None
        dlg._detach_sweep()
        assert dlg._sweep is None


class TestApply:
    def test_apply_writes_selected_combo_and_saves(self, qapp):
        dlg = _make_dialog(qapp, {"whisper_model": "tiny.en"})
        dlg._on_result([
            {"model": "small.en", "gain_mode": "rms",
             "noise_profile": True, "wer": 0.10},
        ])
        dlg._apply_selected()
        assert dlg._config["whisper_model"] == "small.en"
        assert dlg._config["stt_gain_mode"] == "rms"
        assert dlg._config["stt_noise_profile"] is True
        dlg._config.save.assert_called_once()


class TestCancel:
    def test_reject_during_recording_disconnects_capture(self, qapp):
        dlg = _make_dialog(qapp)
        dlg._start_recording()
        dlg.reject()
        assert dlg._capture is None
        # Emitting after reject must not raise or buffer anywhere.
        dlg._worker.audio_chunk.emit(np.zeros(512, dtype=np.float32))
