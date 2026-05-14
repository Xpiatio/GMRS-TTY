import sys
import json
import os
import glob
import datetime
import re
import traceback
import collections

import numpy as np
import sounddevice as sd
import soundfile as sf
from piper.voice import PiperVoice
from piper.config import SynthesisConfig

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QTextEdit, QLineEdit, QPushButton,
    QDialog, QFormLayout, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QDoubleSpinBox,
)
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QThread, Signal

CONFIG_FILE = "config.json"
CONTACTS_FILE = "contacts.json"

# WCAG 2.1 AA color palette. Text colors meet ≥4.5:1 contrast against white;
# UI borders/icons meet ≥3:1. Picked from the Tailwind palette which has
# documented contrast ratios.
COLOR_RX = "#15803D"      # green-700, 5.59:1 on white — incoming transmissions
COLOR_TX = "#1D4ED8"      # blue-700, 7.10:1 on white — outgoing transmissions
COLOR_ERROR = "#B91C1C"   # red-700, 6.45:1 on white — errors
COLOR_WARN = "#92400E"    # amber-800, 8.13:1 on white — warnings / info
PILL_BG = "#FEF3C7"       # amber-100 background for pending-station pills
PILL_TEXT = "#78350F"     # amber-900, ≥10:1 on PILL_BG
PILL_BORDER = "#A16207"   # amber-700, 4.05:1 on white (UI border)

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


LETTER_TO_NATO = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta",
    "E": "Echo", "F": "Foxtrot", "G": "Golf", "H": "Hotel",
    "I": "India", "J": "Juliet", "K": "Kilo", "L": "Lima",
    "M": "Mike", "N": "November", "O": "Oscar", "P": "Papa",
    "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray",
    "Y": "Yankee", "Z": "Zulu",
}


def callsign_to_nato(callsign):
    """'WSLZ233' -> 'Whiskey Sierra Lima Zulu 2 3 3'. Letters become NATO words,
    digits stay individual."""
    parts = []
    for ch in callsign.upper():
        if ch in LETTER_TO_NATO:
            parts.append(LETTER_TO_NATO[ch])
        elif ch.isdigit():
            parts.append(ch)
    return ' '.join(parts)


def spell_digits_in_callsigns(text):
    """Insert spaces between the digits of any GMRS callsign so TTS reads them
    individually ('233' -> '2 3 3') instead of as 'two hundred thirty-three'."""
    def repl(m):
        cs = m.group(1)
        prefix = re.match(r'^[A-Za-z]+', cs).group(0)
        digits = cs[len(prefix):]
        return f"{prefix} {' '.join(digits)}"
    return CALLSIGN_RE.sub(repl, text)


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


def sort_contacts(contacts):
    """Return `contacts` sorted alphabetically by callsign (case-insensitive),
    with the special 'ALL' open-call entry pinned at index 0 and ties broken
    by operator name so shared family callsigns get a stable order."""
    def key(c):
        cs = (c.get("callsign", "") or "").upper()
        nm = (c.get("name", "") or "").upper()
        # ALL is the open-call shortcut, not a real station; keep it first
        # regardless of where it would sort alphabetically.
        if cs == "ALL":
            return (0, "", "")
        return (1, cs, nm)
    return sorted(contacts, key=key)

class AudioPlayerThread(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, audio_data, sample_rate, device=None):
        super().__init__()
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.device = device if device not in (None, -1) else None

    def run(self):
        try:
            sd.play(self.audio_data, samplerate=self.sample_rate, device=self.device)
            sd.wait()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()


class TTSSynthesisThread(QThread):
    """Renders Piper synthesis off the GUI thread and emits the assembled
    int16 PCM buffer (with PTT lead-in/tail silence already padded in).
    Only one instance runs at a time — espeak-ng's global state is not safe
    under concurrent synthesis."""
    ready = Signal(object, int)  # (np.ndarray int16 or None, sample_rate)
    error = Signal(str)

    def __init__(self, voice, text, lead_seconds, tail_seconds, parent=None):
        super().__init__(parent)
        self.voice = voice
        self.text = text
        self.lead_seconds = lead_seconds
        self.tail_seconds = tail_seconds

    def run(self):
        try:
            syn_config = (
                SynthesisConfig(speaker_id=0)
                if self.voice.config.num_speakers > 1 else None
            )
            sample_rate = self.voice.config.sample_rate

            chunks = []
            for chunk in self.voice.synthesize(self.text, syn_config=syn_config):
                arr = chunk.audio_int16_array
                if len(arr) > 0:
                    chunks.append(arr)

            if not chunks:
                self.ready.emit(None, sample_rate)
                return

            lead_samples = int(self.lead_seconds * sample_rate)
            tail_samples = int(self.tail_seconds * sample_rate)
            total = lead_samples + sum(len(c) for c in chunks) + tail_samples
            # np.zeros so lead and tail regions are already silence; no
            # extra concatenates to splice them in.
            audio = np.zeros(total, dtype=np.int16)
            pos = lead_samples
            for c in chunks:
                n = len(c)
                audio[pos:pos + n] = c
                pos += n
            self.ready.emit(audio, sample_rate)
        except Exception as e:
            self.error.emit(str(e))


