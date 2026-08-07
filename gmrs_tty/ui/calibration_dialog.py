"""STT calibration wizard dialog.

Four steps (Qt port of Hearthwave's CalibrationDialog.tsx flow):

1. **Intro** — shows the reference passage; the operator arranges for it to
   be read over the air (or reads it into the mic on a loopback source).
2. **Recording** — buffers the raw RX audio that the running STT worker is
   already fanning out via its ``audio_chunk`` signal.
3. **Analyzing** — sweeps gain mode × noise profile × every staged Whisper
   model against the reading, ranked by word-error-rate.
4. **Results** — ranked table; *Apply best* (or the selected row) writes
   ``whisper_model`` / ``stt_gain_mode`` / ``stt_noise_profile`` to config.

Escape cancels cleanly at any step: capture disconnects and is discarded;
an in-flight sweep is orphaned (its signals disconnected) and cleaned up
when its thread finishes — a Whisper sweep cannot be killed mid-decode.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QProgressBar, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from gmrs_tty.stt.calibration import PREAMBLE_TEXT, CalibrationCapture
from gmrs_tty.stt.calibration_worker import CalibrationSweepWorker

# Sweeps orphaned by a cancelled dialog live here until their thread
# finishes; a QThread must never be garbage-collected while running.
_ORPHANED_SWEEPS: list[CalibrationSweepWorker] = []

MIN_CAPTURE_S = 2.0

RESULT_COLUMNS = ("Model", "Gain mode", "Noise profile", "WER")


class CalibrationDialog(QDialog):
    def __init__(self, stt_worker, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrate STT")
        self.setMinimumSize(640, 440)

        self._worker = stt_worker
        self._config = config
        self._capture: CalibrationCapture | None = None
        self._sweep: CalibrationSweepWorker | None = None
        self._results: list[dict] = []
        self._recording_started = 0.0

        root = QVBoxLayout(self)
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_intro_step())
        self._stack.addWidget(self._build_recording_step())
        self._stack.addWidget(self._build_analyzing_step())
        self._stack.addWidget(self._build_results_step())
        root.addWidget(self._stack, 1)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

    # ------------------------------------------------------------------
    # Step builders
    # ------------------------------------------------------------------

    def _heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        # Focusable so each step change lands screen-reader focus on the
        # step heading rather than an arbitrary control.
        label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return label

    def _build_intro_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._intro_heading = self._heading("Step 1 of 4 — The reference passage")
        layout.addWidget(self._intro_heading)
        explain = QLabel(
            "Calibration measures which settings transcribe your radio "
            "best. Have another station read this passage over the air "
            "(or read it yourself on a loopback input), then compare "
            "every combination of model, gain mode, and noise profile "
            "against it."
        )
        explain.setWordWrap(True)
        layout.addWidget(explain)
        passage = QTextEdit()
        passage.setReadOnly(True)
        passage.setPlainText(PREAMBLE_TEXT)
        passage.setAccessibleName("Reference passage")
        passage.setAccessibleDescription(
            "The text the remote station should read aloud during recording."
        )
        layout.addWidget(passage, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._start_btn = QPushButton("&Start recording")
        self._start_btn.setToolTip(
            "Begin buffering incoming radio audio for the calibration reading."
        )
        self._start_btn.setAccessibleName("Start calibration recording")
        self._start_btn.setAccessibleDescription(
            "Starts recording incoming radio audio. Have the passage read "
            "over the air, then stop to analyze."
        )
        self._start_btn.clicked.connect(self._start_recording)
        buttons.addWidget(self._start_btn)
        layout.addLayout(buttons)
        return page

    def _build_recording_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._recording_heading = self._heading("Step 2 of 4 — Recording")
        layout.addWidget(self._recording_heading)
        self._elapsed_label = QLabel("Recording… 0 s")
        self._elapsed_label.setAccessibleName("Recording elapsed time")
        layout.addWidget(self._elapsed_label)
        hint = QLabel(
            "Key up and read the passage now. Click Stop when the "
            "reading is complete (at least a few seconds of audio)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._stop_btn = QPushButton("S&top and analyze")
        self._stop_btn.setToolTip("Finish recording and start the settings sweep.")
        self._stop_btn.setAccessibleName("Stop recording and analyze")
        self._stop_btn.setAccessibleDescription(
            "Stops the recording and analyzes it against every settings "
            "combination. Analysis can take several minutes."
        )
        self._stop_btn.clicked.connect(self._stop_and_analyze)
        buttons.addWidget(self._stop_btn)
        layout.addLayout(buttons)
        return page

    def _build_analyzing_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._analyzing_heading = self._heading("Step 3 of 4 — Analyzing")
        layout.addWidget(self._analyzing_heading)
        self._progress_bar = QProgressBar()
        self._progress_bar.setAccessibleName("Calibration sweep progress")
        layout.addWidget(self._progress_bar)
        self._progress_label = QLabel("Loading models…")
        self._progress_label.setAccessibleName("Calibration sweep status")
        self._progress_label.setWordWrap(True)
        layout.addWidget(self._progress_label)
        layout.addStretch(1)
        return page

    def _build_results_step(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._results_heading = self._heading("Step 4 of 4 — Results")
        layout.addWidget(self._results_heading)
        self._results_table = QTableWidget(0, len(RESULT_COLUMNS))
        self._results_table.setHorizontalHeaderLabels(RESULT_COLUMNS)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._results_table.setAccessibleName("Calibration results")
        self._results_table.setAccessibleDescription(
            "Settings combinations ranked by word error rate, best first. "
            "Select a row and choose Apply selected."
        )
        layout.addWidget(self._results_table, 1)
        self._results_note = QLabel()
        self._results_note.setWordWrap(True)
        layout.addWidget(self._results_note)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._apply_btn = QPushButton("&Apply selected")
        self._apply_btn.setToolTip(
            "Save the selected combination's model, gain mode, and noise "
            "profile to Settings."
        )
        self._apply_btn.setAccessibleName("Apply selected calibration result")
        self._apply_btn.setAccessibleDescription(
            "Writes the selected combination to the configuration. A model "
            "change takes effect the next time Listen starts."
        )
        self._apply_btn.clicked.connect(self._apply_selected)
        buttons.addWidget(self._apply_btn)
        layout.addLayout(buttons)
        return page

    # ------------------------------------------------------------------
    # Flow
    # ------------------------------------------------------------------

    def _go_to(self, index: int, heading: QLabel) -> None:
        self._stack.setCurrentIndex(index)
        heading.setFocus()

    def _start_recording(self) -> None:
        self._capture = CalibrationCapture(sample_rate=self._worker.SAMPLE_RATE)
        self._capture.start()
        self._worker.audio_chunk.connect(self._capture.feed_raw)
        self._recording_started = time.monotonic()
        self._elapsed_label.setText("Recording… 0 s")
        self._elapsed_timer.start()
        self._go_to(1, self._recording_heading)

    def _tick_elapsed(self) -> None:
        elapsed = int(time.monotonic() - self._recording_started)
        self._elapsed_label.setText(f"Recording… {elapsed} s")

    def _disconnect_capture(self) -> None:
        if self._capture is None:
            return
        try:
            self._worker.audio_chunk.disconnect(self._capture.feed_raw)
        except (TypeError, RuntimeError):
            pass
        self._elapsed_timer.stop()

    def _stop_and_analyze(self) -> None:
        self._disconnect_capture()
        audio = self._capture.stop() if self._capture is not None else None
        self._capture = None
        if audio is None or audio.size < int(MIN_CAPTURE_S * self._worker.SAMPLE_RATE):
            self._elapsed_label.setText(
                "No audio captured — key up and read the passage before stopping."
            )
            self._start_btn.setEnabled(True)
            self._go_to(0, self._intro_heading)
            return

        self._progress_bar.setRange(0, 0)  # indeterminate until first combo
        self._progress_label.setText("Loading models…")
        self._go_to(2, self._analyzing_heading)

        self._sweep = CalibrationSweepWorker(
            audio, self._worker.SAMPLE_RATE, self._config.vad_threshold,
        )
        self._sweep.progress.connect(self._on_progress)
        self._sweep.result.connect(self._on_result)
        self._sweep.error.connect(self._on_sweep_error)
        self._sweep.finished.connect(self._sweep.deleteLater)
        self._sweep.start()

    def _on_progress(self, entry: dict) -> None:
        total = int(entry.get("total", 0) or 0)
        index = int(entry.get("index", 0) or 0)
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(index)
        text = (
            f"Combination {index} of {total}: {entry.get('model', '')}, "
            f"{entry.get('gain_mode', '')} gain, noise profile "
            f"{'on' if entry.get('noise_profile') else 'off'} — "
            f"{entry.get('wer', 0.0):.0%} word error rate"
        )
        self._progress_label.setText(text)

    def _on_result(self, results: list) -> None:
        self._results = list(results)
        self._results_table.setRowCount(len(self._results))
        for r, entry in enumerate(self._results):
            values = (
                entry.get("model", ""),
                entry.get("gain_mode", ""),
                "on" if entry.get("noise_profile") else "off",
                f"{entry.get('wer', 0.0):.1%}",
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._results_table.setItem(r, c, item)
        if self._results:
            self._results_table.resizeColumnsToContents()
            self._results_table.selectRow(0)  # recommended = lowest WER
            self._results_note.setText(
                "The top row is the recommended combination. A model change "
                "takes effect the next time Listen starts."
            )
        self._apply_btn.setEnabled(bool(self._results))
        self._go_to(3, self._results_heading)

    def _on_sweep_error(self, msg: str) -> None:
        self._progress_bar.setRange(0, 1)
        self._progress_bar.setValue(0)
        self._progress_label.setText(f"Calibration failed: {msg}")
        self._sweep = None

    def _apply_selected(self) -> None:
        row = self._results_table.currentRow()
        if row < 0 or row >= len(self._results):
            return
        entry = self._results[row]
        self._config["whisper_model"] = entry.get("model", self._config.whisper_model)
        self._config["stt_gain_mode"] = entry.get("gain_mode", "agc")
        self._config["stt_noise_profile"] = bool(entry.get("noise_profile", False))
        self._config.save()
        self.accept()

    # ------------------------------------------------------------------
    # Cancel semantics
    # ------------------------------------------------------------------

    def reject(self) -> None:
        self._disconnect_capture()
        self._capture = None
        if self._sweep is not None and self._sweep.isRunning():
            # A Whisper decode can't be interrupted; orphan the sweep and
            # reap the thread object once it finishes on its own.
            sweep = self._sweep
            for signal in (sweep.progress, sweep.result, sweep.error):
                try:
                    signal.disconnect()
                except (TypeError, RuntimeError):
                    pass
            _ORPHANED_SWEEPS.append(sweep)
            sweep.finished.connect(lambda: _ORPHANED_SWEEPS.remove(sweep))
            self._sweep = None
        super().reject()
