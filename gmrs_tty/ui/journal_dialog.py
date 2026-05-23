"""Pop-up dialog for browsing saved session journal entries."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

from gmrs_tty.persistence.journal import delete_journal, load_journals


class JournalDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Session Journals")
        self.setMinimumSize(720, 480)
        self.resize(900, 580)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._entries: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left — entry list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        list_label = QLabel("Entries")
        list_label.setStyleSheet("font-weight: bold;")
        self._list = QListWidget()
        self._list.setAccessibleName("Journal entry list")
        self._list.currentRowChanged.connect(self._on_selection_changed)
        left_layout.addWidget(list_label)
        left_layout.addWidget(self._list, 1)

        self._delete_btn = QPushButton("Delete entry")
        self._delete_btn.setEnabled(False)
        self._delete_btn.setToolTip("Permanently delete the selected journal entry.")
        self._delete_btn.setAccessibleName("Delete selected journal entry")
        self._delete_btn.clicked.connect(self._delete_selected)
        left_layout.addWidget(self._delete_btn)

        # Right — detail view
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        self._title_label = QLabel()
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setAccessibleName("Journal entry detail")
        right_layout.addWidget(self._title_label)
        right_layout.addWidget(self._detail, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([260, 620])

        root.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._reload()

    def _reload(self) -> None:
        self._entries = load_journals()
        self._list.clear()
        self._title_label.clear()
        self._detail.clear()

        if not self._entries:
            placeholder = QListWidgetItem("No journal entries yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
            self._detail.setPlainText(
                "Generate your first journal entry by clicking\n"
                "Tools → Generate Session Journal."
            )
            return

        for entry in self._entries:
            date_part = (entry.get("exported_at") or "")[:10]
            title_part = entry.get("title") or "Untitled"
            label = f"{date_part}  —  {title_part}" if date_part else title_part
            self._list.addItem(QListWidgetItem(label))

        self._list.setCurrentRow(0)

    def _on_selection_changed(self, row: int) -> None:
        self._delete_btn.setEnabled(0 <= row < len(self._entries))
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        self._title_label.setText(entry.get("title") or "Untitled")

        exported = html.escape(entry.get("exported_at") or "")

        callsigns_locations = entry.get("callsigns_locations")
        if callsigns_locations:
            cs_rows = "".join(
                f"<tr><td style='padding:2px 12px 2px 0'><b>{html.escape(c.get('callsign', ''))}</b></td>"
                f"<td style='padding:2px 0'>{html.escape(c.get('location', 'Not stated'))}</td></tr>"
                for c in callsigns_locations
            )
            cs_section = (
                "<p><b>Callsigns &amp; Locations</b></p>"
                "<table border='0' cellpadding='0' cellspacing='0'>"
                f"{cs_rows}"
                "</table>"
            )
        else:
            flat = html.escape(", ".join(entry.get("callsigns") or []) or "None")
            cs_section = f"<p><b>Callsigns Detected:</b> {flat}</p>"

        summary = html.escape(entry.get("summary") or "").replace("\n", "<br>")
        transcript_raw = html.escape(entry.get("transcript") or "").replace("\n", "<br>")

        body = (
            f"<p><b>Exported:</b> {exported}</p>"
            f"{cs_section}"
            f"<hr>"
            f"<p><b>Summary</b></p>"
            f"<p>{summary}</p>"
            f"<hr>"
            f"<p><b>Transcript</b></p>"
            f"<p style='font-family:monospace;font-size:11px'>{transcript_raw}</p>"
        )
        self._detail.setHtml(body)

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        title = entry.get("title") or "Untitled"
        answer = QMessageBox.question(
            self,
            "Delete Journal Entry",
            f'Permanently delete “{title}”?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_journal(entry["_file"])
        except OSError as exc:
            QMessageBox.warning(self, "Delete Failed", f"Could not delete entry:\n{exc}")
            return
        self._reload()