class PTT:
    """PTT interface. Modes share lead-in/tail silence padding so the radio's
    keying ramp or VOX hang time doesn't clip audio."""
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def key(self):
        pass

    def unkey(self):
        pass

    def close(self):
        pass


class ManualPTT(PTT):
    """User keys the radio themselves; app just plays audio."""


class VoxPTT(PTT):
    """Radio's VOX circuit auto-keys on detected audio. Extra trailing silence
    keeps VOX engaged so the last syllable isn't clipped on dropout."""
    tail_seconds = 0.15


class SerialPTT(PTT):
    """USB-serial RTS or DTR drives an external transistor on the radio's PTT line.
    Lead-in/tail give the TX chain time to settle on both sides of the audio."""
    lead_in_seconds = 0.05
    tail_seconds = 0.05

    def __init__(self, port, line="RTS"):
        import serial
        self.line = (line or "RTS").upper()
        self.port = serial.Serial(port)
        self.port.rts = False
        self.port.dtr = False

    def key(self):
        if self.line == "DTR":
            self.port.dtr = True
        else:
            self.port.rts = True

    def unkey(self):
        if self.line == "DTR":
            self.port.dtr = False
        else:
            self.port.rts = False

    def close(self):
        try:
            self.unkey()
            self.port.close()
        except Exception:
            pass


def make_ptt(config):
    mode = config.get("ptt_mode", "manual")
    if mode == "usb_ftdi":
        port = (config.get("ptt_serial_port") or "").strip()
        line = config.get("ptt_serial_line", "RTS")
        if not port:
            print("PTT: USB FTDI selected but no serial port configured; falling back to manual.")
            return ManualPTT()
        try:
            return SerialPTT(port, line)
        except Exception as e:
            print(f"PTT: failed to open serial port {port}: {e}; falling back to manual.")
            return ManualPTT()
    if mode == "vox":
        return VoxPTT()
    return ManualPTT()


