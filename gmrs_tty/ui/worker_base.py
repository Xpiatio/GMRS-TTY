"""Thin QThread base for single-shot background tasks.

Subclass, override ``_run()``, and connect to ``error`` for failures.
The ``run()`` scaffolding catches any unhandled exception and routes it
to the ``error`` signal so callers never need to repeat the try/except
boilerplate.
"""
from __future__ import annotations

from abc import abstractmethod

from PySide6.QtCore import QThread, Signal


class WorkerBase(QThread):
    """QThread with a standard ``error`` signal and exception scaffolding.

    Subclasses implement ``_run()``; ``run()`` wraps it in a try/except
    and emits ``error`` on failure. Override ``run()`` directly only when
    the default exception handling is wrong for your use-case (e.g.
    DeviceQueryThread, which silently returns an empty list on failure).
    """

    error = Signal(str)

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self.error.emit(str(exc))

    @abstractmethod
    def _run(self) -> None: ...
