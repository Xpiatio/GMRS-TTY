from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QMessageBox

from gmrs_tty.ai.journal_worker import JournalWorker
from gmrs_tty.persistence.journal import save_journal
from gmrs_tty.ui.journal_dialog import JournalDialog

if TYPE_CHECKING:
    from gmrs_tty.ui.main_window import MainWindow


class JournalController(QObject):
    """Owns journal generation lifecycle: worker, UI button states, file save."""

    def __init__(self, window: "MainWindow", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._worker: JournalWorker | None = None

    def open_dialog(self) -> None:
        # Modeless with no stored reference — Qt owns the lifetime and deletes
        # the widget on close.
        dlg = JournalDialog(parent=self._window)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()
        dlg.raise_()

    def generate(self) -> None:
        window = self._window
        api_key = window.config.gemini_api_key
        if not api_key:
            QMessageBox.information(
                window,
                "Gemini API Key Required",
                "No Gemini API key is configured.\n\n"
                "Add your key under Settings → Configuration → Gemini API Key.",
            )
            return

        transcript = window.chat_display.toPlainText().strip()
        if not transcript:
            QMessageBox.information(
                window,
                "No Transcript",
                "The conversation log is empty. Start a listening session before "
                "generating a journal entry.",
            )
            return

        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                window,
                "Already Generating",
                "A journal entry is already being generated. Please wait.",
            )
            return

        callsigns = window.attendance_panel.callsigns() if window.attendance_panel else []
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._set_ui_enabled(False)
        window.statusBar().showMessage("Generating journal entry via Gemini…")

        self._worker = JournalWorker(api_key, transcript, callsigns, timestamp, parent=window)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def cleanup(self) -> None:
        """Disconnect and drain the in-flight worker. Called from closeEvent."""
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._worker.wait(300)
        self._worker = None

    # ---- Private -----------------------------------------------------------

    def _on_finished(self, result: dict) -> None:
        window = self._window
        transcript = window.chat_display.toPlainText().strip()
        title = result.get("title", "Untitled Session")
        summary = result.get("summary", "")
        ai_locs = result.get("callsigns_locations")
        if not isinstance(ai_locs, list):
            ai_locs = []

        # Merge: AI result has locations; attendance panel is ground truth for
        # which callsigns were actually heard.
        panel_callsigns = set(window.attendance_panel.callsigns() if window.attendance_panel else [])
        ai_known = {c.get("callsign", "") for c in ai_locs}
        merged = list(ai_locs) + [
            {"callsign": cs, "location": "Not stated"}
            for cs in panel_callsigns if cs and cs not in ai_known
        ]
        try:
            path = save_journal(title, summary, merged, transcript)
            window.statusBar().showMessage(f"Journal saved: {path}", 5000)
        except OSError as exc:
            window.statusBar().clearMessage()
            QMessageBox.warning(window, "Journal Save Error", f"Could not save journal:\n{exc}")
        self._reset_ui()

    def _on_error(self, message: str) -> None:
        window = self._window
        window.statusBar().clearMessage()
        QMessageBox.warning(
            window,
            "Journal Generation Failed",
            f"Gemini returned an error:\n\n{message}",
        )
        self._reset_ui()

    def _reset_ui(self) -> None:
        self._set_ui_enabled(True)
        self._worker = None

    def _set_ui_enabled(self, enabled: bool) -> None:
        window = self._window
        window._generate_journal_action.setEnabled(enabled)
        window.journal_icon_btn.setEnabled(enabled)
        window.generate_journal_btn.setEnabled(enabled)
