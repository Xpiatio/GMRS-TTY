# GMRS-TTY Technical Specification

## 1. Overview
The GMRS-TTY (Amateur Radio Accessibility Communicator) is a software application designed to assist hard-of-hearing, deaf, or mute individuals in communicating over GMRS (General Mobile Radio Service) radio frequencies. It acts as a modern TTY interface, converting incoming voice transmissions to text (STT) and outgoing typed messages to voice (TTS). The application is built using **Python and the PySide6 framework** to ensure rapid development, accessible machine learning libraries, and robust cross-platform support (Windows, Linux, Raspberry Pi).

The application is designed for **fully off-grid operation**: all speech-to-text, text-to-speech, voice-activity-detection, and contact-management features must function without any internet connectivity, suitable for emergency communications, remote field deployments, and disaster scenarios. Distribution targets include native installation on Raspberry Pi (ARM64), Linux (x86_64), and Windows (10/11), as well as a Docker container image for reproducible deployment across all supported platforms.

## 2. User Interface (UI) Requirements
The application will feature a user-friendly interface divided into Configuration and Main Communication views.

### 2.1 Configuration Page
- **Required Fields**: Personal Callsign, Name, Location (e.g., Grid Square or City/State).
- **Persistence**: Configuration data must be saved to a local configuration file (e.g., `config.json`) and automatically loaded upon application startup.

### 2.2 Main Dashboard
- **Header**: Clearly displays the currently configured Callsign, Name, and Location for user reference.
- **Target Selection**: A dropdown menu used to select the intended recipient for an outgoing message. The default value is "All". It is populated automatically from the application's contact records and manually entered contacts.
- **Rx Section (Incoming)**: A large, scrollable "chat room" style text area displaying live transcriptions of incoming radio transmissions, each line timestamped (`[RX HH:MM:SS]: ...`).
- **Pending Stations Bar**: A horizontal strip between the chat area and the input row. When the STT detects a new GMRS callsign in incoming transcriptions that is not yet in the contact list, a yellow pill button appears (`+ Add {CALLSIGN}`) with a tooltip showing the detected name/location heuristics. Clicking it opens a prefilled "Add Station" dialog.
- **Tx Section (Outgoing)**: A `Listen` toggle, the Target Selection dropdown, a text input box, and a `Transmit` button. Pressing Enter in the input box transmits.
- **Standalone Station ID Button**: A `This is` button under the Transmit row sends a one-click station ID (`This is [CALL], [NATO phonetic CALL]. [name] from [location].`) and resets the 15-minute ID timer. No input text required.
- **Status Bar**: Qt status bar surfaces STT load state (`Loading Whisper model...`, `Listening...`, `Paused (transmitting)`, `Stopped listening`) and error messages.

### 2.3 Contact Management Screen
- **Functionality**: A separate screen accessible via a menu that allows the user to manually add, remove, or modify entries for known callsigns and names.
- **Persistence**: Contact data is saved to `contacts.json`.

### 2.4 Configuration Dialog
- **Identity**: Callsign, Name, Location.
- **Audio**: Voice model dropdown (with a `Test` button that previews the selected voice), Input Device dropdown, Output Device dropdown (separate from input so TTS can be routed to a USB sound card / Signalink / Digirig channel feeding the radio).
- **STT tuning**: VAD threshold (0.10–0.95, default 0.5).
- **PTT**: Mode dropdown (Manual / VOX / USB FTDI). Serial Port and Control Line (RTS or DTR) fields enable only when USB FTDI is selected.
- **Hot-reload**: Changes to input device or VAD threshold restart the listener automatically. Changes to PTT mode/port/line reopen the PTT backend.

