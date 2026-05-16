from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class QuickMessagesDialog(QDialog):
    """User-facing editor for the quick-message preset strip.

    Shape mirrors ContactsDialog: a single-column phrase table on top, an
    Add / Remove / Move-Up / Move-Down button row, and standard OK/Cancel
    buttons. Reordering is exposed because the strip respects the saved
    order (and the first nine slots map to Alt+1..Alt+9 shortcuts).
    """

    def __init__(self, current_messages, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Messages")
        self.setMinimumSize(520, 360)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "One-click preset phrases for the main dashboard. "
            "Use <code>{Name}</code> tokens for fill-in prompts "
            "(e.g. <code>QSY to channel {N}</code>). "
            "The first nine entries get Alt+1 through Alt+9 shortcuts.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, 1, self)
        self.table.setHorizontalHeaderLabels(["Phrase"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(True)
        self.table.setAccessibleName("Quick message presets")
        self.table.setAccessibleDescription(
            "Ordered list of preset phrases. Each row becomes a one-click "
            "button on the main dashboard."
        )
        layout.addWidget(self.table)

        self._populate(current_messages)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("&Add", self)
        self.add_btn.setToolTip("Append a new blank preset row.")
        self.add_btn.setAccessibleName("Add preset")
        self.add_btn.clicked.connect(self._add_row)
        btn_row.addWidget(self.add_btn)

        self.remove_btn = QPushButton("&Remove Selected", self)
        self.remove_btn.setToolTip("Delete the currently selected preset row.")
        self.remove_btn.setAccessibleName("Remove selected preset")
        self.remove_btn.clicked.connect(self._remove_row)
        btn_row.addWidget(self.remove_btn)

        self.up_btn = QPushButton("Move &Up", self)
        self.up_btn.setToolTip(
            "Move the selected preset one row up. Affects the dashboard "
            "order and which presets get the Alt+1..Alt+9 shortcuts."
        )
        self.up_btn.setAccessibleName("Move preset up")
        self.up_btn.clicked.connect(lambda: self._move_row(-1))
        btn_row.addWidget(self.up_btn)

        self.down_btn = QPushButton("Move &Down", self)
        self.down_btn.setToolTip("Move the selected preset one row down.")
        self.down_btn.setAccessibleName("Move preset down")
        self.down_btn.clicked.connect(lambda: self._move_row(1))
        btn_row.addWidget(self.down_btn)

        layout.addLayout(btn_row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _populate(self, messages):
        self.table.setRowCount(len(messages))
        for row, phrase in enumerate(messages):
            self.table.setItem(row, 0, QTableWidgetItem(phrase))

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))

    def _remove_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _move_row(self, delta):
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        # Swap the items, then move the selection so the user can keep nudging.
        a = self.table.item(row, 0)
        b = self.table.item(target, 0)
        a_text = a.text() if a else ""
        b_text = b.text() if b else ""
        self.table.setItem(row, 0, QTableWidgetItem(b_text))
        self.table.setItem(target, 0, QTableWidgetItem(a_text))
        self.table.setCurrentCell(target, 0)

    def get_quick_messages(self):
        """Return the edited list, skipping blank rows so the strip never
        shows an unlabeled button."""
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            phrase = (item.text() if item else "").strip()
            if phrase:
                result.append(phrase)
        return result
