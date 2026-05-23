from __future__ import annotations

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

        # ── Chat display ──────────────────────────────────────────────────
        self.chat_display = ChatDisplay(self)
        self.chat_display.setFont(theme.font_chat())
        self.chat_display.setStyleSheet(theme.chat_display_stylesheet())
        self.chat_display.setAccessibleName("Conversation log (touch view)")
        self.chat_display.setAccessibleDescription(
            "Touchscreen copy of the main conversation log. "
            "Shows the same messages as the desktop view."
        )
        self._main_layout.addWidget(self.chat_display, 1)

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
        self.sync_theme_glyph()
