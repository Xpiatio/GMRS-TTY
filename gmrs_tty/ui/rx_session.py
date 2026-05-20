"""Streaming-RX session state machine.

Extracted from MainWindow so the chat-rendering + utterance-tracking logic
can be tested without a running Qt application. MainWindow constructs one
instance and delegates ``on_transcription_segment`` calls here.
"""
from __future__ import annotations

from typing import Callable


class RXSession:
    """Track one in-progress utterance and append streaming segments to chat.

    Partials with a new uid open a fresh timestamped chat line. Subsequent
    partials with the same uid grow that line in-place. On the final segment,
    ``on_utterance_complete`` fires once with the full accumulated text so
    the caller can run callsign discovery.

    Designed to be Qt-free so it can be exercised in plain pytest.

    Args:
        chat:                Object with ``append_message(html, color)`` and
                             ``append_to_block(block, text, color)`` methods.
        on_utterance_complete: Callback invoked with ``(text: str)`` when a
                             utterance ends (is_final=True or new uid arrives).
        format_timestamp:    No-arg callable that returns an ``HH:MM:SS`` string.
        filter_fn:           Optional text transform applied before display
                             (e.g. profanity masking). Defaults to identity.
    """

    def __init__(
        self,
        chat,
        on_utterance_complete: Callable[[str], None],
        format_timestamp: Callable[[], str],
        filter_fn: Callable[[str], str] | None = None,
    ) -> None:
        self._chat = chat
        self._on_complete = on_utterance_complete
        self._format_ts = format_timestamp
        self._filter = filter_fn or (lambda t: t)
        self._uid: int | None = None
        self._block: int | None = None
        self._text: str = ""

    # ------------------------------------------------------------------

    def receive(self, uid: int, text: str, is_final: bool, color: str) -> None:
        """Append one transcription segment to the chat.

        Args:
            uid:      Utterance identifier from STTWorker.
            text:     Transcribed text for this segment.
            is_final: True on the last segment of an utterance.
            color:    CSS-compatible color string for the chat line.
        """
        text = self._filter(text)
        if not text:
            return

        if uid != self._uid:
            # New utterance — flush any in-progress one so its callsigns still land.
            if self._uid is not None and self._text:
                self._on_complete(self._text)
            ts = self._format_ts()
            block = self._chat.append_message(f"<b>[RX {ts}]:</b> {text}", color=color)
            self._uid = uid
            self._block = block
            self._text = text
        else:
            appended = self._chat.append_to_block(self._block, " " + text, color=color)
            if not appended:
                # Chat was cleared mid-utterance — open a fresh line.
                ts = self._format_ts()
                self._block = self._chat.append_message(
                    f"<b>[RX {ts}]:</b> {text}", color=color
                )
                self._text = text
            else:
                self._text += " " + text

        if is_final:
            self._on_complete(self._text)
            self._uid = None
            self._block = None
            self._text = ""

    def flush(self) -> None:
        """Flush any in-progress utterance. Call before tearing down the STT worker."""
        if self._uid is not None and self._text:
            self._on_complete(self._text)
        self._uid = None
        self._block = None
        self._text = ""
