import datetime
import os
import traceback

from piper.voice import PiperVoice
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QRadioButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from gmrs_tty.audio.playback import AudioPlayerThread
from gmrs_tty.constants import (
    CONFIG_FILE, CONTACTS_FILE,
    SERVICE_FRS, SERVICE_GMRS, normalize_service,
)
from gmrs_tty.fcc.id_rule import format_outgoing_message, format_standalone_id
from gmrs_tty.net.online import is_online
from gmrs_tty.persistence.contacts import (
    index_contacts_by_callsign,
    known_callsigns,
    sort_contacts,
)
from gmrs_tty.persistence.json_store import load_json, save_json
from gmrs_tty.ptt import make_ptt
from gmrs_tty.stt.worker import STTWorker
from gmrs_tty.text.callsigns import detect_callsigns, spell_digits_in_callsigns
from gmrs_tty.text.metadata import extract_name_location
from gmrs_tty.text.profanity import mask_profanity
from gmrs_tty.text.placeholders import find_placeholders, substitute_placeholders
from gmrs_tty.text.shorthand import expand_tty_abbreviations
from gmrs_tty.tts.synthesizer import TTSSynthesisThread
from gmrs_tty.ui import theme
from gmrs_tty.ui.chat_display import ChatDisplay
from gmrs_tty.ui.config_dialog import ConfigDialog
from gmrs_tty.ui.contacts_dialog import AddContactDialog, ContactsDialog
from gmrs_tty.ui.flow_layout import FlowLayout
from gmrs_tty.ui.quick_messages_dialog import QuickMessagesDialog

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
        self.resize(800, 600)

        # State Initialization
        self.config = load_json(CONFIG_FILE, {"callsign": "N0CALL", "name": "Default", "location": "Unknown"})
        self.contacts = sort_contacts(load_json(CONTACTS_FILE, [{"callsign": "All", "name": "Everyone"}]))
        self.last_tx_time = None

        self.voice_cache = {}
        self.stt_worker = None
        # Reused across Listen toggles so we don't pay the ~1–3s Whisper
        # load on every restart. Invalidated when whisper_model changes.
        self._stt_whisper = None
        self._stt_vad_model = None
        self._stt_whisper_model_name = None
        # Streaming-RX state: long utterances arrive as multiple partial
        # transcription_segment signals under one utterance_id. We hold the
        # block number of the currently-growing chat line plus the
        # accumulated text so callsign scanning runs once on the full
        # utterance when the final segment arrives.
        self._open_rx_uid = None
        self._open_rx_block = None
        self._open_rx_text = ""
        self.pending_buttons = {}  # callsign -> QPushButton
        self._pending_row_height = None  # cached pill row height for scroll cap
        # In-flight FCC auto-add lookups, keyed by callsign. A second detection
        # of the same callsign mid-lookup is suppressed so we don't hammer the
        # API with duplicate requests for one operator who keys up twice.
        self._callsign_lookups = {}
        self.ptt = make_ptt(self.config)

        # Apply persisted theme before init_ui so the header label, pending
        # pills, and chat-display all paint in the right palette on the
        # first frame instead of flashing light-then-dark.
        theme.apply_theme(
            QApplication.instance(),
            bool(self.config.get("dark_mode", False)),
        )

        self.init_ui()
        self._sync_service_radios()
        self.update_header()
        self.populate_target_dropdown()
        self.populate_quick_messages_strip()
        self._refresh_callsign_index()
        self._apply_service_mode()
        self._check_bundled_models()

    def _check_bundled_models(self):
        model_name = self.config.get("whisper_model", "small.en")
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
        self.stop_stt()
        for attr in ('tts_thread', 'audio_thread'):
            thread = getattr(self, attr, None)
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait()
        # FCC auto-add lookups sit on a 5s HTTP timeout; disconnect their
        # signals so a late result can't touch a torn-down window, then give
        # each thread a brief window to exit cleanly before the process tears
        # down. They emit nothing further once disconnected so leaking the
        # native thread is harmless.
        for cs, worker in list(self._callsign_lookups.items()):
            try:
                worker.result_ready.disconnect()
            except (TypeError, RuntimeError):
                pass
            if worker.isRunning():
                worker.wait(100)
        self._callsign_lookups.clear()
        try:
            self.ptt.close()
        except Exception:
            pass
        super().closeEvent(event)

    def init_ui(self):
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 0. Service-mode toggle. Sits above the header so the active radio
        # service is the first thing the user sees — switching to FRS disables
        # every callsign-dependent feature in this app, which is a big enough
        # behavioral shift that it earns top-of-window placement.
        service_row = QHBoxLayout()
        service_label = QLabel("Service:", self)
        service_label.setAccessibleName("Radio service")
        service_row.addWidget(service_label)
        self._service_group = QButtonGroup(self)
        self._service_group.setExclusive(True)
        self.gmrs_radio = QRadioButton("&GMRS", self)
        self.gmrs_radio.setAccessibleName("Operate in GMRS mode")
        self.gmrs_radio.setAccessibleDescription(
            "FCC-licensed General Mobile Radio Service. Callsign framing, "
            "15-minute ID rule, contacts, callsign verification, and "
            "callsign highlighting are all enabled."
        )
        self.gmrs_radio.setToolTip(
            "FCC-licensed GMRS operation. All callsign features active."
        )
        self.frs_radio = QRadioButton("&FRS", self)
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
        service_row.addWidget(self.gmrs_radio)
        service_row.addWidget(self.frs_radio)
        service_row.addStretch(1)
        # Right-anchored quick-access icon strip: 🌙/☀️ (theme) | Q (Quick
        # Messages) | 👤 (Contacts) | ⚙️ (Configuration). Theme sits leftmost
        # because it's the only item that isn't "open a dialog" — placing it
        # next to the stretch keeps the dialog-launching icons visually
        # grouped on the right. The cog stays rightmost per the established
        # "settings last on a toolbar" convention. All icons share one font
        # bump so the row height stays balanced.
        icon_font = QFont(self.font())
        icon_font.setPointSize(icon_font.pointSize() + 4)

        # Theme (dark-mode) toggle. The glyph reflects the *destination*
        # state — moon when in light, sun when in dark — so the affordance
        # reads as "click to become this". Stays enabled in FRS mode; the
        # theme is service-agnostic.
        self.theme_toggle_btn = QToolButton(self)
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
        service_row.addWidget(self.theme_toggle_btn)

        # Quick Messages icon. Plain bold "Q" — the operator already learns
        # "Q" as the symbol for this strip via the menu mnemonic, so the
        # letter doubles as its own affordance. Usable in both GMRS and FRS.
        self.quick_messages_icon_btn = QToolButton(self)
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
        service_row.addWidget(self.quick_messages_icon_btn)

        # Contacts icon. Same destination as Settings → Contacts (Ctrl+B).
        # Disabled in FRS mode (no callsigns, no contacts) by the same code
        # path that disables the Contacts menu action.
        self.contacts_icon_btn = QToolButton(self)
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
        service_row.addWidget(self.contacts_icon_btn)

        # Configuration cog. Rightmost — "settings last" convention. Stays
        # enabled in FRS mode because Configuration is service-agnostic
        # (voice, audio devices, PTT mode all apply to both modes).
        self.config_icon_btn = QToolButton(self)
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
        service_row.addWidget(self.config_icon_btn)

        # Internet-connectivity indicator. Sits at the far-right of the
        # service row (after the action icons) so it reads as a status
        # display rather than a button — matches the OS taskbar convention
        # where network status lives in the corner. Online features
        # (FCC callsign verification) gate on this state; the indicator is
        # the user-visible side of that contract. Hidden in FRS mode.
        self.online_indicator = QLabel(ONLINE_LABEL_ONLINE, self)
        self.online_indicator.setAccessibleName("Internet connectivity status")
        self.online_indicator.setAccessibleDescription(
            "Indicates whether online features (FCC callsign verification) "
            "are available. Updates every 30 seconds."
        )
        service_row.addWidget(self.online_indicator)

        # toggled fires on both selection AND deselection within the group;
        # we only care about the newly-checked button, so guard inside the
        # handler by reading the group state.
        self.gmrs_radio.toggled.connect(self._on_service_toggled)
        self.frs_radio.toggled.connect(self._on_service_toggled)
        main_layout.addLayout(service_row)

        # 1. Header (User Info). Bold via QFont so size scales with system font (WCAG 1.4.4).
        self.header_label = QLabel("Loading...", self)
        header_font = QFont(self.font())
        header_font.setBold(True)
        header_font.setPointSize(header_font.pointSize() + 2)
        self.header_label.setFont(header_font)
        self.header_label.setStyleSheet(theme.header_stylesheet())
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_label.setAccessibleName("Station information")
        self.header_label.setAccessibleDescription(
            "Your configured callsign, operator name, and location."
        )
        main_layout.addWidget(self.header_label)

        # 2. Chat-toolbar row. Right-aligned Clear-chat button sits above the
        # chat so it's visibly associated with the log it controls, without
        # crowding the TX input row below.
        chat_toolbar = QHBoxLayout()
        chat_toolbar.addStretch(1)
        self.clear_chat_btn = QPushButton("Clear &chat", self)
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
        chat_toolbar.addWidget(self.clear_chat_btn)
        main_layout.addLayout(chat_toolbar)

        # 2. Main Chat Room (Rx Section). No hardcoded font-size so the OS font-scale
        # setting carries through.
        self.chat_display = ChatDisplay(self)
        self.chat_display.setStyleSheet("padding: 5px;")
        self.chat_display.setAccessibleName("Conversation log")
        self.chat_display.setAccessibleDescription(
            "Timestamped log of incoming radio transmissions and outgoing messages. "
            "Known callsigns are highlighted; hover for the operator names linked to each one."
        )
        main_layout.addWidget(self.chat_display)

        # 2b. Pending stations bar (populates when STT detects unknown callsigns).
        # Layout: [QScrollArea wrapping a FlowLayout of pills] [Dismiss all].
        # The flow layout wraps pills to the next row when horizontal space
        # runs out; the scroll area caps visible height to PENDING_PILL_MAX_ROWS
        # rows and exposes a vertical scrollbar past that.
        self.pending_bar = QHBoxLayout()
        self.pending_bar.setSpacing(5)

        self.pending_pills_widget = QWidget()
        self.pending_flow = FlowLayout(self.pending_pills_widget, margin=0, spacing=5)

        self.pending_scroll = QScrollArea(self)
        self.pending_scroll.setWidgetResizable(True)
        self.pending_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.pending_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.pending_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.pending_scroll.setWidget(self.pending_pills_widget)
        self.pending_scroll.hide()
        self.pending_bar.addWidget(self.pending_scroll, 1)

        self.clear_pending_btn = QPushButton("&Dismiss all", self)
        self.clear_pending_btn.setToolTip(
            "Dismiss every pending station pill without adding any callsigns."
        )
        self.clear_pending_btn.setAccessibleName("Dismiss all pending stations")
        self.clear_pending_btn.setAccessibleDescription(
            "Remove every pending station pill without adding any of the detected callsigns to contacts."
        )
        self.clear_pending_btn.clicked.connect(self._clear_all_pending_pills)
        self.clear_pending_btn.hide()
        self.pending_bar.addWidget(self.clear_pending_btn, 0, Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(self.pending_bar)

        # 2c. Quick-messages preset strip. Sits between the pending bar and
        # the TX row so common phrases ("Radio check", "Standing by", "QSY to
        # channel {N}") are one click away. Presets ride the same TX pipeline
        # as the typed message-input box, so callsign framing, the 15-minute
        # ID rule, PTT keying, and STT auto-pause all still apply.
        self.quick_messages_widget = QWidget(self)
        self.quick_messages_flow = FlowLayout(
            self.quick_messages_widget, margin=0, spacing=5
        )
        self.quick_messages_widget.setAccessibleName("Quick message presets")
        self.quick_messages_widget.setAccessibleDescription(
            "Row of one-click preset phrases. Edit the list from "
            "Settings, Quick Messages."
        )
        main_layout.addWidget(self.quick_messages_widget)
        # Will be repopulated by populate_quick_messages_strip(); start hidden
        # so users without saved presets don't see an empty band.
        self.quick_messages_widget.hide()

        # 3. Input Area (Tx Section). Mnemonics: Alt+L Listen, Alt+T Transmit, Alt+I This is.
        input_layout = QHBoxLayout()

        self.listen_btn = QPushButton("&Listen", self)
        self.listen_btn.setCheckable(True)
        self.listen_btn.setToolTip("Toggle microphone capture / live transcription (Alt+L, Ctrl+L)")
        self.listen_btn.setAccessibleName("Listen toggle")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio. Currently stopped."
        )
        self.listen_btn.toggled.connect(self.toggle_listening)
        input_layout.addWidget(self.listen_btn)

        # Live mic-input level meter. Sits next to Listen so the user can
        # confirm at a glance that audio is reaching the app — the most
        # common hardware-troubleshooting question is "is my cable / device
        # actually wired up?"
        self.audio_level_meter = QProgressBar(self)
        self.audio_level_meter.setRange(0, 100)
        self.audio_level_meter.setValue(0)
        self.audio_level_meter.setTextVisible(False)
        self.audio_level_meter.setFixedWidth(80)
        self.audio_level_meter.setToolTip(
            "Microphone input level. Moves when audio is reaching the app — "
            "use this to verify your radio / cable / input device is wired up."
        )
        self.audio_level_meter.setAccessibleName("Microphone input level")
        self.audio_level_meter.setAccessibleDescription(
            "Real-time peak amplitude of the captured audio. Stays at zero "
            "when Listen is off or no audio is arriving."
        )
        input_layout.addWidget(self.audio_level_meter)

        self.target_dropdown = QComboBox(self)
        self.target_dropdown.setMinimumWidth(120)
        self.target_dropdown.setAccessibleName("Transmission target")
        self.target_dropdown.setAccessibleDescription(
            "Pick a contact callsign to address, or All for an open call."
        )
        self.target_dropdown.setToolTip("Recipient callsign for the next transmission")
        input_layout.addWidget(self.target_dropdown)

        self.message_input = QLineEdit(self)
        self.message_input.setPlaceholderText("Type your message here...")
        self.message_input.setAccessibleName("Outgoing message")
        self.message_input.setAccessibleDescription(
            "Text to speak as the next transmission. Press Enter or use Transmit."
        )
        self.message_input.returnPressed.connect(self.transmit_message)
        input_layout.addWidget(self.message_input)

        self.transmit_btn = QPushButton("&Transmit", self)
        self.transmit_btn.setToolTip("Speak the message through the configured voice (Alt+T, Ctrl+Return)")
        self.transmit_btn.setAccessibleName("Transmit message")
        self.transmit_btn.clicked.connect(self.transmit_message)
        input_layout.addWidget(self.transmit_btn)

        main_layout.addLayout(input_layout)

        # 3b. Standalone ID button row (sits under Transmit)
        id_layout = QHBoxLayout()
        id_layout.addStretch()
        self.id_btn = QPushButton("Th&is is", self)
        self.id_btn.setToolTip("Transmit station ID: This is [callsign]. [name] from [location] (Alt+I, Ctrl+I)")
        self.id_btn.setAccessibleName("Send station ID")
        self.id_btn.clicked.connect(self.transmit_id_only)
        id_layout.addWidget(self.id_btn)
        main_layout.addLayout(id_layout)

        # Explicit tab order so keyboard users get a predictable traversal: Listen,
        # target, message, Transmit, This is.
        self.setTabOrder(self.listen_btn, self.target_dropdown)
        self.setTabOrder(self.target_dropdown, self.message_input)
        self.setTabOrder(self.message_input, self.transmit_btn)
        self.setTabOrder(self.transmit_btn, self.id_btn)

        # Global keyboard shortcuts (in addition to menu shortcuts).
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.listen_btn.toggle)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.transmit_message)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.transmit_message)
        QShortcut(QKeySequence("Ctrl+I"), self, activated=self.transmit_id_only)
        # Ctrl+K (clear chat) lives on the Settings → Clear chat menu action so
        # the shortcut shows up next to the menu label and double-binding is
        # avoided.

        # Alt+1 … Alt+9 fire the first nine quick-message presets, in order.
        # User-defined phrases can't carry unique alphabetic mnemonics so we
        # claim the digit row instead; everything past slot nine is mouse-only.
        for i in range(QUICK_MESSAGE_SHORTCUT_COUNT):
            QShortcut(
                QKeySequence(f"Alt+{i + 1}"),
                self,
                activated=lambda index=i: self._send_preset(index),
            )

        # Online/offline indicator was built into the service row above so
        # it lives next to the action icons rather than down in the status
        # bar. The refresh timer is owned here because init_ui is also
        # responsible for the periodic re-probe schedule.
        self._refresh_online_indicator()
        self._online_timer = QTimer(self)
        self._online_timer.setInterval(ONLINE_REFRESH_MS)
        self._online_timer.timeout.connect(self._refresh_online_indicator)
        self._online_timer.start()

        self.statusBar().showMessage("Ready")

        # Reasonable minimum so high-DPI / large-font users don't get clipping.
        self.setMinimumSize(720, 520)

        # 4. Menus
        self.create_menus()

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

    def update_header(self):
        """Updates the top bar with current user info. In FRS mode the
        callsign segment is replaced with a 'FRS Mode' label since FRS has
        no callsign — the operator/location segments stay useful for the
        on-screen log."""
        name = self.config.get('name', 'N/A')
        loc = self.config.get('location', 'N/A')
        if self._service_mode() == SERVICE_FRS:
            self.header_label.setText(f"FRS Mode | Operator: {name} | Location: {loc}")
        else:
            call = self.config.get('callsign', 'N/A')
            self.header_label.setText(f"Station: {call} | Operator: {name} | Location: {loc}")

    def _service_mode(self):
        return normalize_service(self.config.get("radio_service"))

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
        if self.config.get("radio_service") == new_mode:
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
        recoloring, online indicator. Idempotent — safe to call from any
        path that just rebuilt the palette."""
        self._refresh_theme_toggle_glyph()
        if hasattr(self, "header_label"):
            self.header_label.setStyleSheet(theme.header_stylesheet())
        self._restyle_pending_pills()
        if hasattr(self, "chat_display"):
            self.chat_display.restyle_for_theme()
        if hasattr(self, "online_indicator"):
            self._refresh_online_indicator()

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
        """Re-apply the current palette's pill stylesheet to every live
        pending-station pill so an in-flight pill list survives a theme
        flip. The stylesheet builder is the single source of truth so the
        toggle path and add_pending_station can't drift apart."""
        sheet = theme.pill_stylesheet()
        for btn in self.pending_buttons.values():
            btn.setStyleSheet(sheet)

    def _apply_service_mode(self):
        """Enable / disable every callsign-dependent UI surface based on the
        active service. Idempotent — safe to call from init, toggle handlers,
        and config-dialog OK.

        In FRS the following are disabled or hidden:
          • target dropdown (no callsign to address)
          • 'This is' standalone-ID button (no ID rule applies)
          • online indicator + verification (FCC lookups are GMRS/HAM only)
          • pending-station bar (no detection without callsigns)
          • Contacts menu action (informational reason in tooltip)
          • chat-display pill highlighter (no callsigns to highlight)
        """
        is_frs = self._service_mode() == SERVICE_FRS

        # Header reflects mode immediately.
        self.update_header()

        # Target dropdown only makes sense when callsigns are in play.
        self.target_dropdown.setVisible(not is_frs)

        # Standalone ID button — disable rather than hide so its row layout
        # stays stable and keyboard tab-order doesn't reshuffle silently.
        self.id_btn.setEnabled(not is_frs)
        if is_frs:
            self.id_btn.setToolTip(
                "Station ID is GMRS-only — FRS has no Part 95 ID requirement. "
                "Switch to GMRS to re-enable."
            )
        else:
            self.id_btn.setToolTip(
                "Transmit station ID: This is [callsign]. [name] from [location] "
                "(Alt+I, Ctrl+I)"
            )

        # Online indicator: hide in FRS, since the only online feature
        # (callsign verification) doesn't apply.
        self.online_indicator.setVisible(not is_frs)

        # Pending bar: hide and clear in FRS so old pills don't linger.
        if is_frs:
            self._clear_all_pending_pills()
        self.pending_scroll.setVisible(not is_frs and bool(self.pending_buttons))
        self.clear_pending_btn.setVisible(not is_frs and bool(self.pending_buttons))

        # Contacts menu action — disable with explanatory tooltip so users
        # discover the feature exists and know how to re-enable it.
        if hasattr(self, "_contacts_action"):
            self._contacts_action.setEnabled(not is_frs)
            if is_frs:
                self._contacts_action.setStatusTip(
                    "Contacts apply to GMRS only — switch to GMRS to manage them."
                )
            else:
                self._contacts_action.setStatusTip(
                    "Add, edit, or remove known callsigns."
                )

        # Quick-access contacts icon button mirrors the menu action — same
        # destination, same disable rule, same explanatory tooltip.
        if hasattr(self, "contacts_icon_btn"):
            self.contacts_icon_btn.setEnabled(not is_frs)
            if is_frs:
                self.contacts_icon_btn.setToolTip(
                    "Contacts apply to GMRS only — switch to GMRS to manage them."
                )
            else:
                self.contacts_icon_btn.setToolTip("Contacts (Ctrl+B)")

        # Chat-display pill highlighting: clearing the index suppresses all
        # callsign highlighting on existing and future lines.
        self._refresh_callsign_index()

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
        dlg = ConfigDialog(self.config, self)
        if dlg.exec():
            old_device = self.config.get("input_device", -1)
            old_threshold = self.config.get("vad_threshold", 0.5)
            old_ptt = (
                self.config.get("ptt_mode", "manual"),
                self.config.get("ptt_serial_port", ""),
                self.config.get("ptt_serial_line", "RTS"),
            )
            self.config = dlg.get_config()
            save_json(CONFIG_FILE, self.config)
            self.update_header()
            stt_settings_changed = (
                old_device != self.config.get("input_device", -1)
                or old_threshold != self.config.get("vad_threshold", 0.5)
            )
            if stt_settings_changed and self.listen_btn.isChecked():
                self.stop_stt()
                self.start_stt()
            new_ptt = (
                self.config.get("ptt_mode", "manual"),
                self.config.get("ptt_serial_port", ""),
                self.config.get("ptt_serial_line", "RTS"),
            )
            if new_ptt != old_ptt:
                try:
                    self.ptt.close()
                except Exception:
                    pass
                self.ptt = make_ptt(self.config)

    def open_contacts_dialog(self):
        dlg = ContactsDialog(self.contacts, parent=self)
        if dlg.exec():
            self.contacts = sort_contacts(dlg.get_contacts())
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
        raw = self.config.get("quick_messages", []) or []
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

        self.quick_messages_widget.setVisible(bool(presets))

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
        transmission so a half-filled placeholder never goes on-air."""
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
        """
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

        if self.config.get("filter_profanity", True):
            text = mask_profanity(text)

        if not prefaced:
            target_name = ""

        spoken_text, self.last_tx_time = format_outgoing_message(
            text=text,
            target_call=target_call or "",
            target_name=target_name,
            my_call=self.config.get("callsign", "N0CALL"),
            my_name=self.config.get("name", "Default User"),
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
        if self._service_mode() == SERVICE_FRS:
            # FRS has no ID rule. The button is disabled, but the Ctrl+I /
            # Alt+I shortcuts are also bound at window level — guard here so
            # a stray hotkey can't push a callsign on-air.
            return
        spoken_text, self.last_tx_time = format_standalone_id(
            my_call=self.config.get("callsign", "N0CALL"),
            my_name=self.config.get("name", "Default User"),
            my_location=self.config.get("location", ""),
            now=datetime.datetime.now(),
        )

        formatted_msg = f"<b>[TX ID]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=theme.palette().tx)

        self._synthesize_and_play(spell_digits_in_callsigns(spoken_text))

    def _set_tx_buttons_enabled(self, enabled):
        self.transmit_btn.setEnabled(enabled)
        self.id_btn.setEnabled(enabled)

    def _synthesize_and_play(self, tts_text):
        """Kick off Piper synthesis on a background thread and hand the result
        to the player when ready. Manages TX button state across both stages."""
        tts_text = expand_tty_abbreviations(tts_text)
        self._set_tx_buttons_enabled(False)

        voice_path = self.config.get("voice", "")
        if not voice_path or not os.path.exists(voice_path):
            self.append_to_chat("<i>Error: No valid Piper voice selected. Please select one in Settings -> Configuration.</i>", color=theme.palette().error)
            self._set_tx_buttons_enabled(True)
            return

        if voice_path not in self.voice_cache:
            try:
                self.voice_cache[voice_path] = PiperVoice.load(voice_path)
            except Exception as e:
                self.append_to_chat(f"<i>Failed to load voice model: {e}</i>", color=theme.palette().error)
                self._set_tx_buttons_enabled(True)
                return

        voice = self.voice_cache[voice_path]

        self.tts_thread = TTSSynthesisThread(
            voice, tts_text,
            self.ptt.lead_in_seconds, self.ptt.tail_seconds,
            length_scale=float(self.config.get("tts_length_scale", 1.0)),
            parent=self,
        )
        self.tts_thread.ready.connect(self._on_tts_synthesized)
        self.tts_thread.error.connect(self._on_tts_synthesis_error)
        self.tts_thread.start()

    def _on_tts_synthesized(self, audio, sample_rate):
        if audio is None or len(audio) == 0:
            self.append_to_chat("<i>Warning: Piper generated no audio.</i>", color=theme.palette().error)
            self._set_tx_buttons_enabled(True)
            return

        self.audio_thread = AudioPlayerThread(
            audio, sample_rate, device=self.config.get("output_device", -1)
        )
        self.audio_thread.finished.connect(self.on_tts_finished)
        self.audio_thread.error.connect(self.on_tts_error)
        self._pause_stt_for_tx()
        try:
            self.ptt.key()
        except Exception as e:
            self.append_to_chat(f"<i>PTT key failed: {e}</i>", color=theme.palette().error)
        self.audio_thread.start()

    def _on_tts_synthesis_error(self, msg):
        traceback.print_exc()
        self.append_to_chat(f"<i>TTS Error: {msg}</i>", color=theme.palette().error)
        self._resume_stt_after_tx()
        self._set_tx_buttons_enabled(True)

    def on_tts_finished(self):
        try:
            self.ptt.unkey()
        except Exception:
            pass
        self._resume_stt_after_tx()
        self._set_tx_buttons_enabled(True)

    def on_tts_error(self, error_msg):
        try:
            self.ptt.unkey()
        except Exception:
            pass
        self._resume_stt_after_tx()
        self.append_to_chat(f"<i>TTS Error: {error_msg}</i>", color=theme.palette().error)
        self._set_tx_buttons_enabled(True)

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
            # longer exists. The fallback in on_transcription_segment
            # catches it, but resetting here keeps the next partial from
            # appearing under a misleading uid match.
            self._open_rx_uid = None
            self._open_rx_block = None
            self._open_rx_text = ""

    def _refresh_callsign_index(self):
        """Recompute the known-callsign lookup and push it to the chat widget.
        Past chat lines are re-scanned so newly-added contacts get retroactive
        pill highlighting. In FRS mode the index is forced empty — there are
        no callsigns in FRS, so highlighting them would be misleading."""
        if self._service_mode() == SERVICE_FRS:
            index = {}
        else:
            index = index_contacts_by_callsign(self.contacts)
        self.chat_display.set_callsign_index(index)
        self.chat_display.rescan_all_blocks()

    def toggle_listening(self, on):
        if on:
            self.start_stt()
        else:
            self.stop_stt()

    def start_stt(self):
        if self.stt_worker and self.stt_worker.isRunning():
            return
        desired_model = self.config.get("whisper_model", "small.en")
        if desired_model != self._stt_whisper_model_name:
            self._stt_whisper = None
            self._stt_vad_model = None
        self.stt_worker = STTWorker(
            input_device=self.config.get("input_device", -1),
            whisper_model=desired_model,
            vad_threshold=self.config.get("vad_threshold", 0.5),
            whisper=self._stt_whisper,
            vad_model=self._stt_vad_model,
            parent=self,
        )
        self.stt_worker.transcribed_segment.connect(self.on_transcription_segment)
        self.stt_worker.error.connect(self.on_stt_error)
        self.stt_worker.status.connect(self.on_stt_status)
        self.stt_worker.audio_level.connect(self.audio_level_meter.setValue)
        self.stt_worker.start()
        self.listen_btn.setText("&Listening…")
        self.listen_btn.setAccessibleDescription(
            "Microphone capture and live transcription are active. Toggle off to stop."
        )

    def stop_stt(self):
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
            if worker.whisper is not None and worker.vad_model is not None:
                self._stt_whisper = worker.whisper
                self._stt_vad_model = worker.vad_model
                self._stt_whisper_model_name = worker.whisper_model_name
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
        if self.config.get("time_format", "24h") == "12h":
            h12 = now.hour % 12 or 12
            suffix = "AM" if now.hour < 12 else "PM"
            return f"{h12}:{now.minute:02d}:{now.second:02d} {suffix}"
        return now.strftime("%H:%M:%S")

    def on_transcription_segment(self, uid, text, is_final):
        """Render a streaming RX segment into the chat.

        Partials with a new utterance_id open a fresh `[RX HH:MM:SS]:` line
        and remember its block number. Subsequent partials with the same
        uid grow that same line in place, so a long transmission reads as
        one continuous chat line instead of a stack of fragments. On the
        final segment, callsign discovery runs once over the accumulated
        text — the same one-scan-per-utterance behavior as the old
        non-streaming path.
        """
        if self.config.get("filter_profanity", True):
            text = mask_profanity(text)
        if not text:
            return

        if uid != self._open_rx_uid:
            ts = self._format_timestamp()
            block_number = self.chat_display.append_message(
                f"<b>[RX {ts}]:</b> {text}", color=theme.palette().rx
            )
            self._open_rx_uid = uid
            self._open_rx_block = block_number
            self._open_rx_text = text
        else:
            appended = self.chat_display.append_to_block(
                self._open_rx_block, " " + text, color=theme.palette().rx
            )
            if not appended:
                # The block went away (chat cleared mid-utterance). Start
                # a fresh line so the rest of the utterance still surfaces.
                ts = self._format_timestamp()
                self._open_rx_block = self.chat_display.append_message(
                    f"<b>[RX {ts}]:</b> {text}", color=theme.palette().rx
                )
                self._open_rx_text = text
            else:
                self._open_rx_text += " " + text

        if is_final:
            self.scan_for_unknown_stations(self._open_rx_text)
            self._open_rx_uid = None
            self._open_rx_block = None
            self._open_rx_text = ""

    def scan_for_unknown_stations(self, text):
        # `known` spans every callsign field on every contact (primary + GMRS
        # + HAM cross-references) so a detected HAM call doesn't show a
        # redundant '+ Add' pill when that operator's GMRS call is already
        # in the contact list (and vice versa).
        if self._service_mode() == SERVICE_FRS:
            # FRS users don't carry callsigns — detection would only generate
            # noise pills for anyone speaking a callsign on a shared FRS/GMRS
            # frequency, which the operator can't act on usefully.
            return
        my_call = self.config.get("callsign", "").upper()
        known = known_callsigns(self.contacts)
        detected = detect_callsigns(text)
        # Online state is cached for ~60s so this is cheap; capture once per
        # scan so a single utterance picks a consistent verdict for every
        # callsign it surfaces.
        online = is_online()
        for cs in detected:
            if cs == my_call or cs in known or cs in self.pending_buttons:
                continue
            name, location = extract_name_location(text, cs)
            self.add_pending_station(cs, name, location)
            # Only attempt auto-add when we have a transcript-derived first
            # name to verify against — without one, the FCC name comparison
            # in `verify_callsign` will short-circuit to a callsign_only
            # status that we'd never auto-add anyway.
            if online and name and cs not in self._callsign_lookups:
                self._start_callsign_lookup(cs, name, location)

    def _start_callsign_lookup(self, callsign, name, location):
        """Kick off a background FCC lookup that can auto-add the station if
        the licensee name matches the transcript-derived name. Imported here
        (rather than at module load) so MainWindow's import-time graph stays
        free of the FCC stack for users who never enable Listen."""
        from gmrs_tty.fcc.auto_add import CallsignLookupWorker
        worker = CallsignLookupWorker(callsign, name, location, parent=self)
        worker.result_ready.connect(self._on_callsign_lookup_result)
        worker.finished.connect(lambda cs=callsign: self._cleanup_callsign_lookup(cs))
        self._callsign_lookups[callsign] = worker
        worker.start()

    def _cleanup_callsign_lookup(self, callsign):
        worker = self._callsign_lookups.pop(callsign, None)
        if worker is not None:
            worker.deleteLater()

    def _on_callsign_lookup_result(self, callsign, name, location, result):
        """Handle the FCC lookup result on the UI thread.

        ``verified`` means the FCC licensee name matched the transcript name,
        so we auto-add the contact with full GMRS / HAM cross-references and
        retire the pending pill. Any other status leaves the pill in place
        for manual review — a name mismatch is the family-member case where
        the operator still deserves a contact entry but not the licensee's
        cross-references.
        """
        if result.status != "verified":
            return
        if callsign in known_callsigns(self.contacts):
            # Lookup raced with a manual add; honor the user's edit.
            self._remove_pending_pill(callsign)
            return
        if callsign not in self.pending_buttons:
            # User dismissed the pill while the lookup was in flight — respect
            # the dismissal rather than silently adding the contact anyway.
            return
        from gmrs_tty.fcc.crossref import apply_verification
        contact = {"callsign": callsign, "name": name, "location": location}
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        contact = apply_verification(contact, result, now_iso=now_iso)
        self.contacts.append(contact)
        self.contacts = sort_contacts(self.contacts)
        save_json(CONTACTS_FILE, self.contacts)
        self.populate_target_dropdown()
        self._refresh_callsign_index()
        self._remove_pending_pill(callsign)
        op_name = (contact.get("name") or "").strip() or "(no name)"
        self.append_to_chat(
            f"<i>Auto-added contact: {callsign} ({op_name})</i>",
            color=theme.palette().rx,
        )

    def add_pending_station(self, callsign, name, location):
        btn = QPushButton(f"+ Add {callsign}", self)
        # Pill colors come from the active palette so a later theme toggle
        # can re-style every live pill via `_restyle_pending_pills` without
        # divergence between this builder and the toggle path.
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
            lambda pos, cs=callsign, b=btn: self._show_pending_pill_menu(b, pos, cs)
        )
        self.pending_buttons[callsign] = btn
        self.pending_flow.addWidget(btn)
        self._cap_pending_scroll_height(btn)
        self._update_pending_bar_visibility()

    def _show_pending_pill_menu(self, btn, pos, callsign):
        """Right-click / long-press menu for a pending-station pill.

        Long-press on touch platforms is synthesized into a context-menu event
        by Qt, so this single handler covers both interactions."""
        menu = QMenu(self)
        dismiss_action = menu.addAction(f"Dismiss {callsign}")
        dismiss_action.setStatusTip(
            f"Remove the pending pill for {callsign} without adding it to contacts."
        )
        if menu.exec(btn.mapToGlobal(pos)) is dismiss_action:
            self._remove_pending_pill(callsign)

    def _remove_pending_pill(self, callsign):
        btn = self.pending_buttons.pop(callsign, None)
        if btn is not None:
            btn.setParent(None)
            btn.deleteLater()
        self._update_pending_bar_visibility()

    def _clear_all_pending_pills(self):
        for callsign in list(self.pending_buttons.keys()):
            self._remove_pending_pill(callsign)

    def _update_pending_bar_visibility(self):
        has_pills = bool(self.pending_buttons)
        self.clear_pending_btn.setVisible(has_pills)
        self.pending_scroll.setVisible(has_pills)

    def _cap_pending_scroll_height(self, sample_btn):
        """Lock the pending-pill scroll area to PENDING_PILL_MAX_ROWS rows.

        The pill row height is the same for every pill (shared styling), so we
        measure once on the first pill and reuse it. Beyond the cap, the
        scroll area's vertical scrollbar takes over."""
        if self._pending_row_height is not None:
            return
        row_h = sample_btn.sizeHint().height()
        if row_h <= 0:
            return
        spacing = max(self.pending_flow.spacing(), 0)
        rows = PENDING_PILL_MAX_ROWS
        max_h = rows * row_h + (rows - 1) * spacing
        self.pending_scroll.setMaximumHeight(max_h)
        self._pending_row_height = row_h

    def open_add_contact_dialog(self, callsign, name, location):
        dlg = AddContactDialog(callsign, name, location, self)
        if dlg.exec():
            contact = dlg.get_contact()
            if not contact["callsign"]:
                return
            contact = self._verify_contact_if_online(contact)
            for c in self.contacts:
                if c.get("callsign", "").upper() == contact["callsign"]:
                    c.update(contact)
                    break
            else:
                self.contacts.append(contact)
            self.contacts = sort_contacts(self.contacts)
            save_json(CONTACTS_FILE, self.contacts)
            self.populate_target_dropdown()
            self._refresh_callsign_index()
        self._remove_pending_pill(callsign)

    def _verify_contact_if_online(self, contact):
        """Run FCC verification against `contact` when online, returning a new
        dict with verification fields populated. Offline / failed lookups pass
        through unchanged so the user can still add the contact — they just
        won't get a green check until connectivity is restored. Imported here
        to keep the FCC dependency out of MainWindow's import-time graph for
        users who never open the add-contact flow."""
        from gmrs_tty.fcc.crossref import apply_verification, verify_callsign
        if not is_online():
            return contact
        result = verify_callsign(contact["callsign"], contact.get("name", ""))
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return apply_verification(contact, result, now_iso=now_iso)

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