class STTWorker(QThread):
    """Captures mic audio, gates on Silero VAD, transcribes speech with faster-whisper."""
    transcribed = Signal(str)
    error = Signal(str)
    status = Signal(str)

    SAMPLE_RATE = 16000
    CHUNK_SAMPLES = 512  # required by Silero VAD at 16kHz
    PRE_BUFFER_CHUNKS = 10  # ~320ms of pre-speech context
    MIN_SPEECH_DURATION_S = 0.4  # drops kerchunks / blips
    BANDPASS_LOW_HZ = 300   # narrowband-FM voice floor
    BANDPASS_HIGH_HZ = 3000  # narrowband-FM voice ceiling

    # Common Whisper hallucinations on silence/noise — drop these
    HALLUCINATIONS = frozenset({
        "you", "thank you", "thanks", "thanks for watching",
        "thank you for watching", "thanks for watching!", "bye", ".",
        "okay", "ok", "yeah", "mm", "hmm",
    })

    MODELS_STT_DIR = os.path.join("Models", "STT")

    def __init__(self, input_device=None, whisper_model="small.en", vad_threshold=0.5,
                 whisper=None, vad_model=None, parent=None):
        super().__init__(parent)
        self.input_device = input_device if input_device not in (None, -1) else None
        self.whisper_model_name = whisper_model
        self.whisper_model_path = os.path.join(self.MODELS_STT_DIR, whisper_model)
        self.vad_threshold = float(vad_threshold)
        self._running = True
        self._paused = False
        # Public so MainWindow can hoist them out after the worker stops and
        # hand them back to the next worker — avoids re-loading on every
        # Listen toggle. Either both are None (need to load) or both are set.
        self.whisper = whisper
        self.vad_model = vad_model

    def stop(self):
        self._running = False

    def pause(self):
        """Suspend transcription (e.g., while the app is transmitting) without
        tearing down the Whisper/VAD models or audio stream."""
        self._paused = True

    def resume(self):
        self._paused = False

    def run(self):
        try:
            from silero_vad import load_silero_vad, VADIterator
            from faster_whisper import WhisperModel
            import noisereduce as nr
            from scipy.signal import butter, sosfiltfilt
        except Exception as e:
            self.error.emit(f"STT dependencies missing — run 'pip install -r requirements.txt': {e}")
            return

        if not self._running:
            return

        if not os.path.isdir(self.whisper_model_path):
            self.error.emit(
                f"Whisper model not found at '{self.whisper_model_path}'. "
                f"Run 'python bootstrap_models.py --model {self.whisper_model_name}' on an "
                f"internet-connected machine, then copy Models/ here. "
                f"GMRS-TTY does not download models at runtime."
            )
            return

        try:
            if self.whisper is None or self.vad_model is None:
                self.status.emit(f"Loading Whisper model from {self.whisper_model_path}...")
                self.whisper = WhisperModel(
                    self.whisper_model_path, device="cpu", compute_type="int8"
                )
                self.vad_model = load_silero_vad()
            whisper = self.whisper
            vad_iter = VADIterator(
                self.vad_model,
                sampling_rate=self.SAMPLE_RATE,
                threshold=self.vad_threshold,
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            )
            nyquist = self.SAMPLE_RATE / 2
            self._bandpass_sos = butter(
                4,
                [self.BANDPASS_LOW_HZ / nyquist, self.BANDPASS_HIGH_HZ / nyquist],
                btype="band",
                output="sos",
            )
            self._sosfiltfilt = sosfiltfilt
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
        was_paused = False

        try:
            while self._running:
                try:
                    data, _ = stream.read(self.CHUNK_SAMPLES)
                except Exception as e:
                    self.error.emit(f"Audio read error: {e}")
                    break

                if self._paused:
                    if not was_paused:
                        collected = []
                        in_speech = False
                        rolling.clear()
                        try:
                            vad_iter.reset_states()
                        except Exception:
                            pass
                        self.status.emit("Paused (transmitting)")
                        was_paused = True
                    continue

                if was_paused:
                    try:
                        vad_iter.reset_states()
                    except Exception:
                        pass
                    self.status.emit("Listening...")
                    was_paused = False

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
            filtered = self._sosfiltfilt(self._bandpass_sos, audio).astype(np.float32)
            denoised = nr_module.reduce_noise(
                y=filtered, sr=self.SAMPLE_RATE, prop_decrease=0.7
            ).astype(np.float32)

            segments, _ = whisper.transcribe(
                denoised, language="en", beam_size=1, vad_filter=False
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            normalized = text.lower().strip(".,!?;: ")
            if not text or normalized in self.HALLUCINATIONS:
                return

            self.transcribed.emit(text)
        except Exception as e:
            self.error.emit(f"Transcription error: {e}")


class ConfigDialog(QDialog):
    """Dialog for editing user configuration."""

    TEST_SAMPLE_TEXT = "GMRS-TTY voice test. Radio check, one two three."

    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setMinimumWidth(420)
        self.config = current_config
        self._test_voice_cache = {}
        self._test_player = None

        layout = QFormLayout(self)

        self.callsign_input = QLineEdit(self.config.get("callsign", ""))
        self.name_input = QLineEdit(self.config.get("name", ""))
        self.location_input = QLineEdit(self.config.get("location", ""))
        self.voice_input = QComboBox()
        self.input_device_input = QComboBox()
        self.output_device_input = QComboBox()
        self.ptt_mode_input = QComboBox()
        self.ptt_mode_input.addItem("Manual (you press PTT on the radio)", "manual")
        self.ptt_mode_input.addItem("VOX (radio auto-keys on audio)", "vox")
        self.ptt_mode_input.addItem("USB FTDI / Serial (RTS or DTR)", "usb_ftdi")
        current_ptt = self.config.get("ptt_mode", "manual")
        idx = self.ptt_mode_input.findData(current_ptt)
        if idx >= 0:
            self.ptt_mode_input.setCurrentIndex(idx)

        self.ptt_serial_port_input = QLineEdit(self.config.get("ptt_serial_port", ""))
        self.ptt_serial_port_input.setPlaceholderText("/dev/ttyUSB0 or COM3")

        self.ptt_serial_line_input = QComboBox()
        self.ptt_serial_line_input.addItem("RTS", "RTS")
        self.ptt_serial_line_input.addItem("DTR", "DTR")
        current_line = self.config.get("ptt_serial_line", "RTS")
        idx = self.ptt_serial_line_input.findData(current_line)
        if idx >= 0:
            self.ptt_serial_line_input.setCurrentIndex(idx)

        self.ptt_mode_input.currentIndexChanged.connect(self._update_ptt_fields)

        self.vad_threshold_input = QDoubleSpinBox()
        self.vad_threshold_input.setRange(0.10, 0.95)
        self.vad_threshold_input.setSingleStep(0.05)
        self.vad_threshold_input.setDecimals(2)
        self.vad_threshold_input.setValue(float(self.config.get("vad_threshold", 0.5)))
        self.vad_threshold_input.setToolTip(
            "Silero VAD speech probability cutoff. Lower = more sensitive "
            "(catches quiet/weak signals but more false starts); "
            "higher = stricter (cleaner gating on noisy channels). Default 0.5."
        )

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

        self.test_voice_button = QPushButton("&Test")
        self.test_voice_button.setToolTip("Play a short sample with the selected voice (Alt+T)")
        self.test_voice_button.setAccessibleName("Test selected voice")
        self.test_voice_button.setAccessibleDescription(
            "Play a short audio sample with the currently selected Piper voice."
        )
        self.test_voice_button.clicked.connect(self.test_voice)

        voice_row = QWidget()
        voice_row_layout = QHBoxLayout(voice_row)
        voice_row_layout.setContentsMargins(0, 0, 0, 0)
        voice_row_layout.addWidget(self.voice_input, 1)
        voice_row_layout.addWidget(self.test_voice_button)

        self.input_device_input.addItem("System Default", -1)
        self.output_device_input.addItem("System Default", -1)
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev.get('max_input_channels', 0) > 0:
                    self.input_device_input.addItem(f"{i}: {dev['name']}", i)
                if dev.get('max_output_channels', 0) > 0:
                    self.output_device_input.addItem(f"{i}: {dev['name']}", i)
        except Exception as e:
            print(f"Could not enumerate audio devices: {e}")

        current_dev = self.config.get("input_device", -1)
        idx = self.input_device_input.findData(current_dev)
        if idx >= 0:
            self.input_device_input.setCurrentIndex(idx)

        current_out = self.config.get("output_device", -1)
        idx = self.output_device_input.findData(current_out)
        if idx >= 0:
            self.output_device_input.setCurrentIndex(idx)

        # Mnemonics on every field — Alt+letter jumps focus to the input via
        # QFormLayout's automatic buddy linking. Letters are unique within this dialog.
        layout.addRow("&Callsign:", self.callsign_input)
        layout.addRow("&Name:", self.name_input)
        layout.addRow("&Location:", self.location_input)
        layout.addRow("&Voice Model:", voice_row)
        layout.addRow("&Input Device:", self.input_device_input)
        layout.addRow("&Output Device:", self.output_device_input)
        layout.addRow("VA&D Threshold:", self.vad_threshold_input)
        layout.addRow("&PTT Mode:", self.ptt_mode_input)
        layout.addRow("&Serial Port:", self.ptt_serial_port_input)
        layout.addRow("Control Lin&e:", self.ptt_serial_line_input)
        self._update_ptt_fields()

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
            "output_device": self.output_device_input.currentData(),
            "vad_threshold": round(self.vad_threshold_input.value(), 2),
            "ptt_mode": self.ptt_mode_input.currentData(),
            "ptt_serial_port": self.ptt_serial_port_input.text().strip(),
            "ptt_serial_line": self.ptt_serial_line_input.currentData(),
        }

    def _update_ptt_fields(self):
        is_serial = self.ptt_mode_input.currentData() == "usb_ftdi"
        self.ptt_serial_port_input.setEnabled(is_serial)
        self.ptt_serial_line_input.setEnabled(is_serial)

    def test_voice(self):
        voice_path = self.voice_input.currentData()
        if not voice_path or not os.path.exists(voice_path):
            QMessageBox.warning(self, "Test Voice", "No valid Piper voice selected.")
            return

        self.test_voice_button.setEnabled(False)
        self.test_voice_button.setText("Loading…")
        QApplication.processEvents()

        try:
            if voice_path not in self._test_voice_cache:
                self._test_voice_cache[voice_path] = PiperVoice.load(voice_path)
            voice = self._test_voice_cache[voice_path]

            self.test_voice_button.setText("Speaking…")
            QApplication.processEvents()

            syn_config = SynthesisConfig(speaker_id=0) if voice.config.num_speakers > 1 else None
            chunks = [
                c.audio_int16_array
                for c in voice.synthesize(self.TEST_SAMPLE_TEXT, syn_config=syn_config)
                if len(c.audio_int16_array) > 0
            ]
            if not chunks:
                QMessageBox.warning(self, "Test Voice", "Voice generated no audio.")
                self._reset_test_button()
                return
            data = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)

            self._test_player = AudioPlayerThread(
                data, voice.config.sample_rate, device=self.output_device_input.currentData()
            )
            self._test_player.finished.connect(self._reset_test_button)
            self._test_player.error.connect(lambda msg: QMessageBox.warning(self, "Test Voice", f"Playback error: {msg}"))
            self._test_player.start()
        except Exception as e:
            QMessageBox.warning(self, "Test Voice", f"Failed: {e}")
            self._reset_test_button()

    def _reset_test_button(self):
        self.test_voice_button.setEnabled(True)
        self.test_voice_button.setText("Test")


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
        self.chat_display = QTextEdit(self)
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("padding: 5px;")
        self.chat_display.setAccessibleName("Conversation log")
        self.chat_display.setAccessibleDescription(
            "Timestamped log of incoming radio transmissions and outgoing messages."
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
        """Fills the target selection combo box with current contacts."""
        self.target_dropdown.clear()
        for contact in self.contacts:
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

    def transmit_message(self):
        """Handles when the user attempts to send a message."""
        text = self.message_input.text().strip()
        target_call = self.target_dropdown.currentData()
        prefaced = bool(target_call and target_call.upper() != "ALL")

        # Empty text is only valid when calling a specific station — the preface itself is the call.
        if not text and not prefaced:
            return

        my_call = self.config.get("callsign", "N0CALL")
        my_name = self.config.get("name", "Default User")

        now = datetime.datetime.now()

        if prefaced:
            target_name = next(
                (c.get("name", "") for c in self.contacts
                 if c.get("callsign", "").upper() == target_call.upper()),
                ""
            ).strip()
            target_label = f"{target_call} {target_name}" if target_name else target_call
            # Preface contains callsign + name, so it satisfies FCC ID on its own.
            if text:
                spoken_text = f"{my_call} {my_name} calling {target_label}. {text}"
            else:
                spoken_text = f"{my_call} {my_name} calling {target_label}."
            self.last_tx_time = now
        else:
            spoken_text = text
            if self.last_tx_time is None or (now - self.last_tx_time).total_seconds() > 15 * 60:
                spoken_text += f". This is {my_call} {my_name}."
                self.last_tx_time = now

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
        my_call = self.config.get("callsign", "N0CALL")
        my_name = self.config.get("name", "Default User")
        my_location = self.config.get("location", "").strip()
        nato_call = callsign_to_nato(my_call)

        if my_location:
            spoken_text = f"This is {my_call}, {nato_call}. {my_name} from {my_location}."
        else:
            spoken_text = f"This is {my_call}, {nato_call}. {my_name}."

        self.last_tx_time = datetime.datetime.now()

        formatted_msg = f"<b>[TX ID]:</b> {spoken_text}"
        self.append_to_chat(formatted_msg, color=COLOR_TX)

        self._synthesize_and_play(spell_digits_in_callsigns(spoken_text))

    def _set_tx_buttons_enabled(self, enabled):
        self.transmit_btn.setEnabled(enabled)
        self.id_btn.setEnabled(enabled)

    def _synthesize_and_play(self, tts_text):
        """Kick off Piper synthesis on a background thread and hand the result
        to the player when ready. Manages TX button state across both stages."""
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
        self.chat_display.append(f"<span style='color:{color};'>{text}</span>")

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
        self.listen_btn.setText("&Listen")
        self.listen_btn.setAccessibleDescription(
            "Start or stop transcribing incoming radio audio. Currently stopped."
        )

    def on_transcription(self, text):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.append_to_chat(f"<b>[RX {ts}]:</b> {text}", color=COLOR_RX)
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Apply a clean, default styling
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())