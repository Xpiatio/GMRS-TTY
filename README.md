# GMRS-TTY

A modern TTY-style accessibility communicator for GMRS (General Mobile Radio Service) radio. Designed to let hard-of-hearing, deaf, or mute operators participate in voice radio conversations by live-transcribing incoming audio and speaking out typed messages.

Cross-platform desktop app built with **Python + PySide6**, fully offline, with FCC Part 95 ID rules built into the message flow.

## Features

### Receive (Rx)
- Live microphone capture with **Silero VAD** — only transcribes when a human is speaking; ignores static and kerchunks. VAD sensitivity is tunable in Configuration. After ~30 s of continuous silence the VAD is automatically re-baselined so detection stays responsive on long-quiet channels.
- **Squelch-open pre-trigger** — a peak-amplitude edge detector starts buffering audio the moment a remote operator's carrier opens (well before voice arrives), so the leading syllables of a transmission survive Silero's onset latency and reach Whisper intact. If the carrier drops without VAD ever firing — i.e., a kerchunk, accidental key, or noise burst — the buffered audio is discarded so nothing reaches the chat. When VAD does fire, the full pre-voice buffer (capped at ~2 s) is prepended to the utterance before bandpass + denoise + transcription.
- **Streaming transcription for long utterances** — speech that runs longer than ~5 s is sliced at the quietest point in the next 500 ms (so cuts land between words, not mid-syllable) and handed to a background Whisper thread; the capture loop never blocks. Partial transcripts arrive in order under a shared utterance id, and the chat renders them as a single growing line — `[RX 14:32:01]: hello bob how are you today...` — so the operator sees the transmission accumulate in real time instead of waiting for the unkey. Each partial still runs through bandpass + denoise + Whisper-hallucination filtering, and callsign-discovery scanning runs once over the full accumulated text when the final segment lands.
- **Auto-pause during TX** — listening pauses automatically while the app is transmitting so your own TTS isn't transcribed back; resumes immediately after the unkey, with VAD state reset so no in-progress speech bleeds across the boundary.
- **Listen-only / RX-only mode** — a **Listen only** toggle (Alt+O) sits beside the Listen button on the strip above the chat. When checked, every TX path is short-circuited: Transmit, **This is**, Enter-to-send on the message field, the quick-message preset buttons, and the Ctrl+Return / Ctrl+I / Alt+1…Alt+9 global shortcuts all refuse to fire (the buttons grey out to make the gate visible). Microphone capture, live transcription, callsign detection, callsigns detected, and the chat surface keep working normally. The flag persists to `config.json` under `listen_only` so an operator who finishes a session in RX-only mode comes back up the same way; toggling it back off re-enables transmission instantly.
- **YouTube Stream audio source (testing)** — select **YouTube Stream (no speakers)** in the Input Device dropdown (Configuration dialog) and paste any YouTube URL. Audio is streamed via `yt-dlp` → `ffmpeg` directly into the STT/VAD pipeline without touching any audio output device — nothing plays through speakers. The stream loops automatically when the video ends; the CDN URL is re-resolved on each restart. Requires `yt-dlp` ≥ 2026.03.17 and `ffmpeg` on PATH (the system apt package is often too old — install into the virtualenv with `pip install --upgrade yt-dlp`).
- **300–3000 Hz bandpass filter** applied per utterance — matches the narrowband-FM voice band, strips hum and out-of-band hiss before denoising.
- **Noise reduction** (spectral gating) applied per utterance after bandpass and before transcription.
- Offline transcription via **faster-whisper** (`small.en` by default, int8 CPU).
- Drops short blips (<400 ms) and common Whisper hallucinations on silence.

