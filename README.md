# GMRS-TTY

A modern TTY-style accessibility communicator for GMRS (General Mobile Radio Service) radio. Designed to let hard-of-hearing, deaf, or mute operators participate in voice radio conversations by live-transcribing incoming audio and speaking out typed messages.

Cross-platform desktop app built with **Python + PySide6**, fully offline, with FCC Part 95 ID rules built into the message flow.

## Features

### Receive (Rx)
- Live microphone capture with **Silero VAD** — only transcribes when a human is speaking; ignores static and kerchunks. VAD sensitivity is tunable in Configuration. After ~30 s of continuous silence the VAD is automatically re-baselined so detection stays responsive on long-quiet channels.
- **Squelch-open pre-trigger** — a peak-amplitude edge detector starts buffering audio the moment a remote operator's carrier opens (well before voice arrives), so the leading syllables of a transmission survive Silero's onset latency and reach Whisper intact. If the carrier drops without VAD ever firing — i.e., a kerchunk, accidental key, or noise burst — the buffered audio is discarded so nothing reaches the chat. When VAD does fire, the full pre-voice buffer (capped at ~2 s) is prepended to the utterance before bandpass + denoise + transcription.
- **Streaming transcription for long utterances** — speech that runs longer than ~5 s is sliced at the quietest point in the next 500 ms (so cuts land between words, not mid-syllable) and handed to a background Whisper thread; the capture loop never blocks. Partial transcripts arrive in order under a shared utterance id, and the chat renders them as a single growing line — `[RX 14:32:01]: hello bob how are you today...` — so the operator sees the transmission accumulate in real time instead of waiting for the unkey. Each partial still runs through bandpass + denoise + Whisper-hallucination filtering, and callsign-discovery scanning runs once over the full accumulated text when the final segment lands.
- **Auto-pause during TX** — listening pauses automatically while the app is transmitting so your own TTS isn't transcribed back; resumes immediately after the unkey, with VAD state reset so no in-progress speech bleeds across the boundary.
- **Audio monitor** — a **Monitor** toggle (Alt+M) on the listen strip routes incoming radio audio to the configured output device in real-time via a thread-safe bounded ring buffer (~1 s cap, oldest samples dropped to prevent lag). Audio is delivered unfiltered: only the necessary 16 kHz → 48 kHz polyphase upsample is applied; TX mute/unmute transitions apply a 5 ms linear fade to eliminate clicks. Lets the operator hear the raw channel audio through speakers while the app simultaneously transcribes it. Available only when **Listen-only** mode is active (so it cannot coexist with outgoing transmissions). The power-on default is persisted in `config.json` as `monitor_enabled` and toggled globally from **Settings → Configuration → Audio → Monitor audio**.
- **Listen-only / RX-only mode** — a **Listen only** toggle (Alt+O) sits beside the Listen button on the strip above the chat. When checked, every TX path is short-circuited: Transmit, **This is**, Enter-to-send on the message field, the quick-message preset buttons, and the Ctrl+Return / Ctrl+I / Alt+1…Alt+9 global shortcuts all refuse to fire (the buttons grey out to make the gate visible). Microphone capture, live transcription, callsign detection, callsigns detected, and the chat surface keep working normally. The flag persists to `config.json` under `listen_only` so an operator who finishes a session in RX-only mode comes back up the same way; toggling it back off re-enables transmission instantly.
- **System Audio Output (loopback) input source** — select **System Audio Output (loopback)** in the Input Device dropdown (Configuration dialog). The app captures whatever is playing through the selected audio output — open YouTube in a browser, play a podcast, use any media player — and feeds that audio into the STT/VAD pipeline just like a microphone. On Linux, uses `parec --device=<sink>.monitor` via PulseAudio/PipeWire; on Windows, uses WASAPI loopback via sounddevice. A **Monitor Sink** sub-dropdown appears when this mode is selected so you can target a specific output device (e.g., HDMI vs. built-in speakers); "System Default" follows whatever is set as your default playback device. No extra tools required beyond the base install.
- **300–3000 Hz bandpass filter** — applied to the live monitor stream and per utterance before denoising, matching the narrowband-FM voice band and stripping hum and out-of-band hiss.
- **Noise reduction** (spectral gating) applied per utterance after bandpass, followed by **RMS normalization to −20 dBFS** so weak or distant stations reach Whisper at a consistent level.
- Offline transcription via **faster-whisper** (`small.en` by default, int8 CPU).
- Drops short blips (<400 ms) and common Whisper hallucinations on silence.

### AI session journals
- **Generate Session Journal** (Tools menu / Ctrl+J / **Generate log entry** button on the listen strip) — sends the current conversation transcript and detected callsigns to Google Gemini 3.5 Flash, which writes an AI-generated title, a per-callsign location table (extracted from what each operator stated in the transcript), and a detailed 3–5 paragraph narrative summary. The entry is saved as a timestamped JSON file under `journals/YYYYMMDD_HHMMSS.json`. Callsigns tracked by the Callsigns Detected panel are merged into the result so no locally-observed station is silently omitted if the AI misses it. Requires a free Google Gemini API key set in Settings → Configuration → Behavior → Gemini API Key; attempting to generate without a key or with an empty transcript shows an informative prompt. Generation runs on a background thread so the UI stays live. The **Generate log entry** button on the listen strip (next to **Clear chat**) is only visible when a Gemini API key is configured.
- **View Session Journals** (Tools menu / Ctrl+Shift+J / 📓 toolbar button) — a non-modal split-pane browser listing all saved journal entries newest-first. Select any entry to view its title, export timestamp, and three sections: a **Callsigns & Locations** table (each detected callsign with the location the operator stated in the transcript, or "Not stated"), a detailed **Summary**, and the full **Transcript**. Individual entries can be permanently deleted with a confirmation prompt. The dialog can stay open while listening.

