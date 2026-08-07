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
        self._ts: str = ""
        # The most recently closed utterance, kept so a two-tier final pass
        # that lands after the line closed can still rewrite that line
        # instead of appending a duplicate of the same transmission.
        self._closed_uid: int | None = None
        self._closed_block: int | None = None
        self._closed_ts: str = ""

    # ------------------------------------------------------------------

    def receive(
        self, uid: int, text: str, is_final: bool, color: str,
        replace: bool = False,
    ) -> None:
        """Append one transcription segment to the chat.

        Args:
            uid:      Utterance identifier from STTWorker.
            text:     Transcribed text for this segment.
            is_final: True on the last segment of an utterance.
            color:    CSS-compatible color string for the chat line.
            replace:  True for a two-tier full-utterance re-transcription
                      that supersedes the accumulated partial texts — the
                      utterance's chat line is rewritten, not grown.
        """
        text = self._filter(text)

        if replace and text:
            self._replace_utterance(uid, text, color)
            return

        if not text:
            # An empty *final* still closes the utterance — the two-tier
            # pipeline emits one to release the partials when a final pass
            # is abandoned or fails.
            if is_final and uid == self._uid:
                self._close()
            return

        if uid != self._uid:
            # New utterance — close any in-progress one so its callsigns still
            # land and its line stays addressable by a late final pass.
            if self._uid is not None:
                self._close()
            self._open_line(uid, text, color)
        else:
            appended = self._chat.append_to_block(self._block, " " + text, color=color)
            if not appended:
                # Chat was cleared mid-utterance — open a fresh line.
                self._open_line(uid, text, color)
            else:
                self._text += " " + text

        if is_final:
            self._close()

    def _open_line(self, uid: int, text: str, color: str) -> None:
        self._ts = self._format_ts()
        self._block = self._chat.append_message(
            f"<b>[RX {self._ts}]:</b> {text}", color=color
        )
        self._uid = uid
        self._text = text

    def _close(self) -> None:
        if self._text:
            self._on_complete(self._text)
        self._closed_uid = self._uid
        self._closed_block = self._block
        self._closed_ts = self._ts
        self._uid = None
        self._block = None
        self._text = ""

    def _replace_utterance(self, uid: int, text: str, color: str) -> None:
        """Rewrite the utterance's chat line with the final-pass text."""
        if uid == self._uid and self._block is not None:
            replaced = self._chat.replace_block(
                self._block, f"<b>[RX {self._ts}]:</b> {text}", color=color
            )
            if replaced:
                self._text = text
            else:
                # Chat was cleared mid-utterance — same uid, safe to reopen.
                self._open_line(uid, text, color)
            self._close()
            return
        # The line already closed (the slow final pass can land after the next
        # transmission starts). Rewrite it in place — appending would show the
        # same transmission twice, once superseded. The completion callback
        # still fires so callsign discovery sees the corrected text.
        if uid == self._closed_uid and self._closed_block is not None:
            replaced = self._chat.replace_block(
                self._closed_block, f"<b>[RX {self._closed_ts}]:</b> {text}",
                color=color,
            )
            if replaced:
                self._on_complete(text)
                return
        # No line left to rewrite (chat cleared, or an unknown uid) — show the
        # replacement on its own line without disturbing what's in progress.
        ts = self._format_ts()
        self._chat.append_message(f"<b>[RX {ts}]:</b> {text}", color=color)
        self._on_complete(text)

    def flush(self) -> None:
        """Flush any in-progress utterance. Call before tearing down the STT worker."""
        if self._uid is None:
            return
        self._close()