### Rolling RX spectrometer (waterfall)
- **Live audio waterfall** below the chat log gives the deaf/HoH operator a *visual* readout of incoming RX audio — squelch breaks, voice formants, carrier whistles, and neighbor-channel splatter become visible the moment they arrive on the channel, complementing the transcription pane. The widget runs the same audio stream that feeds VAD/STT, so there is no second capture pipeline to maintain.
- **View → Show waterfall** (Ctrl+Shift+W, default off) toggles the widget on a per-launch basis. The choice — along with color map, frequency range, and time window — persists to `config.json` under `spectrometer` so the operator's last preference comes back on the next run. The widget starts and stops alongside the **Listen** toggle, so it never spends CPU while listening is off.
- **Color map** — Viridis (perceptually uniform, colorblind-safe; default) or Grayscale (hue-free). Both are available from **View → Color map**.
- **Frequency range** — voice band (300–3400 Hz, the narrowband-FM speech window) or full Nyquist (0–8 kHz, diagnostics for splatter / intermod / carrier whistles). Pick from **View → Frequency range**.
- **Time window** — 10 / 30 / 60 second history strip; **View → Time window**.
- **VAD + squelch overlays** — vertical markers draw on the waterfall at every VAD on/off transition (white) and every squelch-open/close edge (amber) so the operator can correlate the spectrogram with the existing transcription pipeline events.
- **Performance** — the FFT runs on its own QThread at 1024-sample frames with 50 % overlap (~32 ms hop at 16 kHz) and writes one column per frame into a `QImage`. The audio tap drops oldest samples first if the consumer falls behind, so the spectrometer can never starve VAD/STT. Designed to hold under 10 % CPU on a Raspberry Pi 4 at default settings.
- **Accessibility** — the widget is *for* deaf/HoH operators, but it never becomes the only indicator of an event (the chat log still gives a non-visual fallback). `accessibleName` and `accessibleDescription` summarize the current band, window, and color map. A "describe current activity" line (e.g., "Strong signal at 1.2 kHz") echoes in the status bar so screen readers (NVDA / JAWS / Orca / VoiceOver) announce meaningful changes rather than a stream of pixel updates. Up / Down arrow keys adjust the dB ceiling, Left / Right adjust the floor — keyboard-only operators tune the contrast without leaving the main window.

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
- **TTY + radio vernacular expansion** — outgoing shorthand from the Corada TDD/TTY Etiquette Glossary (e.g. `GA`, `SKSK`, `ASAP`, `ILY`, `MSG`, `CUL`) plus the ARRL/CW radio vernacular (`73`, `88`, Q-signals `QSL`/`QSO`/`QTH`/`QRZ`/`QRM`/`QRN`/`QRT`, and CW shorthand `HW`, `OM`, `XYL`, `WX`, `TNX`, `RST`, `ES`, `FB`, `AGN`, `B4`) is rewritten into full words before TTS speaks it, so the receiver hears "Go ahead" / "best regards" rather than "G A" / "seven three". Matching is case-insensitive and word-bounded, longest-key-first, so `QSO` expands to "radio contact" while `Q` inside other words still passes through unchanged.
- **PG-13 profanity filter** — strong language (the f-word, s-word, slurs, and similar) is masked with asterisks (`shit` → `s***`) in both RX transcripts and outgoing TX messages before TTS speaks them. Mild PG-13 language (`damn`, `hell`, `crap`, bare `ass`) passes through unchanged. Word-bounded so substrings like `Scunthorpe` or `classroom` are never false-positives. Toggle in **Configuration → Filter profanity** (default on); useful for keeping the channel inside FCC Part 95 obscenity expectations.
- **Adjustable speech rate** — a slider in Configuration (just under the voice picker) maps to Piper's `length_scale` from `0.70×` to `1.50×`; `1.00×` is the voice's native pace, higher is slower, lower is faster. The Test button auditions the current slider value before you save.
- **Quick-message presets** — a configurable strip of one-click phrase buttons (seed list: `Radio check`, `Loud and clear`, `Standing by`, `Acknowledged`, `Say again`, `QSY to channel {N}`, `Clear`, `Monitoring`, `Net check-in`, `Emergency traffic`) sits between the pending-station bar and the message field. Click — or press **Alt+1** … **Alt+9** for the first nine — to transmit through the standard TX pipeline (callsign framing, 15-minute ID rule, PTT keying, STT auto-pause all still apply). Curly-brace tokens like `{N}` in `QSY to channel {N}` prompt for a value before transmitting. Edit the list (add / remove / reorder) from **Settings → Quick Messages…**; persisted to `config.json` under `quick_messages`.
- "All" target is transmitted as-is (no preface).