### Rolling RX spectrometer (waterfall)
- **Live audio waterfall** below the chat log gives the deaf/HoH operator a *visual* readout of incoming RX audio — squelch breaks, voice formants, carrier whistles, and neighbor-channel splatter become visible the moment they arrive on the channel, complementing the transcription pane. The widget runs the same audio stream that feeds VAD/STT, so there is no second capture pipeline to maintain.
- **View → Waterfall → Show waterfall** (Ctrl+Shift+W, default off) toggles the widget on a per-launch basis. The choice — along with color map, frequency range, and time window — persists to `config.json` under `spectrometer` so the operator's last preference comes back on the next run. The widget starts and stops alongside the **Listen** toggle, so it never spends CPU while listening is off.
- **Color map** — Viridis (perceptually uniform, colorblind-safe; default) or Grayscale (hue-free). Both are available from **View → Waterfall → Color map**.
- **Frequency range** — voice band (300–3400 Hz, the narrowband-FM speech window) or full Nyquist (0–8 kHz, diagnostics for splatter / intermod / carrier whistles). Pick from **View → Waterfall → Frequency range**.
- **Time window** — 10 / 30 / 60 second history strip; **View → Waterfall → Time window**.
- **VAD + squelch overlays** — vertical markers draw on the waterfall at every VAD on/off transition (white) and every squelch-open/close edge (amber) so the operator can correlate the spectrogram with the existing transcription pipeline events.
- **Performance** — the FFT runs on its own QThread at 1024-sample frames with 50 % overlap (~32 ms hop at 16 kHz) and writes one column per frame into a `QImage`. The audio tap drops oldest samples first if the consumer falls behind, so the spectrometer can never starve VAD/STT. Designed to hold under 10 % CPU on a Raspberry Pi 4 at default settings.
- **Accessibility** — the widget is *for* deaf/HoH operators, but it never becomes the only indicator of an event (the chat log still gives a non-visual fallback). `accessibleName` and `accessibleDescription` summarize the current band, window, and color map. A "describe current activity" line (e.g., "Strong signal at 1.2 kHz") echoes in the status bar so screen readers (NVDA / JAWS / Orca / VoiceOver) announce meaningful changes rather than a stream of pixel updates. Up / Down arrow keys adjust the dB ceiling, Left / Right adjust the floor — keyboard-only operators tune the contrast without leaving the main window.

### Transmit (Tx)
- Offline TTS via **Piper** with local ONNX voice models.
- **Voice preview** — the Voice tab of the Configuration dialog has a Test button next to the voice dropdown that plays a short sample so you can audition each voice before saving.
- **PTT keying** — three modes selectable on the PTT tab of Configuration:
  - **Manual** — you key your radio yourself; the app just plays audio.
  - **VOX** — your radio auto-keys on detected audio; the app appends a short tail of silence so the last syllable survives the VOX hang dropout.
  - **USB FTDI / Serial** — the app keys PTT through a USB-serial adapter's RTS or DTR line (drives an external transistor / opto on the radio's PTT pin). Adds short lead-in/tail silence so the radio's keying ramp doesn't clip the audio.
- **FCC formatting** — automatically prepends `[Your call] [Your name] calling [Target]` when targeting a specific station.
- **15-minute ID rule** — appends your callsign + name when more than 15 minutes have passed since last identification.
- **Standalone "This is" ID button** — one-click station identification: `This is [CALL], [NATO phonetic CALL]. [name] from [location].` Resets the 15-minute ID timer.
- **Spoken-callsign formatting** — TTS reads callsign digits one at a time (`WSLZ 2 3 3` rather than "two hundred thirty-three") so the receiver hears them as letters and digits, not numbers.
- **TTY + radio vernacular expansion** — outgoing shorthand from the Corada TDD/TTY Etiquette Glossary (e.g. `GA`, `SKSK`, `ASAP`, `ILY`, `MSG`, `CUL`) plus the ARRL/CW radio vernacular (`73`, `88`, Q-signals `QSL`/`QSO`/`QTH`/`QRZ`/`QRM`/`QRN`/`QRT`, and CW shorthand `HW`, `OM`, `XYL`, `WX`, `TNX`, `RST`, `ES`, `FB`, `AGN`, `B4`) is rewritten into full words before TTS speaks it, so the receiver hears "Go ahead" / "best regards" rather than "G A" / "seven three". Matching is case-insensitive and word-bounded, longest-key-first, so `QSO` expands to "radio contact" while `Q` inside other words still passes through unchanged.
- **PG-13 profanity filter** — strong language (the f-word, s-word, slurs, and similar) is masked with asterisks (`shit` → `s***`) in both RX transcripts and outgoing TX messages before TTS speaks them. Mild PG-13 language (`damn`, `hell`, `crap`, bare `ass`) passes through unchanged. Word-bounded so substrings like `Scunthorpe` or `classroom` are never false-positives. Toggle in **Configuration → Behavior → Filter profanity** (default on); useful for keeping the channel inside FCC Part 95 obscenity expectations.
- **Adjustable speech rate** — a slider on the Voice tab of Configuration maps to Piper's `length_scale` from `0.70×` to `1.50×`; `1.00×` is the voice's native pace, higher is slower, lower is faster. The Test button auditions the current slider value before you save.
- **Quick-message presets** — a configurable strip of one-click phrase buttons (seed list: `Radio check`, `Loud and clear`, `Standing by`, `Acknowledged`, `Say again`, `QSY to channel {N}`, `Clear`, `Monitoring`, `Net check-in`, `Emergency traffic`) sits between the pending-station bar and the message field. Click — or press **Alt+1** … **Alt+9** for the first nine — to transmit through the standard TX pipeline (callsign framing, 15-minute ID rule, PTT keying, STT auto-pause all still apply). Curly-brace tokens like `{N}` in `QSY to channel {N}` prompt for a value before transmitting. Edit the list (add / remove / reorder) from **Settings → Quick Messages…**; persisted to `config.json` under `quick_messages`.
- "All" target is transmitted as-is (no preface).

