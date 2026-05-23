from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDockWidget

from gmrs_tty.audio.spectro_worker import SpectrogramWorker
from gmrs_tty.constants import CONFIG_FILE
from gmrs_tty.persistence.json_store import save_json
from gmrs_tty.stt.worker import STTWorker
from gmrs_tty.ui import dock_layout, theme
from gmrs_tty.ui.dock_layout import CompactTitleBar
from gmrs_tty.ui.spectro_colormap import AVAILABLE_COLORMAPS
from gmrs_tty.ui.spectrogram_widget import (
    AVAILABLE_FREQ_RANGES, FREQ_RANGE_FULL, FREQ_RANGE_VOICE,
    SpectrogramWidget, SpectroSettings, TIME_WINDOWS_S,
)

if TYPE_CHECKING:
    from gmrs_tty.ui.main_window import MainWindow


class SpectrometerManager(QObject):
    """Owns the rolling-FFT waterfall: widget, worker, dock, and menu actions."""

    def __init__(self, window: "MainWindow", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.settings: SpectroSettings = SpectroSettings.from_config(window.config)
        self.widget: SpectrogramWidget | None = None
        self.worker: SpectrogramWorker | None = None
        self.dock: QDockWidget | None = None
        self._capture_event_hooked: bool = False
        self._toggle_action: QAction | None = None
        self._cmap_actions: dict = {}
        self._freq_actions: dict = {}
        self._window_actions: dict = {}

    def build_dock(self) -> QDockWidget:
        """Create the SpectrogramWidget and its hosting dock. Returns the dock."""
        window = self._window
        self.widget = SpectrogramWidget(
            sample_rate=STTWorker.SAMPLE_RATE,
            frame_size=1024,
            settings=self.settings,
            parent=window,
        )
        self.widget.activity_text_changed.connect(self._on_activity)

        dock = QDockWidget("Waterfall", window)
        dock.setObjectName(dock_layout.DOCK_WATERFALL)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setWidget(self.widget)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(window, dock)
        # Mirror the persistent View-menu toggle: a manual close of the
        # dock has to stop the FFT worker so we don't keep paying CPU on
        # an invisible widget.
        dock.visibilityChanged.connect(self._on_dock_visibility_changed)
        self.dock = dock
        return dock

    def install_menu_actions(self, view_menu) -> QAction:
        """Add a Waterfall submenu (toggle + option submenus) to view_menu.

        Returns the toggle QAction so MainWindow can store a reference for the
        Panels submenu dock-shortcut table (which skips the waterfall dock's
        own toggleViewAction in favour of this action)."""
        window = self._window
        waterfall_menu = view_menu.addMenu("&Waterfall")

        toggle_action = QAction("&Show waterfall", window)
        toggle_action.setCheckable(True)
        toggle_action.setChecked(self.settings.enabled)
        toggle_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        toggle_action.setStatusTip(
            "Toggle the rolling RX spectrometer (waterfall) below the chat."
        )
        toggle_action.triggered.connect(self.toggle)
        waterfall_menu.addAction(toggle_action)
        self._toggle_action = toggle_action

        waterfall_menu.addSeparator()

        freq_labels = {FREQ_RANGE_VOICE: "&Voice band (300–3400 Hz)",
                       FREQ_RANGE_FULL:  "&Full band (0–Nyquist)"}
        self._build_option_menu(
            waterfall_menu, "&Color map", AVAILABLE_COLORMAPS,
            label_fn=str.capitalize,
            checked_fn=lambda n: self.settings.colormap == n,
            setter_fn=self.set_colormap,
            actions_attr="_cmap_actions",
        )
        self._build_option_menu(
            waterfall_menu, "&Frequency range", AVAILABLE_FREQ_RANGES,
            label_fn=freq_labels.__getitem__,
            checked_fn=lambda k: self.settings.freq_range == k,
            setter_fn=self.set_freq_range,
            actions_attr="_freq_actions",
        )
        self._build_option_menu(
            waterfall_menu, "&Time window", TIME_WINDOWS_S,
            label_fn=lambda s: f"{s} seconds",
            checked_fn=lambda s: self.settings.time_window_s == s,
            setter_fn=self.set_time_window,
            actions_attr="_window_actions",
        )
        return toggle_action

    def toggle(self, checked: bool) -> None:
        self.settings.enabled = bool(checked)
        if self.widget is not None:
            self.widget.setVisible(self.settings.enabled)
        self.dock.setVisible(self.settings.enabled)
        if self.settings.enabled:
            # Mirror the STT lifecycle: if listening is active when the
            # operator turns the waterfall on, start the FFT worker too so
            # rows appear immediately rather than waiting for a Listen
            # toggle cycle.
            stt = self._window.stt_worker
            if stt is not None and stt.isRunning():
                self.start(stt)
        else:
            self.stop()
        self._persist()

    def set_colormap(self, name: str) -> None:
        self._apply_option(AVAILABLE_COLORMAPS, "colormap", "_cmap_actions", name)

    def set_freq_range(self, key: str) -> None:
        self._apply_option(AVAILABLE_FREQ_RANGES, "freq_range", "_freq_actions", key)

    def set_time_window(self, seconds) -> None:
        self._apply_option(TIME_WINDOWS_S, "time_window_s", "_window_actions", int(seconds))

    def start(self, stt_worker) -> None:
        """Spin up the FFT worker and wire it to the STT audio tap. Idempotent."""
        if not self.settings.enabled:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = SpectrogramWorker(
            sample_rate=STTWorker.SAMPLE_RATE,
            frame_size=1024,
            hop_size=512,
            parent=self._window,
        )
        self.worker.row_ready.connect(self.widget.push_row)
        if stt_worker is not None:
            stt_worker.audio_chunk.connect(self.worker.push_chunk)
            stt_worker.capture_event.connect(self.widget.mark_event)
            self._capture_event_hooked = True
        self.worker.start()

    def stop(self) -> None:
        """Tear down the FFT worker, disconnecting the STT tap first."""
        stt = self._window.stt_worker
        if stt is not None:
            try:
                stt.audio_chunk.disconnect(self.worker.push_chunk)
            except (TypeError, RuntimeError, AttributeError):
                pass
            if self._capture_event_hooked:
                try:
                    stt.capture_event.disconnect(self.widget.mark_event)
                except (TypeError, RuntimeError):
                    pass
                self._capture_event_hooked = False
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
            if worker.isRunning():
                worker.wait(2000)
            worker.deleteLater()

    def _on_dock_visibility_changed(self, visible: bool) -> None:
        if not self._window._ui_ready:
            return
        if visible == self.settings.enabled:
            return
        # Route through toggle so persistence + worker lifecycle stay in one place.
        self._toggle_action.setChecked(visible)
        self.toggle(visible)

    def _on_activity(self, text: str) -> None:
        if self.settings.enabled:
            self._window.statusBar().showMessage(f"Waterfall: {text}", 2500)

    def _persist(self) -> None:
        self._window.config["spectrometer"] = self.settings.to_config()
        save_json(CONFIG_FILE, self._window.config)

    def _build_option_menu(self, parent_menu, title, options,
                           label_fn, checked_fn, setter_fn, actions_attr):
        menu = parent_menu.addMenu(title)
        actions = {}
        for opt in options:
            act = QAction(label_fn(opt), self._window)
            act.setCheckable(True)
            act.setChecked(checked_fn(opt))
            act.triggered.connect(lambda _checked=False, v=opt: setter_fn(v))
            menu.addAction(act)
            actions[opt] = act
        setattr(self, actions_attr, actions)
        return menu

    def _apply_option(self, valid_set, attr, actions_attr, value) -> None:
        if value not in valid_set:
            return
        setattr(self.settings, attr, value)
        for k, act in getattr(self, actions_attr).items():
            act.setChecked(k == value)
        if self.widget is not None:
            self.widget.apply_settings(self.settings)
        self._persist()
