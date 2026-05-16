import datetime
import os
import traceback

from piper.voice import PiperVoice
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from gmrs_tty.audio.playback import AudioPlayerThread
from gmrs_tty.constants import (
    COLOR_ERROR, COLOR_RX, COLOR_TX, COLOR_WARN,
    CONFIG_FILE, CONTACTS_FILE,
    PILL_BG, PILL_BORDER, PILL_TEXT,
)
from gmrs_tty.fcc.id_rule import format_outgoing_message, format_standalone_id
from gmrs_tty.persistence.contacts import index_contacts_by_callsign, sort_contacts
from gmrs_tty.persistence.json_store import load_json, save_json
from gmrs_tty.ptt import make_ptt
from gmrs_tty.stt.worker import STTWorker
from gmrs_tty.text.callsigns import detect_callsigns, spell_digits_in_callsigns
from gmrs_tty.text.metadata import extract_name_location
from gmrs_tty.text.profanity import mask_profanity
from gmrs_tty.text.placeholders import find_placeholders, substitute_placeholders
from gmrs_tty.text.shorthand import expand_tty_abbreviations
from gmrs_tty.tts.synthesizer import TTSSynthesisThread
from gmrs_tty.ui.chat_display import ChatDisplay
from gmrs_tty.ui.config_dialog import ConfigDialog
from gmrs_tty.ui.contacts_dialog import AddContactDialog, ContactsDialog
from gmrs_tty.ui.flow_layout import FlowLayout
from gmrs_tty.ui.quick_messages_dialog import QuickMessagesDialog

PENDING_PILL_MAX_ROWS = 3
QUICK_MESSAGE_SHORTCUT_COUNT = 9


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
        self.pending_buttons = {}  # callsign -> QPushButton
        self._pending_row_height = None  # cached pill row height for scroll cap
        self.ptt = make_ptt(self.config)

        self.init_ui()
        self.update_header()
        self.populate_target_dropdown()
        self.populate_quick_messages_strip()
        self._refresh_callsign_index()
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
                color=COLOR_WARN,
            )

    def closeEvent(self, event):
        self.stop_stt()
        for attr in ('tts_thread', 'audio_thread'):
            thread = getattr(self, attr, None)
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait()
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

        # 1. Header (User Info). Bold via QFont so size scales with system font (WCAG 1.4.4).
        self.header_label = QLabel("Loading...", self)
        header_font = QFont(self.font())
        header_font.setBold(True)
        header_font.setPointSize(header_font.pointSize() + 2)
        self.header_label.setFont(header_font)
        self.header_label.setStyleSheet(
            "padding: 10px; background-color: #F0F0F0; border-radius: 5px;"
        )
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
        """Updates the top bar with current user info."""
        call = self.config.get('callsign', 'N/A')
        name = self.config.get('name', 'N/A')
        loc = self.config.get('location', 'N/A')
        self.header_label.setText(f"Station: {call} | Operator: {name} | Location: {loc}")

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
        """
        target_data = self.target_dropdown.currentData() or ("", "")
        target_call, target_name = target_data
        prefaced = bool(target_call and target_call.upper() != "ALL")

        # Empty text is only valid when calling a specific station — the preface itself is the call.
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
        )

        formatted_msg = f"<b>[TX to {target_call}]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=COLOR_TX)

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
        spoken_text, self.last_tx_time = format_standalone_id(
            my_call=self.config.get("callsign", "N0CALL"),
            my_name=self.config.get("name", "Default User"),
            my_location=self.config.get("location", ""),
            now=datetime.datetime.now(),
        )

        formatted_msg = f"<b>[TX ID]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=COLOR_TX)

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
            self.append_to_chat("<i>Error: No valid Piper voice selected. Please select one in Settings -> Configuration.</i>", color=COLOR_ERROR)
            self._set_tx_buttons_enabled(True)
            return

        if voice_path not in self.voice_cache:
            try:
                self.voice_cache[voice_path] = PiperVoice.load(voice_path)
            except Exception as e:
                self.append_to_chat(f"<i>Failed to load voice model: {e}</i>", color=COLOR_ERROR)
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
            self.append_to_chat("<i>Warning: Piper generated no audio.</i>", color=COLOR_ERROR)
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
            self.append_to_chat(f"<i>PTT key failed: {e}</i>", color=COLOR_ERROR)
        self.audio_thread.start()

    def _on_tts_synthesis_error(self, msg):
        traceback.print_exc()
        self.append_to_chat(f"<i>TTS Error: {msg}</i>", color=COLOR_ERROR)
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
        self.append_to_chat(f"<i>TTS Error: {error_msg}</i>", color=COLOR_ERROR)
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

    def _refresh_callsign_index(self):
        """Recompute the known-callsign lookup and push it to the chat widget.
        Past chat lines are re-scanned so newly-added contacts get retroactive
        pill highlighting."""
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
        self.stt_worker.transcribed.connect(self.on_transcription)
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
                worker.transcribed.disconnect(self.on_transcription)
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

    def on_transcription(self, text):
        if self.config.get("filter_profanity", True):
            text = mask_profanity(text)
        ts = self._format_timestamp()
        self.append_to_chat(f"<b>[RX {ts}]:</b> {text}", color=COLOR_RX)
        self.scan_for_unknown_stations(text)

    def scan_for_unknown_stations(self, text):
        my_call = self.config.get("callsign", "").upper()
        known = {c.get("callsign", "").upper() for c in self.contacts}
        detected = detect_callsigns(text)
        for cs in detected:
            if cs == my_call or cs in known or cs in self.pending_buttons:
                continue
            name, location = extract_name_location(text, cs)
            self.add_pending_station(cs, name, location)

    def add_pending_station(self, callsign, name, location):
        btn = QPushButton(f"+ Add {callsign}", self)
        # WCAG: amber-100 background + amber-900 text gives ≥10:1 contrast; border
        # is amber-700 (4.05:1 against white) so the pill is distinguishable for
        # users who don't perceive color cues. Focus ring is left to the platform.
        btn.setStyleSheet(
            "QPushButton {"
            f" background-color: {PILL_BG};"
            f" color: {PILL_TEXT};"
            f" border: 2px solid {PILL_BORDER};"
            " padding: 4px 10px; border-radius: 4px;"
            "}"
        )
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

    def on_stt_error(self, msg):
        self.append_to_chat(f"<i>STT Error: {msg}</i>", color=COLOR_ERROR)
        self.listen_btn.blockSignals(True)
        self.listen_btn.setChecked(False)
        self.listen_btn.setText("&Listen")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio. Currently stopped."
        )
        self.listen_btn.blockSignals(False)

    def on_stt_status(self, msg):
        self.statusBar().showMessage(msg, 5000)
