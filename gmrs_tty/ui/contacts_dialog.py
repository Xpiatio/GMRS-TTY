import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from gmrs_tty.fcc.crossref import apply_verification, verify_callsign
from gmrs_tty.net.online import is_online
from gmrs_tty.persistence.contacts import sort_contacts_by_suffix

VERIFIED_COL = 3
VERIFIED_GLYPH = "✓"
VERIFIED_COLOR = "#15803D"  # green-700, matches COLOR_RX (≥4.5:1 on white)


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _verified_cell(contact):
    """Build the verified-column QTableWidgetItem for `contact`. Returns a
    non-editable cell whose appearance + accessibility text encode the verified
    flag without relying on color alone."""
    verified = bool(contact.get("verified"))
    text = VERIFIED_GLYPH if verified else ""
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if verified:
        item.setForeground(QBrush(QColor(VERIFIED_COLOR)))
        tip_lines = ["Verified against FCC database."]
        if contact.get("license_name"):
            tip_lines.append(f"Licensee: {contact['license_name']}")
        if contact.get("gmrs_callsign"):
            tip_lines.append(f"GMRS: {contact['gmrs_callsign']}")
        if contact.get("ham_callsign"):
            tip_lines.append(f"HAM: {contact['ham_callsign']}")
        if contact.get("verified_at"):
            tip_lines.append(f"Checked: {contact['verified_at']}")
        item.setToolTip("\n".join(tip_lines))
    else:
        tip_lines = ["Not yet verified."]
        if contact.get("license_name"):
            tip_lines = [
                f"FCC license is held by {contact['license_name']}, "
                "which doesn't match this contact's name."
            ]
        # GMRS / HAM cross-references are useful context even when name
        # didn't match — e.g. a family-member row on a shared callsign still
        # benefits from showing the licensee's HAM call.
        if contact.get("gmrs_callsign"):
            tip_lines.append(f"GMRS: {contact['gmrs_callsign']}")
        if contact.get("ham_callsign"):
            tip_lines.append(f"HAM: {contact['ham_callsign']}")
        item.setToolTip("\n".join(tip_lines))
    return item


