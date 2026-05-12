import sys
import json
import os
import glob
import datetime
import re
import wave
import io
import traceback
import tempfile
import collections

import numpy as np
import sounddevice as sd
import soundfile as sf
from piper.voice import PiperVoice
from piper.config import SynthesisConfig

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QTextEdit, QLineEdit, QPushButton, QDialog,
    QFormLayout, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QThread, Signal

CONFIG_FILE = "config.json"
CONTACTS_FILE = "contacts.json"

# GMRS callsign formats: modern (W + 3 letters + 3 digits) and legacy (KAE/KAA + 3-4 digits)
CALLSIGN_RE = re.compile(r'\b(W[A-Z]{3}\d{3}|KA[A-Z]\d{3,4})\b', re.IGNORECASE)

# NATO phonetic alphabet (case insensitive)
NATO_PHONETIC = {
    "alpha": "A", "alfa": "A", "bravo": "B", "charlie": "C", "delta": "D",
    "echo": "E", "foxtrot": "F", "golf": "G", "hotel": "H", "india": "I",
    "juliet": "J", "juliett": "J", "kilo": "K", "lima": "L", "mike": "M",
    "november": "N", "oscar": "O", "papa": "P", "quebec": "Q", "romeo": "R",
    "sierra": "S", "tango": "T", "uniform": "U", "victor": "V", "whiskey": "W",
    "whisky": "W", "xray": "X", "yankee": "Y", "zulu": "Z",
}
NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "fife": "5", "six": "6", "seven": "7", "eight": "8",
    "niner": "9", "nine": "9",
}
SINGLE_CHAR_RUN_RE = re.compile(r'\b(?:[A-Za-z0-9][\s\-.,]+){2,}[A-Za-z0-9]\b')
LOCATION_RE = re.compile(
    r'\b(?:in|from|near|at)\s+([A-Z][a-z]+(?:[\s,]+[A-Z][a-z]+){0,3})',
)


def _convert_phonetics(text):
    """Replace NATO phonetic words and spelled-out digits with letters/digits."""
    def repl(m):
        w = m.group(0).lower()
        return NATO_PHONETIC.get(w, NUMBER_WORDS.get(w, m.group(0)))
    return re.sub(r'\b[A-Za-z]+\b', repl, text)


def _collapse_single_char_runs(text):
    """Collapse runs of single-char tokens separated by whitespace, hyphens, periods, or commas.
    'W S L Z 2 3 3' -> 'WSLZ233', 'W.S.L.Z.2.3.3' -> 'WSLZ233', 'W, S, L, Z, 2, 3, 3' -> 'WSLZ233'."""
    return SINGLE_CHAR_RUN_RE.sub(
        lambda m: re.sub(r'[\s\-.,]+', '', m.group(0)), text
    )


def _join_letters_and_digits(text):
    """Join a letter block to an adjacent digit block: 'WSLZ 233', 'WSLZ.233', 'WSLZ, 233' -> 'WSLZ233'."""
    return re.sub(r'([A-Za-z]{2,})[\s\-.,]+(\d{3,4})\b', r'\1\2', text)


def detect_callsigns(text):
    """Return uppercased GMRS callsigns found in raw or phonetic/spaced forms.
    Handles separators: whitespace, hyphens, and periods between letters/digits."""
    if not text:
        return []
    found = set()
    phonetic = _convert_phonetics(text)
    variants = [
        text,
        _join_letters_and_digits(text),
        _collapse_single_char_runs(text),
        _join_letters_and_digits(_collapse_single_char_runs(text)),
        _collapse_single_char_runs(phonetic),
        _join_letters_and_digits(phonetic),
        _join_letters_and_digits(_collapse_single_char_runs(phonetic)),
    ]
    for variant in variants:
        for m in CALLSIGN_RE.finditer(variant):
            found.add(m.group(1).upper())
    return sorted(found)


def extract_name_location(text, callsign):
    """Heuristic: name is the first capitalized word after the callsign mention;
    location is the capitalized phrase after 'in/from/near/at' anywhere in the text."""
    name = ""
    location = ""
    upper = text.upper()
    idx = upper.find(callsign)
    if idx >= 0:
        after = text[idx + len(callsign):].lstrip(",.;: \t")
        name_match = re.match(r'([A-Z][a-z]+)', after)
        if name_match:
            name = name_match.group(1)
    loc_match = LOCATION_RE.search(text)
    if loc_match:
        location = loc_match.group(1).strip(" ,")
    return name, location