### 2.5 Accessibility (WCAG 2.1 AA)
The application is built for users with disabilities. The UI is held to **WCAG 2.1 Level AA** — the practical baseline that DOJ and Section 508 reference for software ADA compliance. The requirements below are normative for this project: a PR that regresses any of them should be rejected.
- **Color contrast (WCAG 1.4.3)**: text colors meet ≥4.5:1 against the chat background; UI borders (1.4.11) meet ≥3:1. The chat palette is defined as module-level constants in `main.py` (`COLOR_RX`, `COLOR_TX`, `COLOR_ERROR`, `COLOR_WARN`, `PILL_*`) so contrast can be audited in one place.
- **Color not the sole cue (WCAG 1.4.1)**: every RX line is prefixed `[RX HH:MM:SS]:`, every TX line `[TX to …]:` or `[TX ID]:`, every error line carries an "Error:" / "Failed:" / "Warning:" word; color is supplemental, not load-bearing.
- **Full keyboard operation (WCAG 2.1.1)**: every action is reachable by keyboard. Tab order is explicit (`setTabOrder`) — Listen → target → message → Transmit → This is. Mnemonics underline a unique letter per actionable label (Alt+L Listen, Alt+T Transmit, Alt+I This is, Alt+S Settings → Alt+C Configuration / Alt+N Contacts); none collide. Global shortcuts via `QShortcut` cover the same actions for users on platforms where Alt navigation is awkward (Ctrl+L, Ctrl+Return/Enter, Ctrl+I, Ctrl+, , Ctrl+B).
- **Programmatic name / role / state (WCAG 4.1.2)**: every non-decorative widget has an `accessibleName` and (where helpful) `accessibleDescription` so screen readers (NVDA, JAWS, Orca, VoiceOver) report meaningful semantics through Qt's accessibility bridge. Stateful widgets (Listen toggle) update their description on state change.
- **Resize text / scale (WCAG 1.4.4)**: stylesheets do not specify pixel `font-size`. The header bold uses `QFont` relative to the app font (`pointSize + 2`), so the OS font-scale setting carries through. The main window has a 720×520 minimum that comfortably accommodates 150 %–200 % font scale without clipping.
- **Visible focus (WCAG 2.4.7)**: the Fusion style's focus indicator is preserved — no `outline: none` or `:focus { … }` overrides that strip it.
- **Predictable interaction (WCAG 3.2)**: tooltips on every actionable control surface the keyboard shortcut, so discovery is hint-rich without requiring a manual.
- **Status messages**: transient feedback uses `QStatusBar.showMessage`, which Qt's accessibility tree exposes to screen readers without forcing focus. The chat log is a transcript-by-design rather than a live-announcement region; users review it on demand.

## 3. Core Components

### 3.1 Audio Processing (Simulation Mode)
Since physical radio hardware is not yet integrated, the application must operate in a localized simulation mode:
- **Microphone**: Routes the computer's built-in microphone audio to the STT engine to simulate incoming radio traffic.
- **Speakers**: Routes the TTS engine's synthesized audio to the computer's speakers to simulate outgoing radio transmissions and allow user verification.

### 3.2 Speech-to-Text (STT) - Receive (Rx)
- Continuously monitors the configured audio input device on a background `QThread` (`STTWorker`), pushing results to the UI via Qt signals.
- **VAD-gated**: Silero VAD (`silero-vad` package) gates the audio stream at 16 kHz / 512-sample chunks. Only utterances bounded by VAD start/end events are transcribed. A configurable VAD threshold (0.10–0.95, default 0.5) controls sensitivity.
- **Per-utterance DSP**: each VAD-bounded utterance is passed through a 4th-order 300–3000 Hz Butterworth bandpass (`scipy.signal.sosfiltfilt`) to match the narrowband-FM voice band, then through `noisereduce` spectral gating with `prop_decrease=0.7`, before STT.
- **Offline STT**: faster-whisper (CTranslate2 backend) with `compute_type="int8"` on CPU. Default model `small.en`; the variant is configurable via the `whisper_model` config key (`tiny.en` / `base.en` / `small.en` / `medium.en` / `large-v3`).
- **Pre-buffer & utterance gating**: a 10-chunk (~320 ms) rolling pre-buffer is prepended to each speech segment so VAD-padded onsets aren't clipped. Utterances shorter than 0.4 s are dropped (kerchunks / blips), as are common Whisper hallucinations on silence (`you`, `thank you`, `thanks for watching`, etc.).
- **Auto-pause during TX**: the STT worker is paused while the app is transmitting so the TTS isn't transcribed back. On resume, the VAD state is reset so an in-progress speech segment doesn't bleed across the TX boundary.
- **No runtime fetch**: the Whisper model is loaded from `Models/STT/<model_name>/` (pre-staged by `bootstrap_models.py`). If the directory is missing the listener fails fast with an explicit instruction; the app never falls back to a network fetch.

