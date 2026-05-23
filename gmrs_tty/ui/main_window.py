import datetime
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDockWidget, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QRadioButton, QSizePolicy,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from gmrs_tty.config import AppConfig
from gmrs_tty.ui.tx_controller import TXController
from gmrs_tty.audio.monitor import AudioMonitor
from gmrs_tty.constants import (
    CONFIG_FILE, CONTACTS_FILE,
    SERVICE_FRS, SERVICE_GMRS, normalize_service,
    utc_now_iso,
)
from gmrs_tty.fcc.id_rule import format_outgoing_message, format_standalone_id
from gmrs_tty.net.online import is_online
from gmrs_tty.persistence.contacts import (
    deduplicate_ham_cross_references,
    index_contacts_by_callsign,
    known_callsigns,
    sort_contacts,
)
from gmrs_tty.persistence.json_store import load_json, save_json
from gmrs_tty.ptt import make_ptt
from gmrs_tty.stt.worker import ModelCache, STTWorker
from gmrs_tty.text.callsigns import spell_digits_in_callsigns
from gmrs_tty.text.profanity import mask_profanity
from gmrs_tty.text.placeholders import find_placeholders, substitute_placeholders

from gmrs_tty.ui import theme
from gmrs_tty.ui import dock_layout
from gmrs_tty.ui.attendance_panel import AttendancePanel
from gmrs_tty.ui.chat_display import ChatDisplay
from gmrs_tty.ui.config_dialog import ConfigDialog
from gmrs_tty.ui.contacts_dialog import ContactsDialog
from gmrs_tty.ui.dock_layout import CompactTitleBar
from gmrs_tty.ui.flow_layout import FlowLayout
from gmrs_tty.ui.journal_controller import JournalController
from gmrs_tty.ui.pending_station_manager import PendingStationManager
from gmrs_tty.ui.quick_messages_dialog import QuickMessagesDialog
from gmrs_tty.ui.rx_session import RXSession
from gmrs_tty.ui.spectro_manager import SpectrometerManager

PENDING_PILL_MAX_ROWS = 3
QUICK_MESSAGE_SHORTCUT_COUNT = 9
# How often we re-probe the network for the online indicator. Long enough that
# the probe (cached at the net layer with PROBE_TTL_SECONDS) is essentially a
# no-op between fires, short enough that a router reboot is reflected in well
# under a minute.
ONLINE_REFRESH_MS = 30_000

ONLINE_LABEL_ONLINE = "● Online"
ONLINE_LABEL_OFFLINE = "○ Offline"

