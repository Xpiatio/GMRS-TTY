"""Pop-up dialog for browsing saved session journal entries."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from gmrs_tty.persistence.journal import load_journals


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
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        self._title_label.setText(entry.get("title") or "Untitled")

        exported = entry.get("exported_at") or ""
        callsigns = ", ".join(entry.get("callsigns") or []) or "None"
        summary = (entry.get("summary") or "").replace("\n", "<br>")

        html = (
            f"<p><b>Exported:</b> {exported}</p>"
            f"<p><b>Callsigns Detected:</b> {callsigns}</p>"
            f"<hr>"
            f"<p>{summary}</p>"
        )
        self._detail.setHtml(html)
