# GMRS-TTY

A modern TTY-style accessibility communicator for GMRS (General Mobile Radio Service) radio. Designed to let hard-of-hearing, deaf, or mute operators participate in voice radio conversations by live-transcribing incoming audio and speaking out typed messages.

Cross-platform desktop app built with **Python + PySide6**, fully offline, with FCC Part 95 ID rules built into the message flow.

## Features

### Receive (Rx)
- Live microphone capture with **Silero VAD** — only transcribes when a human is speaking; ignores static and kerchunks. VAD sensitivity is tunable in Configuration. After ~30 s of continuous silence the VAD is automatically re-baselined so detection stays responsive on long-quiet channels.
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
- **TTY abbreviation expansion** — outgoing shorthand from the Corada TDD/TTY Etiquette Glossary (e.g. `GA`, `SKSK`, `ASAP`, `ILY`, `MSG`, `CUL`) is rewritten into full words before TTS speaks it, so the receiver hears "Go ahead" rather than "G A". Matching is case-insensitive and word-bounded, so it won't expand letters embedded in larger words (e.g. `Q` inside `QSO`).
- **Adjustable speech rate** — a slider in Configuration (just under the voice picker) maps to Piper's `length_scale` from `0.70×` to `1.50×`; `1.00×` is the voice's native pace, higher is slower, lower is faster. The Test button auditions the current slider value before you save.
- "All" target is transmitted as-is (no preface).

### Contact discovery
- Detects callsigns in incoming transcriptions across formats:
  - GMRS modern (`WSLZ233`), GMRS legacy (`KAE1234`), and US amateur (`K1ABC`, `KD9XYZ`, `W1AW`).
  - Compact form: `WSLZ233`
  - Spaced: `W S L Z 2 3 3`
  - With separators: `W.S.L.Z.233`, `WSLZ-233`, `WSLZ, 233`
  - NATO phonetic: `Whiskey Sierra Lima Zulu Two Three Three` (also `X-ray` / `X ray`).
- Unknown stations appear as one-click `+ Add` pills below the chat with the detected name/location pre-filled. Right-click (or long-press) a pill to dismiss it without adding the callsign, or use the **Dismiss all** button on the right edge of the pending-stations bar to clear every pending pill at once.
- **Known callsigns are pill-highlighted in the chat** — any callsign that matches an entry in Contacts is rendered with the amber pill palette (bold, amber background) wherever it appears in RX or TX lines, in any of the recognized forms (compact, spaced, NATO phonetic, hyphenated, or period/comma-separated). Hovering reveals every name (and location, when present) sharing that callsign, so family-shared GMRS calls expose all of their operators at a glance. New contacts retroactively re-highlight earlier transmissions.
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
- Linux: PortAudio dev libs (`sudo apt install libportaudio2 portaudio19-dev`). On PipeWire systems, also install `pulseaudio-utils` for the `parec` binary (`sudo apt install pulseaudio-utils`) — the app prefers it for mic capture because PortAudio's PipeWire-via-ALSA bridge can silently deliver flat-zero audio on PipeWire 1.4. If `parec` is missing the app falls back to PortAudio.
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
- **Chat area** — incoming (green `[RX HH:MM:SS]`) and outgoing (blue `[TX to ...]`) messages. Callsigns that match a saved contact are styled with an amber, bold pill; hover any pill to see every operator name (and location, if recorded) associated with that callsign.
- **Listen** button — toggles microphone capture and live transcription. Loads the bundled Whisper model from `Models/STT/<whisper_model>/` (no network); fails fast with a clear instruction if the model directory is missing.
- **Input level meter** (right of Listen) — a thin bar that shows real-time peak amplitude of the captured audio. Use it to verify your radio / cable / input device is actually wired up: if it stays at zero while you transmit into the radio, the app isn't getting audio. Stays at zero when Listen is off.
- **Target dropdown** — pick a callsign from your contacts, or "All" for general transmission. Entries are sorted alphabetically by callsign (ties broken by operator name); the "All" open-call entry is pinned at the top.
- **Message box + Transmit** — type and hit Enter (or click Transmit) to speak the message through Piper.
- **"This is" button** — sits under the Transmit row; sends a standalone station ID without needing to type anything.
- **Pending stations bar** (between chat and input) — yellow pill buttons appear when a new GMRS callsign is detected on RX. Hover for the detected name/location preview; click to open a prefilled "Add Station" dialog, or right-click / long-press to dismiss a single pill without adding the callsign. As more pills arrive, the bar wraps to additional rows up to a maximum of three; past that, a vertical scrollbar appears so the chat area doesn't get squeezed. A **Dismiss all** button (Alt+D) appears on the right whenever any pending pills are present and clears them all in one click.

### Settings menu

