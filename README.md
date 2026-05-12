# GMRS-TTY

A modern TTY-style accessibility communicator for GMRS (General Mobile Radio Service) radio. Designed to let hard-of-hearing, deaf, or mute operators participate in voice radio conversations by live-transcribing incoming audio and speaking out typed messages.

Cross-platform desktop app built with **Python + PySide6**, fully offline, with FCC Part 95 ID rules built into the message flow.

## Features

### Receive (Rx)
- Live microphone capture with **Silero VAD** — only transcribes when a human is speaking; ignores static and kerchunks.
- Offline transcription via **faster-whisper** (`small.en` by default, int8 CPU).
- **Noise reduction** (spectral gating) applied per utterance before transcription.
- Drops short blips (<400 ms) and common Whisper hallucinations on silence.

### Transmit (Tx)
- Offline TTS via **Piper** with local ONNX voice models.
- **FCC formatting** — automatically prepends `[Your call] [Your name] calling [Target]` when targeting a specific station.
- **15-minute ID rule** — appends your callsign + name when more than 15 minutes have passed since last identification.
- "All" target is transmitted as-is (no preface).

### Contact discovery
- Detects GMRS callsigns in incoming transcriptions:
  - Compact form: `WSLZ233`
  - Spaced: `W S L Z 2 3 3`
  - With separators: `W.S.L.Z.233`, `WSLZ-233`, `WSLZ, 233`
  - NATO phonetic: `Whiskey Sierra Lima Zulu Two Three Three`
- Unknown stations appear as one-click `+ Add` pills below the chat with the detected name/location pre-filled.
- Manual contact management dialog (callsign, name, location).

### Cross-platform & off-grid
- Targets Raspberry Pi, Linux, Windows.
- All STT/TTS/VAD models run locally — no internet required at runtime.
- Future stages: bundled models for air-gapped install + multi-arch Docker image.

## Requirements

- Python 3.11+ (3.13 recommended)
- A working microphone and speaker
- Linux: PortAudio dev libs (`sudo apt install libportaudio2 portaudio19-dev`)
- ~2 GB disk for dependencies (torch, CTranslate2, ONNX Runtime) + ~250 MB for the Whisper model on first run

## Install

```bash
git clone <repo-url> GMRS-TTY
cd GMRS-TTY

python3 -m venv .venv
source .venv/bin/activate              # Linux/macOS
# .venv\Scripts\activate                # Windows

pip install -r requirements.txt
```

### Voice models (Piper)

Download one or more Piper ONNX voices and their accompanying `.json` config files into a `Voices/` directory at the project root:

```
Voices/
├── en_US-ryan-high.onnx
├── en_US-ryan-high.onnx.json
├── en_US-amy-medium.onnx
└── en_US-amy-medium.onnx.json
```

Voices: https://github.com/rhasspy/piper/blob/master/VOICES.md

### Configure

```bash
cp config.example.json config.json
$EDITOR config.json    # set your callsign, name, location, and preferred voice
```

The `input_device` field is `-1` (system default) by default; the Configuration dialog in the app provides a dropdown of available input devices once you're running.

## Run

```bash
source .venv/bin/activate
python main.py
```

## Usage

### Main window

- **Header** shows your configured callsign, name, and location.
- **Chat area** — incoming (green `[RX HH:MM:SS]`) and outgoing (blue `[TX to ...]`) messages.
- **Listen** button — toggles microphone capture and live transcription. First click triggers a Whisper model download (~250 MB) on the very first run, then it's cached.
- **Target dropdown** — pick a callsign from your contacts, or "All" for general transmission.
- **Message box + Transmit** — type and hit Enter (or click Transmit) to speak the message through Piper.
- **Pending stations bar** (between chat and input) — yellow pill buttons appear when a new GMRS callsign is detected on RX. Hover for the detected name/location preview; click to open a prefilled "Add Station" dialog.

### Settings menu

- **Configuration** — edit callsign, name, location, voice model, and input device.
- **Contacts** — table editor for known callsigns/names/locations.

## FCC Compliance Notes (GMRS, Part 95)

This software is built to make FCC Part 95 GMRS compliance easier:

- Outbound messages always carry your callsign and name when targeting a specific station.
- The 15-minute ID rule is enforced automatically — your callsign + name are appended when more than 15 minutes have passed since the last identification.
- Identification is appended even on short messages if the rule triggers.

You are still responsible for legal operation. This app does not replace a valid FCC GMRS license.

## Project structure

```
GMRS-TTY/
├── main.py                 # PySide6 app, STT worker, TTS playback, detection logic
├── requirements.txt        # Python dependencies
├── config.example.json     # Template — copy to config.json and edit
├── Voices/                 # Piper voice models (gitignored; download yourself)
├── spec.md                 # Original problem statement
├── technical_spec.md       # Detailed technical spec
├── implementation_plan.md  # Staged build plan (Stages 1–8)
└── README.md
```

## Roadmap

Tracked in [implementation_plan.md](implementation_plan.md):

1. ✅ PySide6 skeleton + config/contacts JSON
2. ✅ Piper TTS + speaker output + GMRS message formatting
3. ✅ Silero VAD + faster-whisper STT + noise reduction
4. ⚠️ Refinement (auto-scroll, device picker, timer reset) — partial
5. ⏳ Hardware hooks (`pyserial` PTT keying around TTS)
6. ⏳ Off-grid model bundling (pre-stage Whisper + Silero for air-gapped install)
7. ⏳ Cross-platform packaging (Windows installer, Linux/Pi tarballs)
8. ⏳ Multi-arch Docker image (`linux/amd64` + `linux/arm64`)

## Contributing

Issues, feature requests, and pull requests are welcome. A few ground rules:

- Keep changes focused — one concern per PR.
- Match the existing style (no comments unless the *why* is non-obvious; clear names over docstrings).
- New dependencies should be justified — this project's off-grid goal means every dep must work without internet at runtime.
- If you add functionality that affects FCC compliance behavior (callsign formatting, ID timing, etc.), call it out explicitly in the PR description.

## License

GMRS-TTY is released under the [MIT License](LICENSE).

Third-party components (Python dependencies, bundled Piper voice models, runtime-downloaded Whisper/Silero models) retain their own licenses — see [NOTICES.md](NOTICES.md) for attribution and terms. Note in particular that the `en_US-libritts-high` voice is **CC BY 4.0** and requires attribution if you redistribute it.
