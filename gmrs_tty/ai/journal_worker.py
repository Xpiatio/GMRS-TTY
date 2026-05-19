"""QThread worker that calls Gemini and emits the result."""
from __future__ import annotations

from PySide6.QtCore import Signal

from gmrs_tty.ai.gemini_client import generate_journal
from gmrs_tty.ui.worker_base import WorkerBase


class JournalWorker(WorkerBase):
    finished = Signal(dict)

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

    def _run(self) -> None:
        result = generate_journal(
            self._api_key,
            self._transcript,
            self._callsigns,
            self._timestamp,
        )
        self.finished.emit(result)
