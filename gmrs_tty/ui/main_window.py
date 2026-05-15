import datetime
import os
import traceback

from piper.voice import PiperVoice
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
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
from gmrs_tty.text.shorthand import expand_tty_abbreviations
from gmrs_tty.tts.synthesizer import TTSSynthesisThread
from gmrs_tty.ui.chat_display import ChatDisplay
from gmrs_tty.ui.config_dialog import ConfigDialog
from gmrs_tty.ui.contacts_dialog import AddContactDialog, ContactsDialog


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
        self.ptt = make_ptt(self.config)

        self.init_ui()
        self.update_header()
        self.populate_target_dropdown()
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

        # 2b. Pending stations bar (populates when STT detects unknown callsigns)
        self.pending_bar = QHBoxLayout()
        self.pending_bar.setSpacing(5)
        self.pending_bar.addStretch()
        main_layout.addLayout(self.pending_bar)

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
        so the entry never duplicates."""
        self.target_dropdown.clear()
        self.target_dropdown.addItem("All (Everyone)", userData="All")
        for contact in self.contacts:
            if (contact.get("callsign", "") or "").upper() == "ALL":
                continue
            display_text = f"{contact['callsign']} ({contact['name']})"
            self.target_dropdown.addItem(display_text, userData=contact['callsign'])

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

    def transmit_message(self):
        """Handles when the user attempts to send a message."""
        text = self.message_input.text().strip()
        target_call = self.target_dropdown.currentData()
        prefaced = bool(target_call and target_call.upper() != "ALL")

        # Empty text is only valid when calling a specific station — the preface itself is the call.
        if not text and not prefaced:
            return

        target_name = ""
        if prefaced:
            target_name = next(
                (c.get("name", "") for c in self.contacts
                 if c.get("callsign", "").upper() == target_call.upper()),
                ""
            )

        spoken_text, self.last_tx_time = format_outgoing_message(
            text=text,
            target_call=target_call or "",
            target_name=target_name,
            my_call=self.config.get("callsign", "N0CALL"),
            my_name=self.config.get("name", "Default User"),
            last_id_time=self.last_tx_time,
            now=datetime.datetime.now(),
        )

        # Append to chat (original form for readability)
        formatted_msg = f"<b>[TX to {target_call}]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=COLOR_TX)

        # Clear input box; TTS spells out callsign digits ('233' -> '2 3 3').
        self.message_input.clear()

        if prefaced:
            for i in range(self.target_dropdown.count()):
                data = self.target_dropdown.itemData(i)
                if data and str(data).upper() == "ALL":
                    self.target_dropdown.setCurrentIndex(i)
                    break

        self._synthesize_and_play(spell_digits_in_callsigns(spoken_text))

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
        btn.setToolTip("\n".join(tooltip_parts))
        btn.setAccessibleName(f"Add station {callsign}")
        descr = f"Open the Add Station dialog prefilled for callsign {callsign}"
        if name:
            descr += f", operator {name}"
        if location:
            descr += f", location {location}"
        btn.setAccessibleDescription(descr + ".")
        btn.clicked.connect(
            lambda _checked=False, cs=callsign, n=name, loc=location:
                self.open_add_contact_dialog(cs, n, loc)
        )
        self.pending_buttons[callsign] = btn
        # Insert before the stretch so buttons stack left-to-right
        self.pending_bar.insertWidget(self.pending_bar.count() - 1, btn)

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
        btn = self.pending_buttons.pop(callsign, None)
        if btn is not None:
            btn.setParent(None)
            btn.deleteLater()

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
