from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QToolButton, QVBoxLayout, QWidget

from gmrs_tty.ui import theme
from gmrs_tty.ui.chat_display import ChatDisplay

_THEME_GLYPH_TO_DARK = "\U0001F319"   # 🌙
_THEME_GLYPH_TO_LIGHT = "☀️"


class TouchView(QWidget):
    """Touchscreen-optimised full-panel view.

    Layout (top → bottom):
      • Pending pills row   — injected after construction via set_pending_widget()
      • Chat display        — stretch
      • Row 1 (tall)        — Listen (checkable) | Listen Only (checkable)
      • Row 2 (medium)      — Monitor | 🌙 Theme | Callsigns | Generate Log | View Logs

    All buttons delegate to MainWindow handlers via connections made in
    _build_central_widget.  Sync helpers keep visual state in step with
    the normal view without re-triggering those handlers.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(
            theme.SPACING_S, theme.SPACING_S,
            theme.SPACING_S, theme.SPACING_S,
        )
        self._main_layout.setSpacing(theme.SPACING_S)

        p = theme.palette()

        # ── Chat display + scroll-to-bottom overlay ───────────────────────
        self._chat_container = QWidget(self)
        _chat_container_layout = QVBoxLayout(self._chat_container)
        _chat_container_layout.setContentsMargins(0, 0, 0, 0)
        _chat_container_layout.setSpacing(0)

        self.chat_display = ChatDisplay(self._chat_container)
        self.chat_display.setFont(theme.font_chat())
        self.chat_display.setStyleSheet(theme.chat_display_stylesheet())
        self.chat_display.setAccessibleName("Conversation log (touch view)")
        self.chat_display.setAccessibleDescription(
            "Touchscreen copy of the main conversation log. "
            "Shows the same messages as the desktop view."
        )
        _chat_container_layout.addWidget(self.chat_display)

        self.scroll_to_bottom_btn = QPushButton("▼", self._chat_container)
        self.scroll_to_bottom_btn.setFixedSize(56, 56)
        self.scroll_to_bottom_btn.setToolTip("Scroll to bottom")
        self.scroll_to_bottom_btn.setAccessibleName("Scroll chat to bottom")
        self.scroll_to_bottom_btn.setAccessibleDescription(
            "Jump the conversation log to the most recent message."
        )
        self.scroll_to_bottom_btn.setStyleSheet(theme.scroll_to_bottom_btn_stylesheet())
        self.scroll_to_bottom_btn.clicked.connect(self._scroll_to_bottom)
        self.scroll_to_bottom_btn.hide()
        self.scroll_to_bottom_btn.raise_()

        self._chat_container.installEventFilter(self)
        self.chat_display.verticalScrollBar().valueChanged.connect(self._update_scroll_btn)
        self.chat_display.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._update_scroll_btn()
        )

        self._main_layout.addWidget(self._chat_container, 1)

        # ── Row 1: primary radio controls (tall) ─────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(theme.SPACING_M)

        self.listen_btn = QPushButton("Listen", self)
        self.listen_btn.setCheckable(True)
        self.listen_btn.setMinimumHeight(80)
        self.listen_btn.setStyleSheet(theme.touch_btn_stylesheet(p.rx))
        self.listen_btn.setAccessibleName("Listen toggle (touch)")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio."
        )
        row1.addWidget(self.listen_btn, 1)

        self.listen_only_btn = QPushButton("Listen Only", self)
        self.listen_only_btn.setCheckable(True)
        self.listen_only_btn.setMinimumHeight(80)
        self.listen_only_btn.setStyleSheet(theme.touch_btn_stylesheet(p.warn))
        self.listen_only_btn.setToolTip(
            "Block all transmissions while still receiving (Alt+O)."
        )
        self.listen_only_btn.setAccessibleName("Listen only toggle (touch)")
        self.listen_only_btn.setAccessibleDescription(
            "Block all outgoing transmissions while still receiving."
        )
        row1.addWidget(self.listen_only_btn, 1)

        self._main_layout.addLayout(row1)

        # ── Row 2: secondary controls (medium) ───────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(theme.SPACING_S)

        self.monitor_btn = QPushButton("Monitor", self)
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setEnabled(False)
        self.monitor_btn.setMinimumHeight(56)
        self.monitor_btn.setStyleSheet(theme.touch_btn_stylesheet(p.tx))
        self.monitor_btn.setToolTip(
            "Play incoming audio through speakers (Alt+M). "
            "Available when Listen-only is on."
        )
        self.monitor_btn.setAccessibleName("Monitor audio toggle (touch)")
        row2.addWidget(self.monitor_btn, 1)

        self.theme_btn = QToolButton(self)
        self.theme_btn.setMinimumHeight(56)
        self.theme_btn.setMinimumWidth(56)
        self.theme_btn.setFont(theme.font_icon())
        self.theme_btn.setAutoRaise(True)
        self.theme_btn.setAccessibleName("Toggle dark mode (touch)")
        row2.addWidget(self.theme_btn, 0)

        self.attendance_btn = QPushButton("Callsigns", self)
        self.attendance_btn.setMinimumHeight(56)
        self.attendance_btn.setStyleSheet(theme.checkable_btn_stylesheet(p.rx))
        self.attendance_btn.setToolTip("Show / hide the Callsigns Detected panel.")
        self.attendance_btn.setAccessibleName("View callsigns detected (touch)")
        row2.addWidget(self.attendance_btn, 1)

        self.generate_btn = QPushButton("Generate Log", self)
        self.generate_btn.setMinimumHeight(56)
        self.generate_btn.setStyleSheet(theme.checkable_btn_stylesheet(p.rx))
        self.generate_btn.setToolTip("Generate an AI session journal entry (Ctrl+J).")
        self.generate_btn.setAccessibleName("Generate session journal (touch)")
        self.generate_btn.setVisible(False)
        row2.addWidget(self.generate_btn, 1)

        self.journals_btn = QPushButton("View Logs", self)
        self.journals_btn.setMinimumHeight(56)
        self.journals_btn.setStyleSheet(theme.checkable_btn_stylesheet(p.rx))
        self.journals_btn.setToolTip("Browse saved session journals (Ctrl+Shift+J).")
        self.journals_btn.setAccessibleName("View session journals (touch)")
        row2.addWidget(self.journals_btn, 1)

        self._main_layout.addLayout(row2)

        # Set initial theme glyph
        self.sync_theme_glyph()

    # ── Pending widget injection ──────────────────────────────────────────

    def set_pending_widget(self, widget: QWidget) -> None:
        """Insert the pending-stations scroll area at the top of the layout."""
        self._main_layout.insertWidget(0, widget)

    # ── Sync helpers ─────────────────────────────────────────────────────

    def sync_listen_state(self, checked: bool, text: str = "") -> None:
        """Mirror normal Listen button state without retriggering handlers."""
        self.listen_btn.blockSignals(True)
        self.listen_btn.setChecked(checked)
        if text:
            self.listen_btn.setText(text)
        self.listen_btn.blockSignals(False)

    def sync_listen_only_state(self, checked: bool) -> None:
        """Mirror normal Listen Only button state without retriggering handlers."""
        self.listen_only_btn.blockSignals(True)
        self.listen_only_btn.setChecked(checked)
        self.listen_only_btn.blockSignals(False)

    def sync_monitor_state(self, checked: bool, enabled: bool) -> None:
        """Mirror normal Monitor button state without retriggering handlers."""
        self.monitor_btn.blockSignals(True)
        self.monitor_btn.setChecked(checked)
        self.monitor_btn.blockSignals(False)
        self.monitor_btn.setEnabled(enabled)

    def sync_theme_glyph(self) -> None:
        """Update the theme button glyph to advertise the next theme state."""
        if theme.is_dark():
            self.theme_btn.setText(_THEME_GLYPH_TO_LIGHT)
            self.theme_btn.setToolTip("Switch to light mode")
        else:
            self.theme_btn.setText(_THEME_GLYPH_TO_DARK)
            self.theme_btn.setToolTip("Switch to dark mode")

    def set_generate_visible(self, visible: bool) -> None:
        self.generate_btn.setVisible(visible)

    # ── Scroll-to-bottom overlay ──────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._chat_container and event.type() == QEvent.Type.Resize:
            self._reposition_scroll_btn()
        return super().eventFilter(obj, event)

    def _reposition_scroll_btn(self) -> None:
        margin = theme.SPACING_S
        btn = self.scroll_to_bottom_btn
        container = self._chat_container
        btn.move(
            container.width() - btn.width() - margin,
            container.height() - btn.height() - margin,
        )

    def _update_scroll_btn(self) -> None:
        sb = self.chat_display.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 2
        self._reposition_scroll_btn()
        self.scroll_to_bottom_btn.setVisible(not at_bottom)
        if self.scroll_to_bottom_btn.isVisible():
            self.scroll_to_bottom_btn.raise_()

    def _scroll_to_bottom(self) -> None:
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Theme restyle ─────────────────────────────────────────────────────

    def restyle(self) -> None:
        """Reapply theme stylesheets to all touch-specific widgets."""
        p = theme.palette()
        self.chat_display.setStyleSheet(theme.chat_display_stylesheet())
        self.chat_display.restyle_for_theme()
        self.listen_btn.setStyleSheet(theme.touch_btn_stylesheet(p.rx))
        self.listen_only_btn.setStyleSheet(theme.touch_btn_stylesheet(p.warn))
        self.monitor_btn.setStyleSheet(theme.touch_btn_stylesheet(p.tx))
        self.attendance_btn.setStyleSheet(theme.checkable_btn_stylesheet(p.rx))
        self.generate_btn.setStyleSheet(theme.checkable_btn_stylesheet(p.rx))
        self.journals_btn.setStyleSheet(theme.checkable_btn_stylesheet(p.rx))
        self.scroll_to_bottom_btn.setStyleSheet(theme.scroll_to_bottom_btn_stylesheet())
        self.sync_theme_glyph()
