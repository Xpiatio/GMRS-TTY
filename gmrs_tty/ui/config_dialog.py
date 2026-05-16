import glob
import os

import numpy as np
from piper.config import SynthesisConfig
from piper.voice import PiperVoice
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSlider, QWidget,
)

from gmrs_tty.audio.playback import AudioPlayerThread
from gmrs_tty.ui.device_query import DeviceQueryThread


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

        self.time_format_input = QComboBox()
        self.time_format_input.addItem("24-hour (14:32:15)", "24h")
        self.time_format_input.addItem("12-hour (2:32:15 PM)", "12h")
        current_time_format = self.config.get("time_format", "24h")
        idx = self.time_format_input.findData(current_time_format)
        if idx >= 0:
            self.time_format_input.setCurrentIndex(idx)
        self.time_format_input.setToolTip(
            "Clock format for RX timestamps in the conversation log."
        )

        self.filter_profanity_input = QCheckBox("Mask strong language with asterisks (PG-13)")
        self.filter_profanity_input.setChecked(
            bool(self.config.get("filter_profanity", True))
        )
        self.filter_profanity_input.setToolTip(
            "When enabled, strong profanity in incoming transcripts and outgoing "
            "messages is masked (e.g. 'shit' -> 's***'). Helps keep transmissions "
            "within FCC Part 95 obscenity expectations."
        )
        self.filter_profanity_input.setAccessibleName("Filter profanity")
        self.filter_profanity_input.setAccessibleDescription(
            "Mask strong language in both RX transcripts and TX messages "
            "with asterisks. Recommended for GMRS operation."
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

        # Speech-rate slider: integer 70..150 maps to Piper length_scale
        # 0.70..1.50 (step 0.05). 1.00× = the voice's native pace; higher
        # values slow speech, lower values speed it up. Stored in config as
        # `tts_length_scale` (a float).
        self.length_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.length_scale_slider.setRange(70, 150)
        self.length_scale_slider.setSingleStep(5)
        self.length_scale_slider.setPageStep(10)
        self.length_scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.length_scale_slider.setTickInterval(10)
        initial_scale = float(self.config.get("tts_length_scale", 1.0))
        self.length_scale_slider.setValue(int(round(initial_scale * 100)))
        self.length_scale_slider.setToolTip(
            "Piper synthesis speed. 1.00× is the voice's native pace; higher "
            "is slower, lower is faster. Useful when listeners need more time."
        )
        self.length_scale_slider.setAccessibleName("Speech rate")
        self.length_scale_slider.setAccessibleDescription(
            "Adjust how fast the TTS voice speaks. 1.00 times is normal, "
            "higher values are slower, lower values are faster."
        )

        self.length_scale_value_label = QLabel()
        self.length_scale_value_label.setMinimumWidth(64)
        self.length_scale_slider.valueChanged.connect(self._update_length_scale_label)
        self._update_length_scale_label(self.length_scale_slider.value())

        rate_row = QWidget()
        rate_row_layout = QHBoxLayout(rate_row)
        rate_row_layout.setContentsMargins(0, 0, 0, 0)
        rate_row_layout.addWidget(self.length_scale_slider, 1)
        rate_row_layout.addWidget(self.length_scale_value_label)

        # Device enumeration happens on a background thread; PortAudio's
        # query_devices() can block hundreds of ms on ALSA/PulseAudio and
        # contend with the live STT InputStream. Until it finishes we show
        # a placeholder and disable OK so the user can't save a half-loaded
        # configuration.
        self.input_device_input.addItem("Loading devices…", -1)
        self.input_device_input.setEnabled(False)
        self.output_device_input.addItem("Loading devices…", -1)
        self.output_device_input.setEnabled(False)
        self._device_thread = DeviceQueryThread(self)
        self._device_thread.devices_ready.connect(self._on_devices_ready)
        self._device_thread.start()

        # Mnemonics on every field — Alt+letter jumps focus to the input via
        # QFormLayout's automatic buddy linking. Letters are unique within this dialog.
        layout.addRow("&Callsign:", self.callsign_input)
        layout.addRow("&Name:", self.name_input)
        layout.addRow("&Location:", self.location_input)
        layout.addRow("&Voice Model:", voice_row)
        layout.addRow("Speech &Rate:", rate_row)
        layout.addRow("&Input Device:", self.input_device_input)
        layout.addRow("&Output Device:", self.output_device_input)
        layout.addRow("VA&D Threshold:", self.vad_threshold_input)
        layout.addRow("Time &Format:", self.time_format_input)
        layout.addRow("Filter profanit&y:", self.filter_profanity_input)
        layout.addRow("&PTT Mode:", self.ptt_mode_input)
        layout.addRow("&Serial Port:", self.ptt_serial_port_input)
        layout.addRow("Control Lin&e:", self.ptt_serial_line_input)
        self._update_ptt_fields()

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        # OK stays disabled until DeviceQueryThread finishes so the user
        # can't save a config with the "Loading devices…" placeholder.
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

    def _on_devices_ready(self, devices):
        self.input_device_input.clear()
        self.output_device_input.clear()
        self.input_device_input.addItem("System Default", -1)
        self.output_device_input.addItem("System Default", -1)
        for i, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) > 0:
                self.input_device_input.addItem(f"{i}: {dev['name']}", i)
            if dev.get('max_output_channels', 0) > 0:
                self.output_device_input.addItem(f"{i}: {dev['name']}", i)
        current_dev = self.config.get("input_device", -1)
        idx = self.input_device_input.findData(current_dev)
        if idx >= 0:
            self.input_device_input.setCurrentIndex(idx)
        current_out = self.config.get("output_device", -1)
        idx = self.output_device_input.findData(current_out)
        if idx >= 0:
            self.output_device_input.setCurrentIndex(idx)
        self.input_device_input.setEnabled(True)
        self.output_device_input.setEnabled(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    def get_config(self):
        return {
            "callsign": self.callsign_input.text().strip().upper(),
            "name": self.name_input.text().strip(),
            "location": self.location_input.text().strip(),
            "voice": self.voice_input.currentData(),
            "tts_length_scale": round(self.length_scale_slider.value() / 100.0, 2),
            "input_device": self.input_device_input.currentData(),
            "output_device": self.output_device_input.currentData(),
            "vad_threshold": round(self.vad_threshold_input.value(), 2),
            "time_format": self.time_format_input.currentData(),
            "filter_profanity": self.filter_profanity_input.isChecked(),
            "ptt_mode": self.ptt_mode_input.currentData(),
            "ptt_serial_port": self.ptt_serial_port_input.text().strip(),
            "ptt_serial_line": self.ptt_serial_line_input.currentData(),
        }

    def _update_length_scale_label(self, value):
        scale = value / 100.0
        if value == 100:
            suffix = " (normal)"
        elif value < 100:
            suffix = " (faster)"
        else:
            suffix = " (slower)"
        self.length_scale_value_label.setText(f"{scale:.2f}×{suffix}")

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

            syn_config = SynthesisConfig(
                speaker_id=0 if voice.config.num_speakers > 1 else None,
                length_scale=self.length_scale_slider.value() / 100.0,
            )
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