### Touch-screen mode
- **⊞ Touch toggle** on the service toolbar switches the app to a large-button, touch-optimised full-panel view. Click ⊞ to enter; click ⊟ to return to the standard desktop layout.
- The touch view shows a compact pending-stations pill row at the top, the full chat log in the centre, and two rows of large, thumb-friendly buttons at the bottom. **Row 1** (80 px tall): **Listen** (checkable) | **Listen Only** (checkable). **Row 2** (56 px tall): **Monitor** | 🌙/☀️ Theme | **Callsigns** | **Generate Log** (visible only when a Gemini API key is configured) | **View Logs**.
- A **▼ scroll-to-bottom button** (56×56 px, round) overlays the bottom-right corner of the chat area whenever you've scrolled up from the latest message. Tapping it jumps back to the bottom. It disappears automatically when the log is already at the newest line.
- Pending-station **`+ Add` pills** are larger in touch mode — bolder text, extra padding, and 44 px minimum height — so they're easy to tap accurately.
- Tapping **Callsigns** in touch mode floats the Callsigns Detected dock as an overlay without leaving touch mode. The **Remove selected** and **Clear callsigns detected** buttons inside that panel also scale to 44 px minimum height for reliable touch targets.
- All dock panels (Station, Waterfall, Pending Stations, Quick Messages, Transmit) are automatically hidden when entering touch mode and restored to their previous positions and visibility on exit — the desktop layout is preserved.
- The chat log, incoming transcriptions, TX messages, and callsign highlighting stay in sync between the touch and normal views; switching modes never drops a message.
- The preference persists to `config.json` as `touch_mode` so operators who leave the app in touch mode come back to the touch view on the next launch. Works in both GMRS and FRS modes.

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
- Unknown stations appear as one-click `+ Add` pills below the chat with the detected name/location pre-filled. The "unknown" check considers all three callsign fields on every contact (`callsign`, `gmrs_callsign`, `ham_callsign`), so a HAM call detected over the air won't pill if the operator's GMRS call is already saved (and vice versa). Right-click (or long-press) a pill to dismiss it without adding the callsign, or use the **Dismiss all** button on the right edge of the pending-stations bar to clear every pending pill at once. The Add Station dialog has a **Look Up** button (Alt+U) next to the Callsign field — clicking it queries the FCC database on a background thread and pre-fills any empty Name or Location fields from the license record. Works with callsign-only, callsign + name, or callsign + location depending on what's already in the form. Shows a status line indicating whether the callsign was verified, found with a name mismatch, or not found. Disabled when offline.
- **Auto-add on FCC name match (online)** — when an unknown callsign is detected with a plausible operator name in the same transcript and the app is online, the callsign is also cross-referenced against the FCC database in the background. If the licensee name matches the spoken name, the contact is added automatically with full GMRS + HAM cross-references and a green verified check; the pending pill retires itself and a "Auto-added contact: …" line appears in the chat. Mismatches (the family-member-on-shared-call case), offline runs, transcripts without a detected name, and HTTP errors all fall back to the manual `+ Add` pill flow — nothing is added without an active FCC name match. The lookup runs on a worker thread so the UI never blocks on the API.
- **Known callsigns are pill-highlighted in the chat** — any callsign that matches an entry in Contacts is rendered with the amber pill palette (bold, amber background) wherever it appears in RX or TX lines, in any of the recognized forms (compact, spaced, NATO phonetic, hyphenated, or period/comma-separated). **Matching considers all three callsign fields on a contact** (`callsign`, `gmrs_callsign`, `ham_callsign`), so a contact whose primary is their HAM call still lights up when a remote operator addresses them by their GMRS call, and vice versa. Hovering reveals every entry sharing that callsign — each one shows name, location, and the contact's GMRS / HAM cross-references when known — so family-shared GMRS calls expose all of their operators (with each operator's individual amateur call) at a glance. New contacts retroactively re-highlight earlier transmissions.
- **Fuzzy callsign logic (opt-in)** — when the `fuzzy_callsign` toggle is on (Settings → Configuration → Behavior → Fuzzy callsigns; default off), an incoming callsign that differs from a known contact by **exactly one character** (same length, same letter-or-digit shape at the differing position) is treated as a hit on that contact. The detected token is rewritten in the chat to the canonical form so the line reads as a normal pill, and the "+ Add" pending-station pill is suppressed for that near-miss. Designed for the common STT case where Whisper hears `WSLZ233` as `WSLZ234` or `WSIZ233`. Ambiguous cases — two contacts equally one character away — are left alone so the operator can resolve them manually. Toggling the flag mid-session re-scans existing chat lines and corrects past near-misses retroactively; turning it back off leaves prior rewrites in place (the canonical form is already on the screen).
- **FCC callsign verification (online, opt-in)** — when the app detects an internet connection, contacts are cross-referenced against the public FCC license database via the [ke8rxnwx crossref API](https://api.ke8rxnwx.net/crossref/). A row earns a **green ✓ in the Verified column** when (a) the callsign is in the active FCC database and (b) the contact's name matches a token in the license holder's name. Matching covers three patterns: exact tokens ("Smith" ↔ "Smith"), diminutives that are literal prefixes ("Tim" ↔ "Timothy", "Ben" ↔ "Benjamin", "Tom" ↔ "Thomas"), and non-prefix nicknames via a curated lookup table ("Dick" ↔ "Richard", "Bob" ↔ "Robert", "Bill" ↔ "William", "Jim" ↔ "James", "Jack" ↔ "John", "Peggy" ↔ "Margaret", etc. — see `gmrs_tty/text/nicknames.py` for the full table; pull requests adding more are welcome). Ambiguous nicknames ("Sandy" → Alexander or Sandra; "Pat" → Patrick or Patricia) match either canonical, on the grounds that family-shared GMRS callsigns make the gender check more trouble than it's worth. Family members on a shared GMRS callsign whose name doesn't match the licensee remain unverified — the lookup still records the licensee name in the tooltip so you can see why. Verified lookups also persist **`gmrs_callsign` and `ham_callsign` fields** on the contact entry, pulled from the FCC `related` cross-reference list (service codes `ZA` for GMRS and `HA`/`HV` for Amateur). For an operator licensed for both services, a HAM call entered as the primary will resolve its associated GMRS call (and vice versa); both are shown in the Verified cell tooltip. Cross-references are **only** written when the contact's name matches the licensee — a family-member row on a shared GMRS call (whose name doesn't match the licensee) keeps its own GMRS / HAM fields untouched, because those callsigns describe the licensee, not the family member. A verified lookup also **backfills the contact's `location` field** with the FCC city (title-cased) when the row had no location of its own; any value the operator already typed is left alone. Save and **Verify all** share the same gate: rows whose `verified` flag is True with unchanged callsign / name are treated as cached and skipped on both paths (so opening / closing Contacts doesn't churn the verified-at timestamp), while newly-added rows, in-dialog edits, and previously-failed lookups all earn a fresh FCC round trip. **Offline behavior:** the Verify all button disables, save-time verification is skipped, and previously-earned green checks are preserved untouched (a transient outage won't nuke your verified state). A live **● Online / ○ Offline** indicator sits at the far right of the top service row so you know when online features are available.
- **HAM-cross-reference deduplication** — when an existing GMRS-primary contact (callsign in the primary field, HAM listed under `ham_callsign`) ends up shadowed by a separately-saved row whose primary callsign equals that HAM call and whose operator name matches, the duplicate row is dropped at load time and at every contacts save / auto-add. Keeps roll-call surfaces (Callsigns Detected panel, target dropdown, chat tooltips) showing one row per person rather than one row per service. Family-shared GMRS callsigns are preserved — rows with the same primary callsign but different operator names never match each other's HAM cross-references and stay in place.
- Manual contact management dialog (callsign, name, location, verified status).

### Cross-platform & off-grid
- Targets Raspberry Pi and Linux.
- All STT/TTS/VAD models run locally — **the core radio workflow needs no internet at runtime**. The Whisper model is pre-staged via a one-time `bootstrap_models.py` run on a connected machine, after which the entire source tree (including `Models/` and `Voices/`) is portable to air-gapped targets.
- **Online features (FCC callsign verification) are strictly opt-in via connectivity**: a periodic probe of the crossref API decides whether they're available. If the probe fails — no network, DNS broken, API down — the relevant UI controls disable themselves and the app falls back to its fully-offline behavior. The radio workflow (RX transcription, TX synthesis, PTT keying, contact management) never depends on the network.
- **Debian/Ubuntu**: self-contained `.deb` built by `scripts/build-deb.sh` (bundles all Python wheels + offline models; requires Python 3.13 on target).
- Future stages: multi-arch Docker image, Raspberry Pi tarball.

### Accessibility (WCAG 2.1 AA)
This application exists for users with disabilities, so accessibility is a hard design constraint rather than a nice-to-have. The UI targets WCAG 2.1 Level AA — the practical baseline DOJ and Section 508 reference for software ADA compliance.
- **Color contrast** — text colors meet ≥4.5:1 against the chat background (Tailwind palette: RX `#15803D`, TX `#1D4ED8`, errors `#B91C1C`, warnings `#92400E`). UI borders (e.g. pending-station pills) meet ≥3:1.
- **State never conveyed by color alone** — every RX line is prefixed `[RX HH:MM:SS]:`, TX lines `[TX to …]:` / `[TX ID]:`, errors say "Error:" or "Failed:" in the text; color is supplemental, never the only cue.
- **Full keyboard operation** — explicit tab order (Listen → target → message → Transmit → This is). Mnemonics on every actionable label: Alt+L Listen, Alt+O Listen only, Alt+M Monitor, Alt+T Transmit, Alt+I This is, Alt+S Settings → Alt+C Configuration, Alt+N Contacts. Global shortcuts: Ctrl+L toggle Listen, Ctrl+Return/Enter Transmit, Ctrl+I send ID, Ctrl+K clear chat (with confirmation — also Tools → Clear Chat), Ctrl+, open Configuration, Ctrl+B open Contacts.
- **Screen reader support** — every non-decorative widget has an `accessibleName` and (where helpful) `accessibleDescription` for the Qt accessibility bridge (NVDA / JAWS / Orca / VoiceOver). Listen button's description updates with state ("currently stopped" / "currently active"). Pending-station pills announce as "Add station {CALLSIGN}".
- **Font scaling** — no hard-coded `font-size:` in stylesheets. The header bold uses `QFont` relative sizing, so the OS font-scale setting carries through.
- **Resizable, predictable layout** — main window has a 720×520 minimum so high-DPI / large-font setups don't clip. All dialogs are resizable.
- **Focus visible** — relies on the Fusion style's default focus indicator (Qt does not strip outlines; we don't either).

