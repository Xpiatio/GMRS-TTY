# GMRS-TTY

A modern TTY-style accessibility communicator for GMRS (General Mobile Radio Service) radio. Designed to let hard-of-hearing, deaf, or mute operators participate in voice radio conversations by live-transcribing incoming audio and speaking out typed messages.

Cross-platform desktop app built with **Python + PySide6**, fully offline, with FCC Part 95 ID rules built into the message flow.

## Features

### Receive (Rx)
- Live microphone capture with **Silero VAD** — only transcribes when a human is speaking; ignores static and kerchunks. VAD sensitivity is tunable in Configuration.
- **Auto-pause during TX** — listening pauses automatically while the app is transmitting so your own TTS isn't transcribed back; resumes immediately after the unkey, with VAD state reset so no in-progress speech bleeds across the boundary.
- **300–3000 Hz bandpass filter** applied per utterance — matches the narrowband-FM voice band, strips hum and out-of-band hiss before denoising.
- **Noise reduction** (spectral gating) applied per utterance after bandpass and before transcription.
- Offline transcription via **faster-whisper** (`small.en` by default, int8 CPU).
- Drops short blips (<400 ms) and common Whisper hallucinations on silence.

### Transmit (Tx)
- Offline TTS via **Piper** with local ONNX voice models.
- **Voice preview** — the Configuration dialog has a Test button next to the voice dropdown that plays a short sample so you can audition each voice before saving.
- **PTT keying** — three modes selectable in Configuration:
  - **Manual** — you key your radio yourself; the app just plays audio.
  - **VOX** — your radio auto-keys on detected audio; the app appends a short tail of silence so the last syllable survives the VOX hang dropout.
  - **USB FTDI / Serial** — the app keys PTT through a USB-serial adapter's RTS or DTR line (drives an external transistor / opto on the radio's PTT pin). Adds short lead-in/tail silence so the radio's keying ramp doesn't clip the audio.
- **FCC formatting** — automatically prepends `[Your call] [Your name] calling [Target]` when targeting a specific station.
- **15-minute ID rule** — appends your callsign + name when more than 15 minutes have passed since last identification.
- **Standalone "This is" ID button** — one-click station identification: `This is [CALL], [NATO phonetic CALL]. [name] from [location].` Resets the 15-minute ID timer.
- **Spoken-callsign formatting** — TTS reads callsign digits one at a time (`WSLZ 2 3 3` rather than "two hundred thirty-three") so the receiver hears them as letters and digits, not numbers.
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
- All STT/TTS/VAD models run locally — **no internet required at runtime**. The app never attempts a network fetch; the Whisper model is pre-staged via a one-time `bootstrap_models.py` run on a connected machine, after which the entire source tree (including `Models/` and `Voices/`) is portable to air-gapped targets.
- Future stages: multi-arch Docker image, distribution packaging.

### Accessibility (WCAG 2.1 AA)
This application exists for users with disabilities, so accessibility is a hard design constraint rather than a nice-to-have. The UI targets WCAG 2.1 Level AA — the practical baseline DOJ and Section 508 reference for software ADA compliance.
- **Color contrast** — text colors meet ≥4.5:1 against the chat background (Tailwind palette: RX `#15803D`, TX `#1D4ED8`, errors `#B91C1C`, warnings `#92400E`). UI borders (e.g. pending-station pills) meet ≥3:1.
- **State never conveyed by color alone** — every RX line is prefixed `[RX HH:MM:SS]:`, TX lines `[TX to …]:` / `[TX ID]:`, errors say "Error:" or "Failed:" in the text; color is supplemental, never the only cue.
- **Full keyboard operation** — explicit tab order (Listen → target → message → Transmit → This is). Mnemonics on every actionable label: Alt+L Listen, Alt+T Transmit, Alt+I This is, Alt+S Settings → Alt+C Configuration, Alt+N Contacts. Global shortcuts: Ctrl+L toggle Listen, Ctrl+Return/Enter Transmit, Ctrl+I send ID, Ctrl+, open Configuration, Ctrl+B open Contacts.
- **Screen reader support** — every non-decorative widget has an `accessibleName` and (where helpful) `accessibleDescription` for the Qt accessibility bridge (NVDA / JAWS / Orca / VoiceOver). Listen button's description updates with state ("currently stopped" / "currently active"). Pending-station pills announce as "Add station {CALLSIGN}".
- **Font scaling** — no hard-coded `font-size:` in stylesheets. The header bold uses `QFont` relative sizing, so the OS font-scale setting carries through.
- **Resizable, predictable layout** — main window has a 720×520 minimum so high-DPI / large-font setups don't clip. All dialogs are resizable.
- **Focus visible** — relies on the Fusion style's default focus indicator (Qt does not strip outlines; we don't either).

