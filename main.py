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

from speakerid import (
    SpeakerEmbedder,
    VoiceprintStore,
    UnknownClusterer,
    RxUtterance,
    SpeakerMatch,
    MIN_EMBED_DURATION_S,
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QTextEdit, QTextBrowser, QLineEdit, QPushButton,
    QDialog, QFormLayout, QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QDoubleSpinBox, QCheckBox, QInputDialog
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
    """Captures mic audio, gates on Silero VAD, transcribes speech with faster-whisper,
    and (when enabled) extracts an ECAPA speaker embedding for each utterance."""
    transcribed = Signal(object)  # RxUtterance
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
                 speaker_id_enabled=True, parent=None):
        super().__init__(parent)
        self.input_device = input_device if input_device not in (None, -1) else None
        self.whisper_model_name = whisper_model
        self.whisper_model_path = os.path.join(self.MODELS_STT_DIR, whisper_model)
        self.vad_threshold = float(vad_threshold)
        self.speaker_id_enabled = bool(speaker_id_enabled)
        self._embedder = None
        self._running = True
        self._paused = False

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
            self.status.emit(f"Loading Whisper model from {self.whisper_model_path}...")
            whisper = WhisperModel(self.whisper_model_path, device="cpu", compute_type="int8")
            vad_model = load_silero_vad()
            vad_iter = VADIterator(
                vad_model,
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

        if self.speaker_id_enabled:
            self.status.emit("Loading speaker model...")
            embedder = SpeakerEmbedder()
            if embedder.load():
                self._embedder = embedder
            else:
                self.status.emit(f"Speaker ID unavailable: {embedder.error}")

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

            duration = len(denoised) / self.SAMPLE_RATE
            embedding = None
            if self._embedder is not None and duration >= MIN_EMBED_DURATION_S:
                embedding = self._embedder.embed(denoised, sample_rate=self.SAMPLE_RATE)

            self.transcribed.emit(
                RxUtterance(text=text, duration_seconds=duration, embedding=embedding)
            )
        except Exception as e:
            self.error.emit(f"Transcription error: {e}")


class ConfigDialog(QDialog):
    """Dialog for editing user configuration."""

    TEST_SAMPLE_TEXT = "GMRS-TTY voice test. Radio check, one two three."

    def __init__(self, current_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setMinimumWidth(300)
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

        self.speaker_id_input = QCheckBox("Tag RX lines with detected speaker")
        self.speaker_id_input.setChecked(
            bool(self.config.get("speaker_id_enabled", True))
        )
        self.speaker_id_input.setToolTip(
            "When enabled, each RX line is tagged with the matched callsign / name, "
            "or with a session-anonymous label (Voice A, Voice B, ...) for unknown voices. "
            "Aggressive auto-enrollment: every confident match attaches the new sample "
            "to the contact's voiceprint, with an [undo] link in the chat. "
            "Self-IDs (callsign detected in transcript) override centroid matches."
        )

        self.speaker_match_input = QDoubleSpinBox()
        self.speaker_match_input.setRange(0.50, 0.95)
        self.speaker_match_input.setSingleStep(0.05)
        self.speaker_match_input.setDecimals(2)
        self.speaker_match_input.setValue(
            float(self.config.get("speaker_match_threshold", 0.75))
        )
        self.speaker_match_input.setToolTip(
            "Cosine-similarity cutoff for a confident speaker match. "
            "Above this -> RX line is tagged with the callsign and the embedding is "
            "auto-enrolled. Default 0.75."
        )

        self.speaker_tentative_input = QDoubleSpinBox()
        self.speaker_tentative_input.setRange(0.50, 0.85)
        self.speaker_tentative_input.setSingleStep(0.05)
        self.speaker_tentative_input.setDecimals(2)
        self.speaker_tentative_input.setValue(
            float(self.config.get("speaker_tentative_threshold", 0.65))
        )
        self.speaker_tentative_input.setToolTip(
            "Cosine-similarity cutoff for a tentative match. Between this and the "
            "confident threshold the RX tag gets a '?' suffix and nothing is auto-enrolled. "
            "Below this the speaker falls into the unknown-voice clusterer. Default 0.65."
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

        self.test_voice_button = QPushButton("Test")
        self.test_voice_button.setToolTip("Play a short sample with the selected voice")
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

        layout.addRow("Callsign:", self.callsign_input)
        layout.addRow("Name:", self.name_input)
        layout.addRow("Location:", self.location_input)
        layout.addRow("Voice Model:", voice_row)
        layout.addRow("Input Device:", self.input_device_input)
        layout.addRow("Output Device:", self.output_device_input)
        layout.addRow("VAD Threshold:", self.vad_threshold_input)
        layout.addRow("Speaker ID:", self.speaker_id_input)
        layout.addRow("Match Threshold:", self.speaker_match_input)
        layout.addRow("Tentative Threshold:", self.speaker_tentative_input)
        layout.addRow("PTT Mode:", self.ptt_mode_input)
        layout.addRow("Serial Port:", self.ptt_serial_port_input)
        layout.addRow("Control Line:", self.ptt_serial_line_input)
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
            "speaker_id_enabled": self.speaker_id_input.isChecked(),
            "speaker_match_threshold": round(self.speaker_match_input.value(), 2),
            "speaker_tentative_threshold": round(self.speaker_tentative_input.value(), 2),
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
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                with wave.open(tmp_path, 'wb') as wav_file:
                    voice.synthesize_wav(self.TEST_SAMPLE_TEXT, wav_file, syn_config=syn_config)
                data, _ = sf.read(tmp_path, dtype='int16')
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            if len(data) == 0:
                QMessageBox.warning(self, "Test Voice", "Voice generated no audio.")
                self._reset_test_button()
                return

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
    """Dialog for managing known contacts and their voiceprints."""

    SAMPLES_COL = 3
    ACTIONS_COL = 4

    def __init__(self, current_contacts, voiceprint_store=None, record_fn=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contact Management")
        self.setMinimumSize(720, 360)
        self.contacts = current_contacts
        self.voiceprint_store = voiceprint_store
        self.record_fn = record_fn

        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Callsign", "Name", "Location", "Voiceprint", "Voice Actions"]
        )
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
            self._install_voice_widgets(row)

    def _install_voice_widgets(self, row):
        self._refresh_samples_cell(row)
        actions = QWidget()
        h = QHBoxLayout(actions)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        record_btn = QPushButton("Record")
        record_btn.setToolTip("Capture ~5 s through the configured input device "
                              "(matches the live RX DSP pipeline) and add it to this contact's voiceprint.")
        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Delete all voiceprint samples for this contact.")
        record_btn.clicked.connect(self._on_record_clicked)
        reset_btn.clicked.connect(self._on_reset_clicked)
        h.addWidget(record_btn)
        h.addWidget(reset_btn)
        self.table.setCellWidget(row, self.ACTIONS_COL, actions)

    def _refresh_samples_cell(self, row):
        cs_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        callsign = cs_item.text().strip().upper() if cs_item else ""
        name = name_item.text().strip() if name_item else ""
        text = ""
        if self.voiceprint_store and callsign and callsign != "ALL":
            n = self.voiceprint_store.sample_count(callsign, name)
            if n > 0:
                meta = self.voiceprint_store.meta(callsign, name)
                last = (meta.get("last_enrolled") or "")[:10]
                text = f"{n} sample{'s' if n != 1 else ''}"
                if last:
                    text += f" · last {last}"
        samples_item = QTableWidgetItem(text)
        samples_item.setFlags(samples_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, self.SAMPLES_COL, samples_item)

    def _row_of_action_button(self, button):
        if button is None:
            return -1
        cell = button.parent()
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, self.ACTIONS_COL) is cell:
                return r
        return -1

    def _on_record_clicked(self):
        row = self._row_of_action_button(self.sender())
        if row < 0:
            return
        cs_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        callsign = cs_item.text().strip().upper() if cs_item else ""
        name = name_item.text().strip() if name_item else ""
        if not callsign or callsign == "ALL":
            QMessageBox.warning(self, "Record Voice", "Pick a valid callsign first.")
            return
        if self.record_fn is None:
            QMessageBox.warning(self, "Record Voice", "Voice recording is unavailable.")
            return
        if self.record_fn(callsign, name):
            self._refresh_samples_cell(row)

    def _on_reset_clicked(self):
        row = self._row_of_action_button(self.sender())
        if row < 0:
            return
        cs_item = self.table.item(row, 0)
        name_item = self.table.item(row, 1)
        callsign = cs_item.text().strip().upper() if cs_item else ""
        name = name_item.text().strip() if name_item else ""
        if not callsign or callsign == "ALL" or self.voiceprint_store is None:
            return
        n = self.voiceprint_store.sample_count(callsign, name)
        display = f"{callsign} ({name})" if name else callsign
        if n == 0:
            QMessageBox.information(self, "Reset Voiceprint",
                                    f"No voice samples enrolled for {display}.")
            return
        reply = QMessageBox.question(
            self, "Reset Voiceprint",
            f"Delete all {n} voice sample{'s' if n != 1 else ''} for {display}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.voiceprint_store.reset_contact(callsign, name)
            self._refresh_samples_cell(row)

    def add_row(self):
        row_pos = self.table.rowCount()
        self.table.insertRow(row_pos)
        self.table.setItem(row_pos, 0, QTableWidgetItem("NEW_CALL"))
        self.table.setItem(row_pos, 1, QTableWidgetItem("New Name"))
        self.table.setItem(row_pos, 2, QTableWidgetItem(""))
        self._install_voice_widgets(row_pos)

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
        self.ptt = make_ptt(self.config)

        try:
            self.voiceprint_store = VoiceprintStore()
        except Exception as e:
            print(f"voiceprint store init failed: {e}")
            self.voiceprint_store = None
        self.unknown_clusterer = UnknownClusterer()

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
                color="orange",
            )

    def closeEvent(self, event):
        self.stop_stt()
        if hasattr(self, 'audio_thread') and self.audio_thread.isRunning():
            self.audio_thread.quit()
            self.audio_thread.wait()
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

        # 1. Header (User Info)
        self.header_label = QLabel("Loading...", self)
        self.header_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px; background-color: #f0f0f0; border-radius: 5px;")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.header_label)

        # 2. Main Chat Room (Rx Section)
        self.chat_display = QTextBrowser(self)
        self.chat_display.setOpenLinks(False)
        self.chat_display.setOpenExternalLinks(False)
        self.chat_display.anchorClicked.connect(self._on_chat_anchor_clicked)
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

        # 3b. Standalone ID button row (sits under Transmit)
        id_layout = QHBoxLayout()
        id_layout.addStretch()
        self.id_btn = QPushButton("This is", self)
        self.id_btn.setToolTip("Transmit station ID: This is [callsign]. [name] from [location]")
        self.id_btn.clicked.connect(self.transmit_id_only)
        id_layout.addWidget(self.id_btn)
        main_layout.addLayout(id_layout)

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
            old_threshold = self.config.get("vad_threshold", 0.5)
            old_speaker_id = self.config.get("speaker_id_enabled", True)
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
                or old_speaker_id != self.config.get("speaker_id_enabled", True)
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
        dlg = ContactsDialog(
            self.contacts,
            voiceprint_store=self.voiceprint_store,
            record_fn=self.record_voice_sample,
            parent=self,
        )
        if dlg.exec():
            self.contacts = dlg.get_contacts()
            save_json(CONTACTS_FILE, self.contacts)
            self.populate_target_dropdown()

    def record_voice_sample(self, callsign, name):
        """Manual enrollment path: stop STT (the input device is exclusive on most
        backends), record ~5 s through the configured input, run the same
        bandpass+denoise the live pipeline uses so enrollment and recognition see
        the same conditions, embed, and enroll. Returns True on success.

        `name` distinguishes operators on a shared family callsign — each
        (callsign, name) gets its own voiceprint bank."""
        if self.voiceprint_store is None:
            QMessageBox.warning(self, "Record Voice", "Voiceprint store unavailable.")
            return False

        duration_s = 5.0
        sr = 16000
        input_device = self.config.get("input_device", -1)
        device = None if input_device in (None, -1) else input_device

        display_label = f"{callsign} ({name})" if name else callsign
        reply = QMessageBox.question(
            self,
            f"Record voice sample: {display_label}",
            f"Speak clearly for ~{duration_s:.0f} seconds after clicking OK.\n\n"
            f"For best matching on-air, feed your radio's RX audio into the same "
            f"input device you use for listening — the sample passes through the "
            f"same bandpass + denoise pipeline as live transcription.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return False

        was_listening = self.stt_worker is not None and self.stt_worker.isRunning()
        if was_listening:
            self.stop_stt()

        try:
            self.statusBar().showMessage(f"Recording {callsign}...")
            QApplication.processEvents()
            audio = sd.rec(
                int(duration_s * sr),
                samplerate=sr,
                channels=1,
                dtype='float32',
                device=device,
            )
            sd.wait()
            audio = audio[:, 0].copy()
        except Exception as e:
            QMessageBox.warning(self, "Record Voice", f"Recording failed: {e}")
            if was_listening:
                self._restart_listen()
            return False

        try:
            from scipy.signal import butter, sosfiltfilt
            import noisereduce as nr
            nyquist = sr / 2
            sos = butter(
                4,
                [STTWorker.BANDPASS_LOW_HZ / nyquist, STTWorker.BANDPASS_HIGH_HZ / nyquist],
                btype="band",
                output="sos",
            )
            filtered = sosfiltfilt(sos, audio).astype(np.float32)
            denoised = nr.reduce_noise(
                y=filtered, sr=sr, prop_decrease=0.7
            ).astype(np.float32)
        except Exception as e:
            QMessageBox.warning(self, "Record Voice", f"Signal processing failed: {e}")
            if was_listening:
                self._restart_listen()
            return False

        try:
            embedder = SpeakerEmbedder()
            if not embedder.load():
                QMessageBox.warning(
                    self, "Record Voice", f"Speaker model unavailable: {embedder.error}"
                )
                return False
            emb = embedder.embed(denoised, sample_rate=sr)
            if emb is None:
                QMessageBox.warning(
                    self, "Record Voice",
                    "Could not compute speaker embedding from this sample.",
                )
                return False
            self.voiceprint_store.enroll(callsign, name, emb, source="manual")
            self.statusBar().showMessage(
                f"Enrolled voice sample for {display_label}", 5000
            )
            return True
        finally:
            if was_listening:
                self._restart_listen()

    def _restart_listen(self):
        """Re-enter listen mode after a manual recording. Keeps the button state
        in sync without firing toggle_listening twice."""
        if not self.listen_btn.isChecked():
            self.listen_btn.setChecked(True)
        else:
            self.start_stt()

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
        self.append_to_chat(formatted_msg, color="blue")

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
        self.append_to_chat(formatted_msg, color="blue")

        self._synthesize_and_play(spell_digits_in_callsigns(spoken_text))

    def _set_tx_buttons_enabled(self, enabled):
        self.transmit_btn.setEnabled(enabled)
        self.id_btn.setEnabled(enabled)

    def _synthesize_and_play(self, tts_text):
        """Render `tts_text` through Piper and play it; manages TX button state."""
        self._set_tx_buttons_enabled(False)

        voice_path = self.config.get("voice", "")
        if not voice_path or not os.path.exists(voice_path):
            self.append_to_chat("<i>Error: No valid Piper voice selected. Please select one in Settings -> Configuration.</i>", color="red")
            self._set_tx_buttons_enabled(True)
            return

        if voice_path not in self.voice_cache:
            try:
                self.voice_cache[voice_path] = PiperVoice.load(voice_path)
            except Exception as e:
                self.append_to_chat(f"<i>Failed to load voice model: {e}</i>", color="red")
                self._set_tx_buttons_enabled(True)
                return

        voice = self.voice_cache[voice_path]

        # Synthesize sequentially in the main thread (avoids espeak-ng thread crashes).
        try:
            sentences = re.split(r'(?<=[.!?])\s+', tts_text)
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

                    data, _ = sf.read(temp_wav_path, dtype='int16')
                    if len(data) > 0:
                        audio_chunks.append(data)
                    else:
                        self.append_to_chat(f"<i>Warning: Piper generated 0 frames for: '{sentence}'</i>", color="red")
                finally:
                    if os.path.exists(temp_wav_path):
                        os.remove(temp_wav_path)

            if audio_chunks:
                full_audio = np.concatenate(audio_chunks)
                sample_rate = voice.config.sample_rate
                lead_samples = int(self.ptt.lead_in_seconds * sample_rate)
                tail_samples = int(self.ptt.tail_seconds * sample_rate)
                if lead_samples > 0:
                    full_audio = np.concatenate([
                        np.zeros(lead_samples, dtype=full_audio.dtype), full_audio,
                    ])
                if tail_samples > 0:
                    full_audio = np.concatenate([
                        full_audio, np.zeros(tail_samples, dtype=full_audio.dtype),
                    ])
                self.audio_thread = AudioPlayerThread(
                    full_audio, sample_rate, device=self.config.get("output_device", -1)
                )
                self.audio_thread.finished.connect(self.on_tts_finished)
                self.audio_thread.error.connect(self.on_tts_error)
                self._pause_stt_for_tx()
                try:
                    self.ptt.key()
                except Exception as e:
                    self.append_to_chat(f"<i>PTT key failed: {e}</i>", color="red")
                self.audio_thread.start()
            else:
                self._set_tx_buttons_enabled(True)

        except Exception as e:
            traceback.print_exc()
            self.append_to_chat(f"<i>TTS Error: {str(e)}</i>", color="red")
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
        self.append_to_chat(f"<i>TTS Error: {error_msg}</i>", color="red")
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
        self.unknown_clusterer.reset()
        self.stt_worker = STTWorker(
            input_device=self.config.get("input_device", -1),
            whisper_model=self.config.get("whisper_model", "small.en"),
            vad_threshold=self.config.get("vad_threshold", 0.5),
            speaker_id_enabled=bool(self.config.get("speaker_id_enabled", True)),
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

    def on_transcription(self, payload):
        # Back-compat: tolerate a plain-string payload from older signal shapes.
        utt = payload if isinstance(payload, RxUtterance) else RxUtterance(
            text=str(payload), duration_seconds=0.0, embedding=None
        )

        speaker_enabled = bool(self.config.get("speaker_id_enabled", True))
        if not speaker_enabled or self.voiceprint_store is None:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.append_to_chat(f"<b>[RX {ts}]:</b> {utt.text}", color="green")
            self.scan_for_unknown_stations(utt.text)
            return

        self_id = self._self_id_callsign(utt.text)
        match = self._identify_speaker(utt, self_id)
        enrollment = self._auto_enroll(utt, match, self_id)
        self._render_rx_line(utt, match, enrollment)
        self.scan_for_unknown_stations(utt.text)

    def _self_id_callsign(self, text):
        """First known-contact callsign mentioned in the transcript, or None.
        Used as a ground-truth speaker signal that overrides centroid matching
        and protects against poisoning a print on a wrong-but-confident match."""
        known = {
            c.get("callsign", "").upper()
            for c in self.contacts
            if c.get("callsign", "").upper() not in ("", "ALL")
        }
        for cs in detect_callsigns(text):
            if cs in known:
                return cs
        return None

    def _identify_speaker(self, utt, self_id):
        if self_id is not None:
            cs, nm = self._disambiguate_self_id(self_id, utt.embedding)
            return SpeakerMatch(
                label=cs, score=1.0, kind="confident",
                callsign=cs, name=(nm if nm is not None else ""),
            )
        if utt.embedding is None:
            return SpeakerMatch(label="?", score=0.0, kind="unknown")
        confident_thr = float(self.config.get("speaker_match_threshold", 0.75))
        tentative_thr = float(self.config.get("speaker_tentative_threshold", 0.65))
        best = self.voiceprint_store.best_match(utt.embedding)
        if best is not None:
            callsign, name, score = best
            if score >= confident_thr:
                return SpeakerMatch(
                    label=callsign, score=score, kind="confident",
                    callsign=callsign, name=name,
                )
            if score >= tentative_thr:
                return SpeakerMatch(
                    label=f"{callsign}?", score=score, kind="tentative",
                    callsign=callsign, name=name,
                )
        cluster_label, cluster_score = self.unknown_clusterer.assign(utt.embedding)
        return SpeakerMatch(
            label=cluster_label, score=cluster_score, kind="cluster",
            cluster_label=cluster_label,
        )

    def _disambiguate_self_id(self, callsign, embedding):
        """Decide which family-member operator a self-ID callsign refers to.
        Returns (callsign, name) when we have an answer, or (callsign, None)
        when multiple family members share the callsign and we can't tell —
        callers should treat `name is None` as 'ambiguous' (display falls
        back to bare callsign; auto-enroll refuses to write)."""
        matches = [
            c for c in self.contacts
            if c.get("callsign", "").upper() == callsign
            and c.get("callsign", "").upper() != "ALL"
        ]
        if len(matches) == 1:
            return callsign, (matches[0].get("name", "") or "")
        if not matches:
            return callsign, ""
        if self.voiceprint_store is not None and embedding is not None:
            best = self.voiceprint_store.best_match(embedding, callsign_filter=callsign)
            if best is not None:
                confident_thr = float(self.config.get("speaker_match_threshold", 0.75))
                if best[2] >= confident_thr:
                    return best[0], (best[1] or "")
        return callsign, None

    def _auto_enroll(self, utt, match, self_id):
        """Aggressive enrollment policy. Self-ID wins over centroid match, but
        only when we can pin the self-ID to a specific family member — otherwise
        we'd poison the wrong person's print."""
        if utt.embedding is None or self.voiceprint_store is None:
            return None
        if self_id is not None:
            target_call, target_name = self._disambiguate_self_id(self_id, utt.embedding)
            if target_name is None:
                return None
        elif match.kind == "confident" and match.callsign:
            target_call = match.callsign
            target_name = match.name or ""
        else:
            return None
        emb_id = self.voiceprint_store.enroll(
            target_call, target_name, utt.embedding, source="auto"
        )
        return (target_call, target_name, emb_id)

    def _render_rx_line(self, utt, match, enrollment):
        from urllib.parse import quote
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        if match.kind == "confident":
            name = match.name or ""
            tag = f"{match.callsign} {name}".strip() if name else match.callsign
        elif match.kind == "tentative":
            name = match.name or ""
            tag = f"{match.callsign}? {name}?" if name else f"{match.callsign}?"
        elif match.kind == "cluster":
            label = match.cluster_label or match.label
            tag = (
                f"&middot; <a href='bind:{label}' "
                f"style='color:#1a73e8; text-decoration:none;'>{label}</a>"
            )
        else:
            tag = "&middot; ?"

        head = f"<b>[RX {ts} {tag}]:</b>"
        suffix = ""
        if enrollment is not None:
            cs, op_name, emb_id = enrollment
            suffix = (
                f" <a href='undo:{cs}:{quote(op_name)}:{emb_id}' "
                f"style='color:#888; font-size:11px; text-decoration:none;'>[undo]</a>"
            )
        html = f"<span style='color:green;'>{head} {utt.text}{suffix}</span>"
        self.chat_display.append(html)

    def _on_chat_anchor_clicked(self, url):
        from urllib.parse import unquote
        s = url.toString()
        if s.startswith("undo:"):
            # Format: undo:CALLSIGN:NAME_urlencoded:emb_id
            parts = s.split(":", 3)
            if len(parts) != 4:
                return
            try:
                _, callsign, name_encoded, emb_id_s = parts
                op_name = unquote(name_encoded)
                emb_id = int(emb_id_s)
            except ValueError:
                return
            if self.voiceprint_store and self.voiceprint_store.unenroll(callsign, op_name, emb_id):
                display = f"{callsign} ({op_name})" if op_name else callsign
                self.statusBar().showMessage(
                    f"Removed auto-enrolled voice sample for {display}", 4000
                )
            else:
                self.statusBar().showMessage("Voice sample already removed", 3000)
        elif s.startswith("bind:"):
            self._bind_cluster(s[len("bind:"):])

    def _bind_cluster(self, cluster_label):
        samples = self.unknown_clusterer.samples_for(cluster_label)
        if not samples:
            QMessageBox.information(
                self, "Bind Voice",
                f"{cluster_label} is no longer available — it may already have been bound.",
            )
            return
        bindable = [
            c for c in self.contacts
            if c.get("callsign", "").upper() not in ("", "ALL")
        ]
        if not bindable:
            QMessageBox.warning(
                self, "Bind Voice",
                "No contacts to bind to. Add one in Settings -> Contacts first.",
            )
            return
        # Callsigns can repeat in contacts (a family shares one GMRS callsign), so
        # show the operator name alongside the call to disambiguate at bind time.
        def _display(c):
            cs = c.get("callsign", "")
            name = c.get("name", "")
            return f"{cs} — {name}" if name else cs
        options = [_display(c) for c in bindable]
        choice, ok = QInputDialog.getItem(
            self, "Bind Voice",
            f"Attach {cluster_label} to which contact?",
            options, 0, False,
        )
        if not ok or not choice:
            return
        try:
            idx = options.index(choice)
        except ValueError:
            return
        picked = bindable[idx]
        cs = picked.get("callsign", "")
        name = picked.get("name", "")
        self.unknown_clusterer.pop_cluster(cluster_label)
        if self.voiceprint_store is not None:
            for sample in samples:
                self.voiceprint_store.enroll(cs, name, sample, source="manual")
        display_label = f"{cs} ({name})" if name else cs
        self.statusBar().showMessage(
            f"Bound {cluster_label} → {display_label} ({len(samples)} samples)", 5000
        )

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