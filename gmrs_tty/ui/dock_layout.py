"""Dockable-panel layout management for MainWindow.

The main window is built around ``QMainWindow``'s dock system: every
operator-facing panel (Station info, Pending stations, Quick messages,
Waterfall, Transmit) is a ``QDockWidget`` the user can drag, float,
tab, or hide. This module owns:

* Stable ``objectName`` constants — required by Qt's
  ``saveState``/``restoreState`` so positions survive a relaunch.
* A schema version so structural changes (added / removed / renamed
  docks) discard old state instead of silently corrupting the UI.
* ``CompactTitleBar`` — a ~14 px replacement for Qt's default ~24 px
  dock chrome. Five docks would otherwise burn ~120 px of vertical
  space versus the old stacked layout.
* ``install_dock_context_menu`` — keyboard-accessible Move-to / Float /
  Close menu on every dock title bar. This is the a11y path for
  operators who cannot drag with a mouse.
* ``cycle_dock_focus`` — F6 / Shift+F6 to walk focus across docks.
* ``build_default_layout`` / ``save_layout`` / ``restore_layout`` — the
  first-launch arrangement plus a base64 round-trip through
  ``config.json["ui_layout"]``.

Layout state is persisted lazily on ``closeEvent`` so we don't churn
``config.json`` every time the operator nudges a splitter.
"""
from __future__ import annotations

import base64
from typing import Optional

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QSizePolicy, QToolButton, QWidget,
)

from gmrs_tty.ui import theme


DEFAULT_LAYOUT_VERSION = 1

# Stable object names. Qt's saveState/restoreState matches docks by
# objectName, so renaming any of these breaks state restoration — bump
# DEFAULT_LAYOUT_VERSION in lockstep so the corrupt state is discarded.
DOCK_STATION = "dock.station"
DOCK_PENDING = "dock.pending"
DOCK_QUICK = "dock.quick"
DOCK_WATERFALL = "dock.waterfall"
DOCK_TRANSMIT = "dock.transmit"
TOOLBAR_SERVICE = "toolbar.service"

# Iteration order used by the F6 focus-cycle and the View menu's "show
# every dock" reset path. Order roughly matches a top-to-bottom read of
# the default layout.
ALL_DOCK_NAMES = (
    DOCK_STATION,
    DOCK_WATERFALL,
    DOCK_PENDING,
    DOCK_QUICK,
    DOCK_TRANSMIT,
)


class CompactTitleBar(QWidget):
    """Slim (~14 px) replacement for ``QDockWidget``'s default title bar.

    Qt's stock title bar is ~24 px tall; with five docks that is ~120 px
    of vertical real estate spent on chrome. The compact bar shows the
    panel name, a float/redock toggle, and (if the dock is closable) a
    hide button — same affordances, less weight. Focus policy is
    ``StrongFocus`` so keyboard users can land here via F6 and then open
    the Move-to menu with the Menu key / Shift+F10.
    """

    def __init__(self, dock: QDockWidget) -> None:
        super().__init__(dock)
        self.setObjectName("dockTitleBar")
        self._dock = dock
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACING_S, 1, theme.SPACING_XS, 1)
        layout.setSpacing(theme.SPACING_XS)

        self._label = QLabel(dock.windowTitle(), self)
        self._label.setFont(theme.font_emphasis())
        layout.addWidget(self._label)
        layout.addStretch(1)

        self._float_btn = QToolButton(self)
        self._float_btn.setText("⧉")  # ⧉ two squares glyph (text-presentation)
        self._float_btn.setAutoRaise(True)
        self._float_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._float_btn.setToolTip("Float or re-dock this panel")
        self._float_btn.setAccessibleName(f"Float {dock.windowTitle()}")
        self._float_btn.clicked.connect(self._toggle_float)
        layout.addWidget(self._float_btn)

        self._close_btn: Optional[QToolButton] = None
        if dock.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable:
            self._close_btn = QToolButton(self)
            self._close_btn.setText("✕")  # ✕ multiplication X (text-presentation)
            self._close_btn.setAutoRaise(True)
            self._close_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self._close_btn.setToolTip("Hide this panel (View menu re-shows it)")
            self._close_btn.setAccessibleName(f"Hide {dock.windowTitle()}")
            self._close_btn.clicked.connect(dock.hide)
            layout.addWidget(self._close_btn)

        dock.windowTitleChanged.connect(self._on_title_changed)
        self.setStyleSheet(theme.dock_title_stylesheet())

    def _on_title_changed(self, title: str) -> None:
        self._label.setText(title)
        self._float_btn.setAccessibleName(f"Float {title}")
        if self._close_btn is not None:
            self._close_btn.setAccessibleName(f"Hide {title}")

    def _toggle_float(self) -> None:
        self._dock.setFloating(not self._dock.isFloating())

    def refresh_palette(self) -> None:
        """Re-apply the title-bar stylesheet after a theme toggle."""
        self.setStyleSheet(theme.dock_title_stylesheet())


