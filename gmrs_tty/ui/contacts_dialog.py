from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from gmrs_tty.persistence.contacts import sort_contacts_by_suffix


class ContactsDialog(QDialog):
    """Dialog for managing known contacts."""

    def __init__(self, current_contacts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contact Management")
        self.setMinimumSize(560, 360)
        self.contacts = current_contacts

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Callsign", "Name", "Location"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName("Contacts table")
        self.table.setAccessibleDescription(
            "Callsign, name, and location for each known contact. Use Tab to edit cells."
        )
        layout.addWidget(self.table)

        self.populate_table()

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Contact")
        self.add_btn.clicked.connect(self.add_row)
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_row)
        self.sort_suffix_btn = QPushButton("Sort by &Suffix")
        self.sort_suffix_btn.setToolTip(
            "Reorder the table by the last 3 digits of each callsign. "
            "'ALL' stays at the top. View-only — clicking OK still saves "
            "the list alphabetically."
        )
        self.sort_suffix_btn.setAccessibleName("Sort contacts by callsign suffix")
        self.sort_suffix_btn.setAccessibleDescription(
            "Reorder the contacts table by the trailing digits of each callsign. "
            "Does not change how the list is saved."
        )
        self.sort_suffix_btn.clicked.connect(self.sort_by_suffix)

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addWidget(self.sort_suffix_btn)
        layout.addLayout(btn_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def populate_table(self):
        self.table.setRowCount(len(self.contacts))
        for row, contact in enumerate(self.contacts):
            self.table.setItem(row, 0, QTableWidgetItem(contact.get("callsign", "")))
            self.table.setItem(row, 1, QTableWidgetItem(contact.get("name", "")))
            self.table.setItem(row, 2, QTableWidgetItem(contact.get("location", "")))

    def add_row(self):
        row_pos = self.table.rowCount()
        self.table.insertRow(row_pos)
        self.table.setItem(row_pos, 0, QTableWidgetItem("NEW_CALL"))
        self.table.setItem(row_pos, 1, QTableWidgetItem("New Name"))
        self.table.setItem(row_pos, 2, QTableWidgetItem(""))

    def remove_row(self):
        selected = self.table.currentRow()
        if selected >= 0:
            self.table.removeRow(selected)

    def sort_by_suffix(self):
        """Reorder the table by the last 3 digits of each callsign. View-only —
        clicking OK still triggers the alphabetical save sort."""
        rows = []
        for row in range(self.table.rowCount()):
            call_item = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            loc_item = self.table.item(row, 2)
            rows.append({
                "callsign": call_item.text().strip() if call_item else "",
                "name": name_item.text().strip() if name_item else "",
                "location": loc_item.text().strip() if loc_item else "",
            })
        self.contacts = sort_contacts_by_suffix(rows)
        self.populate_table()

    def get_contacts(self):
        contacts = []
        for row in range(self.table.rowCount()):
            call_item = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            loc_item = self.table.item(row, 2)

            callsign = call_item.text().strip().upper() if call_item else ""
            name = name_item.text().strip() if name_item else ""
            location = loc_item.text().strip() if loc_item else ""

            if callsign:  # Only save rows that have a callsign
                contacts.append({"callsign": callsign, "name": name, "location": location})
        return contacts


class AddContactDialog(QDialog):
    """Compact dialog used when a new station is detected on RX."""

    def __init__(self, callsign, name, location, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Add Station: {callsign}")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)
        self.callsign_input = QLineEdit(callsign)
        self.name_input = QLineEdit(name)
        self.location_input = QLineEdit(location)
        layout.addRow("&Callsign:", self.callsign_input)
        layout.addRow("&Name:", self.name_input)
        layout.addRow("&Location:", self.location_input)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_contact(self):
        return {
            "callsign": self.callsign_input.text().strip().upper(),
            "name": self.name_input.text().strip(),
            "location": self.location_input.text().strip(),
        }
