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
- **Rx Section (Incoming)**: A large, scrollable "chat room" style text area displaying live transcriptions of incoming radio transmissions.
- **Tx Section (Outgoing)**: A text input box at the bottom for typing new messages, complete with a "Transmit/Enter" trigger.

### 2.3 Contact Management Screen
- **Functionality**: A separate screen accessible via a menu that allows the user to manually add, remove, or modify entries for known callsigns and names.
- **Persistence**: Data from this screen will update the contact records and should be saved locally (e.g., to a `contacts.json` file) for persistence across sessions.

## 3. Core Components

### 3.1 Audio Processing (Simulation Mode)
Since physical radio hardware is not yet integrated, the application must operate in a localized simulation mode:
- **Microphone**: Routes the computer's built-in microphone audio to the STT engine to simulate incoming radio traffic.
- **Speakers**: Routes the TTS engine's synthesized audio to the computer's speakers to simulate outgoing radio transmissions and allow user verification.

### 3.2 Speech-to-Text (STT) - Receive (Rx)
- Continuously monitors the configured audio input device.
- Transcribes voice to text in near real-time using an offline Python STT library (e.g., Vosk or Whisper Python bindings) and appends the text to the Rx Section of the Main Dashboard.

### 3.3 Text-to-Speech (TTS) - Transmit (Tx)
- Takes text input from the Tx Section.
- Generates synthesized speech using the Piper TTS engine with local voice models stored in a `Voices` folder, and outputs it to the configured audio output device.

### 3.4 Contact Discovery & Tracking
- **Record Keeping**: The system will keep a record of callsigns, names, and, if known by transcription, their locations. This includes both automatically discovered contacts and manually managed records from the Contact Management Screen.
- **Message Formatting**: When sending a message to a specific user (a callsign chosen in the Target Selection dropdown), the system automatically formats the outgoing text by adding `[My call sign] [My name] calling [Target call sign]` to the beginning of the message and tags the user's callsign and name at the end.

## 4. FCC Regulatory Compliance (GMRS)
To comply with FCC Part 95 rules for GMRS:
- **Station Identification**: The software must automatically append the user's personal Callsign and Name to outgoing messages to support families sharing a callsign.
- **15-Minute Rule Engine**: The system must track the timestamp of the last transmitted callsign. It will automatically append the callsign and name at the end of a drafted message if it has been more than 15 minutes since the last identification was transmitted, or if it is the conclusion of a communication series.

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

## 6. Future Hardware Integration
- **PTT (Push-To-Talk) Control**: Future iterations will require hardware control (e.g., via Serial COM RTS/DTR pins leveraging `pyserial` or USB GPIO relays) to electrically "key" the radio transmitter before playing TTS audio, and "unkey" it afterward.
- **Audio Routing**: Interface with external USB Soundcards (like a Signalink, Digirig, or custom TRRS cable) wired directly to an SDR, HT, or Mobile radio unit's mic/speaker ports.
- **Bluetooth Support**: Utilize Python Bluetooth libraries (e.g., `Bleak` or `PyBluez`) to enable wireless pairing with Bluetooth-enabled HTs and Mobile radios.
