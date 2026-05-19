"""QThread worker that calls Gemini and emits the result."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from gmrs_tty.ai.gemini_client import GeminiError, generate_journal


class JournalWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(
        self,
        api_key: str,
        transcript: str,
        callsigns: list[str],
        timestamp: str,
        parent=None,
    ):
        super().__init__(parent)
        self._api_key = api_key
        self._transcript = transcript
        self._callsigns = callsigns
        self._timestamp = timestamp

    def run(self):
        try:
            result = generate_journal(
                self._api_key,
                self._transcript,
                self._callsigns,
                self._timestamp,
            )
            self.finished.emit(result)
        except GeminiError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"Unexpected error: {exc}")
