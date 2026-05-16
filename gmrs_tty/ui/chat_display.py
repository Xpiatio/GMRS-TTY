from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QToolTip

from gmrs_tty.constants import PILL_BG, PILL_BORDER, PILL_TEXT
from gmrs_tty.persistence.contacts import format_callsign_tooltip
from gmrs_tty.text.callsigns import find_callsign_spans


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
        """Append a chat line and pill-highlight any known callsigns inside it."""
        self.append(f"<span style='color:{color};'>{html}</span>")
        block = self.document().lastBlock()
        self._apply_pill_format(block.position(), block.text())

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
        for start, end, cs in find_callsign_spans(block_text):
            if cs not in self._callsign_index:
                continue
            span = (start, end)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            cursor = QTextCursor(doc)
            cursor.setPosition(block_start + start)
            cursor.setPosition(
                block_start + end, QTextCursor.MoveMode.KeepAnchor
            )
            cursor.mergeCharFormat(self._pill_format(cs))

    def _pill_format(self, callsign):
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(PILL_BG))
        fmt.setForeground(QColor(PILL_TEXT))
        fmt.setFontWeight(QFont.Weight.Bold)
        # A subtle bottom border via underline gives the rectangle some "pill"
        # affordance — QTextEdit's HTML subset rejects border-radius, so this
        # is the closest visual hint that the run is a distinct token.
        fmt.setFontUnderline(True)
        fmt.setUnderlineColor(QColor(PILL_BORDER))
        fmt.setToolTip(format_callsign_tooltip(callsign, self._callsign_index.get(callsign, [])))
        return fmt

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