### Service mode (GMRS / FRS)
- **Top-of-window toggle** lets you switch between licensed GMRS and unlicensed FRS operation. The chosen mode persists in `config.json` as `radio_service` (default `GMRS`) and is reloaded on next launch.
- **FRS mode turns off every callsign-specific feature** because FRS (Part 95 Subpart B) has no callsign requirement: outgoing TX skips the operator-callsign preface and the 15-minute station-ID rule, the header replaces the callsign segment with `FRS Mode`, the target dropdown and **This is** button hide/disable, callsign detection (pending-station pills) is suppressed, callsign highlighting in the chat log is suppressed, the **Contacts** menu action disables (with a tooltip explaining why), and the online indicator + FCC callsign verification hide.
- **GMRS mode is the default** and behaves exactly as documented in the rest of this README — callsign framing, ID enforcement, contacts, verification, highlighting, and online status are all active. Switching back from FRS restores prior state instantly; saved contacts and the saved callsign are preserved across mode changes.

### Contact discovery
- Detects callsigns in incoming transcriptions across formats:
  - GMRS modern (`WSLZ233`), GMRS legacy (`KAE1234`), and US amateur (`K1ABC`, `KD9XYZ`, `W1AW`).
  - Compact form: `WSLZ233`
  - Spaced: `W S L Z 2 3 3`
  - With separators: `W.S.L.Z.233`, `WSLZ-233`, `WSLZ, 233`
  - NATO phonetic: `Whiskey Sierra Lima Zulu Two Three Three` (also `X-ray` / `X ray`).