## Requirements

**Pre-built installers** (see below) bundle Python, all dependencies, and offline STT models — no separate Python install or pip commands needed.

**From source:**
- Python 3.11+ (3.13 recommended)
- A working microphone and speaker
- Linux: PortAudio dev libs (`sudo apt install libportaudio2 portaudio19-dev`). On PipeWire/PulseAudio systems, also install `pulseaudio-utils` (`sudo apt install pulseaudio-utils`) — provides `parec` and `pactl`, which the app uses for both microphone capture (preferred over PortAudio's PipeWire-via-ALSA bridge, which can silently deliver flat-zero audio on PipeWire 1.4) and System Audio Output (loopback) mode. Without it the app falls back to PortAudio for mic capture; loopback mode requires it on Linux.
- ~1 GB disk for dependencies (CTranslate2, ONNX Runtime, PySide6) plus the STT model (~75 MB for `small.en`, ~150 MB for `medium.en`) fetched once via `bootstrap_models.py`

## Installing a pre-built package

The pre-built installers bundle Python, all Python wheels, and the offline Whisper STT + speaker ID models. No internet needed after download.

### Debian / Ubuntu (`.deb`)

Built by `scripts/build-deb.sh` (x86-64, Python 3.13, all wheels bundled offline).

**Supported platforms:**

| Platform | Python 3.13 source | Install method |
|----------|--------------------|----------------|
| Debian 13 (trixie) / LMDE 7 | native in apt | direct `apt install` |
| Ubuntu 24.10+ (oracular, plucky, …) | native in apt | direct `apt install` |
| Ubuntu 22.04 (jammy) / 24.04 (noble) | deadsnakes PPA | `install.sh` |
| Linux Mint 21 / 22 | deadsnakes PPA | `install.sh` |
| Pop!_OS 22.04 / 24.04 | deadsnakes PPA | `install.sh` |
| Debian 12 (bookworm) | not available | build from source |
| Ubuntu 20.04 (focal) | not available | build from source |

**Debian 13 / LMDE 7 / Ubuntu 24.10+ — direct install:**

```bash
sudo apt install ./gmrs-tty_0.0.1_amd64.deb
gmrs-tty
```

**Ubuntu 22.04 / 24.04 / Mint 21–22 / Pop!_OS — use the install script:**

```bash
# Place install.sh in the same directory as the .deb, then:
sudo bash install.sh
# or with an explicit path:
sudo bash install.sh ./gmrs-tty_0.0.1_amd64.deb
```

`install.sh` is included on the release page alongside the `.deb`. It adds the
[deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) to get
`python3.13`, installs required system libraries, then runs the `.deb` installer.

The postinst creates a virtualenv at `/opt/gmrs-tty/.venv`, installs all bundled wheels offline, and seeds an initial `config.json`. Open **Settings → Configuration** to set your callsign, name, location, and Piper TTS voice.

System dependencies installed automatically: `python3.13`, `python3.13-venv`, `libportaudio2`, `libxcb-cursor0`, `libegl1`, `libgl1`.

### Adding Piper TTS voices

The installers do **not** bundle Piper voice models — they are large, numerous, and user-chosen. Drop `.onnx` + `.onnx.json` pairs into the `Voices/` subdirectory of the install location:

| Platform | Location |
|----------|----------|
| Linux (.deb) | `/opt/gmrs-tty/Voices/` |

Download voices from: https://github.com/rhasspy/piper/blob/master/VOICES.md

---

## Getting Started (from source)

Five steps from a fresh clone to a working radio session: install dependencies, drop in a Piper voice, bootstrap the STT model on an internet-connected machine, set your callsign, and run.

### 1. Install

```bash
git clone <repo-url> GMRS-TTY
cd GMRS-TTY

python3 -m venv .venv
source .venv/bin/activate

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

- **Service toolbar** — a movable `QToolBar` carrying the `GMRS` / `FRS` radio buttons (Alt+G / Alt+F) and the six icon shortcuts on the right edge. Switching to FRS immediately disables every callsign-specific surface in the app; switching back to GMRS restores them. The selection persists to `config.json` as `radio_service`. Icon order, left-to-right: **⊞ / ⊟** toggles touch-screen mode (persisted as `touch_mode`; ⊞ enters touch view, ⊟ exits), **🌙 / ☀️** toggles light/dark theme (persisted as `dark_mode`; glyph shows the *destination* state, so a moon means "click for dark"), bold **Q** opens the Quick Messages editor (Settings → Quick Messages), a **person-head icon** opens Contacts (Settings → Contacts / Ctrl+B), a **📓 notebook icon** opens the Session Journals browser (same as Tools → View Session Journals / Ctrl+Shift+J), and a **cog wheel** opens Configuration (Settings → Configuration / Ctrl+,). Drag the toolbar's left-edge handle to move it to any of the four toolbar areas. The contacts icon disables in FRS mode alongside the menu action; touch, theme, Q, journal, and config stay enabled in both modes.
- **Station panel** (dock — top by default; Ctrl+Shift+S) — your configured callsign, name, and location (GMRS mode) or `FRS Mode | Operator: … | Location: …` (FRS mode). Move it to a side column to free vertical space for chat.
- **Chat surface** (center, always visible) — incoming (green `[RX HH:MM:SS]`) and outgoing (blue `[TX to ...]`) messages. Callsigns that match a saved contact are styled with an amber, bold pill; hover any pill to see every operator name (and location, if recorded) associated with that callsign. When the contact has a confirmed FCC license match, a green `✓` is rendered immediately after the callsign — same semantic as the verified column in Contacts, surfaced inline so it's visible while reading traffic (hover the check for the "FCC license verified" tooltip). The log auto-tails: new messages keep the viewport pinned to the bottom while you're caught up, but if you scroll up to re-read older context, an incoming transmission won't yank you back. A single **Listen strip** sits directly above the chat: the **Listen** toggle (Alt+L / Ctrl+L — starts mic capture + live transcription; fills green when active), the **Listen only** safety toggle (Alt+O — blocks every TX path while leaving capture / transcription untouched; fills amber when on; persisted to `config.json` under `listen_only`), a small gap, and the **Monitor** toggle (Alt+M — routes incoming radio audio unfiltered to the output device in real-time; fills blue when on; available only when Listen-only is active; persisted as `monitor_enabled`) on the left; a thin **input level meter** stretching across the middle (real-time peak amplitude — use it to verify your radio / cable / input device is wired up); a **Clear chat** button (Ctrl+K from anywhere or Tools → Clear Chat; erases every message after a Yes/No confirmation — chat history is in-memory only and can't be recovered once cleared); and — when a Gemini API key is configured — a **Generate log entry** button that triggers **Tools → Generate Session Journal** (Ctrl+J) on the right. The three toggle buttons use a ghost-to-filled visual: unlit = transparent with a muted border; active = solid role color with inverted text, so state is unambiguous at a glance. The Listen toggle and level meter live in the always-visible central widget rather than in any dock so RX feedback is reachable independent of dock state.
- **Waterfall panel** (dock — right by default; Ctrl+Shift+W toggles via View → Show waterfall) — the rolling RX spectrometer. Hidden until enabled; visibility tracks `spectrometer.enabled` in `config.json` independent of the saved layout state.
- **Pending Stations panel** (dock — bottom-left by default; Ctrl+Shift+P) — yellow pill buttons appear when a new GMRS callsign is detected on RX. Hover for the detected name/location preview; click to open a prefilled "Add Station" dialog, or right-click / long-press to dismiss a single pill without adding the callsign. As more pills arrive, the panel wraps to additional rows up to a maximum of three; past that, a vertical scrollbar appears so the chat area doesn't get squeezed. A **Dismiss all** button (Alt+D) appears on the right whenever any pending pills are present and clears them all in one click. The panel hides itself when empty so it doesn't sit on screen as titled-but-blank chrome.
- **Callsigns Detected panel** (dock — bottom, tabbed with Pending Stations; Ctrl+Shift+A toggles via View → Show callsigns detected) — a roll-call grid that records every callsign detected during the current Listen session. Columns: **Callsign | Name | Location | GMRS | HAM**. Unknown callsigns appear with only the Callsign column filled; the moment a callsign is added to (or already in) Contacts, the other four columns auto-populate from that contact entry — adding a station retroactively fills in their row. The list **persists across Listen on/off cycles** — toggling Listen does not reset the grid, so callsigns accumulate across the whole operating session. To remove a single entry without touching Contacts, select its row and click **Remove selected** or right-click and choose **Remove … from session**. The panel's **Clear callsigns detected** button empties the entire list. Feature is fully opt-in: off by default, persisted to `config.json` under `attendance.enabled`, toggled from either **View → Show callsigns detected** or **Settings → Configuration → Behavior → Callsigns Detected**. GMRS only — disabled in FRS mode along with every other callsign-dependent surface.
- **Quick Messages panel** (dock — bottom by default, tabbed with Pending Stations; Ctrl+Shift+Q) — one-click preset buttons (Alt+1 … Alt+9 fire the first nine). Empty list → the dock hides automatically.
- **Transmit panel** (dock — bottom by default; Ctrl+Shift+T) — the TX controls row: **Target dropdown** (callsign from your contacts, or "All" for general transmission), **Message box + Transmit** (type and hit Enter to speak through Piper), and **This is** (sends a standalone station ID). Family-shared GMRS callsigns appear once per operator name in the dropdown; the FCC preface speaks the exact name on the row you selected. The Listen toggle and live input-level meter were previously bundled into this dock; they now live above the chat (see the Listen strip in the chat-surface entry above). The Transmit panel is operationally critical so its **Close** affordance is disabled — it can be moved or floated, but never hidden, to keep the operator from being stranded with no TX path.
- **Online / Offline indicator** (status bar, right edge) — shows whether FCC verification is reachable. Updates every 30 seconds; hides in FRS mode where FCC lookups don't apply.

#### Customizing the layout

Drag any panel's title bar to dock it on the left, right, top, or bottom — or release it outside the main window to float it as a separate window. Tab two panels together by dropping one onto another's title bar. Resize by dragging the splitters between docked areas. Right-click a panel's title bar (or press the **Menu** key when the title bar has focus) for a keyboard-accessible **Move to Left / Right / Top / Bottom**, **Float / Re-dock**, and **Hide** menu — the keyboard path mirrors mouse drag for operators who can't drag.

Keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| Ctrl+Shift+S | Show / hide Station panel |
| Ctrl+Shift+W | Show / hide Waterfall (also from View → Waterfall → Show waterfall) |
| Ctrl+Shift+A | Show / hide Callsigns Detected panel (also from View → Show callsigns detected) |
| Ctrl+Shift+P | Show / hide Pending Stations panel |
| Ctrl+Shift+Q | Show / hide Quick Messages panel |
| Ctrl+Shift+T | Focus / re-show Transmit panel (Closable is off) |
| Ctrl+Shift+0 | Reset layout to default (View → Panels → Reset layout) |
| F6 / Shift+F6 | Walk keyboard focus across visible panel title bars |

The current layout (dock positions, sizes, tabs, floating state, window geometry) is captured to `config.json` under `ui_layout` on close and restored on next launch. If the saved state is missing, malformed, or from a different schema version, the default arrangement is used and re-written on next close — no user action needed. `Ctrl+Shift+0` (or View → Panels → Reset layout) snaps back to the default at any time while preserving your dark-mode and waterfall preferences.

### Tools menu

- **Generate Session Journal…** (Ctrl+J / **Generate log entry** button on the listen strip) — sends the current transcript and detected callsigns to Gemini and saves the AI-generated journal entry to `journals/`. The saved entry includes a per-callsign locations table, a detailed summary, and the full transcript. Requires a Gemini API key configured in Settings → Configuration. Disabled with an informative prompt if the key is missing or the chat is empty.
- **View Session Journals…** (Ctrl+Shift+J) — opens the non-modal journal browser. Same destination as the 📓 toolbar button.
- **Clear Chat** (Ctrl+K) — erases every message from the conversation log after a Yes/No confirmation. Chat history is in-memory only and cannot be recovered once cleared.

### Settings menu

Settings contains persistent configuration only — nothing destructive.

- **Configuration** (Alt+S, Alt+C — or Ctrl+,) — five-tab dialog for all persistent settings. OK is disabled until device enumeration finishes.
  - **Identity** — Callsign, Name, Location: used in callsign preface, station-ID announcements, and the Station panel.
  - **Audio** — Input Device (system mic, specific device, or **System Audio Output (loopback)** — selecting loopback reveals a Monitor Sink dropdown to target a specific output; play audio in any browser or media player and the app transcribes it), Output Device (where TTS audio plays — pick a USB sound card / Signalink / Digirig channel to feed your radio directly), Monitor audio (checkbox: whether the Monitor toggle activates automatically when Listen-only mode starts; default off), VAD Threshold (0.10–0.95; lower = more sensitive to weak/quiet signals, higher = stricter; default 0.5). Changes to the input device or VAD threshold restart the listener automatically.
  - **Voice** — Voice Model (dropdown of `.onnx` files in `Voices/`) with a **Test** button that auditions the current voice at the current speech rate. Speech Rate slider maps to Piper's `length_scale` from 0.70× to 1.50×; 1.00× is native pace, higher is slower, lower is faster.
  - **PTT** — PTT Mode: **Manual** (you press PTT on the radio yourself), **VOX** (radio auto-keys on detected audio), or **USB FTDI / Serial** (app keys PTT via a USB-serial adapter's RTS or DTR line — when selected, Serial Port and Control Line fields enable).
  - **Behavior** — Time Format (24-hour default or 12-hour with AM/PM for RX timestamps), Filter profanity (PG-13 masking on RX and TX; default on), Fuzzy callsigns (rewrite off-by-one detections to the nearest contact and suppress the pending-station pill; default off), Callsigns Detected (log every callsign heard per Listen session; default off — also reachable from View → Show callsigns detected), **Gemini API Key** (password field with Show/Hide toggle — leave blank to disable session journal generation; obtain a free key at https://aistudio.google.com/app/apikey).
- **Contacts** (Alt+S, Alt+N — or Ctrl+B) — six-column editor: **Callsign | Name | Location | GMRS | HAM | Verified**. The GMRS and HAM columns auto-populate from FCC verification (when online) but are also hand-editable for rows you haven't verified yet; values are uppercased on save like the primary callsign. The **Verified** column shows green ✓ when the callsign is active in the FCC database and the contact's name matches the licensee. The list is sorted alphabetically by callsign whenever it loads or you save changes. A **Sort by Suffix** button (Alt+S inside the dialog) reorders the table by the last 3 digits of each callsign for visual scanning; the saved order remains alphabetical. A **Verify all** button (Alt+V) checks every not-yet-verified row against the FCC database when online (verified rows are skipped unless their callsign or name was edited in-dialog); it disables automatically when the app is offline. Saving the dialog uses the same gate as Verify all — already-verified, unedited rows are cached and skipped on save too; new rows, edits, and previously-failed lookups get a fresh FCC round trip. Offline saves keep their prior verified state. **Import…** (Alt+I) and **Export…** (Alt+X) buttons let you share contacts between instances or back them up: **JSON** preserves all fields including FCC-verified metadata for a lossless round-trip; **CSV** exports the five user-editable columns (Callsign, Name, Location, GMRS, HAM) for editing in a spreadsheet. Import merges incoming contacts into the current list — existing entries (matched by callsign + name) are updated with any non-blank fields from the file while their verification metadata is preserved; new callsigns are appended.

## User manual

A full-reference user manual (29 pages, PDF) lives at
[docs/USER_MANUAL.pdf](docs/USER_MANUAL.pdf). It covers installation,
first-run configuration, every dialog, the keyboard-shortcut cheat
sheet, GMRS vs FRS behavior, PTT modes, the RX/TX pipelines, FCC
verification semantics, accessibility, off-grid operation, on-disk file
formats, and the AI session journal feature (powered by Google Gemini
3.5 Flash).

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
│   ├── ai/                 # Gemini REST client (stdlib urllib) + JournalWorker QThread
│   ├── audio/              # capture (parec/PortAudio), DSP (bandpass + denoise), VAD, playback, spectrogram (FFT + ring buffer + QThread worker)
│   ├── fcc/                # Part 95 ID-rule formatting (15-min timer, preface, standalone ID) + crossref callsign verification
│   ├── net/                # Online-status probe (cached) for opt-in network features
│   ├── persistence/        # JSON store + contact sort/sort-by-suffix + journal save/load/delete
│   ├── ptt/                # PTT base + Manual / VOX / Serial implementations + factory
│   ├── stt/                # WhisperTranscriber + STTWorker orchestrator
│   ├── text/               # callsign detection, NATO/phonetics, TTY shorthand, PG-13 profanity filter, name/location heuristics
│   ├── tts/                # Piper TTSSynthesisThread
│   └── ui/                 # MainWindow, ConfigDialog, ContactsDialog, AddContactDialog, JournalDialog, DeviceQueryThread, FlowLayout, SpectrogramWidget
├── tests/                  # pytest suites covering pure logic (text/, fcc/, persistence/, ptt/, ui/)
├── requirements.txt        # Runtime Python dependencies
├── requirements-dev.txt    # pytest + pytest-cov for the test suite
├── pyproject.toml          # pytest configuration
├── config.example.json     # Template — copy to config.json and edit
├── scripts/
│   ├── build-deb.sh        # Build the Debian .deb installer
│   └── build_user_manual.py # Regenerate docs/USER_MANUAL.pdf
├── journals/               # AI-generated session journal entries (auto-created; gitignored)
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

- Multi-arch Docker image (`linux/amd64` + `linux/arm64`)
- Parallel LoRa-mesh transmit (Meshtastic / Meshcore / other LoRa/Halo devices over USB or Bluetooth, fanned out alongside the GMRS voice TX)
- Future hardware (Bluetooth HT/mobile audio, hamlib CAT/CI-V rig control)

## Contributing

Issues, feature requests, and pull requests are welcome. A few ground rules:

- Keep changes focused — one concern per PR.
- Match the existing style (no comments unless the *why* is non-obvious; clear names over docstrings).
- New dependencies should be justified — this project's off-grid goal means every dep must work without internet at runtime.
- If you add functionality that affects FCC compliance behavior (callsign formatting, ID timing, etc.), call it out explicitly in the PR description.

## License

GMRS-TTY is released under the [MIT License](LICENSE).

Third-party components (Python dependencies, bundled Piper voice models, runtime-downloaded Whisper/Silero models) retain their own licenses — see [NOTICES.md](NOTICES.md) for attribution and terms. Note in particular that the `en_US-libritts-high` voice is **CC BY 4.0** and requires attribution if you redistribute it.