### 3.3 Text-to-Speech (TTS) - Transmit (Tx)
- Takes text input from the Tx Section.
- Generates synthesized speech using the Piper TTS engine with local voice models stored in a `Voices` folder, and outputs it to the configured audio output device.
- **Callsign digit-spelling**: before synthesis, callsign digits are spaced out (`WSLZ233` → `WSLZ 2 3 3`) so the receiver hears digits as digits, not as the number "two hundred thirty-three".
- **NATO phonetic** in standalone ID: the "This is" button reads the user's callsign letters in NATO phonetic followed by individual digits ("Whiskey Sierra Lima Zulu 2 3 3").
- **Sentence-wise synthesis**: messages are split on sentence terminators and synthesized in the main thread sequentially to avoid `espeak-ng` thread crashes; chunks are concatenated and played in a single `AudioPlayerThread` so PTT timing is deterministic.

### 3.4 Contact Discovery & Tracking
- **Record Keeping**: The system will keep a record of callsigns, names, and, if known by transcription, their locations. This includes both automatically discovered contacts and manually managed records from the Contact Management Screen.
- **Callsign detection forms**: GMRS callsigns are detected in compact (`WSLZ233`), spaced (`W S L Z 2 3 3`), separator (`WSLZ-233`, `WSLZ.233`, `WSLZ, 233`), and NATO-phonetic (`Whiskey Sierra Lima Zulu Two Three Three`) forms. Both modern (`W[A-Z]{3}\d{3}`) and legacy (`KA[A-Z]\d{3,4}`) formats are recognized.
- **Name/location heuristics**: first capitalized word after a detected callsign is taken as the name; capitalized phrase after `in/from/near/at` anywhere in the utterance is taken as the location. Both are prefilled into the Add Station dialog.
- **Message Formatting**: When sending a message to a specific user (a callsign chosen in the Target Selection dropdown), the system automatically formats the outgoing text by adding `[My call sign] [My name] calling [Target call sign]` to the beginning of the message and tags the user's callsign and name at the end.

### 3.5 PTT Control (Push-To-Talk)
- **Manual mode**: app plays audio only; the operator keys the radio themselves.
- **VOX mode**: relies on the radio's VOX circuit to auto-key on detected audio. The app appends ~150 ms of trailing silence so the last syllable isn't clipped by VOX hang-time dropout.
- **USB FTDI / Serial mode** (`pyserial`): the app keys PTT through a USB-serial adapter's RTS or DTR line (drives an external transistor / opto on the radio's PTT pin). Lead-in and tail silence (~50 ms each) bracket the audio so the radio's keying ramp doesn't clip start or end.
- **Selection & hot-reload**: PTT mode, serial port, and control line (RTS/DTR) are all configurable in the Configuration dialog. Switching modes reopens the PTT backend without restarting the app. If USB FTDI is selected but the serial port can't be opened, the app falls back to Manual and logs the reason.
- **Sequencing**: TX flow is `pause STT → key PTT → play audio (with lead/tail silence) → unkey PTT → resume STT`. STT pause/resume is wired into PTT keying so the app never transcribes its own TTS.