- Unknown stations appear as one-click `+ Add` pills below the chat with the detected name/location pre-filled. The "unknown" check considers all three callsign fields on every contact (`callsign`, `gmrs_callsign`, `ham_callsign`), so a HAM call detected over the air won't pill if the operator's GMRS call is already saved (and vice versa). Right-click (or long-press) a pill to dismiss it without adding the callsign, or use the **Dismiss all** button on the right edge of the pending-stations bar to clear every pending pill at once.
- **Auto-add on FCC name match (online)** — when an unknown callsign is detected with a plausible operator name in the same transcript and the app is online, the callsign is also cross-referenced against the FCC database in the background. If the licensee name matches the spoken name, the contact is added automatically with full GMRS + HAM cross-references and a green verified check; the pending pill retires itself and a "Auto-added contact: …" line appears in the chat. Mismatches (the family-member-on-shared-call case), offline runs, transcripts without a detected name, and HTTP errors all fall back to the manual `+ Add` pill flow — nothing is added without an active FCC name match. The lookup runs on a worker thread so the UI never blocks on the API.
- **Known callsigns are pill-highlighted in the chat** — any callsign that matches an entry in Contacts is rendered with the amber pill palette (bold, amber background) wherever it appears in RX or TX lines, in any of the recognized forms (compact, spaced, NATO phonetic, hyphenated, or period/comma-separated). **Matching considers all three callsign fields on a contact** (`callsign`, `gmrs_callsign`, `ham_callsign`), so a contact whose primary is their HAM call still lights up when a remote operator addresses them by their GMRS call, and vice versa. Hovering reveals every entry sharing that callsign — each one shows name, location, and the contact's GMRS / HAM cross-references when known — so family-shared GMRS calls expose all of their operators (with each operator's individual amateur call) at a glance. New contacts retroactively re-highlight earlier transmissions.
- **Fuzzy callsign logic (opt-in)** — when the `fuzzy_callsign` toggle is on (Settings → Configuration → Fuzzy callsigns; default off), an incoming callsign that differs from a known contact by **exactly one character** (same length, same letter-or-digit shape at the differing position) is treated as a hit on that contact. The detected token is rewritten in the chat to the canonical form so the line reads as a normal pill, and the "+ Add" pending-station pill is suppressed for that near-miss. Designed for the common STT case where Whisper hears `WSLZ233` as `WSLZ234` or `WSIZ233`. Ambiguous cases — two contacts equally one character away — are left alone so the operator can resolve them manually. Toggling the flag mid-session re-scans existing chat lines and corrects past near-misses retroactively; turning it back off leaves prior rewrites in place (the canonical form is already on the screen).
- **FCC callsign verification (online, opt-in)** — when the app detects an internet connection, contacts are cross-referenced against the public FCC license database via the [ke8rxnwx crossref API](https://api.ke8rxnwx.net/crossref/). A row earns a **green ✓ in the Verified column** when (a) the callsign is in the active FCC database and (b) the contact's name matches a token in the license holder's name. Matching covers three patterns: exact tokens ("Smith" ↔ "Smith"), diminutives that are literal prefixes ("Tim" ↔ "Timothy", "Ben" ↔ "Benjamin", "Tom" ↔ "Thomas"), and non-prefix nicknames via a curated lookup table ("Dick" ↔ "Richard", "Bob" ↔ "Robert", "Bill" ↔ "William", "Jim" ↔ "James", "Jack" ↔ "John", "Peggy" ↔ "Margaret", etc. — see `gmrs_tty/text/nicknames.py` for the full table; pull requests adding more are welcome). Ambiguous nicknames ("Sandy" → Alexander or Sandra; "Pat" → Patrick or Patricia) match either canonical, on the grounds that family-shared GMRS callsigns make the gender check more trouble than it's worth. Family members on a shared GMRS callsign whose name doesn't match the licensee remain unverified — the lookup still records the licensee name in the tooltip so you can see why. Verified lookups also persist **`gmrs_callsign` and `ham_callsign` fields** on the contact entry, pulled from the FCC `related` cross-reference list (service codes `ZA` for GMRS and `HA`/`HV` for Amateur). For an operator licensed for both services, a HAM call entered as the primary will resolve its associated GMRS call (and vice versa); both are shown in the Verified cell tooltip. Cross-references are **only** written when the contact's name matches the licensee — a family-member row on a shared GMRS call (whose name doesn't match the licensee) keeps its own GMRS / HAM fields untouched, because those callsigns describe the licensee, not the family member. A verified lookup also **backfills the contact's `location` field** with the FCC city (title-cased) when the row had no location of its own; any value the operator already typed is left alone. Save and **Verify all** share the same gate: rows whose `verified` flag is True with unchanged callsign / name are treated as cached and skipped on both paths (so opening / closing Contacts doesn't churn the verified-at timestamp), while newly-added rows, in-dialog edits, and previously-failed lookups all earn a fresh FCC round trip. **Offline behavior:** the Verify all button disables, save-time verification is skipped, and previously-earned green checks are preserved untouched (a transient outage won't nuke your verified state). A live **● Online / ○ Offline** indicator sits at the far right of the top service row so you know when online features are available.
- **HAM-cross-reference deduplication** — when an existing GMRS-primary contact (callsign in the primary field, HAM listed under `ham_callsign`) ends up shadowed by a separately-saved row whose primary callsign equals that HAM call and whose operator name matches, the duplicate row is dropped at load time and at every contacts save / auto-add. Keeps roll-call surfaces (Callsigns Detected panel, target dropdown, chat tooltips) showing one row per person rather than one row per service. Family-shared GMRS callsigns are preserved — rows with the same primary callsign but different operator names never match each other's HAM cross-references and stay in place.
- Manual contact management dialog (callsign, name, location, verified status).

### Cross-platform & off-grid
- Targets Raspberry Pi, Linux, Windows.
- All STT/TTS/VAD models run locally — **the core radio workflow needs no internet at runtime**. The Whisper model is pre-staged via a one-time `bootstrap_models.py` run on a connected machine, after which the entire source tree (including `Models/` and `Voices/`) is portable to air-gapped targets.
- **Online features (FCC callsign verification) are strictly opt-in via connectivity**: a periodic probe of the crossref API decides whether they're available. If the probe fails — no network, DNS broken, API down — the relevant UI controls disable themselves and the app falls back to its fully-offline behavior. The radio workflow (RX transcription, TX synthesis, PTT keying, contact management) never depends on the network.
- Future stages: multi-arch Docker image, distribution packaging.

### Accessibility (WCAG 2.1 AA)
This application exists for users with disabilities, so accessibility is a hard design constraint rather than a nice-to-have. The UI targets WCAG 2.1 Level AA — the practical baseline DOJ and Section 508 reference for software ADA compliance.
- **Color contrast** — text colors meet ≥4.5:1 against the chat background (Tailwind palette: RX `#15803D`, TX `#1D4ED8`, errors `#B91C1C`, warnings `#92400E`). UI borders (e.g. pending-station pills) meet ≥3:1.
- **State never conveyed by color alone** — every RX line is prefixed `[RX HH:MM:SS]:`, TX lines `[TX to …]:` / `[TX ID]:`, errors say "Error:" or "Failed:" in the text; color is supplemental, never the only cue.
- **Full keyboard operation** — explicit tab order (Listen → target → message → Transmit → This is). Mnemonics on every actionable label: Alt+L Listen, Alt+O Listen only, Alt+T Transmit, Alt+I This is, Alt+S Settings → Alt+C Configuration, Alt+N Contacts. Global shortcuts: Ctrl+L toggle Listen, Ctrl+Return/Enter Transmit, Ctrl+I send ID, Ctrl+K clear chat (with confirmation), Ctrl+, open Configuration, Ctrl+B open Contacts.
- **Screen reader support** — every non-decorative widget has an `accessibleName` and (where helpful) `accessibleDescription` for the Qt accessibility bridge (NVDA / JAWS / Orca / VoiceOver). Listen button's description updates with state ("currently stopped" / "currently active"). Pending-station pills announce as "Add station {CALLSIGN}".
- **Font scaling** — no hard-coded `font-size:` in stylesheets. The header bold uses `QFont` relative sizing, so the OS font-scale setting carries through.
- **Resizable, predictable layout** — main window has a 720×520 minimum so high-DPI / large-font setups don't clip. All dialogs are resizable.
- **Focus visible** — relies on the Fusion style's default focus indicator (Qt does not strip outlines; we don't either).

