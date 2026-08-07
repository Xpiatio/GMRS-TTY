import glob
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from gmrs_tty.constants import (
    GAIN_MODES, VALID_WHISPER_MODELS, VOICE_TEST_TEXT, validate_voice_path,
)
from gmrs_tty.stt.worker import STTWorker
from gmrs_tty.ui.device_query import DeviceQueryThread

GAIN_MODE_LABELS = {
    "agc": "Dynamic AGC (recommended)",
    "rms": "One-shot RMS normalize",
    "off": "No gain",
}


class ConfigDialog(QDialog):
    """Dialog for editing user configuration."""

    TEST_SAMPLE_TEXT = VOICE_TEST_TEXT

    def __init__(self, current_config, voice_test_fn=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setMinimumWidth(420)
        self.config = current_config
        self._voice_test_fn = voice_test_fn
        self._test_player = None

        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        for label, builder in [
            ("Identity", self._build_identity_rows),
            ("Audio", self._build_audio_rows),
            ("Voice", self._build_voice_rows),
            ("STT", self._build_stt_rows),
            ("PTT", self._build_ptt_rows),
            ("Behavior", self._build_behavior_rows),
        ]:
            page = QWidget()
            form = QFormLayout(page)
            builder(form)
            tabs.addTab(page, label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        # OK stays disabled until DeviceQueryThread finishes so the user
        # can't save a config with the "Loading devices…" placeholder.
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        outer.addWidget(self.buttons)

    # ------------------------------------------------------------------
    # Section builders — each adds its own rows to the shared QFormLayout
    # ------------------------------------------------------------------

    def _build_identity_rows(self, layout: QFormLayout) -> None:
        self.callsign_input = QLineEdit(self.config.get("callsign", ""))
        self.name_input = QLineEdit(self.config.get("name", ""))
        self.location_input = QLineEdit(self.config.get("location", ""))
        layout.addRow("&Callsign:", self.callsign_input)
        layout.addRow("&Name:", self.name_input)
        layout.addRow("&Location:", self.location_input)

    def _build_voice_rows(self, layout: QFormLayout) -> None:
        self.voice_input = QComboBox()
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
        # values slow speech, lower values speed it up.
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

        layout.addRow("&Voice Model:", voice_row)
        layout.addRow("Speech &Rate:", rate_row)

    def _build_audio_rows(self, layout: QFormLayout) -> None:
        self._audio_layout = layout
        self.input_device_input = QComboBox()
        self.input_device_input.addItem("Loading devices…", -1)
        self.input_device_input.setEnabled(False)

        self.monitor_sink_input = QComboBox()
        self.monitor_sink_input.addItem("Loading…", "")
        self.monitor_sink_input.setToolTip(
            "Which audio output to capture. Play audio in your browser, media "
            "player, or any app — the app will listen to that output. "
            "\"System Default\" follows whatever is set as your default playback device."
        )
        self.monitor_sink_input.setAccessibleName("Monitor sink")
        self.monitor_sink_input.setAccessibleDescription(
            "Select the audio output device whose playback will be captured as input."
        )

        self.output_device_input = QComboBox()
        self.output_device_input.addItem("Loading devices…", -1)
        self.output_device_input.setEnabled(False)

        self.monitor_enabled_input = QCheckBox("Play incoming radio audio through speakers by default")
        self.monitor_enabled_input.setChecked(bool(self.config.get("monitor_enabled", False)))
        self.monitor_enabled_input.setToolTip(
            "When enabled, the Monitor toggle turns on automatically when you "
            "activate Listen-only mode. The Monitor toggle on the main window "
            "controls this live; this setting determines the power-on default."
        )
        self.monitor_enabled_input.setAccessibleName("Monitor audio by default")
        self.monitor_enabled_input.setAccessibleDescription(
            "When checked, the Monitor toggle will be on automatically each time "
            "you activate Listen-only mode."
        )

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

        # Device enumeration happens on a background thread; PortAudio's
        # query_devices() can block hundreds of ms on ALSA/PulseAudio and
        # contend with the live STT InputStream. Until it finishes we show
        # a placeholder and disable OK so the user can't save a half-loaded
        # configuration.
        self._device_thread = DeviceQueryThread(self)
        self._device_thread.devices_ready.connect(self._on_devices_ready)
        self._device_thread.monitor_sources_ready.connect(self._on_monitor_sources_ready)
        self._device_thread.start()

        layout.addRow("&Input Device:", self.input_device_input)
        layout.addRow("&Monitor Sink:", self.monitor_sink_input)
        layout.setRowVisible(self.monitor_sink_input, False)
        self.input_device_input.currentIndexChanged.connect(self._update_input_device_fields)
        layout.addRow("&Output Device:", self.output_device_input)
        layout.addRow("&Monitor audio:", self.monitor_enabled_input)
        layout.addRow("VA&D Threshold:", self.vad_threshold_input)

    def _build_behavior_rows(self, layout: QFormLayout) -> None:
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
        self.filter_profanity_input.setChecked(bool(self.config.get("filter_profanity", True)))
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

        self.fuzzy_callsign_input = QCheckBox(
            "Replace near-miss callsigns with the closest contact"
        )
        self.fuzzy_callsign_input.setChecked(bool(self.config.get("fuzzy_callsign", False)))
        self.fuzzy_callsign_input.setToolTip(
            "Fuzzy callsign logic: when an incoming callsign differs from a "
            "saved contact by exactly one letter or digit, rewrite it in the "
            "chat log to the known callsign and skip the '+ Add' pending pill. "
            "Helpful when STT mishears a single character; ambiguous cases "
            "(two contacts equally close) are left alone."
        )
        self.fuzzy_callsign_input.setAccessibleName("Fuzzy callsign logic")
        self.fuzzy_callsign_input.setAccessibleDescription(
            "When enabled, a detected callsign that is off by one character "
            "from a contact is rewritten in the chat to that contact's "
            "callsign and the pending-station prompt is suppressed."
        )

        self.attendance_enabled_input = QCheckBox(
            "Track callsigns heard during each listening session"
        )
        self.attendance_enabled_input.setChecked(
            bool((self.config.get("attendance") or {}).get("enabled", False))
        )
        self.attendance_enabled_input.setToolTip(
            "When enabled, the Callsigns Detected panel logs every callsign detected "
            "during a Listen session. Rows show Callsign, Name, Location, GMRS "
            "and HAM — the contact columns fill in automatically when a "
            "callsign is in (or added to) contacts. Show or hide the panel "
            "any time via View → Show callsigns detected (Ctrl+Shift+A). GMRS only."
        )
        self.attendance_enabled_input.setAccessibleName(
            "Track listening-session callsigns detected"
        )
        self.attendance_enabled_input.setAccessibleDescription(
            "When enabled, the Callsigns Detected panel records every callsign "
            "detected during a Listen session. The panel can be shown or "
            "hidden from the View menu."
        )

        self.gemini_api_key_input = QLineEdit(self.config.get("gemini_api_key", ""))
        self.gemini_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key_input.setPlaceholderText("AIza…  (leave blank to disable journal export)")
        self.gemini_api_key_input.setToolTip(
            "Google Gemini API key used to generate session journal summaries. "
            "Obtain one free at https://aistudio.google.com/app/apikey. "
            "Leave blank to disable the Generate Journal feature."
        )
        self.gemini_api_key_input.setAccessibleName("Gemini API key")
        self.gemini_api_key_input.setAccessibleDescription(
            "Google Gemini API key for AI-generated session journal summaries. "
            "Leave blank to disable journal generation."
        )
        self._gemini_show_btn = QToolButton()
        self._gemini_show_btn.setText("Show")
        self._gemini_show_btn.setCheckable(True)
        self._gemini_show_btn.toggled.connect(self._toggle_api_key_visibility)
        gemini_row = QWidget()
        gemini_row_layout = QHBoxLayout(gemini_row)
        gemini_row_layout.setContentsMargins(0, 0, 0, 0)
        gemini_row_layout.addWidget(self.gemini_api_key_input, 1)
        gemini_row_layout.addWidget(self._gemini_show_btn)

        self.tx_conditioning_input = QCheckBox("Condition TX audio for radio (band-limit + compress)")
        self.tx_conditioning_input.setChecked(bool(self.config.get("tx_conditioning", False)))
        self.tx_conditioning_input.setToolTip(
            "Band-limits synthesized speech to the 300–3000 Hz FM voice "
            "channel, gently compresses peaks, and normalizes the level so "
            "the voice modulates the radio consistently without clipping. "
            "Leave off if TTS plays through regular speakers."
        )
        self.tx_conditioning_input.setAccessibleName("Condition TX audio")
        self.tx_conditioning_input.setAccessibleDescription(
            "When checked, synthesized speech is band-limited, compressed, "
            "and level-normalized before it drives the radio's microphone input."
        )

        self.tx_max_duration_input = QSpinBox()
        self.tx_max_duration_input.setRange(0, 600)
        self.tx_max_duration_input.setSuffix(" s")
        self.tx_max_duration_input.setSpecialValueText("Off")
        self.tx_max_duration_input.setValue(int(self.config.get("tx_max_duration_seconds", 60)))
        self.tx_max_duration_input.setToolTip(
            "Hard cap on how long PTT may stay keyed for one transmission. "
            "If playback runs longer, TX is stopped and PTT released. "
            "0 disables the cap."
        )
        self.tx_max_duration_input.setAccessibleName("Maximum transmission length")
        self.tx_max_duration_input.setAccessibleDescription(
            "Longest a single transmission may key the radio, in seconds. "
            "Zero disables the limit."
        )

        self.tx_synth_timeout_input = QSpinBox()
        self.tx_synth_timeout_input.setRange(0, 300)
        self.tx_synth_timeout_input.setSuffix(" s")
        self.tx_synth_timeout_input.setSpecialValueText("Off")
        self.tx_synth_timeout_input.setValue(
            int(self.config.get("tx_synthesis_timeout_seconds", 30))
        )
        self.tx_synth_timeout_input.setToolTip(
            "How long to wait for speech synthesis before giving up. The "
            "radio is never keyed when synthesis times out. 0 disables."
        )
        self.tx_synth_timeout_input.setAccessibleName("Synthesis timeout")
        self.tx_synth_timeout_input.setAccessibleDescription(
            "Maximum seconds to wait for text-to-speech synthesis before "
            "aborting the transmission. Zero disables the timeout."
        )

        layout.addRow("Time &Format:", self.time_format_input)
        layout.addRow("Filter profanit&y:", self.filter_profanity_input)
        layout.addRow("F&uzzy callsigns:", self.fuzzy_callsign_input)
        layout.addRow("Callsigns &Detected:", self.attendance_enabled_input)
        layout.addRow("Condition T&X audio:", self.tx_conditioning_input)
        layout.addRow("Max TX &length:", self.tx_max_duration_input)
        layout.addRow("Synthesis &timeout:", self.tx_synth_timeout_input)
        layout.addRow("&Gemini API Key:", gemini_row)

    def _build_stt_rows(self, layout: QFormLayout) -> None:
        self.whisper_model_input = QComboBox()
        staged = sorted(
            m for m in VALID_WHISPER_MODELS
            if os.path.isdir(os.path.join(STTWorker.MODELS_STT_DIR, m))
        )
        current_model = self.config.get("whisper_model", "small.en")
        if current_model not in staged:
            staged.append(current_model)
        for m in staged:
            self.whisper_model_input.addItem(m, m)
        idx = self.whisper_model_input.findData(current_model)
        if idx >= 0:
            self.whisper_model_input.setCurrentIndex(idx)
        self.whisper_model_input.setToolTip(
            "Whisper model used for transcription. Only models already staged "
            "under Models/STT are listed — run bootstrap_models.py to add more. "
            "Larger models are more accurate but slower."
        )
        self.whisper_model_input.setAccessibleName("Whisper model")
        self.whisper_model_input.setAccessibleDescription(
            "Select which locally staged Whisper model transcribes incoming audio."
        )

        self.gain_mode_input = QComboBox()
        for mode in GAIN_MODES:
            self.gain_mode_input.addItem(GAIN_MODE_LABELS[mode], mode)
        idx = self.gain_mode_input.findData(self.config.get("stt_gain_mode", "agc"))
        if idx >= 0:
            self.gain_mode_input.setCurrentIndex(idx)
        self.gain_mode_input.setToolTip(
            "Gain stage applied to each utterance before transcription. "
            "Dynamic AGC levels weak and strong stations smoothly; RMS applies "
            "one flat gain; No gain leaves levels untouched."
        )
        self.gain_mode_input.setAccessibleName("STT gain mode")
        self.gain_mode_input.setAccessibleDescription(
            "Choose how audio levels are normalized before speech recognition."
        )

        self.noise_profile_input = QCheckBox(
            "Learn the channel noise floor while squelch is closed"
        )
        self.noise_profile_input.setChecked(bool(self.config.get("stt_noise_profile", False)))
        self.noise_profile_input.setToolTip(
            "Samples static between transmissions and uses it as the noise "
            "estimate when denoising speech, instead of guessing from the "
            "speech itself. Can improve accuracy on consistently noisy channels."
        )
        self.noise_profile_input.setAccessibleName("Noise profile denoising")
        self.noise_profile_input.setAccessibleDescription(
            "When checked, background static sampled between transmissions "
            "improves noise reduction on incoming speech."
        )

        self.saved_phrases_input = QPlainTextEdit()
        self.saved_phrases_input.setPlainText("\n".join(self.config.get("saved_phrases", [])))
        self.saved_phrases_input.setPlaceholderText("One phrase per line, e.g. a club name or local landmark")
        self.saved_phrases_input.setFixedHeight(72)
        self.saved_phrases_input.setToolTip(
            "Custom words or phrases the transcriber should recognize — names, "
            "landmarks, club jargon. Added to the Whisper vocabulary bias "
            "alongside built-in radio procedure words and contact callsigns."
        )
        self.saved_phrases_input.setAccessibleName("Custom vocabulary phrases")
        self.saved_phrases_input.setAccessibleDescription(
            "Enter one phrase per line to bias speech recognition toward "
            "words it would otherwise mishear."
        )

        self.vocab_max_callsigns_input = QSpinBox()
        self.vocab_max_callsigns_input.setRange(0, 50)
        self.vocab_max_callsigns_input.setValue(int(self.config.get("stt_vocab_max_callsigns", 15)))
        self.vocab_max_callsigns_input.setToolTip(
            "How many contact callsigns to include in the recognition "
            "vocabulary. Each costs ~6 of the ~223 available prompt tokens; "
            "newer contacts win when over the limit."
        )
        self.vocab_max_callsigns_input.setAccessibleName("Maximum vocabulary callsigns")
        self.vocab_max_callsigns_input.setAccessibleDescription(
            "Limit how many saved contact callsigns bias speech recognition."
        )

        self.debug_capture_input = QCheckBox("Save each utterance's audio and transcripts to disk")
        self.debug_capture_input.setChecked(bool(self.config.get("stt_debug_capture", False)))
        self.debug_capture_input.setToolTip(
            "Records raw, segmented, and processed audio plus transcripts for "
            "every utterance — used with the offline eval tool "
            "(python -m gmrs_tty.tools.eval_stt) to measure accuracy. "
            "Leave off in normal use; captures grow quickly."
        )
        self.debug_capture_input.setAccessibleName("STT debug capture")
        self.debug_capture_input.setAccessibleDescription(
            "When checked, every received utterance is saved to the debug "
            "directory for offline transcription-accuracy analysis."
        )

        self.debug_dir_input = QLineEdit(self.config.get("stt_debug_dir", "debug/stt"))
        self.debug_dir_input.setPlaceholderText("debug/stt")
        self.debug_dir_input.setToolTip("Directory where debug captures are written.")
        self.debug_dir_input.setAccessibleName("Debug capture directory")
        self.debug_dir_input.setAccessibleDescription(
            "Filesystem path where utterance debug captures are stored."
        )
        self.debug_capture_input.toggled.connect(self.debug_dir_input.setEnabled)
        self.debug_dir_input.setEnabled(self.debug_capture_input.isChecked())

        layout.addRow("Whisper &Model:", self.whisper_model_input)
        layout.addRow("&Gain mode:", self.gain_mode_input)
        layout.addRow("Noise pro&file:", self.noise_profile_input)
        layout.addRow("Custom p&hrases:", self.saved_phrases_input)
        layout.addRow("Ma&x callsigns:", self.vocab_max_callsigns_input)
        layout.addRow("De&bug capture:", self.debug_capture_input)
        layout.addRow("Debug director&y:", self.debug_dir_input)

    def _build_ptt_rows(self, layout: QFormLayout) -> None:
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

        self.vox_primer_input = QCheckBox("Play a short priming tone before speech")
        self.vox_primer_input.setChecked(bool(self.config.get("vox_primer_enabled", False)))
        self.vox_primer_input.setToolTip(
            "For VOX-keyed radios: a 1 kHz tone keys the radio and a short "
            "gap lets it settle, so the first spoken word isn't clipped."
        )
        self.vox_primer_input.setAccessibleName("VOX primer tone")
        self.vox_primer_input.setAccessibleDescription(
            "When checked, a short tone precedes speech so a VOX-keyed radio "
            "is fully keyed before the message starts."
        )

        self.vox_primer_ms_input = QSpinBox()
        self.vox_primer_ms_input.setRange(50, 2000)
        self.vox_primer_ms_input.setSingleStep(50)
        self.vox_primer_ms_input.setSuffix(" ms")
        self.vox_primer_ms_input.setValue(int(self.config.get("vox_primer_ms", 300)))
        self.vox_primer_ms_input.setToolTip(
            "Length of the VOX priming tone. Longer tones suit radios with "
            "slow VOX attack; 300 ms works for most."
        )
        self.vox_primer_ms_input.setAccessibleName("VOX primer tone length")
        self.vox_primer_ms_input.setAccessibleDescription(
            "Duration of the priming tone in milliseconds."
        )

        self.vox_primer_word_enabled_input = QCheckBox("Speak a priming word before the message")
        self.vox_primer_word_enabled_input.setChecked(
            bool(self.config.get("vox_primer_word_enabled", False))
        )
        self.vox_primer_word_enabled_input.setToolTip(
            "Speaks a keyword (e.g. \"transmit\") before the actual message, "
            "as an alternative or supplement to the tone, so the radio keys "
            "on a clear spoken word."
        )
        self.vox_primer_word_enabled_input.setAccessibleName("VOX priming word")
        self.vox_primer_word_enabled_input.setAccessibleDescription(
            "When checked, a spoken keyword precedes every transmitted message."
        )

        self.vox_primer_word_input = QLineEdit(self.config.get("vox_primer_word", "transmit"))
        self.vox_primer_word_input.setToolTip("The word spoken before the message.")
        self.vox_primer_word_input.setAccessibleName("Priming word")
        self.vox_primer_word_input.setAccessibleDescription(
            "The keyword spoken before each transmitted message."
        )
        self.vox_primer_word_enabled_input.toggled.connect(self.vox_primer_word_input.setEnabled)
        self.vox_primer_word_input.setEnabled(self.vox_primer_word_enabled_input.isChecked())

        layout.addRow("&PTT Mode:", self.ptt_mode_input)
        layout.addRow("&Serial Port:", self.ptt_serial_port_input)
        layout.addRow("Control Lin&e:", self.ptt_serial_line_input)
        layout.addRow("V&OX primer tone:", self.vox_primer_input)
        layout.addRow("Primer &length:", self.vox_primer_ms_input)
        layout.addRow("Primin&g word:", self.vox_primer_word_enabled_input)
        layout.addRow("&Word:", self.vox_primer_word_input)
        self._update_ptt_fields()

    # ------------------------------------------------------------------
    # Slots and helpers
    # ------------------------------------------------------------------

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
        self.input_device_input.addItem("System Audio Output (loopback)", "system_monitor")
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
        self._update_input_device_fields()

    def _on_monitor_sources_ready(self, sources):
        saved_sink = self.config.get("system_monitor_sink", "")
        self.monitor_sink_input.clear()
        for display_name, sink_id in sources:
            self.monitor_sink_input.addItem(display_name, sink_id)
        idx = self.monitor_sink_input.findData(saved_sink)
        if idx >= 0:
            self.monitor_sink_input.setCurrentIndex(idx)

    def get_config(self):
        return {
            "callsign": self.callsign_input.text().strip().upper(),
            "name": self.name_input.text().strip(),
            "location": self.location_input.text().strip(),
            "voice": self.voice_input.currentData(),
            "tts_length_scale": round(self.length_scale_slider.value() / 100.0, 2),
            "input_device": self.input_device_input.currentData(),
            "system_monitor_sink": self.monitor_sink_input.currentData() or "",
            "output_device": self.output_device_input.currentData(),
            "monitor_enabled": self.monitor_enabled_input.isChecked(),
            "vad_threshold": round(self.vad_threshold_input.value(), 2),
            "whisper_model": self.whisper_model_input.currentData(),
            "stt_gain_mode": self.gain_mode_input.currentData(),
            "stt_noise_profile": self.noise_profile_input.isChecked(),
            "saved_phrases": [
                line.strip()
                for line in self.saved_phrases_input.toPlainText().splitlines()
                if line.strip()
            ],
            "stt_vocab_max_callsigns": self.vocab_max_callsigns_input.value(),
            "stt_debug_capture": self.debug_capture_input.isChecked(),
            "stt_debug_dir": self.debug_dir_input.text().strip() or "debug/stt",
            "time_format": self.time_format_input.currentData(),
            "filter_profanity": self.filter_profanity_input.isChecked(),
            "fuzzy_callsign": self.fuzzy_callsign_input.isChecked(),
            # Attendance is a nested sub-dict so future per-session settings
            # (sort order, persistence, etc.) can land alongside ``enabled``
            # without crowding the top-level namespace.
            "attendance": {
                "enabled": self.attendance_enabled_input.isChecked(),
            },
            "gemini_api_key": self.gemini_api_key_input.text().strip(),
            "ptt_mode": self.ptt_mode_input.currentData(),
            "ptt_serial_port": self.ptt_serial_port_input.text().strip(),
            "ptt_serial_line": self.ptt_serial_line_input.currentData(),
            "vox_primer_enabled": self.vox_primer_input.isChecked(),
            "vox_primer_ms": self.vox_primer_ms_input.value(),
            "vox_primer_word_enabled": self.vox_primer_word_enabled_input.isChecked(),
            "vox_primer_word": self.vox_primer_word_input.text().strip() or "transmit",
            "tx_conditioning": self.tx_conditioning_input.isChecked(),
            "tx_max_duration_seconds": self.tx_max_duration_input.value(),
            "tx_synthesis_timeout_seconds": self.tx_synth_timeout_input.value(),
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

    def _update_input_device_fields(self, _index=None):
        is_monitor = self.input_device_input.currentData() == "system_monitor"
        self._audio_layout.setRowVisible(self.monitor_sink_input, is_monitor)

    def _toggle_api_key_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.gemini_api_key_input.setEchoMode(mode)
        self._gemini_show_btn.setText("Hide" if visible else "Show")

    def _update_ptt_fields(self):
        is_serial = self.ptt_mode_input.currentData() == "usb_ftdi"
        self.ptt_serial_port_input.setEnabled(is_serial)
        self.ptt_serial_line_input.setEnabled(is_serial)

    def test_voice(self):
        voice_path = self.voice_input.currentData()
        if not validate_voice_path(voice_path):
            QMessageBox.warning(self, "Test Voice", "No valid Piper voice selected.")
            return

        if self._voice_test_fn is None:
            QMessageBox.warning(self, "Test Voice", "Voice test is not available.")
            return

        self.test_voice_button.setEnabled(False)
        self.test_voice_button.setText("Speaking…")
        QApplication.processEvents()
        self._voice_test_fn(
            voice_path,
            self.length_scale_slider.value() / 100.0,
            self.output_device_input.currentData(),
            self._reset_test_button,
        )

    def _reset_test_button(self):
        self.test_voice_button.setEnabled(True)
        self.test_voice_button.setText("Test")
