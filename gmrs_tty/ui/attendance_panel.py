"""Listening-session attendance grid widget.

A read-only table of every callsign heard during the current Listen
session. Each row carries Callsign / Name / Location / GMRS / HAM; the
last four fill in automatically when the callsign is already in (or
later added to) the contact list.

The panel owns an ``AttendanceTracker`` (ordered de-duped set of heard
callsigns) and a snapshot of the current contacts. MainWindow drives it
via ``record(callsign)`` on every RX detection and ``refresh(contacts)``
whenever the contact list changes. The Listen on→off cycle and the
panel's own Clear button both route through ``clear()``.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QMenu,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from gmrs_tty.persistence.attendance import (
    AttendanceTracker,
    build_attendance_rows,
)
from gmrs_tty.persistence.csv_export import session_to_csv
from gmrs_tty.ui import theme


COLUMNS = ("Callsign", "Name", "Location", "GMRS", "HAM")


class AttendancePanel(QWidget):
    # Operator asked for the current grid to be stored as a net session.
    # MainWindow owns the session timestamps, so it handles the save.
    save_session_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracker = AttendanceTracker()
        self._contacts: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.SPACING_S, theme.SPACING_XS, theme.SPACING_S, theme.SPACING_XS
        )
        outer.setSpacing(theme.SPACING_XS)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        # Interactive so the operator can drag dividers; _render calls
        # resizeColumnsToContents() after each data update so columns
        # autofit to content while remaining manually adjustable.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self.table.setAccessibleName("Callsigns Detected grid")
        self.table.setAccessibleDescription(
            "Callsigns detected during the current listening session. "
            "Columns: Callsign, Name, Location, GMRS, HAM. Name and contact "
            "columns fill in automatically when a callsign is in (or added to) contacts."
        )
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemSelectionChanged.connect(self._refresh_remove_button)
        outer.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(theme.SPACING_S)
        button_row.addStretch(1)
        self.save_session_button = QPushButton("&Save session", self)
        self.save_session_button.setToolTip(
            "Store the current grid as a net session record for the "
            "attendance history (Tools → Net Attendance History)."
        )
        self.save_session_button.setAccessibleName("Save session")
        self.save_session_button.setAccessibleDescription(
            "Store the callsigns detected this session as a net session "
            "record for later attendance statistics and CSV export."
        )
        self.save_session_button.clicked.connect(self.save_session_requested.emit)
        button_row.addWidget(self.save_session_button)
        self.export_button = QPushButton("&Export CSV…", self)
        self.export_button.setToolTip(
            "Save the current grid to a CSV file (Callsign, Name, "
            "Location, GMRS, HAM)."
        )
        self.export_button.setAccessibleName("Export callsigns detected as CSV")
        self.export_button.setAccessibleDescription(
            "Save the current callsigns-detected grid to a CSV file."
        )
        self.export_button.clicked.connect(self._export_csv)
        button_row.addWidget(self.export_button)
        self.remove_button = QPushButton("&Remove selected", self)
        self.remove_button.setEnabled(False)
        self.remove_button.setToolTip(
            "Remove the selected callsign from the session list. "
            "Does not affect your contacts."
        )
        self.remove_button.setAccessibleName("Remove selected callsign")
        self.remove_button.setAccessibleDescription(
            "Remove the currently selected callsign from the session list "
            "without deleting it from contacts."
        )
        self.remove_button.clicked.connect(self._remove_selected)
        button_row.addWidget(self.remove_button)
        self.clear_button = QPushButton("Clear callsigns &detected", self)
        self.clear_button.setToolTip(
            "Empty the callsigns-detected list for the current listening session."
        )
        self.clear_button.setAccessibleName("Clear callsigns detected")
        self.clear_button.setAccessibleDescription(
            "Remove every row from the callsigns-detected list. The list keeps "
            "collecting new callsigns as they are detected."
        )
        self.clear_button.clicked.connect(self.clear)
        button_row.addWidget(self.clear_button)
        outer.addLayout(button_row)

    def set_touch_mode(self, enabled: bool) -> None:
        """Resize action buttons for touch-screen use when ``enabled``."""
        min_h = 44 if enabled else 0
        self.remove_button.setMinimumHeight(min_h)
        self.clear_button.setMinimumHeight(min_h)
        self.save_session_button.setMinimumHeight(min_h)
        self.export_button.setMinimumHeight(min_h)

    def rows(self) -> list[dict]:
        """Current grid rows joined against the contacts snapshot — the
        roster shape stored in net session records."""
        return build_attendance_rows(self._tracker.callsigns(), self._contacts)

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "callsigns_detected.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(session_to_csv({"roster": self.rows()}) + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not write file:\n{exc}")

    def record(self, callsign: str) -> None:
        """Add `callsign` to the session. No-op when it has already been
        recorded — repeated transmissions from the same operator don't
        re-render the grid."""
        if self._tracker.record(callsign):
            self._render()

    def clear(self) -> None:
        """Empty the grid. Called by the panel's Clear button and by
        MainWindow at the start of every fresh Listen session."""
        self._tracker.clear()
        self._render()

    def refresh(self, contacts) -> None:
        """Adopt a new contacts snapshot and re-render every row so a
        callsign that was unknown when first heard fills in its Name /
        Location / GMRS / HAM the moment it is saved to contacts."""
        self._contacts = list(contacts or [])
        self._render()

    def callsigns(self) -> list[str]:
        """Currently-recorded callsigns, in heard order. Exposed for tests
        and for parity-check assertions in the MainWindow integration."""
        return self._tracker.callsigns()

    def _refresh_remove_button(self) -> None:
        self.remove_button.setEnabled(bool(self.table.selectedItems()))

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        self._tracker.remove(item.text())
        self._render()

    def _show_context_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        callsign = item.text()
        menu = QMenu(self)
        remove_action = menu.addAction(f"Remove {callsign} from session")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action is remove_action:
            self._tracker.remove(callsign)
            self._render()

    def _render(self) -> None:
        rows = build_attendance_rows(self._tracker.callsigns(), self._contacts)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(("callsign", "name", "location", "gmrs", "ham")):
                item = QTableWidgetItem(row[key])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)
        if rows:
            self.table.resizeColumnsToContents()