## Requirements

- Python 3.11+ (3.13 recommended)
- A working microphone and speaker
- Linux: PortAudio dev libs (`sudo apt install libportaudio2 portaudio19-dev`). On PipeWire systems, also install `pulseaudio-utils` for the `parec` binary (`sudo apt install pulseaudio-utils`) — the app prefers it for mic capture because PortAudio's PipeWire-via-ALSA bridge can silently deliver flat-zero audio on PipeWire 1.4. If `parec` is missing the app falls back to PortAudio.
- ~1 GB disk for dependencies (CTranslate2, ONNX Runtime, PySide6) plus the STT model (~75 MB for `small.en`, ~150 MB for `medium.en`) fetched once via `bootstrap_models.py`
- **Optional (YouTube Stream testing only):** `ffmpeg` (`sudo apt install ffmpeg`) and `yt-dlp` ≥ 2026.03.17 (`pip install --upgrade yt-dlp` — the system apt version is typically too old for YouTube's current streaming protocol)

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

The main window is built on Qt's dockable-panel system: a movable **Service toolbar** at top, a **Chat** surface in the center, four **dockable panels** the operator can rearrange (Station, Waterfall, Pending Stations, Quick Messages), and a **Transmit** dock that stays pinned to the bottom by default but can also be moved or floated. The layout persists to `config.json` under `ui_layout` and restores on next launch. See [Customizing the layout](#customizing-the-layout) below.

- **Service toolbar** — a movable `QToolBar` carrying the `GMRS` / `FRS` radio buttons (Alt+G / Alt+F) and the four icon shortcuts on the right edge. Switching to FRS immediately disables every callsign-specific surface in the app; switching back to GMRS restores them. The selection persists to `config.json` as `radio_service`. Icon order, left-to-right: **🌙 / ☀️** toggles light/dark theme (persisted as `dark_mode`; glyph shows the *destination* state, so a moon means "click for dark"), bold **Q** opens the Quick Messages editor (Settings → Quick Messages), a **person-head icon** opens Contacts (Settings → Contacts / Ctrl+B), and a **cog wheel** opens Configuration (Settings → Configuration / Ctrl+,). Drag the toolbar's left-edge handle to move it to any of the four toolbar areas. The contacts icon disables in FRS mode alongside the menu action; theme, Q, and config stay enabled in both modes.
- **Station panel** (dock — top by default; Ctrl+Shift+S) — your configured callsign, name, and location (GMRS mode) or `FRS Mode | Operator: … | Location: …` (FRS mode). Move it to a side column to free vertical space for chat.
- **Chat surface** (center, always visible) — incoming (green `[RX HH:MM:SS]`) and outgoing (blue `[TX to ...]`) messages. Callsigns that match a saved contact are styled with an amber, bold pill; hover any pill to see every operator name (and location, if recorded) associated with that callsign. When the contact has a confirmed FCC license match, a green `✓` is rendered immediately after the callsign — same semantic as the verified column in Contacts, surfaced inline so it's visible while reading traffic (hover the check for the "FCC license verified" tooltip). The log auto-tails: new messages keep the viewport pinned to the bottom while you're caught up, but if you scroll up to re-read older context, an incoming transmission won't yank you back. A single **Listen strip** sits directly above the chat: the **Listen** toggle (Alt+L / Ctrl+L — starts mic capture + live transcription; loads the bundled Whisper model, fails fast with a clear instruction if the model directory is missing) and the **Listen only** safety toggle (Alt+O — blocks every TX path while leaving capture / transcription untouched; persisted to `config.json` under `listen_only`) on the left, a thin **input level meter** stretching across the middle (real-time peak amplitude — use it to verify your radio / cable / input device is wired up), and a **Clear chat** button on the right (mnemonic Alt+C, Alt+S → Alt+R from the Settings menu, or Ctrl+K from anywhere; erases every message after a Yes/No confirmation — chat history is in-memory only and can't be recovered once cleared). The Listen toggle and level meter live in the always-visible central widget rather than in any dock so RX feedback is reachable independent of dock state.
- **Waterfall panel** (dock — right by default; Ctrl+Shift+W toggles via View → Show waterfall) — the rolling RX spectrometer. Hidden until enabled; visibility tracks `spectrometer.enabled` in `config.json` independent of the saved layout state.
- **Pending Stations panel** (dock — bottom-left by default; Ctrl+Shift+P) — yellow pill buttons appear when a new GMRS callsign is detected on RX. Hover for the detected name/location preview; click to open a prefilled "Add Station" dialog, or right-click / long-press to dismiss a single pill without adding the callsign. As more pills arrive, the panel wraps to additional rows up to a maximum of three; past that, a vertical scrollbar appears so the chat area doesn't get squeezed. A **Dismiss all** button (Alt+D) appears on the right whenever any pending pills are present and clears them all in one click. The panel hides itself when empty so it doesn't sit on screen as titled-but-blank chrome.
- **Callsigns Detected panel** (dock — bottom, tabbed with Pending Stations; Ctrl+Shift+A toggles via View → Show callsigns detected) — a roll-call grid that records every callsign detected during the current Listen session. Columns: **Callsign | Name | Location | GMRS | HAM**. Unknown callsigns appear with only the Callsign column filled; the moment a callsign is added to (or already in) Contacts, the other four columns auto-populate from that contact entry — adding a station retroactively fills in their row. The grid is reset on every Listen on→off cycle (each new session shows only that session's callsigns) and on the panel's **Clear callsigns detected** button. Feature is fully opt-in: off by default, persisted to `config.json` under `attendance.enabled`, toggled from either **View → Show callsigns detected** or **Settings → Configuration → Callsigns Detected**. GMRS only — disabled in FRS mode along with every other callsign-dependent surface.
- **Quick Messages panel** (dock — bottom by default, tabbed with Pending Stations; Ctrl+Shift+Q) — one-click preset buttons (Alt+1 … Alt+9 fire the first nine). Empty list → the dock hides automatically.
- **Transmit panel** (dock — bottom by default; Ctrl+Shift+T) — the TX controls row: **Target dropdown** (callsign from your contacts, or "All" for general transmission), **Message box + Transmit** (type and hit Enter to speak through Piper), and **This is** (sends a standalone station ID). Family-shared GMRS callsigns appear once per operator name in the dropdown; the FCC preface speaks the exact name on the row you selected. The Listen toggle and live input-level meter were previously bundled into this dock; they now live above the chat (see the Listen strip in the chat-surface entry above). The Transmit panel is operationally critical so its **Close** affordance is disabled — it can be moved or floated, but never hidden, to keep the operator from being stranded with no TX path.
- **Online / Offline indicator** (status bar, right edge) — shows whether FCC verification is reachable. Updates every 30 seconds; hides in FRS mode where FCC lookups don't apply.

#### Customizing the layout

Drag any panel's title bar to dock it on the left, right, top, or bottom — or release it outside the main window to float it as a separate window. Tab two panels together by dropping one onto another's title bar. Resize by dragging the splitters between docked areas. Right-click a panel's title bar (or press the **Menu** key when the title bar has focus) for a keyboard-accessible **Move to Left / Right / Top / Bottom**, **Float / Re-dock**, and **Hide** menu — the keyboard path mirrors mouse drag for operators who can't drag.

Keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| Ctrl+Shift+S | Show / hide Station panel |
| Ctrl+Shift+W | Show / hide Waterfall (also from View → Show waterfall) |
| Ctrl+Shift+A | Show / hide Callsigns Detected panel (also from View → Show callsigns detected) |
| Ctrl+Shift+P | Show / hide Pending Stations panel |
| Ctrl+Shift+Q | Show / hide Quick Messages panel |
| Ctrl+Shift+T | Focus / re-show Transmit panel (Closable is off) |
| Ctrl+Shift+0 | Reset layout to default (View → Panels → Reset layout) |
| F6 / Shift+F6 | Walk keyboard focus across visible panel title bars |

The current layout (dock positions, sizes, tabs, floating state, window geometry) is captured to `config.json` under `ui_layout` on close and restored on next launch. If the saved state is missing, malformed, or from a different schema version, the default arrangement is used and re-written on next close — no user action needed. `Ctrl+Shift+0` (or View → Panels → Reset layout) snaps back to the default at any time while preserving your dark-mode and waterfall preferences.

### Settings menu

- **Configuration** (Alt+S, Alt+C — or Ctrl+,) — edit callsign, name, location, voice model (with Test button for voice preview), speech rate (slider mapping to Piper's `length_scale` from 0.70× to 1.50×; 1.00× is the voice's native pace, higher is slower; Test button previews at the current value), input device (system microphone, specific audio device, or **YouTube Stream (no speakers)** for testing — selecting YouTube reveals a URL field; audio is decoded via yt-dlp + ffmpeg, nothing plays through speakers), output device (where TTS audio plays — pick a USB sound card / Signalink / Digirig channel to feed your radio directly), VAD threshold (0.10–0.95; lower = more sensitive to weak/quiet signals, higher = stricter gating on noisy channels; default 0.5), time format (24-hour default or 12-hour with AM/PM for RX timestamps), profanity filter (PG-13 masking on RX and TX; default on), fuzzy callsigns (rewrite off-by-one detections to the nearest contact in the chat and suppress the pending-station pill; default off), callsigns detected (log every callsign heard during each Listen session; default off — also reachable from View → Show callsigns detected), and PTT mode. PTT options: **Manual** (you press PTT on the radio yourself), **VOX** (radio auto-keys on detected audio), or **USB FTDI / Serial** (app keys PTT via a USB-serial adapter's RTS or DTR line — when selected, Serial Port and Control Line fields enable). Changes to the input device or VAD threshold restart the listener automatically.
- **Contacts** (Alt+S, Alt+N — or Ctrl+B) — six-column editor: **Callsign | Name | Location | GMRS | HAM | Verified**. The GMRS and HAM columns auto-populate from FCC verification (when online) but are also hand-editable for rows you haven't verified yet; values are uppercased on save like the primary callsign. The **Verified** column shows green ✓ when the callsign is active in the FCC database and the contact's name matches the licensee. The list is sorted alphabetically by callsign whenever it loads or you save changes. A **Sort by Suffix** button (Alt+S inside the dialog) reorders the table by the last 3 digits of each callsign for visual scanning; the saved order remains alphabetical. A **Verify all** button (Alt+V) checks every not-yet-verified row against the FCC database when online (verified rows are skipped unless their callsign or name was edited in-dialog); it disables automatically when the app is offline. Saving the dialog uses the same gate as Verify all — already-verified, unedited rows are cached and skipped on save too; new rows, edits, and previously-failed lookups get a fresh FCC round trip. Offline saves keep their prior verified state.

## User manual

A full-reference user manual (29 pages, PDF) lives at
[docs/USER_MANUAL.pdf](docs/USER_MANUAL.pdf). It covers installation,
first-run configuration, every dialog, the keyboard-shortcut cheat
sheet, GMRS vs FRS behavior, PTT modes, the RX/TX pipelines, FCC
verification semantics, accessibility, off-grid operation, and the
on-disk file formats.

The PDF is regenerated from [scripts/build_user_manual.py](scripts/build_user_manual.py)
— the script holds the manual content as data so it stays in lockstep
with the codebase. To rebuild after a UI change:

```bash
python scripts/build_user_manual.py
```

## FCC Compliance Notes (GMRS, Part 95)

This software is built to make FCC Part 95 GMRS compliance easier:

- Outbound messages always carry your callsign and name when targeting a specific station.
- The 15-minute ID rule is enforced automatically — your callsign + name are appended when more than 15 minutes have passed since the last identification.
- Identification is appended even on short messages if the rule triggers.
- The PG-13 profanity filter (default on) masks strong language in both RX and TX so transmissions stay within Part 95 obscenity expectations — toggle in Configuration if you operate on a private repeater with different norms.
- **FRS mode (Subpart B) intentionally skips Part 95 Subpart A station-ID rules.** FRS is unlicensed and has no callsign requirement, so callsign framing, the 15-minute timer, and the standalone-ID button are all disabled while the top-of-window service toggle is set to FRS.

You are still responsible for legal operation. This app does not replace a valid FCC GMRS license.

## Project structure

```
GMRS-TTY/
├── main.py                 # Thin entry-point shim → gmrs_tty.app:main
├── bootstrap_models.py     # One-time fetch of the faster-whisper STT model into Models/
├── gmrs_tty/               # Application package
│   ├── app.py              # QApplication wiring
│   ├── constants.py        # WCAG palette, pill colors, config/contacts paths
│   ├── audio/              # capture (parec/PortAudio), DSP (bandpass + denoise), VAD, playback, spectrogram (FFT + ring buffer + QThread worker)
│   ├── fcc/                # Part 95 ID-rule formatting (15-min timer, preface, standalone ID) + crossref callsign verification
│   ├── net/                # Online-status probe (cached) for opt-in network features
│   ├── persistence/        # JSON store + contact sort/sort-by-suffix
│   ├── ptt/                # PTT base + Manual / VOX / Serial implementations + factory
│   ├── stt/                # WhisperTranscriber + STTWorker orchestrator
│   ├── text/               # callsign detection, NATO/phonetics, TTY shorthand, PG-13 profanity filter, name/location heuristics
│   ├── tts/                # Piper TTSSynthesisThread
│   └── ui/                 # MainWindow, ConfigDialog, ContactsDialog, AddContactDialog, DeviceQueryThread, FlowLayout, SpectrogramWidget
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
10. ✅ TTY-to-radio-vernacular translation at TTS time (expand `GA`/`SK`/`73`/Q-signals to spoken form on TX)
11. ⏳ AI-summarized session journal (on-device summaries via `ollama` + Gemma 3n E2B, with a date-stamped history viewer)
12. ✅ Quick / common messages (one-click preset phrases like "Radio check", "Standing by", "QSY to channel {N}", editable per-user)
13. ⏳ Parallel LoRa-mesh transmit (Meshtastic / Meshcore / other LoRa/Halo devices over USB or Bluetooth, fanned out alongside the GMRS voice TX)
14. ✅ Rolling audio spectrometer (live RX waterfall — visual cue for signal activity, formants, squelch breaks, and band interference for the deaf/HoH operator)

## Contributing

Issues, feature requests, and pull requests are welcome. A few ground rules:

- Keep changes focused — one concern per PR.
- Match the existing style (no comments unless the *why* is non-obvious; clear names over docstrings).
- New dependencies should be justified — this project's off-grid goal means every dep must work without internet at runtime.
- If you add functionality that affects FCC compliance behavior (callsign formatting, ID timing, etc.), call it out explicitly in the PR description.

## License

GMRS-TTY is released under the [MIT License](LICENSE).

Third-party components (Python dependencies, bundled Piper voice models, runtime-downloaded Whisper/Silero models) retain their own licenses — see [NOTICES.md](NOTICES.md) for attribution and terms. Note in particular that the `en_US-libritts-high` voice is **CC BY 4.0** and requires attribution if you redistribute it.
