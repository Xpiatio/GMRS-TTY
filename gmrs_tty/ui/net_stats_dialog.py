"""Pop-up dialog for browsing saved net sessions and attendance statistics.

Two tabs: **History** (per-session roster browser with CSV export and
delete, following the JournalDialog splitter pattern) and **Statistics**
(aggregate per-station attendance from
``gmrs_tty.persistence.net_stats.compute_attendance_stats``).
"""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from gmrs_tty.persistence.csv_export import (
    all_sessions_to_csv, session_to_csv, stats_to_csv,
)
from gmrs_tty.persistence.net_sessions import (
    delete_session, load_session, load_session_summaries,
)
from gmrs_tty.persistence.net_stats import compute_attendance_stats

STATS_COLUMNS = (
    ("callsign", "Callsign"),
    ("name", "Name"),
    ("total_nets", "Total nets"),
    ("attended_of_recent", "Of last 10"),
    ("current_streak", "Streak"),
    ("last_seen", "Last seen"),
)


class NetStatsDialog(QDialog):
    def __init__(self, contacts=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Net Attendance History")
        self.setMinimumSize(720, 480)
        self.resize(900, 580)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._contacts = list(contacts or [])
        self._summaries: list[dict] = []
        self._current_session: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget(self)
        tabs.setAccessibleName("Net attendance tabs")
        tabs.addTab(self._build_history_tab(), "&History")
        tabs.addTab(self._build_stats_tab(), "S&tatistics")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setAccessibleDescription("Close the net attendance browser.")
        root.addWidget(buttons)

        self._reload()

    # ------------------------------------------------------------------
    # Tab builders
    # ------------------------------------------------------------------

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        splitter = QSplitter(Qt.Orientation.Horizontal, page)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        list_label = QLabel("Sessions")
        list_label.setStyleSheet("font-weight: bold;")
        self._list = QListWidget()
        self._list.setAccessibleName("Net session list")
        self._list.setAccessibleDescription(
            "Saved Listen sessions, newest first. Select one to view its roster."
        )
        self._list.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(list_label)
        left_layout.addWidget(self._list, 1)

        self._delete_btn = QPushButton("&Delete session")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setToolTip("Permanently delete the selected session.")
        self._delete_btn.setAccessibleName("Delete selected session")
        self._delete_btn.setAccessibleDescription(
            "Permanently deletes the selected net session record."
        )
        self._delete_btn.clicked.connect(self._delete_selected)
        left_layout.addWidget(self._delete_btn)

        self._export_all_btn = QPushButton("Export &all (CSV)…")
        self._export_all_btn.setEnabled(False)
        self._export_all_btn.setToolTip(
            "Save every session's roster to one CSV file "
            "(one row per station per session)."
        )
        self._export_all_btn.setAccessibleName("Export all sessions as CSV")
        self._export_all_btn.setAccessibleDescription(
            "Saves every stored session to a single CSV file."
        )
        self._export_all_btn.clicked.connect(self._export_all)
        left_layout.addWidget(self._export_all_btn)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setAccessibleName("Session detail")
        self._detail.setAccessibleDescription(
            "Roster of the selected session: every callsign heard with its "
            "contact details at the time."
        )
        self._export_btn = QPushButton("&Export session (CSV)…")
        self._export_btn.setEnabled(False)
        self._export_btn.setToolTip("Save the selected session's roster as CSV.")
        self._export_btn.setAccessibleName("Export selected session as CSV")
        self._export_btn.setAccessibleDescription(
            "Saves the selected session's roster to a CSV file."
        )
        self._export_btn.clicked.connect(self._export_selected)
        right_layout.addWidget(self._detail, 1)
        right_layout.addWidget(self._export_btn, 0, Qt.AlignmentFlag.AlignRight)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([280, 600])
        layout.addWidget(splitter, 1)
        return page

    def _build_stats_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "Per-station attendance across every saved session, busiest "
            "station first. A station is a callsign + name pair, so family "
            "members sharing one GMRS callsign count separately."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._stats_table = QTableWidget(0, len(STATS_COLUMNS), page)
        self._stats_table.setHorizontalHeaderLabels([c[1] for c in STATS_COLUMNS])
        self._stats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._stats_table.verticalHeader().setVisible(False)
        self._stats_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._stats_table.setAccessibleName("Attendance statistics grid")
        self._stats_table.setAccessibleDescription(
            "One row per station: callsign, name, total nets attended, "
            "attendance over the last ten nets, current streak, and the "
            "date last heard."
        )
        layout.addWidget(self._stats_table, 1)

        stats_buttons = QHBoxLayout()
        stats_buttons.addStretch(1)
        self._export_stats_btn = QPushButton("Export &stats (CSV)…")
        self._export_stats_btn.setEnabled(False)
        self._export_stats_btn.setToolTip("Save the attendance statistics as CSV.")
        self._export_stats_btn.setAccessibleName("Export statistics as CSV")
        self._export_stats_btn.setAccessibleDescription(
            "Saves the aggregate attendance statistics to a CSV file."
        )
        self._export_stats_btn.clicked.connect(self._export_stats)
        stats_buttons.addWidget(self._export_stats_btn)
        layout.addLayout(stats_buttons)
        return page

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        self._summaries = load_session_summaries()
        self._list.clear()
        self._detail.clear()
        self._current_session = None
        self._export_btn.setEnabled(False)
        self._export_all_btn.setEnabled(bool(self._summaries))

        if not self._summaries:
            placeholder = QListWidgetItem("No sessions saved yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
            self._detail.setPlainText(
                "Save your first session from the Callsigns Detected panel\n"
                "(Save session), or enable auto-save in Settings →\n"
                "Configuration → Behavior."
            )
        else:
            for s in self._summaries:
                date = (s.get("started_at") or "")[:16].replace("T", " ")
                label = f"{date}  —  {s.get('checkin_count', 0)} station(s)"
                self._list.addItem(QListWidgetItem(label))
            self._list.setCurrentRow(0)

        self._render_stats()

    def _render_stats(self) -> None:
        stats = compute_attendance_stats(self._summaries, self._contacts)
        self._stats_rows = stats
        self._stats_table.setRowCount(len(stats))
        for r, row in enumerate(stats):
            for c, (field, _label) in enumerate(STATS_COLUMNS):
                value = row.get(field, "")
                if field == "attended_of_recent":
                    value = f"{value} of {row.get('recent_window', 0)}"
                elif field == "last_seen":
                    value = str(value)[:10]
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._stats_table.setItem(r, c, item)
        if stats:
            self._stats_table.resizeColumnsToContents()
        self._export_stats_btn.setEnabled(bool(stats))

    def _on_selection_changed(self, row: int) -> None:
        valid = 0 <= row < len(self._summaries)
        self._delete_btn.setEnabled(valid)
        self._export_btn.setEnabled(valid)
        if not valid:
            return
        session = load_session(self._summaries[row]["id"])
        self._current_session = session
        if session is None:
            self._detail.setPlainText("Could not read this session file.")
            self._export_btn.setEnabled(False)
            return

        started = html.escape(session.get("started_at", ""))
        ended = html.escape(session.get("ended_at", ""))
        minutes = int(session.get("duration_seconds", 0) or 0) // 60
        roster_rows = "".join(
            "<tr>"
            + "".join(
                f"<td style='padding:2px 12px 2px 0'>{html.escape(str(r.get(f, '')))}</td>"
                for f in ("callsign", "name", "location", "gmrs", "ham")
            )
            + "</tr>"
            for r in session.get("roster") or []
        )
        self._detail.setHtml(
            f"<p><b>Started:</b> {started}<br>"
            f"<b>Ended:</b> {ended}<br>"
            f"<b>Duration:</b> {minutes} min</p>"
            "<p><b>Stations heard</b></p>"
            "<table border='0' cellpadding='0' cellspacing='0'>"
            "<tr><td style='padding:2px 12px 2px 0'><b>Callsign</b></td>"
            "<td style='padding:2px 12px 2px 0'><b>Name</b></td>"
            "<td style='padding:2px 12px 2px 0'><b>Location</b></td>"
            "<td style='padding:2px 12px 2px 0'><b>GMRS</b></td>"
            "<td style='padding:2px 0'><b>HAM</b></td></tr>"
            f"{roster_rows}</table>"
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _save_csv(self, suggested_name: str, content: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", suggested_name, "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(content + "\n")
        except OSError as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not write file:\n{exc}")

    def _export_selected(self) -> None:
        if not self._current_session:
            return
        self._save_csv(
            f"net_session_{self._current_session.get('id', 'session')}.csv",
            session_to_csv(self._current_session),
        )

    def _export_all(self) -> None:
        if not self._summaries:
            return
        self._save_csv("net_sessions_all.csv", all_sessions_to_csv(self._summaries))

    def _export_stats(self) -> None:
        if not getattr(self, "_stats_rows", None):
            return
        self._save_csv("net_attendance_stats.csv", stats_to_csv(self._stats_rows))

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._summaries):
            return
        summary = self._summaries[row]
        date = (summary.get("started_at") or "")[:16].replace("T", " ")
        answer = QMessageBox.question(
            self,
            "Delete Session",
            f"Permanently delete the session from {date or summary['id']}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_session(summary["id"])
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Delete Failed", f"Could not delete session:\n{exc}")
            return
        self._reload()