## 4. FCC Regulatory Compliance (GMRS)
To comply with FCC Part 95 rules for GMRS:
- **Station Identification**: The software must automatically append the user's personal Callsign and Name to outgoing messages to support families sharing a callsign.
- **15-Minute Rule Engine**: The system must track the timestamp of the last transmitted callsign. It will automatically append the callsign and name at the end of a drafted message if it has been more than 15 minutes since the last identification was transmitted, or if it is the conclusion of a communication series.
- **Preface-as-ID**: When the user targets a specific station, the prefaced format `[My call] [My name] calling [Target call] [Target name]` satisfies the ID requirement on its own; the 15-minute timer is reset on send.
- **Standalone ID**: A dedicated "This is" button emits `This is [CALL], [NATO phonetic CALL]. [name] from [location].` and resets the 15-minute timer without requiring the operator to type a message.
- **Spoken-form correctness**: Callsign digits are spelled individually in TTS output (e.g. `233` → `2 3 3`) so the audible ID matches the licensed form rather than being read as a number.

## 5. Deployment & Runtime Requirements

### 5.1 Off-Grid / No-Internet Operation
The application must operate end-to-end without internet connectivity. This is a hard requirement, not an optional mode.
- **No runtime downloads**: STT models (e.g., faster-whisper / Whisper variants), VAD models (Silero), TTS voice models (Piper ONNX + JSON), and any other ML artifacts must be bundled with the application or pre-staged on disk at install time. The application must never attempt to fetch a model on first use.
- **No external services**: no telemetry, analytics, crash reporting, update checks, cloud STT/TTS, or any other outbound network calls.
- **Local-only persistence**: configuration, contacts, and discovered-station records are stored exclusively on the local filesystem (`config.json`, `contacts.json`, voice model directory).
- **Air-gapped installability**: the install/build process must produce an artifact (wheel set, Docker image, or installer) that can be transferred to and run on a machine with no internet access.

### 5.2 Cross-Platform Support
The application must run on each of the following targets with feature parity:
- **Raspberry Pi** (Raspberry Pi OS 64-bit on Pi 4 / Pi 5, ARM64) — primary target for portable, battery-powered field deployments. Model size and CPU choices must keep STT/TTS latency usable on Pi-class hardware.
- **Linux** (x86_64, Debian/Ubuntu and derivatives) — primary target for operator workstations and development.
- **Windows** (10/11, x86_64) — supported for operators who prefer Windows.

All audio I/O, configuration paths, and file handling must be portable across these platforms.

### 5.3 Containerization (Docker)
The application will be packaged as a Docker container for reproducible, dependency-free deployment.
- **Single self-contained image**: includes the Python runtime, all dependencies (PySide6, faster-whisper / CTranslate2, Silero VAD, Piper, noisereduce, sounddevice, etc.), and all bundled models (STT, VAD, and at least one default TTS voice).
- **Multi-architecture build**: published for `linux/amd64` and `linux/arm64` so a single image tag works on Pi and on x86_64 hosts.
- **Audio passthrough**: container must support host audio devices via PulseAudio socket or ALSA device passthrough on Linux/Pi, and the equivalent on Windows hosts (e.g., via WSL2 / Docker Desktop audio routing).
- **GUI passthrough**: the Qt window must render on the host display via X11 socket mount (or Wayland equivalent) on Linux/Pi, and via Docker Desktop's display integration on Windows.
- **USB device passthrough**: USB serial adapters (for future PTT control) and external USB sound cards (Signalink, Digirig, etc.) must be mappable into the container.
- **Persistent volumes**: `config.json`, `contacts.json`, and the `Voices/` directory must be mountable as host volumes so user state survives container rebuilds.

## 6. Hardware Integration

### 6.1 Implemented
- **PTT (Push-To-Talk) Control** — `pyserial`-based USB FTDI / serial keying on RTS or DTR is shipped, alongside Manual and VOX modes. See §3.6.
- **Audio Routing** — separate input and output device pickers in the Configuration dialog allow direct routing to/from external USB sound cards (Signalink, Digirig, custom TRRS cable) wired to the radio's mic/speaker ports.

### 6.2 Future
- **Bluetooth Support**: Utilize Python Bluetooth libraries (e.g., `Bleak` or `PyBluez`) to enable wireless pairing with Bluetooth-enabled HTs and Mobile radios.
- **CAT / CI-V control**: Optional integration with rig-control libraries (e.g., `hamlib`) for frequency / mode set on supported radios.