class ContactsDialog(QDialog):
    """Dialog for managing known contacts.

    Verification is an online feature: when the network probe says we're
    offline, the Verify-all button disables and verification is skipped on
    save. Previously-saved verification state survives an offline session
    untouched."""

    def __init__(self, current_contacts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contact Management")
        self.setMinimumSize(640, 360)
        # Defensive copy so we can compare each row to its original state when
        # deciding what to re-verify on save.
        self.contacts = [dict(c) for c in current_contacts]
        self._online = is_online()

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Callsign", "Name", "Location", "Verified"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(VERIFIED_COL, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAccessibleName("Contacts table")
        self.table.setAccessibleDescription(
            "Callsign, name, location, and FCC-verified status for each known "
            "contact. Use Tab to edit cells. Verified rows are marked with a "
            "green check after a successful FCC database lookup."
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

        # Mnemonic 'V' rather than 'a' or 'l' so it reads naturally alongside
        # the sibling buttons (Add Contact, Remove Selected, Sort by Suffix).
        self.verify_all_btn = QPushButton("&Verify all")
        self.verify_all_btn.setAccessibleName("Verify all callsigns against FCC database")
        self.verify_all_btn.clicked.connect(self.verify_all)
        self._apply_online_state()

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addWidget(self.sort_suffix_btn)
        btn_layout.addWidget(self.verify_all_btn)
        layout.addLayout(btn_layout)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _apply_online_state(self):
        self.verify_all_btn.setEnabled(self._online)
        if self._online:
            self.verify_all_btn.setToolTip(
                "Look up every callsign in the FCC database and update verified status."
            )
        else:
            self.verify_all_btn.setToolTip(
                "Verification is unavailable — the app is offline. "
                "Reconnect to re-enable FCC lookups."
            )

    def populate_table(self):
        self.table.setRowCount(len(self.contacts))
        for row, contact in enumerate(self.contacts):
            self._render_row(row, contact)

    def _render_row(self, row, contact):
        self.table.setItem(row, 0, QTableWidgetItem(contact.get("callsign", "")))
        self.table.setItem(row, 1, QTableWidgetItem(contact.get("name", "")))
        self.table.setItem(row, 2, QTableWidgetItem(contact.get("location", "")))
        self.table.setItem(row, VERIFIED_COL, _verified_cell(contact))

    def add_row(self):
        row_pos = self.table.rowCount()
        self.contacts.append({"callsign": "NEW_CALL", "name": "New Name", "location": ""})
        self.table.insertRow(row_pos)
        self._render_row(row_pos, self.contacts[-1])

    def remove_row(self):
        selected = self.table.currentRow()
        if selected >= 0:
            self.table.removeRow(selected)
            if 0 <= selected < len(self.contacts):
                self.contacts.pop(selected)

    def sort_by_suffix(self):
        """Reorder the table by the last 3 digits of each callsign. View-only —
        clicking OK still triggers the alphabetical save sort. Preserves the
        per-row verification metadata so a sort doesn't drop green checks."""
        self.contacts = sort_contacts_by_suffix(self._read_rows_from_table())
        self.populate_table()

    def _read_rows_from_table(self):
        """Snapshot the editable cells back into dicts, but merge in any
        non-editable metadata (verified, verified_at, license_name) carried by
        the in-memory `self.contacts` so a round-trip through the table doesn't
        wipe the green check. Matching is by row index — fine because we never
        reorder `self.contacts` without re-rendering."""
        rows = []
        for row in range(self.table.rowCount()):
            call_item = self.table.item(row, 0)
            name_item = self.table.item(row, 1)
            loc_item = self.table.item(row, 2)
            base = dict(self.contacts[row]) if row < len(self.contacts) else {}
            base["callsign"] = call_item.text().strip() if call_item else ""
            base["name"] = name_item.text().strip() if name_item else ""
            base["location"] = loc_item.text().strip() if loc_item else ""
            rows.append(base)
        return rows

    def verify_all(self):
        """Re-verify every row against the FCC database. Skips the run with no
        message when offline (the button is also disabled — this is belt-and-
        suspenders for keyboard activation)."""
        if not is_online():
            self._online = False
            self._apply_online_state()
            return
        rows = self._read_rows_from_table()
        now = _now_iso()
        for idx, contact in enumerate(rows):
            cs = (contact.get("callsign") or "").upper()
            if not cs or cs == "ALL":
                continue
            result = verify_callsign(cs, contact.get("name", ""))
            rows[idx] = apply_verification(contact, result, now_iso=now)
        self.contacts = rows
        self.populate_table()

    def get_contacts(self):
        """Hand the current rows back to the caller, re-verifying any row that
        was edited (or never verified) when online. Drops empty-callsign rows.

        Re-verify policy:
          • Skip 'ALL' (it's the broadcast shortcut, not a station).
          • When offline, never verify — preserve whatever flags were on disk.
          • Otherwise, verify if (a) callsign/name changed, or (b) no prior
            verified_at timestamp. Cached verifications survive untouched.
        """
        rows = self._read_rows_from_table()
        online = is_online()
        if not online:
            self._online = False
            self._apply_online_state()

        now = _now_iso()
        out = []
        # Build a lookup keyed by row index into the *original* contacts so we
        # can tell whether a row was edited.
        for idx, current in enumerate(rows):
            callsign = (current.get("callsign") or "").strip().upper()
            if not callsign:
                continue
            current["callsign"] = callsign
            if online and callsign != "ALL":
                if self._needs_reverify(idx, current):
                    result = verify_callsign(callsign, current.get("name", ""))
                    current = apply_verification(current, result, now_iso=now)
            out.append(current)
        return out

    def _needs_reverify(self, row_index, current):
        """Decide if `current` differs from the row we initially loaded enough
        to invalidate any cached verification. Rows that never had a
        verified_at also get re-verified so newly-added contacts pick up a
        check on first save."""
        original = self.contacts[row_index] if row_index < len(self.contacts) else {}
        if not original.get("verified_at"):
            return True
        return (
            (original.get("callsign") or "").upper() != (current.get("callsign") or "").upper()
            or (original.get("name") or "") != (current.get("name") or "")
        )


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