def load_json(filepath, default_data):
    """Helper to load JSON files safely."""
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Error decoding {filepath}. Using defaults.")
    return default_data

def save_json(filepath, data):
    """Helper to save JSON files safely."""
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

class AudioPlayerThread(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, audio_data, sample_rate):
        super().__init__()
        self.audio_data = audio_data
        self.sample_rate = sample_rate

    def run(self):
        try:
            sd.play(self.audio_data, samplerate=self.sample_rate)
            sd.wait()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()


class STTWorker(QThread):
    """Captures mic audio, gates on Silero VAD, transcribes speech with faster-whisper."""
    transcribed = Signal(str)
    error = Signal(str)
    status = Signal(str)

    SAMPLE_RATE = 16000
    CHUNK_SAMPLES = 512  # required by Silero VAD at 16kHz
    PRE_BUFFER_CHUNKS = 10  # ~320ms of pre-speech context
    MIN_SPEECH_DURATION_S = 0.4  # drops kerchunks / blips

    # Common Whisper hallucinations on silence/noise — drop these
    HALLUCINATIONS = frozenset({
        "you", "thank you", "thanks", "thanks for watching",
        "thank you for watching", "thanks for watching!", "bye", ".",
        "okay", "ok", "yeah", "mm", "hmm",
    })

    def __init__(self, input_device=None, whisper_model="small.en", parent=None):
        super().__init__(parent)
        self.input_device = input_device if input_device not in (None, -1) else None
        self.whisper_model_name = whisper_model
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            from silero_vad import load_silero_vad, VADIterator
            from faster_whisper import WhisperModel
            import noisereduce as nr
        except Exception as e:
            self.error.emit(f"STT dependencies missing — run 'pip install -r requirements.txt': {e}")
            return

        if not self._running:
            return

        try:
            self.status.emit("Loading Whisper model (first run downloads ~250MB)...")
            whisper = WhisperModel(self.whisper_model_name, device="cpu", compute_type="int8")
            vad_model = load_silero_vad()
            vad_iter = VADIterator(
                vad_model,
                sampling_rate=self.SAMPLE_RATE,
                threshold=0.5,
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            )
        except Exception as e:
            self.error.emit(f"Failed to initialize STT models: {e}")
            return

        if not self._running:
            return

        try:
            stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype='float32',
                device=self.input_device,
            )
            stream.start()
        except Exception as e:
            self.error.emit(f"Failed to open input device: {e}")
            return

        self.status.emit("Listening...")
        rolling = collections.deque(maxlen=self.PRE_BUFFER_CHUNKS)
        collected = []
        in_speech = False

        try:
            while self._running:
                try:
                    data, _ = stream.read(self.CHUNK_SAMPLES)
                except Exception as e:
                    self.error.emit(f"Audio read error: {e}")
                    break

                chunk = data[:, 0].copy()

                try:
                    speech_dict = vad_iter(chunk, return_seconds=False)
                except Exception as e:
                    print(f"VAD error on chunk: {e}")
                    speech_dict = None

                if speech_dict and 'start' in speech_dict:
                    in_speech = True
                    collected = list(rolling) + [chunk]
                elif speech_dict and 'end' in speech_dict:
                    collected.append(chunk)
                    audio = np.concatenate(collected)
                    in_speech = False
                    collected = []
                    if len(audio) / self.SAMPLE_RATE >= self.MIN_SPEECH_DURATION_S:
                        self._transcribe(audio, whisper, nr)
                elif in_speech:
                    collected.append(chunk)

                rolling.append(chunk)
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            self.status.emit("Stopped listening")

    def _transcribe(self, audio, whisper, nr_module):
        try:
            denoised = nr_module.reduce_noise(
                y=audio, sr=self.SAMPLE_RATE, prop_decrease=0.7
            ).astype(np.float32)

            segments, _ = whisper.transcribe(
                denoised, language="en", beam_size=1, vad_filter=False
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            normalized = text.lower().strip(".,!?;: ")
            if text and normalized not in self.HALLUCINATIONS:
                self.transcribed.emit(text)
        except Exception as e:
            self.error.emit(f"Transcription error: {e}")


class ConfigDialog(QDialog):
    """Dialog for editing user configuration."""
    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setMinimumWidth(300)
        self.config = current_config

        layout = QFormLayout(self)

        self.callsign_input = QLineEdit(self.config.get("callsign", ""))
        self.name_input = QLineEdit(self.config.get("name", ""))
        self.location_input = QLineEdit(self.config.get("location", ""))
        self.voice_input = QComboBox()
        self.input_device_input = QComboBox()

        voices = glob.glob(os.path.join("Voices", "*.onnx"))
        if not voices:
            self.voice_input.addItem("No voices found in Voices/", "")
        else:
            for v in voices:
                self.voice_input.addItem(os.path.basename(v), v)

        current_voice = self.config.get("voice", "")
        if current_voice:
            index = self.voice_input.findData(current_voice)
            if index >= 0:
                self.voice_input.setCurrentIndex(index)

        self.input_device_input.addItem("System Default", -1)
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev.get('max_input_channels', 0) > 0:
                    self.input_device_input.addItem(f"{i}: {dev['name']}", i)
        except Exception as e:
            print(f"Could not enumerate input devices: {e}")

        current_dev = self.config.get("input_device", -1)
        idx = self.input_device_input.findData(current_dev)
        if idx >= 0:
            self.input_device_input.setCurrentIndex(idx)

        layout.addRow("Callsign:", self.callsign_input)
        layout.addRow("Name:", self.name_input)
        layout.addRow("Location:", self.location_input)
        layout.addRow("Voice Model:", self.voice_input)
        layout.addRow("Input Device:", self.input_device_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_config(self):
        return {
            "callsign": self.callsign_input.text().strip().upper(),
            "name": self.name_input.text().strip(),
            "location": self.location_input.text().strip(),
            "voice": self.voice_input.currentData(),
            "input_device": self.input_device_input.currentData(),
        }


class ContactsDialog(QDialog):
    """Dialog for managing known contacts."""
    def __init__(self, current_contacts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contact Management")
        self.setMinimumSize(500, 300)
        self.contacts = current_contacts

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Callsign", "Name", "Location"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.populate_table()

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Contact")
        self.add_btn.clicked.connect(self.add_row)
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_row)

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
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
        self.setMinimumWidth(320)
        layout = QFormLayout(self)
        self.callsign_input = QLineEdit(callsign)
        self.name_input = QLineEdit(name)
        self.location_input = QLineEdit(location)
        layout.addRow("Callsign:", self.callsign_input)
        layout.addRow("Name:", self.name_input)
        layout.addRow("Location:", self.location_input)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GMRS-TTY")
        self.resize(800, 600)

        # State Initialization
        self.config = load_json(CONFIG_FILE, {"callsign": "N0CALL", "name": "Default", "location": "Unknown"})
        self.contacts = load_json(CONTACTS_FILE, [{"callsign": "All", "name": "Everyone"}])
        self.last_tx_time = None

        self.voice_cache = {}
        self.stt_worker = None
        self.pending_buttons = {}  # callsign -> QPushButton

        self.init_ui()
        self.update_header()
        self.populate_target_dropdown()

    def closeEvent(self, event):
        self.stop_stt()
        if hasattr(self, 'audio_thread') and self.audio_thread.isRunning():
            self.audio_thread.quit()
            self.audio_thread.wait()
        super().closeEvent(event)

    def init_ui(self):
        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 1. Header (User Info)
        self.header_label = QLabel("Loading...", self)
        self.header_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.header_label)

        # 2. Main Chat Room (Rx Section)
        self.chat_display = QTextEdit(self)
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("font-size: 14px; padding: 5px;")
        main_layout.addWidget(self.chat_display)

        # 2b. Pending stations bar (populates when STT detects unknown callsigns)
        self.pending_bar = QHBoxLayout()
        self.pending_bar.setSpacing(5)
        self.pending_bar.addStretch()
        main_layout.addLayout(self.pending_bar)

        # 3. Input Area (Tx Section)
        input_layout = QHBoxLayout()

        self.listen_btn = QPushButton("Listen", self)
        self.listen_btn.setCheckable(True)
        self.listen_btn.setToolTip("Toggle microphone capture / live transcription")
        self.listen_btn.toggled.connect(self.toggle_listening)
        input_layout.addWidget(self.listen_btn)

        self.target_dropdown = QComboBox(self)
        self.target_dropdown.setMinimumWidth(120)
        input_layout.addWidget(self.target_dropdown)

        self.message_input = QLineEdit(self)
        self.message_input.setPlaceholderText("Type your message here...")
        self.message_input.returnPressed.connect(self.transmit_message)
        input_layout.addWidget(self.message_input)

        self.transmit_btn = QPushButton("Transmit", self)
        self.transmit_btn.clicked.connect(self.transmit_message)
        input_layout.addWidget(self.transmit_btn)

        main_layout.addLayout(input_layout)

        self.statusBar().showMessage("Ready")

        # 4. Menus
        self.create_menus()

    def create_menus(self):
        menubar = self.menuBar()
        
        # Settings Menu
        settings_menu = menubar.addMenu("Settings")
        
        config_action = QAction("Configuration", self)
        config_action.triggered.connect(self.open_config_dialog)
        settings_menu.addAction(config_action)

        contacts_action = QAction("Contacts", self)
        contacts_action.triggered.connect(self.open_contacts_dialog)
        settings_menu.addAction(contacts_action)

    def update_header(self):
        """Updates the top bar with current user info."""
        call = self.config.get('callsign', 'N/A')
        name = self.config.get('name', 'N/A')
        loc = self.config.get('location', 'N/A')
        self.header_label.setText(f"Station: {call} | Operator: {name} | Location: {loc}")

    def populate_target_dropdown(self):
        """Fills the target selection combo box with current contacts."""
        self.target_dropdown.clear()
        for contact in self.contacts:
            display_text = f"{contact['callsign']} ({contact['name']})"
            self.target_dropdown.addItem(display_text, userData=contact['callsign'])

    def open_config_dialog(self):
        dlg = ConfigDialog(self.config, self)
        if dlg.exec():
            old_device = self.config.get("input_device", -1)
            self.config = dlg.get_config()
            save_json(CONFIG_FILE, self.config)
            self.update_header()
            if old_device != self.config.get("input_device", -1) and self.listen_btn.isChecked():
                self.stop_stt()
                self.start_stt()

    def open_contacts_dialog(self):
        dlg = ContactsDialog(self.contacts, self)
        if dlg.exec():
            self.contacts = dlg.get_contacts()
            save_json(CONTACTS_FILE, self.contacts)
            self.populate_target_dropdown()

    def transmit_message(self):
        """Handles when the user attempts to send a message."""
        text = self.message_input.text().strip()
        if not text:
            return

        target_call = self.target_dropdown.currentData()
        target_name = self.target_dropdown.currentText().split(" (")[0] # fallback display

        my_call = self.config.get("callsign", "N0CALL")
        my_name = self.config.get("name", "Default User")
        
        now = datetime.datetime.now()
        append_id = False
        # Append ID if this is the first transmission or 15 minutes have passed
        if self.last_tx_time is None or (now - self.last_tx_time).total_seconds() > 15 * 60:
            append_id = True

        if target_call and target_call.upper() != "ALL":
            spoken_text = f"{my_call} {my_name} calling {target_call}. {text}"
        else:
            spoken_text = text
        
        if append_id:
            spoken_text += f". This is {my_call} {my_name}."
            self.last_tx_time = now

        # Append to chat
        formatted_msg = f"<b>[TX to {target_call}]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color="blue")
        
        # Clear input box and disable until finished
        self.message_input.clear()
        self.transmit_btn.setEnabled(False)

        voice_path = self.config.get("voice", "")
        if not voice_path or not os.path.exists(voice_path):
            self.append_to_chat("<i>Error: No valid Piper voice selected. Please select one in Settings -> Configuration.</i>", color="red")
            self.transmit_btn.setEnabled(True)
            return

        # 1. Load Voice Model (cached for speed)
        if voice_path not in self.voice_cache:
            try:
                self.voice_cache[voice_path] = PiperVoice.load(voice_path)
            except Exception as e:
                self.append_to_chat(f"<i>Failed to load voice model: {e}</i>", color="red")
                self.transmit_btn.setEnabled(True)
                return

        voice = self.voice_cache[voice_path]
        
        # 2. Synthesize audio sequentially in the main thread (fixes espeak-ng thread crashes)
        try:
            sentences = re.split(r'(?<=[.!?])\s+', spoken_text)
            audio_chunks = []
            
            syn_config = SynthesisConfig(speaker_id=0) if voice.config.num_speakers > 1 else None

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    temp_wav_path = tmp.name

                try:
                    with wave.open(temp_wav_path, 'wb') as wav_file:
                        voice.synthesize_wav(sentence, wav_file, syn_config=syn_config)
                    
                    data, fs = sf.read(temp_wav_path, dtype='int16')
                    if len(data) > 0:
                        audio_chunks.append(data)
                    else:
                        self.append_to_chat(f"<i>Warning: Piper generated 0 frames for: '{sentence}'</i>", color="red")
                finally:
                    if os.path.exists(temp_wav_path):
                        os.remove(temp_wav_path)
            
            if audio_chunks:
                full_audio = np.concatenate(audio_chunks)
                self.audio_thread = AudioPlayerThread(full_audio, voice.config.sample_rate)
                self.audio_thread.finished.connect(self.on_tts_finished)
                self.audio_thread.error.connect(self.on_tts_error)
                self.audio_thread.start()
            else:
                self.transmit_btn.setEnabled(True)

        except Exception as e:
            traceback.print_exc()
            self.append_to_chat(f"<i>TTS Error: {str(e)}</i>", color="red")
            self.transmit_btn.setEnabled(True)

    def on_tts_finished(self):
        self.transmit_btn.setEnabled(True)

    def on_tts_error(self, error_msg):
        self.append_to_chat(f"<i>TTS Error: {error_msg}</i>", color="red")
        self.transmit_btn.setEnabled(True)

    def append_to_chat(self, text, color="black"):
        """Appends HTML formatted text to the chat display."""
        self.chat_display.append(f"<span style='color:{color};'>{text}</span>")

    def toggle_listening(self, on):
        if on:
            self.start_stt()
        else:
            self.stop_stt()

    def start_stt(self):
        if self.stt_worker and self.stt_worker.isRunning():
            return
        self.stt_worker = STTWorker(
            input_device=self.config.get("input_device", -1),
            parent=self,
        )
        self.stt_worker.transcribed.connect(self.on_transcription)
        self.stt_worker.error.connect(self.on_stt_error)
        self.stt_worker.status.connect(self.on_stt_status)
        self.stt_worker.start()
        self.listen_btn.setText("Listening...")

    def stop_stt(self):
        worker = self.stt_worker
        self.stt_worker = None
        if worker is not None:
            try:
                worker.transcribed.disconnect(self.on_transcription)
                worker.error.disconnect(self.on_stt_error)
                worker.status.disconnect(self.on_stt_status)
            except (TypeError, RuntimeError):
                pass
            worker.stop()
            if worker.isRunning():
                worker.wait(15000)
            worker.deleteLater()
        self.listen_btn.setText("Listen")

    def on_transcription(self, text):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.append_to_chat(f"<b>[RX {ts}]:</b> {text}", color="green")
        self.scan_for_unknown_stations(text)

    def scan_for_unknown_stations(self, text):
        my_call = self.config.get("callsign", "").upper()
        known = {c.get("callsign", "").upper() for c in self.contacts}
        detected = detect_callsigns(text)
        print(f"[scan] text={text!r} detected={detected} my_call={my_call} known={known}", file=sys.stderr)
        for cs in detected:
            if cs == my_call or cs in known or cs in self.pending_buttons:
                print(f"[scan] skipping {cs} (own/known/pending)", file=sys.stderr)
                continue
            name, location = extract_name_location(text, cs)
            print(f"[scan] adding pending {cs} name={name!r} location={location!r}", file=sys.stderr)
            self.add_pending_station(cs, name, location)

    def add_pending_station(self, callsign, name, location):
        btn = QPushButton(f"+ Add {callsign}", self)
        btn.setStyleSheet(
            "QPushButton { background-color: #fff3cd; border: 1px solid #d4a72c; "
            "padding: 4px 8px; border-radius: 4px; }"
        )
        tooltip_parts = [f"Detected new station: {callsign}"]
        if name:
            tooltip_parts.append(f"Name: {name}")
        if location:
            tooltip_parts.append(f"Location: {location}")
        btn.setToolTip("\n".join(tooltip_parts))
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
            save_json(CONTACTS_FILE, self.contacts)
            self.populate_target_dropdown()
        btn = self.pending_buttons.pop(callsign, None)
        if btn is not None:
            btn.setParent(None)
            btn.deleteLater()

    def on_stt_error(self, msg):
        self.append_to_chat(f"<i>STT Error: {msg}</i>", color="red")
        self.listen_btn.blockSignals(True)
        self.listen_btn.setChecked(False)
        self.listen_btn.setText("Listen")
        self.listen_btn.blockSignals(False)

    def on_stt_status(self, msg):
        self.statusBar().showMessage(msg, 5000)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Apply a clean, default styling
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())