- **Configuration** (Alt+S, Alt+C — or Ctrl+,) — edit callsign, name, location, voice model (with Test button for voice preview), speech rate (slider mapping to Piper's `length_scale` from 0.70× to 1.50×; 1.00× is the voice's native pace, higher is slower; Test button previews at the current value), input device, output device (where TTS audio plays — pick a USB sound card / Signalink / Digirig channel to feed your radio directly), VAD threshold (0.10–0.95; lower = more sensitive to weak/quiet signals, higher = stricter gating on noisy channels; default 0.5), time format (24-hour default or 12-hour with AM/PM for RX timestamps), and PTT mode. PTT options: **Manual** (you press PTT on the radio yourself), **VOX** (radio auto-keys on detected audio), or **USB FTDI / Serial** (app keys PTT via a USB-serial adapter's RTS or DTR line — when selected, Serial Port and Control Line fields enable). Changes to the input device or VAD threshold restart the listener automatically.
- **Contacts** (Alt+S, Alt+N — or Ctrl+B) — table editor for known callsigns/names/locations. The list is sorted alphabetically by callsign whenever it loads or you save changes. A **Sort by Suffix** button (Alt+S inside the dialog) reorders the table by the last 3 digits of each callsign for visual scanning; the saved order remains alphabetical.

## FCC Compliance Notes (GMRS, Part 95)

This software is built to make FCC Part 95 GMRS compliance easier:

- Outbound messages always carry your callsign and name when targeting a specific station.
- The 15-minute ID rule is enforced automatically — your callsign + name are appended when more than 15 minutes have passed since the last identification.
- Identification is appended even on short messages if the rule triggers.

You are still responsible for legal operation. This app does not replace a valid FCC GMRS license.

## Project structure

```
GMRS-TTY/
├── main.py                 # Thin entry-point shim → gmrs_tty.app:main
├── bootstrap_models.py     # One-time fetch of the faster-whisper STT model into Models/
├── gmrs_tty/               # Application package
│   ├── app.py              # QApplication wiring
│   ├── constants.py        # WCAG palette, pill colors, config/contacts paths
│   ├── audio/              # capture (parec/PortAudio), DSP (bandpass + denoise), VAD, playback
│   ├── fcc/                # Part 95 ID-rule formatting (15-min timer, preface, standalone ID)
│   ├── persistence/        # JSON store + contact sort/sort-by-suffix
│   ├── ptt/                # PTT base + Manual / VOX / Serial implementations + factory
│   ├── stt/                # WhisperTranscriber + STTWorker orchestrator
│   ├── text/               # callsign detection, NATO/phonetics, TTY shorthand, name/location heuristics
│   ├── tts/                # Piper TTSSynthesisThread
│   └── ui/                 # MainWindow, ConfigDialog, ContactsDialog, AddContactDialog, DeviceQueryThread, FlowLayout
├── tests/                  # pytest suites covering pure logic (text/, fcc/, persistence/, ptt/, ui/)
├── requirements.txt        # Runtime Python dependencies
├── requirements-dev.txt    # pytest + pytest-cov for the test suite
├── pyproject.toml          # pytest configuration
├── config.example.json     # Template — copy to config.json and edit
├── Voices/                 # Piper voice models (gitignored; download yourself)
├── Models/                 # Bundled STT model artifacts (gitignored; run bootstrap_models.py)
├── spec.md                 # Original problem statement
├── technical_spec.md       # Detailed technical spec
├── implementation_plan.md  # Staged build plan (Stages 1–8)
└── README.md
```

## Tests

The pure-logic surface (callsign detection, NATO phonetics, TTY shorthand
expansion, FCC ID-rule formatting, contacts sorting, PTT factory) is
covered by a pytest suite that runs without Qt or audio hardware:

```bash
pip install -r requirements-dev.txt
pytest
```

UI flows (Listen toggle, Transmit, Configuration / Contacts dialogs) are
not yet automated — verify them by running the app after changes.

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
9. ⏳ Future hardware (Bluetooth HT/mobile audio, hamlib CAT/CI-V rig control)
10. ⏳ TTY-to-radio-vernacular translation at TTS time (expand `GA`/`SK`/`73`/Q-signals to spoken form on TX)
11. ⏳ AI-summarized session journal (on-device summaries via `ollama` + Gemma 3n E2B, with a date-stamped history viewer)
12. ⏳ Quick / common messages (one-click preset phrases like "Radio check", "Standing by", "QSY to channel {N}", editable per-user)

## Contributing

Issues, feature requests, and pull requests are welcome. A few ground rules:

- Keep changes focused — one concern per PR.
- Match the existing style (no comments unless the *why* is non-obvious; clear names over docstrings).
- New dependencies should be justified — this project's off-grid goal means every dep must work without internet at runtime.
- If you add functionality that affects FCC compliance behavior (callsign formatting, ID timing, etc.), call it out explicitly in the PR description.

## License

GMRS-TTY is released under the [MIT License](LICENSE).

Third-party components (Python dependencies, bundled Piper voice models, runtime-downloaded Whisper/Silero models) retain their own licenses — see [NOTICES.md](NOTICES.md) for attribution and terms. Note in particular that the `en_US-libritts-high` voice is **CC BY 4.0** and requires attribution if you redistribute it.