## Requirements

- Python 3.11+ (3.13 recommended)
- A working microphone and speaker
- Linux: PortAudio dev libs (`sudo apt install libportaudio2 portaudio19-dev`)
- ~1 GB disk for dependencies (CTranslate2, ONNX Runtime, PySide6) plus the STT model (~75 MB for `small.en`, ~150 MB for `medium.en`) fetched once via `bootstrap_models.py`

## Getting Started

Five steps from a fresh clone to a working radio session: install dependencies, drop in a Piper voice, bootstrap the STT model on an internet-connected machine, set your callsign, and run.

### 1. Install

```bash
git clone <repo-url> GMRS-TTY
cd GMRS-TTY

python3 -m venv .venv
source .venv/bin/activate              # Linux/macOS
# .venv\Scripts\activate                # Windows

pip install -r requirements.txt
```

### 2. Voice models (Piper)

Download one or more Piper ONNX voices and their accompanying `.json` config files into a `Voices/` directory at the project root:

```
Voices/
├── en_US-ryan-high.onnx
├── en_US-ryan-high.onnx.json
├── en_US-amy-medium.onnx
└── en_US-amy-medium.onnx.json
```

Voices: https://github.com/rhasspy/piper/blob/master/VOICES.md

### 3. STT model (faster-whisper)

The Whisper model is not bundled in the repo. Fetch it once on an internet-connected machine:

```bash
python bootstrap_models.py                  # default: small.en
python bootstrap_models.py --model base.en  # smaller, faster, less accurate
python bootstrap_models.py --model medium.en  # higher accuracy, slower
```

This populates `Models/STT/<model_name>/` (faster-whisper CTranslate2 artifacts). The app loads it from there on `Listen` and never attempts network access — if the directory is missing, listening fails fast with an instruction to run the bootstrap.

**For air-gapped installs:** run the bootstrap once on an internet-connected machine, then copy the entire `Models/` directory (alongside the source) to the offline target. Silero VAD and Piper voices ship as local files already, so no other fetches are involved.

### 4. Configure

```bash
cp config.example.json config.json
$EDITOR config.json    # set your callsign, name, location, and preferred voice
```

The `input_device` field is `-1` (system default) by default; the Configuration dialog in the app provides a dropdown of available input devices once you're running.

### 5. Run

```bash
source .venv/bin/activate
python main.py
```

## Usage

### Main window

- **Header** shows your configured callsign, name, and location.
- **Chat area** — incoming (green `[RX HH:MM:SS]`) and outgoing (blue `[TX to ...]`) messages.
- **Listen** button — toggles microphone capture and live transcription. Loads the bundled Whisper model from `Models/STT/<whisper_model>/` (no network); fails fast with a clear instruction if the model directory is missing.
- **Target dropdown** — pick a callsign from your contacts, or "All" for general transmission.
- **Message box + Transmit** — type and hit Enter (or click Transmit) to speak the message through Piper.
- **"This is" button** — sits under the Transmit row; sends a standalone station ID without needing to type anything.
- **Pending stations bar** (between chat and input) — yellow pill buttons appear when a new GMRS callsign is detected on RX. Hover for the detected name/location preview; click to open a prefilled "Add Station" dialog.

### Settings menu

- **Configuration** (Alt+S, Alt+C — or Ctrl+,) — edit callsign, name, location, voice model (with Test button for voice preview), input device, output device (where TTS audio plays — pick a USB sound card / Signalink / Digirig channel to feed your radio directly), VAD threshold (0.10–0.95; lower = more sensitive to weak/quiet signals, higher = stricter gating on noisy channels; default 0.5), and PTT mode. PTT options: **Manual** (you press PTT on the radio yourself), **VOX** (radio auto-keys on detected audio), or **USB FTDI / Serial** (app keys PTT via a USB-serial adapter's RTS or DTR line — when selected, Serial Port and Control Line fields enable). Changes to the input device or VAD threshold restart the listener automatically.
- **Contacts** (Alt+S, Alt+N — or Ctrl+B) — table editor for known callsigns/names/locations.

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
├── bootstrap_models.py     # One-time fetch of the faster-whisper STT model into Models/
├── requirements.txt        # Python dependencies
├── config.example.json     # Template — copy to config.json and edit
├── Voices/                 # Piper voice models (gitignored; download yourself)
├── Models/                 # Bundled STT model artifacts (gitignored; run bootstrap_models.py)
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
4. ✅ Refinement (auto-scroll, input/output device pickers, timer reset)
5. ✅ Hardware hooks (`pyserial` PTT keying around TTS — Manual / VOX / USB FTDI modes)
6. ✅ Off-grid model bundling (Whisper via `bootstrap_models.py`; Silero VAD ONNX ships in the wheel)
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
