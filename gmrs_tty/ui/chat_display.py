from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QToolTip

from gmrs_tty.constants import VERIFIED_GLYPH
from gmrs_tty.persistence.contacts import format_callsign_tooltip
from gmrs_tty.text.callsigns import find_callsign_spans
from gmrs_tty.ui import theme

# Trailing glyph appended after a verified callsign. Leading space keeps the
# checkmark visually detached from the pill's amber background so it reads
# as a separate badge rather than part of the callsign token.
_VERIFIED_SUFFIX = f" {VERIFIED_GLYPH}"


class ChatDisplay(QTextEdit):
    """Read-only chat log that styles known callsigns as a hoverable pill.

    The "pill" is an inline colored, bold span — QTextEdit's HTML subset doesn't
    honour border-radius, so we settle for a high-contrast block highlight and
    rely on the system tooltip to surface every name sharing the callsign.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMouseTracking(True)
        self._callsign_index = {}

    def set_callsign_index(self, index):
        self._callsign_index = dict(index or {})

    def append_message(self, html, color="black"):
        """Append a chat line and pill-highlight any known callsigns inside it.

        The viewport "sticks" to the bottom when the operator was already
        viewing the latest message — new lines stay in view as a live tail.
        If they had scrolled up to read older context, their position is
        preserved so an incoming transmission doesn't yank the view away.

        Returns the block number of the appended line so callers can later
        grow that line with append_to_block (used by streaming RX
        transcription to keep one chat line per utterance).
        """
        sb = self.verticalScrollBar()
        was_at_bottom = sb is None or sb.value() >= sb.maximum() - 2
        self.append(f"<span style='color:{color};'>{html}</span>")
        block = self.document().lastBlock()
        self._apply_pill_format(block.position(), block.text())
        if was_at_bottom and sb is not None:
            sb.setValue(sb.maximum())
        return block.blockNumber()

    def append_to_block(self, block_number, text, color="black"):
        """Append plain text to the end of an existing block and re-apply
        pill formatting on the whole block so newly-arrived callsign tokens
        light up. Used by streaming RX transcription so a single chat line
        grows as partials arrive instead of fragmenting into one line per
        slice. Returns True on success, False if the block is no longer
        valid (e.g., the chat was cleared between partials).
        """
        if not text:
            return False
        doc = self.document()
        block = doc.findBlockByNumber(int(block_number))
        if not block.isValid():
            return False
        sb = self.verticalScrollBar()
        was_at_bottom = sb is None or sb.value() >= sb.maximum() - 2
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text, fmt)
        self._apply_pill_format(block.position(), block.text())
        if was_at_bottom and sb is not None:
            sb.setValue(sb.maximum())
        return True

    def rescan_all_blocks(self):
        """Re-walk every block and apply pill formatting under the current index.
        Used when the contacts list changes so previously-displayed lines get
        retroactive highlighting for newly-added contacts."""
        doc = self.document()
        block = doc.firstBlock()
        while block.isValid():
            self._apply_pill_format(block.position(), block.text())
            block = block.next()

    def _apply_pill_format(self, block_start, block_text):
        if not block_text or not self._callsign_index:
            return
        doc = self.document()
        seen_spans = set()
        spans = []
        for start, end, cs in find_callsign_spans(block_text):
            if cs not in self._callsign_index:
                continue
            span = (start, end)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            spans.append((start, end, cs))
        # Iterate in reverse: inserting the verified-checkmark glyph after one
        # callsign shifts every position later in the block, so applying
        # formats end-first keeps earlier spans' offsets correct.
        for start, end, cs in reversed(spans):
            cursor = QTextCursor(doc)
            cursor.setPosition(block_start + start)
            cursor.setPosition(
                block_start + end, QTextCursor.MoveMode.KeepAnchor
            )
            cursor.mergeCharFormat(self._pill_format(cs))
            if self._is_verified(cs) and not self._has_verified_glyph(
                block_text, end
            ):
                self._insert_verified_glyph(block_start + end)

    def _is_verified(self, callsign):
        """True if any contact under `callsign` has a confirmed FCC match.
        With family-shared GMRS callsigns the license is held by one operator,
        so a single verified entry is enough to flag the call."""
        return any(
            bool(c.get("verified"))
            for c in self._callsign_index.get(callsign, [])
        )

    @staticmethod
    def _has_verified_glyph(block_text, end):
        return block_text[end:end + len(_VERIFIED_SUFFIX)] == _VERIFIED_SUFFIX

    def _insert_verified_glyph(self, position):
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.palette().verified))
        fmt.setFontWeight(QFont.Weight.Bold)
        fmt.setToolTip("FCC license verified for this callsign.")
        cursor.insertText(_VERIFIED_SUFFIX, fmt)

    def _pill_format(self, callsign):
        p = theme.palette()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(p.pill_bg))
        fmt.setForeground(QColor(p.pill_text))
        fmt.setFontWeight(QFont.Weight.Bold)
        # A subtle bottom border via underline gives the rectangle some "pill"
        # affordance — QTextEdit's HTML subset rejects border-radius, so this
        # is the closest visual hint that the run is a distinct token.
        fmt.setFontUnderline(True)
        fmt.setUnderlineColor(QColor(p.pill_border))
        fmt.setToolTip(format_callsign_tooltip(callsign, self._callsign_index.get(callsign, [])))
        return fmt

    def restyle_for_theme(self):
        """Recolor already-rendered text spans to match the active theme.

        The chat document bakes hex foreground colors into HTML spans at
        append-time, so a theme flip doesn't touch existing RX / TX / WARN /
        ERROR text. Walk every fragment, look up its foreground in a
        light↔dark remap, and rewrite the format in place. Pill spans
        (those with a non-transparent background) are skipped here because
        ``rescan_all_blocks`` rebuilds them from the live ``palette()``.
        """
        if theme.is_dark():
            remap = theme.color_remap_light_to_dark()
        else:
            remap = theme.color_remap_dark_to_light()
        if not remap:
            return
        doc = self.document()
        block = doc.firstBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fmt = frag.charFormat()
                    bg = fmt.background()
                    # Pill spans set a real background brush — leave them to
                    # rescan_all_blocks which knows the full pill format.
                    if bg.style() != Qt.BrushStyle.NoBrush:
                        it += 1
                        continue
                    cur_hex = fmt.foreground().color().name().lower()
                    new_hex = remap.get(cur_hex)
                    if new_hex is not None:
                        cursor = QTextCursor(doc)
                        cursor.setPosition(frag.position())
                        cursor.setPosition(
                            frag.position() + frag.length(),
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        replacement = QTextCharFormat()
                        replacement.setForeground(QColor(new_hex))
                        cursor.mergeCharFormat(replacement)
                it += 1
            block = block.next()
        # Pill backgrounds + verified glyph color follow the live palette,
        # so a re-scan picks up the new values for every existing pill.
        self.rescan_all_blocks()

    def event(self, ev):
        if ev.type() == QEvent.Type.ToolTip:
            cursor = self.cursorForPosition(ev.pos())
            # cursorForPosition lands between characters; the format we want is
            # the one immediately to the left of the cursor (the character the
            # user is actually pointing at).
            pos = cursor.position()
            if pos > 0:
                probe = QTextCursor(self.document())
                probe.setPosition(pos - 1)
                probe.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
                tip = probe.charFormat().toolTip()
            else:
                tip = cursor.charFormat().toolTip()
            if tip:
                QToolTip.showText(ev.globalPos(), tip, self)
            else:
                QToolTip.hideText()
                ev.ignore()
            return True
        return super().event(ev)