class _DockContextMenuFilter(QObject):
    """Event filter that surfaces a keyboard-accessible Move-to menu on
    every dock title bar.

    Keyboard users press the Menu key or Shift+F10 while a title bar has
    focus; mouse users right-click. Both routes funnel through Qt's
    ``QEvent.ContextMenu`` event, which this filter intercepts.
    """

    def __init__(self, window: QMainWindow, dock: QDockWidget) -> None:
        super().__init__(dock)
        self._window = window
        self._dock = dock

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu:
            pos = event.globalPos() if event.globalPos() is not None else QPoint(0, 0)
            self._show_menu(pos)
            return True
        return False

    def _show_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self._dock)

        def add_move(label: str, area: Qt.DockWidgetArea) -> None:
            act = QAction(label, menu)
            act.triggered.connect(
                lambda _checked=False, a=area: self._window.addDockWidget(a, self._dock)
            )
            menu.addAction(act)

        add_move("Move to &Left", Qt.DockWidgetArea.LeftDockWidgetArea)
        add_move("Move to &Right", Qt.DockWidgetArea.RightDockWidgetArea)
        add_move("Move to &Top", Qt.DockWidgetArea.TopDockWidgetArea)
        add_move("Move to &Bottom", Qt.DockWidgetArea.BottomDockWidgetArea)
        menu.addSeparator()

        float_label = "Re-&dock" if self._dock.isFloating() else "&Float"
        float_action = QAction(float_label, menu)
        float_action.triggered.connect(
            lambda _checked=False: self._dock.setFloating(not self._dock.isFloating())
        )
        menu.addAction(float_action)

        if self._dock.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable:
            menu.addSeparator()
            close_action = QAction("&Hide panel", menu)
            close_action.triggered.connect(self._dock.hide)
            menu.addAction(close_action)

        menu.exec(global_pos)


def install_dock_context_menu(window: QMainWindow, dock: QDockWidget) -> None:
    """Attach the Move-to / Float / Hide context menu to ``dock``'s title bar.

    The filter is parented to the dock so it dies with the dock; the
    title-bar widget gets ``setContextMenuPolicy(DefaultContextMenu)`` so
    Qt routes right-clicks and Menu-key presses through ``eventFilter``.
    """
    title_bar = dock.titleBarWidget()
    if title_bar is None:
        return
    title_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
    flt = _DockContextMenuFilter(window, dock)
    title_bar.installEventFilter(flt)


def cycle_dock_focus(window: QMainWindow, forward: bool = True) -> None:
    """Move keyboard focus to the next (or previous) visible dock title bar.

    Bound to F6 / Shift+F6 by the main window. Operators who cannot drag
    with a mouse use this to navigate to a panel's title bar, then press
    the Menu key to open the Move-to / Float / Hide menu.
    """
    docks = [
        d for d in window.findChildren(QDockWidget)
        if d.objectName() in ALL_DOCK_NAMES and d.isVisible()
    ]
    if not docks:
        return
    bars = [d.titleBarWidget() for d in docks if d.titleBarWidget() is not None]
    bars = [b for b in bars if b is not None]
    if not bars:
        return
    app = QApplication.instance()
    current = app.focusWidget() if app is not None else None
    try:
        idx = bars.index(current) if current in bars else -1
    except ValueError:
        idx = -1
    step = 1 if forward else -1
    next_bar = bars[(idx + step) % len(bars)]
    next_bar.setFocus(Qt.FocusReason.ShortcutFocusReason)


def build_default_layout(window: QMainWindow) -> None:
    """Apply the first-launch dock arrangement.

    Mimics the old stacked vertical order so existing muscle memory
    survives the upgrade: Station header docked at the top of the main
    area, Pending and Quick Messages tabbed together at the bottom,
    Transmit pinned underneath them, and the Waterfall hidden by default
    (it honors ``spectrometer.enabled`` independently of saved state).
    """
    docks = {d.objectName(): d for d in window.findChildren(QDockWidget)}

    station = docks.get(DOCK_STATION)
    waterfall = docks.get(DOCK_WATERFALL)
    pending = docks.get(DOCK_PENDING)
    quick = docks.get(DOCK_QUICK)
    transmit = docks.get(DOCK_TRANSMIT)

    if station is not None:
        window.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, station)
        station.setFloating(False)
        station.show()

    if waterfall is not None:
        window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, waterfall)
        waterfall.setFloating(False)
        # Visibility follows spectrometer.enabled; MainWindow re-applies
        # that after this call so we don't fight it here.

    if pending is not None:
        window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, pending)
        pending.setFloating(False)
        pending.show()

    if quick is not None:
        window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, quick)
        quick.setFloating(False)
        quick.show()
        if pending is not None:
            window.tabifyDockWidget(pending, quick)
            pending.raise_()

    if transmit is not None:
        window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, transmit)
        transmit.setFloating(False)
        transmit.show()


def save_layout(window: QMainWindow, config: dict) -> None:
    """Capture dock placements + window geometry into ``config["ui_layout"]``.

    ``saveState`` requires a version int — bump in lockstep with
    ``DEFAULT_LAYOUT_VERSION`` so a structural change forces a discard
    on next load instead of restoring into the wrong shape.
    """
    state = bytes(window.saveState(DEFAULT_LAYOUT_VERSION))
    geom = bytes(window.saveGeometry())
    config["ui_layout"] = {
        "version": DEFAULT_LAYOUT_VERSION,
        "state_b64": base64.b64encode(state).decode("ascii"),
        "geometry_b64": base64.b64encode(geom).decode("ascii"),
    }


def restore_layout(window: QMainWindow, config: dict) -> bool:
    """Restore dock placements from ``config["ui_layout"]``.

    Returns True when the saved state was applied, False when it was
    missing, malformed, or written under a different schema version
    (caller falls back to ``build_default_layout``).
    """
    saved = config.get("ui_layout")
    if not isinstance(saved, dict):
        return False
    if saved.get("version") != DEFAULT_LAYOUT_VERSION:
        return False
    state_b64 = saved.get("state_b64")
    geometry_b64 = saved.get("geometry_b64")
    if not isinstance(state_b64, str) or not isinstance(geometry_b64, str):
        return False
    try:
        state = QByteArray(base64.b64decode(state_b64.encode("ascii")))
        geometry = QByteArray(base64.b64decode(geometry_b64.encode("ascii")))
    except (ValueError, TypeError):
        return False
    if not window.restoreGeometry(geometry):
        return False
    if not window.restoreState(state, DEFAULT_LAYOUT_VERSION):
        return False
    return True