# Theme-toggle glyphs. The icon shows the *destination* state — when the
# user is in light mode, the moon invites them to switch to dark; once in
# dark mode the sun invites the return trip. Mirrors the GitHub / Twitter
# convention so the cue reads as "click to become this" rather than
# "you are this".
THEME_GLYPH_TO_DARK = "\U0001F319"   # 🌙 crescent moon
THEME_GLYPH_TO_LIGHT = "☀️"  # ☀️ sun


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GMRS-TTY")
        # Slightly larger default than the pre-dock layout so the operator
        # has elbow room for the bottom-area dock stack without immediate
        # resizing. Persisted geometry restores over this on subsequent
        # launches via dock_layout.restore_layout.
        self.resize(960, 720)

        # State Initialization
        self.config = AppConfig(load_json(CONFIG_FILE, {}))
        self.contacts = sort_contacts(deduplicate_ham_cross_references(
            load_json(CONTACTS_FILE, [{"callsign": "All", "name": "Everyone"}])
        ))
        self.last_tx_time = None

        self.stt_worker = None
        # Listen-only / RX-only safety toggle. When True, every TX path
        # (Transmit button, "This is" ID, Enter on message-input,
        # quick-message presets, Ctrl+Return / Ctrl+I / Alt+1..9 shortcuts)
        # is short-circuited at the `_transmit_text` / `transmit_id_only`
        # entry points so a stray keystroke or hotkey can't push audio
        # on-air. Persists across launches via config["listen_only"].
        self.listen_only = self.config.listen_only
        # Quick-message preset buttons; rebuilt by populate_quick_messages_strip.
        # Held on self so the listen-only refresh can flip their enabled state.
        self._quick_message_buttons = []
        # Reused across Listen toggles so we don't pay the ~1–3s Whisper
        # load on every restart. Invalidated when whisper_model changes.
        self._stt_model_cache: ModelCache | None = None
        # Streaming-RX session: long utterances arrive as multiple partial
        # transcription_segment signals. RXSession tracks the open line,
        # growing it in-place, and fires scan_for_unknown_stations on
        # utterance completion. Built lazily after init_ui so chat_display
        # and _format_timestamp are both available; see _make_rx_session().
        self._rx_session: RXSession | None = None
        self.pending_manager = PendingStationManager(self, parent=self)
        self.tx = TXController(make_ptt(self.config), parent=self)
        self.tx.tx_busy_changed.connect(self._on_tx_busy_changed)
        self.tx.chat_message.connect(self.append_to_chat)
        self.tx.stt_pause_requested.connect(self._pause_stt_for_tx)
        self.tx.stt_resume_requested.connect(self._resume_stt_after_tx)
        self._monitor = AudioMonitor()
        self.spectro_manager = SpectrometerManager(self, parent=self)
        # Attendance grid: feature flag persists at ``attendance.enabled``
        # (default off) so the panel + RX-side recording are both opt-in.
        # The dock itself is always *built* — we just hide it and skip the
        # record() calls when disabled, so flipping the flag at runtime is
        # cheap and doesn't require a layout rebuild.
        self.attendance_enabled = self.config.attendance_enabled
        self.attendance_panel = None
        # Set True while we programmatically toggle dock visibility so the
        # dock's visibilityChanged signal doesn't mistake our own hide
        # (FRS-mode, layout reset, restore-from-saved) for a user click on
        # the title-bar X.
        self._suppress_attendance_visibility = False
        self.journal_controller = JournalController(self, parent=self)

        self._ui_ready = False

        # Apply persisted theme before init_ui so the header label, pending
        # pills, and chat-display all paint in the right palette on the
        # first frame instead of flashing light-then-dark.
        theme.apply_theme(
            QApplication.instance(),
            self.config.dark_mode,
        )

        self.init_ui()
        # Layout restore happens after init_ui — saveState/restoreState
        # match docks by objectName, so every dock must already exist with
        # its stable name before we hand Qt the byte blob. If the saved
        # state is absent, malformed, or from a different schema version
        # we fall back to the documented default arrangement so first-
        # launch users (and anyone upgrading past a layout schema bump)
        # see the intended UI rather than an empty central area.
        if not dock_layout.restore_layout(self, self.config):
            dock_layout.build_default_layout(self)
        # Spectrometer visibility honors its own config key independent of
        # the layout state — re-apply after restore so a saved-state
        # "waterfall hidden" doesn't override a user who just enabled it.
        self.spectro_manager.widget.setVisible(self.spectro_manager.settings.enabled)
        self.spectro_manager.dock.setVisible(self.spectro_manager.settings.enabled)
        # Attendance dock follows ``attendance.enabled`` for the same
        # reason: a saved layout from before the feature was enabled
        # shouldn't override the operator's later opt-in.
        self._set_attendance_dock_visible(self.attendance_enabled)
        # Seed the panel with the current contacts so any callsign
        # subsequently recorded resolves immediately.
        self.attendance_panel.refresh(self.contacts)
        self._sync_service_radios()
        self.update_header()
        self.populate_target_dropdown()
        self.populate_quick_messages_strip()
        self._refresh_callsign_index()
        self._apply_service_mode()
        self._check_bundled_models()

    def _check_bundled_models(self):
        model_name = self.config.whisper_model
        model_path = os.path.join(STTWorker.MODELS_STT_DIR, model_name)
        if not os.path.isdir(model_path):
            self.append_to_chat(
                f"<i>STT model '{model_name}' not found at <code>{model_path}/</code>. "
                f"Listening will fail until you run "
                f"<code>python bootstrap_models.py --model {model_name}</code> "
                f"on an internet-connected machine and copy the resulting "
                f"<code>Models/</code> directory here.</i>",
                color=theme.palette().warn,
            )

    def closeEvent(self, event):
        # stop_stt already runs spectro_manager.stop(), but call it directly
        # too so a window close that races with start_stt mid-flight can't
        # leave the FFT thread orphaned.
        self.stop_stt()
        self.spectro_manager.stop()
        self._monitor.stop()
        for attr in ('tts_thread', 'audio_thread'):
            thread = getattr(self, attr, None)
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait()
        self.pending_manager.disconnect_workers()
        self.journal_controller.cleanup()
        self.tx.close_ptt()
        # Persist dock placements + window geometry so the next launch
        # lands the operator back in the layout they were using. Saves
        # only on close (not every drag) so config.json doesn't churn
        # during normal use; existing dark_mode + spectrometer + radio
        # service keys ride alongside.
        try:
            dock_layout.save_layout(self, self.config)
            save_json(CONFIG_FILE, self.config)
        except Exception:
            # A failed save here must never block window close —
            # next launch falls back to the default layout instead.
            pass
        super().closeEvent(event)

    def init_ui(self):
        # Build order: service toolbar, central widget (chat), every dock,
        # status bar, shortcuts, menus. Docks are *created* here but their
        # placement (which dock area, tabbed-vs-not, visible-vs-hidden) is
        # owned by dock_layout.{restore,build_default}_layout, called from
        # __init__ after this method returns. That separation lets the
        # operator's persisted layout decide initial state without any
        # ``addDockWidget`` call here racing the restore.
        self._build_service_toolbar()
        self._build_central_widget()
        self._build_station_dock()
        self.spectro_manager.build_dock()
        self._build_attendance_dock()
        self.pending_manager.build_dock()
        self._build_quick_messages_dock()
        self._build_transmit_dock()
        self._build_status_bar()
        self._install_global_shortcuts()
        self.create_menus()

        # Online-connectivity refresh kicks off here because init_ui owns
        # the periodic-timer setup. The first probe runs synchronously so
        # the status bar shows the right state on the first paint.
        self._refresh_online_indicator()
        self._online_timer = QTimer(self)
        self._online_timer.setInterval(ONLINE_REFRESH_MS)
        self._online_timer.timeout.connect(self._refresh_online_indicator)
        self._online_timer.start()

        # Reasonable minimum so high-DPI / large-font users don't get clipping.
        self.setMinimumSize(720, 520)
        self._ui_ready = True
        self._rx_session = self._make_rx_session()

    # ---- Section builders ------------------------------------------------

    def _build_service_toolbar(self):
        """Service-mode toggle + quick-access icon strip, hosted on a top
        ``QToolBar`` so the operator can drag it to any of the four toolbar
        areas (or hide it via the View menu)."""
        tb = QToolBar("Service", self)
        tb.setObjectName(dock_layout.TOOLBAR_SERVICE)
        tb.setMovable(True)
        tb.setFloatable(False)
        tb.setStyleSheet(theme.toolbar_focus_stylesheet())

        service_label = QLabel("Service:", tb)
        service_label.setAccessibleName("Radio service")
        tb.addWidget(service_label)

        self._service_group = QButtonGroup(self)
        self._service_group.setExclusive(True)
        self.gmrs_radio = QRadioButton("&GMRS", tb)
        self.gmrs_radio.setAccessibleName("Operate in GMRS mode")
        self.gmrs_radio.setAccessibleDescription(
            "FCC-licensed General Mobile Radio Service. Callsign framing, "
            "15-minute ID rule, contacts, callsign verification, and "
            "callsign highlighting are all enabled."
        )
        self.gmrs_radio.setToolTip(
            "FCC-licensed GMRS operation. All callsign features active."
        )
        self.frs_radio = QRadioButton("&FRS", tb)
        self.frs_radio.setAccessibleName("Operate in FRS mode")
        self.frs_radio.setAccessibleDescription(
            "Unlicensed Family Radio Service. All callsign-specific features "
            "(preface, station ID, contacts, callsign verification, "
            "highlighting, pending-station detection) are disabled — FRS "
            "has no callsign requirement under Part 95 Subpart B."
        )
        self.frs_radio.setToolTip(
            "Unlicensed FRS operation. Callsign features turn off."
        )
        self._service_group.addButton(self.gmrs_radio)
        self._service_group.addButton(self.frs_radio)
        tb.addWidget(self.gmrs_radio)
        tb.addWidget(self.frs_radio)

        # Expanding spacer pushes the icon strip to the right edge of the
        # toolbar — mirrors the QHBoxLayout-with-stretch pattern from the
        # pre-dock layout so the visual rhythm survives the move to QToolBar.
        spacer = QWidget(tb)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Right-anchored quick-access icon strip: 🌙/☀️ (theme) | Q (Quick
        # Messages) | 👤 (Contacts) | ⚙️ (Configuration). Theme sits leftmost
        # because it's the only item that isn't "open a dialog"; the three
        # dialog-launchers stay grouped on the right with the cog rightmost
        # per the established "settings last" toolbar convention. All icons
        # share one font bump so the row height stays balanced.
        icon_font = theme.font_icon()

        # Theme (dark-mode) toggle. The glyph reflects the *destination*
        # state — moon when in light, sun when in dark — so the affordance
        # reads as "click to become this". Stays enabled in FRS mode; the
        # theme is service-agnostic.
        self.theme_toggle_btn = QToolButton(tb)
        self.theme_toggle_btn.setFont(icon_font)
        self.theme_toggle_btn.setAutoRaise(True)
        self.theme_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_toggle_btn.setAccessibleName("Toggle dark mode")
        self.theme_toggle_btn.setAccessibleDescription(
            "Switch the application between light and dark color themes. "
            "Your choice is saved and restored on next launch."
        )
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)
        self._refresh_theme_toggle_glyph()
        tb.addWidget(self.theme_toggle_btn)

        # Quick Messages icon. Plain bold "Q" — the operator already learns
        # "Q" as the symbol for this strip via the menu mnemonic, so the
        # letter doubles as its own affordance. Usable in both GMRS and FRS.
        self.quick_messages_icon_btn = QToolButton(tb)
        self.quick_messages_icon_btn.setText("Q")
        qm_font = QFont(icon_font)
        qm_font.setBold(True)
        self.quick_messages_icon_btn.setFont(qm_font)
        self.quick_messages_icon_btn.setAutoRaise(True)
        self.quick_messages_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_messages_icon_btn.setAccessibleName("Open quick messages")
        self.quick_messages_icon_btn.setAccessibleDescription(
            "Open the quick messages editor to add, edit, or reorder the "
            "one-click preset phrases shown above the message field. Same "
            "destination as Settings → Quick Messages."
        )
        self.quick_messages_icon_btn.setToolTip("Quick Messages")
        self.quick_messages_icon_btn.clicked.connect(self.open_quick_messages_dialog)
        tb.addWidget(self.quick_messages_icon_btn)

        # Contacts icon. Same destination as Settings → Contacts (Ctrl+B).
        # Disabled in FRS mode (no callsigns, no contacts) by the same code
        # path that disables the Contacts menu action.
        self.contacts_icon_btn = QToolButton(tb)
        self.contacts_icon_btn.setText("\U0001F464")  # 👤 bust-in-silhouette
        self.contacts_icon_btn.setFont(icon_font)
        self.contacts_icon_btn.setAutoRaise(True)
        self.contacts_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.contacts_icon_btn.setAccessibleName("Open contacts")
        self.contacts_icon_btn.setAccessibleDescription(
            "Open the contacts editor to add, edit, or remove known "
            "callsigns. Same destination as Settings → Contacts (Ctrl+B)."
        )
        self.contacts_icon_btn.setToolTip("Contacts (Ctrl+B)")
        self.contacts_icon_btn.clicked.connect(self.open_contacts_dialog)
        tb.addWidget(self.contacts_icon_btn)

        # Journal button. Opens the journal dialog to browse saved entries or
        # trigger generation. Label mirrors the Tools menu mnemonic.
        self.journal_icon_btn = QToolButton(tb)
        self.journal_icon_btn.setText("\U0001F4D3")  # 📓 notebook
        self.journal_icon_btn.setFont(icon_font)
        self.journal_icon_btn.setAutoRaise(True)
        self.journal_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.journal_icon_btn.setAccessibleName("Session journals")
        self.journal_icon_btn.setAccessibleDescription(
            "Open the session journals browser. Same destination as "
            "Tools → View Session Journals (Ctrl+Shift+J)."
        )
        self.journal_icon_btn.setToolTip("Session Journals (Ctrl+Shift+J)")
        self.journal_icon_btn.clicked.connect(self.journal_controller.open_dialog)
        tb.addWidget(self.journal_icon_btn)

        # Configuration cog. Rightmost — "settings last" convention. Stays
        # enabled in FRS mode because Configuration is service-agnostic
        # (voice, audio devices, PTT mode all apply to both modes).
        self.config_icon_btn = QToolButton(tb)
        self.config_icon_btn.setText("⚙️")  # gear
        self.config_icon_btn.setFont(icon_font)
        self.config_icon_btn.setAutoRaise(True)
        self.config_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_icon_btn.setAccessibleName("Open configuration")
        self.config_icon_btn.setAccessibleDescription(
            "Open the configuration dialog to edit callsign, voice, audio "
            "devices, VAD threshold, and PTT mode. Same destination as "
            "Settings → Configuration."
        )
        self.config_icon_btn.setToolTip("Configuration (Ctrl+,)")
        self.config_icon_btn.clicked.connect(self.open_config_dialog)
        tb.addWidget(self.config_icon_btn)

        # toggled fires on both selection AND deselection within the group;
        # we only care about the newly-checked button, so guard inside the
        # handler by reading the group state.
        self.gmrs_radio.toggled.connect(self._on_service_toggled)
        self.frs_radio.toggled.connect(self._on_service_toggled)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        self._service_toolbar = tb

    def _build_central_widget(self):
        """Central area = listen/level strip + chat-display.

        The Listen toggle and live mic-level meter live here, above the
        conversation log they feed. They were previously wedged into the
        leftmost column of the Transmit dock, which mixed RX controls into
        a TX surface and squeezed the message-input width. Hosting them in
        the always-visible central widget keeps them reachable regardless
        of dock state and groups them with the chat they drive.
        """
        wrapper = QWidget(self)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(theme.SPACING_S, theme.SPACING_S, theme.SPACING_S, theme.SPACING_S)
        layout.setSpacing(theme.SPACING_S)

        # Listen strip: Listen toggle on the left, live mic-level bar
        # stretching across the middle, Clear-chat on the right. One row
        # keeps the vertical chrome above the chat to a single line.
        listen_strip = QHBoxLayout()
        listen_strip.setContentsMargins(0, 0, 0, 0)
        listen_strip.setSpacing(theme.SPACING_S)

        self.listen_btn = QPushButton("&Listen", wrapper)
        self.listen_btn.setCheckable(True)
        self.listen_btn.setToolTip("Toggle microphone capture / live transcription (Alt+L, Ctrl+L)")
        self.listen_btn.setAccessibleName("Listen toggle")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio. Currently stopped."
        )
        self.listen_btn.toggled.connect(self.toggle_listening)
        listen_strip.addWidget(self.listen_btn)

        # Listen-only safety toggle: when checked, every TX path is blocked.
        # Sits adjacent to Listen because it modifies Listen's contract
        # (microphone in, nothing out). The mnemonic 'o' avoids a clash
        # with the Listen button's 'L'.
        self.listen_only_btn = QPushButton("Listen &only", wrapper)
        self.listen_only_btn.setCheckable(True)
        self.listen_only_btn.setChecked(self.listen_only)
        self.listen_only_btn.setToolTip(
            "Block all transmissions (Alt+O). Microphone capture, "
            "transcription, and chat keep working — Transmit, This is, "
            "quick-message presets, and Enter-to-send are all disabled."
        )
        self.listen_only_btn.setAccessibleName("Listen only toggle")
        self.listen_only_btn.setAccessibleDescription(
            "Block all outgoing transmissions while still receiving. "
            "Currently off." if not self.listen_only else
            "Block all outgoing transmissions while still receiving. "
            "Currently on."
        )
        self.listen_only_btn.toggled.connect(self._on_listen_only_toggled)
        listen_strip.addWidget(self.listen_only_btn)

        self.monitor_btn = QPushButton("&Monitor", wrapper)
        self.monitor_btn.setCheckable(True)
        self.monitor_btn.setEnabled(False)
        self.monitor_btn.setToolTip(
            "Route incoming radio audio to the output device (Alt+M). "
            "Available when Listen-only mode is active."
        )
        self.monitor_btn.setAccessibleName("Monitor audio toggle")
        self.monitor_btn.setAccessibleDescription(
            "Play incoming radio audio through the computer speakers. "
            "Available when Listen and Listen-only are both active. Currently off."
        )
        self.monitor_btn.toggled.connect(self._on_monitor_toggled)
        listen_strip.addWidget(self.monitor_btn)

        self.audio_level_meter = QProgressBar(wrapper)
        self.audio_level_meter.setRange(0, 100)
        self.audio_level_meter.setValue(0)
        self.audio_level_meter.setTextVisible(False)
        self.audio_level_meter.setFixedHeight(8)
        self.audio_level_meter.setToolTip(
            "Microphone input level. Moves when audio is reaching the app — "
            "use this to verify your radio / cable / input device is wired up."
        )
        self.audio_level_meter.setAccessibleName("Microphone input level")
        self.audio_level_meter.setAccessibleDescription(
            "Real-time peak amplitude of the captured audio. Stays at zero "
            "when Listen is off or no audio is arriving."
        )
        listen_strip.addWidget(self.audio_level_meter, 1, Qt.AlignmentFlag.AlignVCenter)

        self.clear_chat_btn = QPushButton("Clear &chat", wrapper)
        self.clear_chat_btn.setToolTip(
            "Erase every message from the conversation log (Ctrl+K). "
            "Chat history isn't saved between runs."
        )
        self.clear_chat_btn.setAccessibleName("Clear conversation log")
        self.clear_chat_btn.setAccessibleDescription(
            "Remove every message from the chat display after confirming. "
            "Chat history is in-memory only and cannot be recovered after clearing."
        )
        self.clear_chat_btn.clicked.connect(self.clear_chat)
        listen_strip.addWidget(self.clear_chat_btn)

        self.generate_journal_btn = QPushButton("Generate &log entry", wrapper)
        self.generate_journal_btn.setToolTip(
            "Generate an AI-powered journal entry from the conversation log (Ctrl+J). "
            "Requires a Gemini API key in Settings → Configuration."
        )
        self.generate_journal_btn.setAccessibleName("Generate session journal")
        self.generate_journal_btn.setAccessibleDescription(
            "Use the Gemini API to summarise the conversation log into a saved journal entry."
        )
        self.generate_journal_btn.clicked.connect(self.journal_controller.generate)
        self.generate_journal_btn.setVisible(bool(self.config.gemini_api_key))
        listen_strip.addWidget(self.generate_journal_btn)

        layout.addLayout(listen_strip)

        # Main chat-display surface. No hardcoded font-size so OS font-scale
        # carries through (WCAG 1.4.4).
        self.chat_display = ChatDisplay(wrapper)
        self.chat_display.setStyleSheet(theme.chat_display_stylesheet())
        self.chat_display.setAccessibleName("Conversation log")
        self.chat_display.setAccessibleDescription(
            "Timestamped log of incoming radio transmissions and outgoing messages. "
            "Known callsigns are highlighted; hover for the operator names linked to each one."
        )
        layout.addWidget(self.chat_display, 1)

        self.setCentralWidget(wrapper)

    def _build_station_dock(self):
        """Station-info dock: callsign / operator / location card. Docked
        at the top by default but the operator may move it to a side
        column if they want more vertical space for chat."""
        content = QWidget(self)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(theme.SPACING_S, theme.SPACING_XS, theme.SPACING_S, theme.SPACING_XS)
        layout.setSpacing(theme.SPACING_S)

        self.header_label = QLabel("Loading...", content)
        self.header_label.setFont(theme.font_header())
        self.header_label.setStyleSheet(theme.header_stylesheet())
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_label.setAccessibleName("Station information")
        self.header_label.setAccessibleDescription(
            "Your configured callsign, operator name, and location."
        )
        layout.addWidget(self.header_label, 1)

        dock = QDockWidget("Station", self)
        dock.setObjectName(dock_layout.DOCK_STATION)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setWidget(content)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(self, dock)
        self.station_dock = dock

    def _build_waterfall_dock(self):
        """Rolling RX spectrometer dock. Initial visibility tracks
        ``spectro_settings.enabled`` — applied after layout restore in
        __init__ so a saved-state hidden never overrides a freshly-
        enabled-by-config waterfall."""
        self.spectro_widget = SpectrogramWidget(
            sample_rate=STTWorker.SAMPLE_RATE,
            frame_size=1024,
            settings=self.spectro_settings,
            parent=self,
        )
        self.spectro_widget.activity_text_changed.connect(self._on_spectro_activity)

        dock = QDockWidget("Waterfall", self)
        dock.setObjectName(dock_layout.DOCK_WATERFALL)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setWidget(self.spectro_widget)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(self, dock)
        # Mirror the persistent View-menu toggle: a manual close of the
        # dock has to stop the FFT worker so we don't keep paying CPU on
        # an invisible widget.
        dock.visibilityChanged.connect(self._on_waterfall_dock_visibility_changed)
        self.waterfall_dock = dock

    def _build_attendance_dock(self):
        """Listening-session attendance dock: a Callsign / Name / Location /
        GMRS / HAM table populated from RX detections during a Listen
        session. Visibility tracks ``attendance.enabled`` so the feature
        is fully opt-in — when disabled the panel exists but is hidden
        and never receives ``record`` calls."""
        self.attendance_panel = AttendancePanel(self)

        dock = QDockWidget("Callsigns Detected", self)
        dock.setObjectName(dock_layout.DOCK_ATTENDANCE)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setWidget(self.attendance_panel)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(self, dock)
        # Closing the dock from its title-bar X mirrors the View-menu
        # toggle: turn the feature off entirely so we don't keep
        # recording into a hidden grid.
        dock.visibilityChanged.connect(self._on_attendance_dock_visibility_changed)
        self.attendance_dock = dock

    def _build_quick_messages_dock(self):
        """Quick-message preset strip. Presets ride the same TX pipeline
        as the typed message-input box, so callsign framing, the 15-minute
        ID rule, PTT keying, and STT auto-pause all still apply."""
        self.quick_messages_widget = QWidget(self)
        self.quick_messages_flow = FlowLayout(
            self.quick_messages_widget,
            margin=theme.SPACING_S,
            spacing=theme.SPACING_S,
        )
        self.quick_messages_widget.setAccessibleName("Quick message presets")
        self.quick_messages_widget.setAccessibleDescription(
            "Row of one-click preset phrases. Edit the list from "
            "Settings, Quick Messages."
        )

        dock = QDockWidget("Quick Messages", self)
        dock.setObjectName(dock_layout.DOCK_QUICK)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setWidget(self.quick_messages_widget)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(self, dock)
        self.quick_dock = dock

    def _build_transmit_dock(self):
        """TX controls dock: target + message input + Transmit + 'This is' (ID).

        The ID button is folded into the same row as Transmit (audit F-008)
        so it sits adjacent to the action it complements instead of
        stranded on its own row. Listen toggle + live mic-level meter used
        to share this dock; they now live above the chat in the central
        widget so RX controls aren't wedged into a TX surface.

        Operationally critical — the dock is movable + floatable but
        **not** closable so an accidental dismiss can't leave the
        operator with no way to transmit.
        """
        content = QWidget(self)
        row = QHBoxLayout(content)
        row.setContentsMargins(theme.SPACING_S, theme.SPACING_S, theme.SPACING_S, theme.SPACING_S)
        row.setSpacing(theme.SPACING_S)

        self.target_dropdown = QComboBox(content)
        self.target_dropdown.setMinimumWidth(120)
        self.target_dropdown.setAccessibleName("Transmission target")
        self.target_dropdown.setAccessibleDescription(
            "Pick a contact callsign to address, or All for an open call."
        )
        self.target_dropdown.setToolTip("Recipient callsign for the next transmission")
        row.addWidget(self.target_dropdown)

        self.message_input = QLineEdit(content)
        self.message_input.setPlaceholderText("Type your message here...")
        self.message_input.setAccessibleName("Outgoing message")
        self.message_input.setAccessibleDescription(
            "Text to speak as the next transmission. Press Enter or use Transmit."
        )
        self.message_input.returnPressed.connect(self.transmit_message)
        row.addWidget(self.message_input, 1)

        self.transmit_btn = QPushButton("&Transmit", content)
        self.transmit_btn.setToolTip("Speak the message through the configured voice (Alt+T, Ctrl+Return)")
        self.transmit_btn.setAccessibleName("Transmit message")
        self.transmit_btn.clicked.connect(self.transmit_message)
        row.addWidget(self.transmit_btn)

        # Standalone ID button. Audit F-008: folded into the input row so
        # it sits adjacent to Transmit rather than stranded on a dedicated
        # right-aligned row.
        self.id_btn = QPushButton("Th&is is", content)
        self.id_btn.setToolTip(
            "Transmit station ID: This is [callsign]. [name] from [location] (Alt+I, Ctrl+I)"
        )
        self.id_btn.setAccessibleName("Send station ID")
        self.id_btn.clicked.connect(self.transmit_id_only)
        row.addWidget(self.id_btn)

        # Explicit tab order so keyboard users get a predictable traversal:
        # Listen (above chat) → target → message → Transmit → This is.
        # setTabOrder is window-level so the central-widget Listen button
        # chains cleanly into the dock-hosted TX widgets.
        self.setTabOrder(self.listen_btn, self.target_dropdown)
        self.setTabOrder(self.target_dropdown, self.message_input)
        self.setTabOrder(self.message_input, self.transmit_btn)
        self.setTabOrder(self.transmit_btn, self.id_btn)

        dock = QDockWidget("Transmit", self)
        dock.setObjectName(dock_layout.DOCK_TRANSMIT)
        # No Closable — the input row is operationally critical, hiding
        # it would strand the operator with no TX path.
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(content)
        dock.setTitleBarWidget(CompactTitleBar(dock))
        dock_layout.install_dock_context_menu(self, dock)
        self.transmit_dock = dock

    def _build_status_bar(self):
        """Status bar: online indicator on the right (matches OS taskbar
        convention), transient `Ready`/event messages on the left."""
        sb = self.statusBar()

        # Internet-connectivity indicator. F-010: NoFocus so keyboard tab
        # traversal skips this purely-informational widget.
        self.online_indicator = QLabel(ONLINE_LABEL_ONLINE, sb)
        self.online_indicator.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.online_indicator.setAccessibleName("Internet connectivity status")
        self.online_indicator.setAccessibleDescription(
            "Indicates whether online features (FCC callsign verification) "
            "are available. Updates every 30 seconds."
        )
        sb.addPermanentWidget(self.online_indicator)
        sb.showMessage("Ready")

    def _install_global_shortcuts(self):
        """Window-level keyboard shortcuts. Existing reservations:
        Ctrl+L Listen, Ctrl+Return/Enter Transmit, Ctrl+I This-is,
        Ctrl+K Clear chat (on menu), Ctrl+B Contacts (on menu),
        Ctrl+, Configuration (on menu), Alt+1..9 quick-message presets,
        Ctrl+Shift+W waterfall toggle (on menu).

        Phase B adds the dock-management bindings: Ctrl+Shift+{S,P,Q,T}
        toggle the four user-hideable docks, Ctrl+Shift+0 resets layout,
        F6 / Shift+F6 walks keyboard focus across visible dock title bars
        so operators who cannot drag with a mouse can still open the
        per-dock Move-to / Float / Hide context menu via the Menu key.
        """
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.listen_btn.toggle)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.transmit_message)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.transmit_message)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self.transmit_id_only)

        # Alt+1 … Alt+9 fire the first nine quick-message presets, in order.
        # User-defined phrases can't carry unique alphabetic mnemonics so we
        # claim the digit row instead; everything past slot nine is mouse-only.
        for i in range(QUICK_MESSAGE_SHORTCUT_COUNT):
            QShortcut(
                QKeySequence(f"Alt+{i + 1}"),
                self,
                activated=lambda index=i: self._send_preset(index),
            )

        QShortcut(
            QKeySequence("Ctrl+Shift+S"), self,
            activated=lambda: self._toggle_dock(self.station_dock),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+P"), self,
            activated=lambda: self._toggle_dock(self.pending_manager.dock),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+Q"), self,
            activated=lambda: self._toggle_dock(self.quick_dock),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+T"), self,
            activated=lambda: self._toggle_dock(self.transmit_dock),
        )
        QShortcut(
            QKeySequence("Ctrl+Shift+0"), self,
            activated=self._reset_layout_to_default,
        )
        QShortcut(
            QKeySequence("F6"), self,
            activated=lambda: dock_layout.cycle_dock_focus(self, forward=True),
        )
        QShortcut(
            QKeySequence("Shift+F6"), self,
            activated=lambda: dock_layout.cycle_dock_focus(self, forward=False),
        )

    def _toggle_dock(self, dock):
        """Show/hide a dock via keyboard shortcut. For docks that aren't
        Closable (Transmit) this simply re-shows when hidden, never hides."""
        if dock.isVisible():
            if dock.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable:
                dock.hide()
            else:
                dock.raise_()
                dock.setFocus(Qt.FocusReason.ShortcutFocusReason)
        else:
            dock.show()
            dock.raise_()

    def _reset_layout_to_default(self):
        """View-menu / Ctrl+Shift+0 entry point: rebuild the documented
        default arrangement, then re-apply spectrometer + attendance
        visibility so the operator's last per-feature choice survives the
        reset."""
        dock_layout.build_default_layout(self)
        sm = self.spectro_manager
        sm.dock.setVisible(sm.settings.enabled)
        sm.widget.setVisible(sm.settings.enabled)
        self._set_attendance_dock_visible(
            self.attendance_enabled and self._service_mode() != SERVICE_FRS
        )

    def create_menus(self):
        menubar = self.menuBar()

        # Settings Menu — Alt+S mnemonic.
        settings_menu = menubar.addMenu("&Settings")

        config_action = QAction("&Configuration…", self)
        config_action.setShortcut(QKeySequence.StandardKey.Preferences)
        config_action.setStatusTip("Edit callsign, voice, devices, VAD threshold, and PTT mode.")
        config_action.triggered.connect(self.open_config_dialog)
        settings_menu.addAction(config_action)

        contacts_action = QAction("Co&ntacts…", self)
        contacts_action.setShortcut(QKeySequence("Ctrl+B"))
        contacts_action.setStatusTip("Add, edit, or remove known callsigns.")
        contacts_action.triggered.connect(self.open_contacts_dialog)
        settings_menu.addAction(contacts_action)
        # Held on self so _apply_service_mode can flip enabled state when the
        # user toggles between GMRS and FRS.
        self._contacts_action = contacts_action

        quick_action = QAction("&Quick Messages…", self)
        quick_action.setStatusTip(
            "Edit the one-click preset phrases shown above the message field."
        )
        quick_action.triggered.connect(self.open_quick_messages_dialog)
        settings_menu.addAction(quick_action)

        settings_menu.addSeparator()

        # Clear-chat lives on the Settings menu rather than a new top-level menu
        # so we don't grow the menubar for a single action; the menu entry
        # surfaces the Ctrl+K shortcut for keyboard-only operators who don't
        # spot the toolbar button.
        # In-menu mnemonic differs from the button's "Clear &chat" because the
        # 'c' inside the open Settings menu already belongs to Configuration —
        # use 'r' to avoid the collision while keeping the button intuitive.
        clear_chat_action = QAction("Clea&r chat", self)
        clear_chat_action.setShortcut(QKeySequence("Ctrl+K"))
        clear_chat_action.setStatusTip(
            "Erase every message from the conversation log."
        )
        clear_chat_action.triggered.connect(self.clear_chat)
        settings_menu.addAction(clear_chat_action)

        # View Menu — Alt+V mnemonic. Houses the rolling RX spectrometer
        # toggle plus its presentation options (color map, frequency range,
        # time window). All actions persist their choice to config.json so
        # the next launch comes up the same way the operator left it.
        view_menu = menubar.addMenu("&View")

        # Waterfall toggle + color/freq/window submenus are owned by the
        # SpectrometerManager so the FFT worker lifecycle stays co-located
        # with the widget and settings.
        self._spectro_toggle_action = self.spectro_manager.install_menu_actions(view_menu)

        view_menu.addSeparator()

        # Attendance toggle. Same on/off semantic as the Configuration
        # dialog's "Track listening-session attendance" checkbox — both
        # write ``attendance.enabled`` in config.json, so the menu state,
        # the Config dialog, and the dock visibility never diverge.
        self._attendance_toggle_action = QAction("Show callsigns &detected", self)
        self._attendance_toggle_action.setCheckable(True)
        self._attendance_toggle_action.setChecked(self.attendance_enabled)
        self._attendance_toggle_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self._attendance_toggle_action.setStatusTip(
            "Toggle the callsigns-detected panel. Disabled in FRS mode."
        )
        self._attendance_toggle_action.triggered.connect(self._on_attendance_toggle)
        view_menu.addAction(self._attendance_toggle_action)

        # Panels submenu — every user-hideable dock gets a toggle action,
        # plus a "Reset layout" entry that snaps everything back to the
        # documented default arrangement. Built from the live dock
        # instances so the labels follow ``setWindowTitle`` and a future
        # rename doesn't drift the menu.
        view_menu.addSeparator()
        panels_menu = view_menu.addMenu("&Panels")
        # Pair every dock that owns a toggleViewAction with its keyboard
        # shortcut so the menu surfaces the binding next to the label.
        dock_shortcuts = {
            self.station_dock: "Ctrl+Shift+S",
            self.spectro_manager.dock: "",  # Already on Ctrl+Shift+W via the action above
            self.pending_manager.dock: "Ctrl+Shift+P",
            self.quick_dock: "Ctrl+Shift+Q",
            self.transmit_dock: "Ctrl+Shift+T",
        }
        for dock, sequence in dock_shortcuts.items():
            if dock is self.spectro_manager.dock:
                # Waterfall toggling is owned by the SpectrometerManager action
                # so the FFT worker lifecycle stays bound to the action. Use
                # that action here too rather than the dock's toggleView.
                continue
            action = dock.toggleViewAction()
            if sequence:
                action.setShortcut(QKeySequence(sequence))
            panels_menu.addAction(action)

        panels_menu.addSeparator()
        reset_action = QAction("&Reset layout to default", self)
        reset_action.setShortcut(QKeySequence("Ctrl+Shift+0"))
        reset_action.setStatusTip(
            "Snap every panel back to the default arrangement. "
            "Keeps your dark-mode and waterfall preferences."
        )
        reset_action.triggered.connect(self._reset_layout_to_default)
        panels_menu.addAction(reset_action)

        # Tools Menu — Alt+T mnemonic. AI-assisted session tools.
        tools_menu = menubar.addMenu("&Tools")

        generate_journal_action = QAction("&Generate Session Journal…", self)
        generate_journal_action.setShortcut(QKeySequence("Ctrl+J"))
        generate_journal_action.setStatusTip(
            "Send the current transcript and callsigns to Gemini to generate "
            "a session journal entry. Requires a Gemini API key in Settings → Configuration."
        )
        generate_journal_action.triggered.connect(self.journal_controller.generate)
        tools_menu.addAction(generate_journal_action)
        self._generate_journal_action = generate_journal_action

        tools_menu.addSeparator()

        view_journals_action = QAction("&View Session Journals…", self)
        view_journals_action.setShortcut(QKeySequence("Ctrl+Shift+J"))
        view_journals_action.setStatusTip(
            "Browse all saved session journal entries."
        )
        view_journals_action.triggered.connect(self.journal_controller.open_dialog)
        tools_menu.addAction(view_journals_action)

    def update_header(self):
        """Updates the top bar with current user info. In FRS mode the
        callsign segment is replaced with a 'FRS Mode' label since FRS has
        no callsign — the operator/location segments stay useful for the
        on-screen log."""
        name = self.config.name or 'N/A'
        loc = self.config.location or 'N/A'
        if self._service_mode() == SERVICE_FRS:
            self.header_label.setText(f"FRS Mode | Operator: {name} | Location: {loc}")
        else:
            call = self.config.callsign or 'N/A'
            self.header_label.setText(f"Station: {call} | Operator: {name} | Location: {loc}")

    def _service_mode(self):
        return normalize_service(self.config.radio_service)

    def _sync_service_radios(self):
        """Initialize the radio buttons from config without triggering the
        toggled-signal write-back loop. Called once at startup."""
        mode = self._service_mode()
        # blockSignals so this programmatic state set doesn't fire the
        # toggled handler — that handler writes config and rebuilds UI,
        # which would be wasteful at startup.
        for btn in (self.gmrs_radio, self.frs_radio):
            btn.blockSignals(True)
        self.gmrs_radio.setChecked(mode == SERVICE_GMRS)
        self.frs_radio.setChecked(mode == SERVICE_FRS)
        for btn in (self.gmrs_radio, self.frs_radio):
            btn.blockSignals(False)

    def _on_service_toggled(self, checked):
        """Handle a user click on either service radio. QButtonGroup fires
        toggled on both buttons (the old one going False, the new one going
        True); we only act on the True edge so we don't double-process."""
        if not checked:
            return
        new_mode = SERVICE_FRS if self.frs_radio.isChecked() else SERVICE_GMRS
        if self.config.radio_service == new_mode:
            return
        self.config["radio_service"] = new_mode
        save_json(CONFIG_FILE, self.config)
        self._apply_service_mode()

    def toggle_theme(self):
        """Flip between light and dark mode, persist the choice, and
        repaint every widget that doesn't follow QPalette automatically."""
        new_dark = not theme.is_dark()
        self.config["dark_mode"] = new_dark
        save_json(CONFIG_FILE, self.config)
        theme.apply_theme(QApplication.instance(), new_dark)
        self._apply_theme_to_widgets()

    def _apply_theme_to_widgets(self):
        """Update every widget that hardcodes colors outside QPalette.

        Called from the toggle path. Touches: theme-icon glyph, header
        label stylesheet, pending-pill stylesheets, chat-display fragment
        recoloring, online indicator, every dock's compact title bar,
        and the service toolbar's focus-ring style. Idempotent — safe to
        call from any path that just rebuilt the palette."""
        if not self._ui_ready:
            return
        self._refresh_theme_toggle_glyph()
        self.header_label.setStyleSheet(theme.header_stylesheet())
        self._restyle_pending_pills()
        self.chat_display.setStyleSheet(theme.chat_display_stylesheet())
        self.chat_display.restyle_for_theme()
        self._refresh_online_indicator()
        # Dock title bars and the service toolbar have their own stylesheets;
        # both need a refresh because they reference palette colors
        # (focus ring, title-bar background) that flip with the theme.
        for dock in self.findChildren(QDockWidget):
            bar = dock.titleBarWidget()
            if isinstance(bar, CompactTitleBar):
                bar.refresh_palette()
        self._service_toolbar.setStyleSheet(theme.toolbar_focus_stylesheet())

    def _refresh_theme_toggle_glyph(self):
        """Set the toggle's glyph + tooltip to advertise the next theme.
        ``destination`` convention: moon means 'click to go to dark',
        sun means 'click to go to light'."""
        if not hasattr(self, "theme_toggle_btn"):
            return
        if theme.is_dark():
            self.theme_toggle_btn.setText(THEME_GLYPH_TO_LIGHT)
            self.theme_toggle_btn.setToolTip("Switch to light mode")
        else:
            self.theme_toggle_btn.setText(THEME_GLYPH_TO_DARK)
            self.theme_toggle_btn.setToolTip("Switch to dark mode")

    def _restyle_pending_pills(self):
        self.pending_manager.restyle_pills()

    @staticmethod
    def _set_frs_gate(widget, is_frs, frs_tip, gmrs_tip, *, use_status_tip=False):
        """Disable `widget` and set an explanatory tip when FRS is active.

        Centralises the repeated setEnabled + tip-swap pattern so
        _apply_service_mode stays flat and each GMRS-only control needs
        only one call site."""
        widget.setEnabled(not is_frs)
        setter = widget.setStatusTip if use_status_tip else widget.setToolTip
        setter(frs_tip if is_frs else gmrs_tip)

    def _apply_service_mode(self):
        """Enable / disable every callsign-dependent UI surface based on the
        active service. Idempotent — safe to call from toggle handlers and
        config-dialog OK.

        In FRS the following are disabled or hidden:
          • target dropdown (no callsign to address)
          • 'This is' standalone-ID button (no ID rule applies)
          • online indicator + verification (FCC lookups are GMRS/HAM only)
          • pending-station bar (no detection without callsigns)
          • Contacts menu action (informational reason in tooltip)
          • chat-display pill highlighter (no callsigns to highlight)
        """
        if not self._ui_ready:
            return
        is_frs = self._service_mode() == SERVICE_FRS

        # Header reflects mode immediately.
        self.update_header()

        # Target dropdown only makes sense when callsigns are in play.
        self.target_dropdown.setVisible(not is_frs)

        # Standalone ID button — disable rather than hide so its row layout
        # stays stable and keyboard tab-order doesn't reshuffle silently.
        self._set_frs_gate(
            self.id_btn, is_frs,
            frs_tip=(
                "Station ID is GMRS-only — FRS has no Part 95 ID requirement. "
                "Switch to GMRS to re-enable."
            ),
            gmrs_tip=(
                "Transmit station ID: This is [callsign]. [name] from [location] "
                "(Alt+I, Ctrl+I)"
            ),
        )

        # Online indicator: hide in FRS, since the only online feature
        # (callsign verification) doesn't apply.
        self.online_indicator.setVisible(not is_frs)

        # Pending bar: PendingStationManager owns its own visibility logic.
        self.pending_manager.apply_service_mode(is_frs)

        # Contacts menu action — disable with explanatory tooltip so users
        # discover the feature exists and know how to re-enable it.
        self._set_frs_gate(
            self._contacts_action, is_frs,
            frs_tip="Contacts apply to GMRS only — switch to GMRS to manage them.",
            gmrs_tip="Add, edit, or remove known callsigns.",
            use_status_tip=True,
        )

        # Quick-access contacts icon button mirrors the menu action — same
        # destination, same disable rule, same explanatory tooltip.
        self._set_frs_gate(
            self.contacts_icon_btn, is_frs,
            frs_tip="Contacts apply to GMRS only — switch to GMRS to manage them.",
            gmrs_tip="Contacts (Ctrl+B)",
        )

        # Attendance grid is GMRS-only (FRS has no callsigns to attend).
        # Disable the View toggle and hide the dock in FRS; restore them
        # to the operator's config-flagged choice when GMRS is active.
        self._set_frs_gate(
            self._attendance_toggle_action, is_frs,
            frs_tip="Callsigns Detected is GMRS-only — switch to GMRS to enable.",
            gmrs_tip="Toggle the callsigns-detected panel.",
            use_status_tip=True,
        )
        if is_frs:
            self._set_attendance_dock_visible(False)
            if self.attendance_panel is not None:
                self.attendance_panel.clear()
        else:
            self._set_attendance_dock_visible(self.attendance_enabled)

        # Chat-display pill highlighting: clearing the index suppresses all
        # callsign highlighting on existing and future lines.
        self._refresh_callsign_index()

        # The id_btn enabled state is owned jointly by service mode (FRS
        # has no ID rule) and listen-only (no TX). Reconcile them through
        # the single _refresh_tx_enabled path so the two gates can't drift.
        self._refresh_tx_enabled()

    def populate_target_dropdown(self):
        """Fills the target selection combo box with current contacts.

        'All (Everyone)' is hard-coded as the first entry regardless of
        contacts.json — it's a UI primitive (broadcast / no preface), not a
        person, so the user can never lose the open-call option by deleting
        all their contacts. Any stray 'All' rows in contacts.json are skipped
        so the entry never duplicates.

        Each row stores ``(callsign, name)`` as its userData so that family
        members sharing a single GMRS callsign stay distinguishable — the
        chosen name is what the preface speaks, not whichever row happens to
        sort first."""
        self.target_dropdown.clear()
        self.target_dropdown.addItem("All (Everyone)", userData=("All", ""))
        for contact in self.contacts:
            if (contact.get("callsign", "") or "").upper() == "ALL":
                continue
            display_text = f"{contact['callsign']} ({contact['name']})"
            self.target_dropdown.addItem(
                display_text,
                userData=(contact['callsign'], contact.get('name', '')),
            )

    def open_config_dialog(self):
        dlg = ConfigDialog(self.config, voice_test_fn=self.tx.test_voice, parent=self)
        if dlg.exec():
            old_device = self.config.input_device
            old_output_device = self.config.output_device
            old_threshold = self.config.vad_threshold
            old_ptt = (
                self.config.ptt_mode,
                self.config.ptt_serial_port,
                self.config.ptt_serial_line,
            )
            old_fuzzy = self.config.fuzzy_callsign
            old_attendance = self.attendance_enabled
            self.config.update(dlg.get_config())
            save_json(CONFIG_FILE, self.config)
            self.update_header()
            new_attendance = self.config.attendance_enabled
            if old_attendance != new_attendance:
                # Push the new state through the same toggle path the View
                # menu uses so the action's checkbox, the dock visibility,
                # and ``self.attendance_enabled`` stay in sync.
                self._attendance_toggle_action.setChecked(new_attendance)
                self._on_attendance_toggle(new_attendance)
            if old_fuzzy != self.config.fuzzy_callsign:
                # Push the new toggle state to the chat widget and rescan
                # existing lines so the operator sees the effect immediately
                # — turning on retro-corrects past near-misses, turning off
                # leaves prior rewrites in place (they're already canonical).
                self._refresh_callsign_index()
            stt_settings_changed = (
                old_device != self.config.input_device
                or old_threshold != self.config.vad_threshold
            )
            if stt_settings_changed and self.listen_btn.isChecked():
                self.stop_stt()
                self.start_stt()
            new_ptt = (
                self.config.ptt_mode,
                self.config.ptt_serial_port,
                self.config.ptt_serial_line,
            )
            if new_ptt != old_ptt:
                self.tx.close_ptt()
                self.tx.ptt = make_ptt(self.config)
            if old_output_device != self.config.output_device and self.monitor_btn.isChecked():
                self._monitor.start(self.config.output_device)
            self.generate_journal_btn.setVisible(bool(self.config.gemini_api_key))

    def open_contacts_dialog(self):
        dlg = ContactsDialog(self.contacts, parent=self)
        if dlg.exec():
            self.contacts = sort_contacts(deduplicate_ham_cross_references(dlg.get_contacts()))
            save_json(CONTACTS_FILE, self.contacts)
            self.populate_target_dropdown()
            self._refresh_callsign_index()

    def open_quick_messages_dialog(self):
        dlg = QuickMessagesDialog(self._quick_messages(), parent=self)
        if dlg.exec():
            self.config["quick_messages"] = dlg.get_quick_messages()
            save_json(CONFIG_FILE, self.config)
            self.populate_quick_messages_strip()

    def _quick_messages(self):
        """Read the saved preset list, filtering out any non-string / blank
        entries so a hand-edited config.json can't crash the strip."""
        raw = self.config.quick_messages or []
        return [p.strip() for p in raw if isinstance(p, str) and p.strip()]

    def populate_quick_messages_strip(self):
        """Tear down the strip and rebuild it from the saved preset list.
        Called at startup and after the editor dialog saves."""
        while self.quick_messages_flow.count():
            item = self.quick_messages_flow.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._quick_message_buttons = []

        presets = self._quick_messages()
        for index, phrase in enumerate(presets):
            btn = QPushButton(phrase, self.quick_messages_widget)
            tip_parts = [f"Transmit: {phrase}"]
            if index < QUICK_MESSAGE_SHORTCUT_COUNT:
                tip_parts.append(f"Shortcut: Alt+{index + 1}")
            placeholders = find_placeholders(phrase)
            if placeholders:
                tip_parts.append(
                    "Prompts for: " + ", ".join(placeholders)
                )
            btn.setToolTip("\n".join(tip_parts))
            btn.setAccessibleName(f"Quick message: {phrase}")
            btn.setAccessibleDescription(
                "Transmit this preset through the standard TX pipeline. "
                "Placeholders in curly braces will prompt for a value before "
                "transmitting."
            )
            btn.clicked.connect(
                lambda _checked=False, p=phrase: self._send_preset_phrase(p)
            )
            self.quick_messages_flow.addWidget(btn)
            self._quick_message_buttons.append(btn)

        # Listen-only must reach the freshly-created buttons; existing
        # state would otherwise only be applied on the *next* tx-state
        # refresh, leaving newly-rebuilt presets clickable in RX-only mode.
        self._refresh_tx_enabled()

        self.quick_messages_widget.setVisible(bool(presets))
        # Hide the whole dock chrome when the operator has no saved
        # presets — keeping the dock visible would leave an empty
        # "Quick Messages" frame on screen with no actionable content.
        self.quick_dock.setVisible(bool(presets))

    def _send_preset(self, index):
        """Alt+N hotkey path: pick the Nth preset (0-indexed) and send it
        through `_send_preset_phrase`. Silently no-ops when the slot is
        empty so unbound digit keys don't misfire."""
        presets = self._quick_messages()
        if 0 <= index < len(presets):
            self._send_preset_phrase(presets[index])

    def _send_preset_phrase(self, phrase):
        """Resolve any `{Name}` placeholders via inline prompts and hand the
        result to the shared TX pipeline. Cancel on any prompt aborts the
        transmission so a half-filled placeholder never goes on-air.

        Short-circuits in listen-only mode so the operator doesn't waste a
        placeholder prompt on a preset that `_transmit_text` would refuse
        anyway. ``_transmit_text`` still re-checks the flag as a last line
        of defense."""
        if self.listen_only:
            self.statusBar().showMessage(
                "Listen-only mode is on — transmission blocked", 4000
            )
            return
        placeholders = find_placeholders(phrase)
        values = {}
        for name in placeholders:
            value, ok = QInputDialog.getText(
                self,
                "Quick Message",
                f"Value for {{{name}}}:",
            )
            if not ok:
                return
            values[name] = value.strip()
        resolved = substitute_placeholders(phrase, values)
        self._transmit_text(resolved)

    def transmit_message(self):
        """Wire the typed message-input box into the shared TX pipeline."""
        if self._transmit_text(self.message_input.text().strip()):
            self.message_input.clear()

    def _transmit_text(self, text):
        """Send `text` through the FCC-framing + TTS pipeline.

        Used by both the typed message-input box and the quick-message presets,
        so target-aware preface, profanity masking, 15-minute ID rule, chat-log
        rendering, target reset to All, and Piper synthesis all happen in one
        place. Returns True if a transmission was kicked off, False if the
        request was a no-op (empty text + open-call target).

        In FRS mode every callsign-shaped step is bypassed: no target preface,
        no station ID, and the chat label drops the 'to <CALL>' segment
        because there is no callsign to address.

        Listen-only short-circuits before any framing or synthesis so a
        bound shortcut (Ctrl+Return, Alt+1..9) can't push a transmission
        through behind a disabled button.
        """
        if self.listen_only:
            self.statusBar().showMessage(
                "Listen-only mode is on — transmission blocked", 4000
            )
            return False
        service = self._service_mode()
        if service == SERVICE_FRS:
            # FRS: callsigns don't exist, so we never preface, never reset
            # target, and never append ID. Empty text is the only no-op.
            target_call, target_name, prefaced = "", "", False
        else:
            target_data = self.target_dropdown.currentData() or ("", "")
            target_call, target_name = target_data
            prefaced = bool(target_call and target_call.upper() != "ALL")

        # Empty text is only valid in GMRS targeted mode — the preface itself
        # is the call. FRS always needs body text.
        if not text and not prefaced:
            return False

        if self.config.filter_profanity:
            text = mask_profanity(text)

        if not prefaced:
            target_name = ""

        spoken_text, self.last_tx_time = format_outgoing_message(
            text=text,
            target_call=target_call or "",
            target_name=target_name,
            my_call=self.config.callsign,
            my_name=self.config.name or "Default User",
            last_id_time=self.last_tx_time,
            now=datetime.datetime.now(),
            service=service,
        )

        if service == SERVICE_FRS:
            formatted_msg = f"<b>[TX]:</b> {spoken_text}"
        else:
            formatted_msg = f"<b>[TX to {target_call}]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=theme.palette().tx)

        if prefaced:
            for i in range(self.target_dropdown.count()):
                data = self.target_dropdown.itemData(i)
                if data and str(data[0]).upper() == "ALL":
                    self.target_dropdown.setCurrentIndex(i)
                    break

        self._synthesize_and_play(spell_digits_in_callsigns(spoken_text))
        return True

    def transmit_id_only(self):
        """Transmit a standalone ID: 'This is [call], [NATO phonetic call]. [name] from [location]'."""
        if self.listen_only:
            # Same defense-in-depth as the FRS guard below — the Ctrl+I
            # hotkey is window-level and fires regardless of button state.
            self.statusBar().showMessage(
                "Listen-only mode is on — transmission blocked", 4000
            )
            return
        if self._service_mode() == SERVICE_FRS:
            # FRS has no ID rule. The button is disabled, but the Ctrl+I /
            # Alt+I shortcuts are also bound at window level — guard here so
            # a stray hotkey can't push a callsign on-air.
            return
        spoken_text, self.last_tx_time = format_standalone_id(
            my_call=self.config.callsign,
            my_name=self.config.name or "Default User",
            my_location=self.config.location,
            now=datetime.datetime.now(),
        )

        formatted_msg = f"<b>[TX ID]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=theme.palette().tx)

        self._synthesize_and_play(spell_digits_in_callsigns(spoken_text))

    def _on_monitor_toggled(self, checked: bool) -> None:
        if checked:
            self._monitor.start(self.config.output_device)
            if self.stt_worker is not None:
                self.stt_worker.audio_chunk.connect(self._monitor.push)
            self.monitor_btn.setAccessibleDescription(
                "Play incoming radio audio through the computer speakers. "
                "Available when Listen and Listen-only are both active. Currently on."
            )
        else:
            if self.stt_worker is not None:
                try:
                    self.stt_worker.audio_chunk.disconnect(self._monitor.push)
                except (TypeError, RuntimeError):
                    pass
            self._monitor.stop()
            self.monitor_btn.setAccessibleDescription(
                "Play incoming radio audio through the computer speakers. "
                "Available when Listen and Listen-only are both active. Currently off."
            )
        self.config["monitor_enabled"] = checked
        try:
            save_json(CONFIG_FILE, self.config)
        except Exception:
            pass

    def _on_tx_busy_changed(self, busy: bool) -> None:
        self._monitor.mute(busy)
        self._refresh_tx_enabled()

    def _refresh_tx_enabled(self):
        """Single source of truth for whether the TX surfaces are clickable.
        Disabled when (a) listen-only is on, or (b) a transmission is mid-
        synthesis/playback. The "This is" button additionally requires GMRS
        (FRS has no station-ID rule). Quick-message preset buttons mirror
        the same gate so they grey out in sync."""
        is_frs = self._service_mode() == SERVICE_FRS
        tx_enabled = not self.listen_only and not self.tx.is_busy
        self.transmit_btn.setEnabled(tx_enabled)
        self.id_btn.setEnabled(tx_enabled and not is_frs)
        for btn in self._quick_message_buttons:
            btn.setEnabled(tx_enabled)

    def _on_listen_only_toggled(self, checked):
        """Persist the listen-only flag and refresh every TX surface."""
        self.listen_only = bool(checked)
        self.config["listen_only"] = self.listen_only
        try:
            save_json(CONFIG_FILE, self.config)
        except Exception:
            # A persistence failure must not block the safety toggle from
            # taking effect — runtime state already updated above.
            pass
        self.listen_only_btn.setAccessibleDescription(
            "Block all outgoing transmissions while still receiving. "
            f"Currently {'on' if self.listen_only else 'off'}."
        )
        self._refresh_tx_enabled()
        # Monitor is only meaningful when transmitting is blocked — enable it
        # when listen-only turns on (if Listen is active) and disable it when
        # listen-only turns off (stopping any in-progress monitor stream).
        if self.stt_worker is not None:
            if self.listen_only:
                self.monitor_btn.setEnabled(True)
                if self.config.monitor_enabled and not self.monitor_btn.isChecked():
                    self.monitor_btn.setChecked(True)
            else:
                if self.monitor_btn.isChecked():
                    self.monitor_btn.setChecked(False)
                self.monitor_btn.setEnabled(False)
        if self.listen_only:
            self.statusBar().showMessage("Listen-only mode: transmissions blocked", 4000)
        else:
            self.statusBar().showMessage("Listen-only mode off: transmissions enabled", 4000)

    def _synthesize_and_play(self, tts_text):
        self.tx.synthesize_and_play(
            tts_text,
            voice_path=self.config.voice,
            length_scale=self.config.tts_length_scale,
            output_device=self.config.output_device,
        )

    def _on_attendance_toggle(self, checked):
        """Apply the new attendance enabled state. Persists to config so the
        next launch comes up the same way, flips dock visibility, and resets
        the menu / dock-visibility pair to a single source of truth.

        Disabling the feature mid-session deliberately *keeps* the existing
        rows in memory — the operator may re-enable shortly and want to
        keep their roll-call. The next ``start_stt`` (or a manual Clear)
        is the only path that wipes the rows."""
        new_state = bool(checked)
        if self._service_mode() == SERVICE_FRS and new_state:
            # FRS has no callsigns to attend, so the action should be
            # disabled in that mode (see _apply_service_mode). This guard
            # keeps a stray hotkey from re-enabling mid-FRS.
            self._attendance_toggle_action.setChecked(False)
            return
        self.attendance_enabled = new_state
        self.config["attendance"] = {"enabled": new_state}
        save_json(CONFIG_FILE, self.config)
        self._set_attendance_dock_visible(new_state)

    def _on_attendance_dock_visibility_changed(self, visible):
        """Title-bar X on the attendance dock turns the feature off so we
        don't keep recording into a hidden grid. Routes through
        ``_on_attendance_toggle`` so the menu checkbox + persistence path
        stay the single source of truth.

        ``_suppress_attendance_visibility`` is set whenever we change dock
        visibility programmatically (FRS-mode hide, layout reset, restore
        from saved state) so this handler only reacts to genuine user
        clicks on the title-bar X."""
        if not self._ui_ready:
            return
        if self._suppress_attendance_visibility:
            return
        if visible == self.attendance_enabled:
            return
        self._attendance_toggle_action.setChecked(visible)
        self._on_attendance_toggle(visible)

    def _set_attendance_dock_visible(self, visible):
        """Toggle the attendance dock without firing the user-click path.
        Use this from every programmatic visibility write (init, layout
        reset, FRS-apply) so ``_on_attendance_dock_visibility_changed``
        stays purely a user-input handler."""
        self._suppress_attendance_visibility = True
        try:
            self.attendance_dock.setVisible(bool(visible))
        finally:
            self._suppress_attendance_visibility = False

    def _pause_stt_for_tx(self):
        if self.stt_worker and self.stt_worker.isRunning():
            self.stt_worker.pause()

    def _resume_stt_after_tx(self):
        if self.stt_worker and self.stt_worker.isRunning():
            self.stt_worker.resume()

    def append_to_chat(self, text, color="black"):
        """Appends HTML formatted text to the chat display."""
        self.chat_display.append_message(text, color=color)

    def clear_chat(self):
        """Wipe the chat display after confirming with the operator.

        Chat history is in-memory only — once cleared it can't be recovered —
        so we gate the action behind a Yes/No prompt to keep an accidental
        button-press or stray Ctrl+K from blowing away a long RX log."""
        reply = QMessageBox.question(
            self,
            "Clear chat",
            "Remove every message from the conversation log? "
            "Chat history isn't saved between runs, so this can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_display.clear()
            # Streaming RX would otherwise try to grow a block that no
            # longer exists. The fallback in RXSession catches it, but
            # flushing here prevents the next partial from appearing under
            # a misleading uid match.
            if self._rx_session:
                self._rx_session.flush()

    def _refresh_callsign_index(self):
        """Recompute the known-callsign lookup and push it to the chat widget.
        Past chat lines are re-scanned so newly-added contacts get retroactive
        pill highlighting. In FRS mode the index is forced empty — there are
        no callsigns in FRS, so highlighting them would be misleading.

        The attendance grid is refreshed in lockstep so a callsign that was
        unknown when first heard fills in its Name / Location / GMRS / HAM
        the moment it's saved to contacts."""
        if self._service_mode() == SERVICE_FRS:
            index = {}
        else:
            index = index_contacts_by_callsign(self.contacts)
        self.chat_display.set_callsign_index(index)
        # Fuzzy mode is meaningless without an index, and meaningless in FRS
        # mode where there are no callsigns to be fuzzy about. Pushing the
        # flag here keeps the chat widget's state in sync with the active
        # service alongside the index it depends on.
        self.chat_display.set_fuzzy_enabled(
            self._service_mode() != SERVICE_FRS
            and self.config.fuzzy_callsign
        )
        self.chat_display.rescan_all_blocks()
        if self.attendance_panel is not None:
            self.attendance_panel.refresh(self.contacts)

    def toggle_listening(self, on):
        if on:
            self.start_stt()
        else:
            self.stop_stt()

    def start_stt(self):
        if self.stt_worker and self.stt_worker.isRunning():
            return
        desired_model = self.config.whisper_model
        if self._stt_model_cache is not None and self._stt_model_cache.model_name != desired_model:
            self._stt_model_cache = None
        self.stt_worker = STTWorker(
            input_device=self.config.input_device,
            whisper_model=desired_model,
            vad_threshold=self.config.vad_threshold,
            model_cache=self._stt_model_cache,
            youtube_url=self.config.youtube_url,
            youtube_cookies_from_browser=self.config.youtube_cookies_from_browser,
            youtube_cookies_file=self.config.youtube_cookies_file,
            parent=self,
        )
        self.stt_worker.transcribed_segment.connect(self.on_transcription_segment)
        self.stt_worker.error.connect(self.on_stt_error)
        self.stt_worker.status.connect(self.on_stt_status)
        self.stt_worker.audio_level.connect(self.audio_level_meter.setValue)
        self.stt_worker.start()
        # Bring the waterfall online too if the operator has it enabled.
        # Done after stt_worker.start() so the audio_chunk signal already
        # exists by the time we connect it through spectro_manager.start().
        if self.spectro_manager.settings.enabled:
            self.spectro_manager.start(self.stt_worker)
        # Monitor is only available in listen-only mode (no TX path active).
        if self.listen_only:
            self.monitor_btn.setEnabled(True)
            if self.config.monitor_enabled and not self.monitor_btn.isChecked():
                self.monitor_btn.setChecked(True)
            elif self.monitor_btn.isChecked():
                # Button was already on from a previous cycle; rewire the signal.
                self._monitor.start(self.config.output_device)
                self.stt_worker.audio_chunk.connect(self._monitor.push)
        self.listen_btn.setText("&Listening…")
        self.listen_btn.setAccessibleDescription(
            "Microphone capture and live transcription are active. Toggle off to stop."
        )

    def stop_stt(self):
        # Flush any in-progress utterance before tearing down so callsigns
        # that appeared in the chat from partial transcripts still land in
        # attendance even when the session ends before VAD fires 'end'.
        if self._rx_session:
            self._rx_session.flush()

        # Disconnect and stop the audio monitor before nulling the worker
        # so the audio_chunk disconnect can still reach the live worker.
        if self.stt_worker is not None and self.monitor_btn.isChecked():
            try:
                self.stt_worker.audio_chunk.disconnect(self._monitor.push)
            except (TypeError, RuntimeError):
                pass
        self._monitor.stop()
        # Uncheck before disabling so the button never lingers in a
        # checked+disabled state; blockSignals prevents a redundant
        # _on_monitor_toggled callback since the stream is already stopped.
        self.monitor_btn.blockSignals(True)
        self.monitor_btn.setChecked(False)
        self.monitor_btn.blockSignals(False)
        self.monitor_btn.setEnabled(False)
        # Tear the spectrometer down first so its STT-signal disconnects
        # run while the worker is still alive — spectro_manager.stop()
        # reaches through self.stt_worker to undo the audio_chunk hookup.
        self.spectro_manager.stop()
        worker = self.stt_worker
        self.stt_worker = None
        if worker is not None:
            try:
                worker.transcribed_segment.disconnect(self.on_transcription_segment)
                worker.error.disconnect(self.on_stt_error)
                worker.status.disconnect(self.on_stt_status)
                worker.audio_level.disconnect(self.audio_level_meter.setValue)
            except (TypeError, RuntimeError):
                pass
            worker.stop()
            if worker.isRunning():
                worker.wait(15000)
            # Hoist loaded models out before the worker is destroyed so the
            # next start_stt can skip the multi-second model load.
            if worker.model_cache is not None:
                self._stt_model_cache = worker.model_cache
            worker.deleteLater()
        self.audio_level_meter.setValue(0)
        self.listen_btn.setText("&Listen")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio. Currently stopped."
        )

    def _format_timestamp(self, now=None):
        """Render an HH:MM:SS clock string honoring the configured time_format
        (24h default, 12h with AM/PM)."""
        if now is None:
            now = datetime.datetime.now()
        if self.config.time_format == "12h":
            h12 = now.hour % 12 or 12
            suffix = "AM" if now.hour < 12 else "PM"
            return f"{h12}:{now.minute:02d}:{now.second:02d} {suffix}"
        return now.strftime("%H:%M:%S")

    def _make_rx_session(self) -> RXSession:
        return RXSession(
            chat=self.chat_display,
            on_utterance_complete=self.pending_manager.scan_for_unknown_stations,
            format_timestamp=self._format_timestamp,
            filter_fn=lambda t: mask_profanity(t) if self.config.filter_profanity else t,
        )

    def on_transcription_segment(self, uid, text, is_final):
        self._rx_session.receive(uid, text, is_final, color=theme.palette().rx)

    def on_stt_error(self, msg):
        self.append_to_chat(f"<i>STT Error: {msg}</i>", color=theme.palette().error)
        self.listen_btn.blockSignals(True)
        self.listen_btn.setChecked(False)
        self.listen_btn.setText("&Listen")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio. Currently stopped."
        )
        self.listen_btn.blockSignals(False)

    def on_stt_status(self, msg):
        self.statusBar().showMessage(msg, 5000)

    def _refresh_online_indicator(self):
        """Re-probe internet connectivity and update the status-bar label.
        Cheap because the underlying probe is cached for ~60s, so the timer
        callback at 30s mostly returns a cached value."""
        online = is_online()
        p = theme.palette()
        if online:
            self.online_indicator.setText(ONLINE_LABEL_ONLINE)
            self.online_indicator.setStyleSheet(f"color: {p.online_online};")
            self.online_indicator.setToolTip(
                "Connected. Online features (FCC callsign verification) are available."
            )
        else:
            self.online_indicator.setText(ONLINE_LABEL_OFFLINE)
            self.online_indicator.setStyleSheet(f"color: {p.online_offline};")
            self.online_indicator.setToolTip(
                "No internet connection detected. Online features are disabled "
                "until connectivity returns."
            )
