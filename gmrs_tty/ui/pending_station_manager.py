from __future__ import annotations

import logging
from typing import TYPE_CHECKING

_log = logging.getLogger(__name__)

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QDockWidget, QFrame, QHBoxLayout, QMenu, QPushButton, QScrollArea, QWidget,
)

from gmrs_tty.constants import CONTACTS_FILE, SERVICE_FRS, utc_now_iso
from gmrs_tty.net.online import is_online
from gmrs_tty.persistence.contacts import (
    deduplicate_ham_cross_references,
    known_callsigns,
    sort_contacts,
)
from gmrs_tty.persistence.json_store import save_json
from gmrs_tty.text.callsigns import detect_callsigns, fuzzy_match_callsign
from gmrs_tty.text.metadata import extract_name_location
from gmrs_tty.ui import dock_layout, theme
from gmrs_tty.ui.contacts_dialog import AddContactDialog
from gmrs_tty.ui.dock_layout import CompactTitleBar
from gmrs_tty.ui.flow_layout import FlowLayout

if TYPE_CHECKING:
    from gmrs_tty.ui.main_window import MainWindow

PENDING_PILL_MAX_ROWS = 3
_MAX_PENDING_LOOKUPS = 50


class PendingStationManager(QObject):
    """Owns the pending-stations dock, pill widgets, and FCC auto-add lookups."""

    def __init__(self, window: "MainWindow", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.buttons: dict = {}         # callsign → QPushButton
        self._lookups: dict = {}        # callsign → CallsignLookupWorker
        self._row_height: int | None = None
        # UI elements — populated by build_dock()
        self.dock: QDockWidget | None = None
        self.scroll: QScrollArea | None = None
        self.pills_widget: QWidget | None = None
        self.flow: FlowLayout | None = None
        self.clear_btn: QPushButton | None = None

    def build_dock(self) -> QDockWidget:
        window = self._window
        content = QWidget(window)
        bar = QHBoxLayout(content)
        bar.setContentsMargins(theme.SPACING_S, theme.SPACING_XS, theme.SPACING_S, theme.SPACING_XS)
        bar.setSpacing(theme.SPACING_S)

        self.pills_widget = QWidget(content)
        self.flow = FlowLayout(self.pills_widget, margin=0, spacing=theme.SPACING_S)

        self.scroll = QScrollArea(content)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setWidget(self.pills_widget)
        self.scroll.hide()
        bar.addWidget(self.scroll, 1)

        self.clear_btn = QPushButton("&Dismiss all", content)
        self.clear_btn.setToolTip(
            "Dismiss every pending station pill without adding any callsigns."
        )
        self.clear_btn.setAccessibleName("Dismiss all pending stations")
        self.clear_btn.setAccessibleDescription(
            "Remove every pending station pill without adding any of the detected callsigns to contacts."
        )
        self.clear_btn.clicked.connect(self.clear_all_pills)
        self.clear_btn.hide()
        bar.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignTop)

        dock = QDockWidget("Pending Stations", window)
        dock.setObjectName(dock_layout.DOCK_PENDING)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setWidget(content)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(window, dock)
        self.dock = dock
        return dock

    # ---- Public API --------------------------------------------------------

    def scan_for_unknown_stations(self, text: str) -> None:
        window = self._window
        if window._service_mode() == SERVICE_FRS:
            # FRS users don't carry callsigns — detection would only generate
            # noise pills for anyone speaking a callsign on a shared FRS/GMRS
            # frequency, which the operator can't act on usefully.
            return
        my_call = window.config.callsign
        known = known_callsigns(window.contacts)
        detected = detect_callsigns(text)
        # Online state is cached for ~60s so this is cheap; capture once per
        # scan so a single utterance picks a consistent verdict for every
        # callsign it surfaces.
        online = is_online()
        fuzzy_on = window.config.fuzzy_callsign
        for cs in detected:
            # Attendance recording runs *before* the unknown/known split so
            # the grid logs every detected station regardless of whether
            # the operator already has them saved.
            canonical = cs
            if fuzzy_on:
                match = fuzzy_match_callsign(cs, known)
                if match:
                    canonical = match
            if window.attendance_enabled and window.attendance_panel is not None and canonical != my_call:
                window.attendance_panel.record(canonical)

            if cs == my_call or cs in known or cs in self.buttons:
                continue
            if fuzzy_on and fuzzy_match_callsign(cs, known):
                continue
            name, location = extract_name_location(text, cs)
            self.add_pending_station(cs, name, location)
            if online and name and cs not in self._lookups:
                self._start_callsign_lookup(cs, name, location)

    def add_pending_station(self, callsign: str, name: str, location: str) -> None:
        btn = QPushButton(f"+ Add {callsign}", self._window)
        btn.setStyleSheet(theme.pill_stylesheet())
        tooltip_parts = [f"Detected new station: {callsign}"]
        if name:
            tooltip_parts.append(f"Name: {name}")
        if location:
            tooltip_parts.append(f"Location: {location}")
        tooltip_parts.append("Right-click to dismiss without adding.")
        btn.setToolTip("\n".join(tooltip_parts))
        btn.setAccessibleName(f"Add station {callsign}")
        descr = f"Open the Add Station dialog prefilled for callsign {callsign}"
        if name:
            descr += f", operator {name}"
        if location:
            descr += f", location {location}"
        descr += ". Right-click or long-press to dismiss without adding."
        btn.setAccessibleDescription(descr)
        btn.clicked.connect(
            lambda _checked=False, cs=callsign, n=name, loc=location:
                self.open_add_contact_dialog(cs, n, loc)
        )
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, cs=callsign, b=btn: self._show_pill_menu(b, pos, cs)
        )
        self.buttons[callsign] = btn
        self.flow.addWidget(btn)
        self._cap_scroll_height(btn)
        self._update_visibility()

    def remove_pill(self, callsign: str) -> None:
        btn = self.buttons.pop(callsign, None)
        if btn is not None:
            btn.setParent(None)
            btn.deleteLater()
        self._update_visibility()

    def clear_all_pills(self) -> None:
        for callsign in list(self.buttons.keys()):
            self.remove_pill(callsign)

    def apply_service_mode(self, is_frs: bool) -> None:
        """Sync pending-dock visibility with the active service mode."""
        if is_frs:
            self.clear_all_pills()
        self.scroll.setVisible(not is_frs and bool(self.buttons))
        self.clear_btn.setVisible(not is_frs and bool(self.buttons))
        self.dock.setVisible(not is_frs and bool(self.buttons))

    def restyle_pills(self) -> None:
        """Repaint all live pills with the current theme stylesheet."""
        for btn in self.buttons.values():
            btn.setStyleSheet(theme.pill_stylesheet())

    def open_add_contact_dialog(self, callsign: str, name: str, location: str) -> None:
        window = self._window
        dlg = AddContactDialog(callsign, name, location, window)
        if dlg.exec():
            contact = dlg.get_contact()
            if not contact["callsign"]:
                return
            contact = self._verify_contact_if_online(contact)
            for c in window.contacts:
                if c.get("callsign", "").upper() == contact["callsign"]:
                    c.update(contact)
                    break
            else:
                window.contacts.append(contact)
            window.contacts = sort_contacts(deduplicate_ham_cross_references(window.contacts))
            save_json(CONTACTS_FILE, window.contacts)
            window.populate_target_dropdown()
            window._refresh_callsign_index()
        self.remove_pill(callsign)

    def disconnect_workers(self) -> None:
        """Disconnect and drain in-flight FCC lookups. Called from closeEvent."""
        for cs, worker in list(self._lookups.items()):
            try:
                worker.result_ready.disconnect()
            except (TypeError, RuntimeError):
                pass
            if worker.isRunning():
                worker.wait(100)
        self._lookups.clear()

    # ---- Private -----------------------------------------------------------

    def _start_callsign_lookup(self, callsign: str, name: str, location: str) -> None:
        if len(self._lookups) >= _MAX_PENDING_LOOKUPS:
            _log.warning("Pending lookup cap reached (%d); skipping FCC lookup for %s.",
                         _MAX_PENDING_LOOKUPS, callsign)
            return
        from gmrs_tty.fcc.auto_add import CallsignLookupWorker
        worker = CallsignLookupWorker(callsign, name, location, parent=self._window)
        worker.result_ready.connect(self._on_lookup_result)
        worker.finished.connect(lambda cs=callsign: self._cleanup_lookup(cs))
        self._lookups[callsign] = worker
        worker.start()

    def _cleanup_lookup(self, callsign: str) -> None:
        worker = self._lookups.pop(callsign, None)
        if worker is not None:
            worker.deleteLater()

    def _on_lookup_result(self, callsign, name, location, result) -> None:
        window = self._window
        if result.status != "verified":
            return
        if callsign in known_callsigns(window.contacts):
            self.remove_pill(callsign)
            return
        if callsign not in self.buttons:
            return
        from gmrs_tty.fcc.crossref import apply_verification
        contact = {"callsign": callsign, "name": name, "location": location}
        now_iso = utc_now_iso()
        contact = apply_verification(contact, result, now_iso=now_iso)
        window.contacts.append(contact)
        window.contacts = sort_contacts(deduplicate_ham_cross_references(window.contacts))
        save_json(CONTACTS_FILE, window.contacts)
        window.populate_target_dropdown()
        window._refresh_callsign_index()
        self.remove_pill(callsign)
        op_name = (contact.get("name") or "").strip() or "(no name)"
        window.append_to_chat(
            f"<i>Auto-added contact: {callsign} ({op_name})</i>",
            color=theme.palette().rx,
        )

    def _show_pill_menu(self, btn, pos, callsign: str) -> None:
        menu = QMenu(self._window)
        dismiss_action = menu.addAction(f"Dismiss {callsign}")
        dismiss_action.setStatusTip(
            f"Remove the pending pill for {callsign} without adding it to contacts."
        )
        if menu.exec(btn.mapToGlobal(pos)) is dismiss_action:
            self.remove_pill(callsign)

    def _update_visibility(self) -> None:
        has_pills = bool(self.buttons)
        self.clear_btn.setVisible(has_pills)
        self.scroll.setVisible(has_pills)
        if self._window._service_mode() != SERVICE_FRS:
            self.dock.setVisible(has_pills)

    def _cap_scroll_height(self, sample_btn) -> None:
        if self._row_height is not None:
            return
        row_h = sample_btn.sizeHint().height()
        if row_h <= 0:
            return
        spacing = max(self.flow.spacing(), 0)
        rows = PENDING_PILL_MAX_ROWS
        max_h = rows * row_h + (rows - 1) * spacing
        self.scroll.setMaximumHeight(max_h)
        self._row_height = row_h

    def _verify_contact_if_online(self, contact: dict) -> dict:
        from gmrs_tty.fcc.crossref import apply_verification, verify_callsign
        if not is_online():
            return contact
        result = verify_callsign(contact["callsign"], contact.get("name", ""))
        now_iso = utc_now_iso()
        return apply_verification(contact, result, now_iso=now_iso)
