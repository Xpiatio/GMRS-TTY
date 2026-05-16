# GMRS-TTY Staged Implementation Plan

Status legend: ✅ complete · ⏳ pending

## Stage 1: Foundation and PySide6 UI Skeleton — ✅ complete
*   **Goal:** Establish the project layout, basic UI, and configuration management.
*   **Tasks:**
    *   ✅ Set up a Python virtual environment and `requirements.txt` (installing `PySide6`).
    *   ✅ Create the main dashboard layout: a header for personal info, a readonly text area for incoming messages (chat room), and an input line with a transmit button for outgoing messages.
    *   ✅ Create the JSON reading/writing module for the configuration page and populate the UI from `config.json` on boot.
    *   ✅ Implement the Contact Management dropdown and manual editing via a secondary window, saving to `contacts.json`.

## Stage 2: Piper TTS & Output Audio Engine — ✅ complete
*   **Goal:** Enable the app to speak the typed messages aloud using Piper.
*   **Tasks:**
    *   ✅ Local `Voices/` directory with Piper ONNX voice models + `.json` configs (gitignored; user-supplied).
    *   ✅ `piper-tts` Python integration; sentence-wise synthesis in the main thread, concatenated chunks played in an `AudioPlayerThread`.
    *   ✅ GMRS formatting on outgoing text: prepend `[My Call] [My Name] calling [Target] [Target Name]`, with `datetime`-based 15-minute FCC ID rule appending sign-off when due.
    *   ✅ Routing via `sounddevice`, with output-device selection separate from input.
    *   ✅ Beyond original plan: callsign digit-spelling for TTS (`233` → `2 3 3`); NATO phonetic readout for the standalone ID button; voice preview Test button in the Configuration dialog.

## Stage 3: Offline STT & Input Audio Engine — ✅ complete
*   **Goal:** Listen to the configured input device and automatically transcribe it to the chat window.
*   **Tasks:**
    *   ✅ STT via `faster-whisper` (CTranslate2 backend, `compute_type="int8"`, configurable variant; default `small.en`).
    *   ✅ Continuous background audio capture via `sounddevice.InputStream` at 16 kHz / 512-sample chunks.
    *   ✅ `STTWorker` is a background `QThread`; transcribed utterances ride a Qt signal as `RxUtterance` payloads (text + duration + optional embedding).
    *   ✅ Silero VAD gating with tunable threshold (0.10–0.95, default 0.5), 10-chunk (~320 ms) pre-buffer, min-speech-duration drop (< 0.4 s), and Whisper-hallucination filtering on silence.
    *   ✅ Per-utterance DSP: 4th-order 300–3000 Hz Butterworth bandpass (narrowband-FM voice band) + `noisereduce` spectral gating before transcription.
    *   ✅ Auto-pause STT during TX so the app doesn't transcribe its own TTS; VAD state resets on resume.

## Stage 4: Refinement and State Management — ✅ complete
*   **Goal:** Tighten the user experience and verify logic.
*   **Tasks:**
    *   ✅ Auto-scrolling chat view (`QTextBrowser` append).
    *   ✅ 15-minute callsign rule resets on every transmission that contains a callsign (prefaced TX, standalone "This is" button, or auto-ID injection).
    *   ✅ Hot-reload: Configuration dialog changes to input device or VAD threshold restart the listener automatically; PTT mode/port/line reopen the PTT backend.
    *   ✅ Input and Output device pickers in Configuration (separate, with system-default option).

## Stage 5: Hardware Hooks Readiness — ✅ complete
*   **Goal:** Prepare the software to step out of simulation mode and interact with real radios.
*   **Tasks:**
    *   ✅ `pyserial` integrated; `SerialPTT` keys RTS or DTR (configurable) around TTS playback.
    *   ✅ Three PTT modes in the Configuration dialog: Manual / VOX / USB FTDI–Serial. Lead-in (~50 ms) and tail (~50 ms VOX 150 ms) silence padding so the radio's keying ramp / VOX hang doesn't clip audio.
    *   ✅ TX sequence: pause STT → key PTT → play audio → unkey PTT → resume STT.
    *   ✅ Graceful fallback: if USB FTDI is selected but the port can't be opened, the app reverts to Manual and logs the reason.

## Stage 6: Off-Grid Model Bundling — ✅ complete
*   **Goal:** Eliminate all runtime network dependencies so the application can run on a fresh, air-gapped install (per spec §5.1).
*   **Implemented (deviation from original plan):**
    *   ✅ One-shot `bootstrap_models.py` fetches the Whisper model (`Models/STT/<variant>/`) via `huggingface_hub.snapshot_download` on an internet-connected machine. The resulting `Models/` tree is portable to air-gapped targets.
    *   ✅ `WhisperModel(...)` loads from the local path; the app never touches the network at runtime.
    *   ✅ Silero VAD ships as ONNX inside the `silero-vad` wheel — already local; no separate vendoring needed. Piper voices remain local in `Voices/`.
    *   ✅ Startup self-check: missing Whisper directory shows a clear chat message at boot; the listener fails fast with an actionable error if a `Listen` is attempted without the model present.
    *   ✅ Offline install procedure documented in `README.md` (bootstrap on a connected machine, copy `Models/` to the offline target).
*   **Not implemented:** vendoring the model binaries directly into the repo (deliberately avoided — they're large and license-heterogeneous; the bootstrap script is the chosen alternative).

## Stage 6.5: Accessibility (WCAG 2.1 AA) — ✅ initial pass complete; ongoing constraint
*   **Goal:** Hold the UI to WCAG 2.1 Level AA — the practical ADA baseline for software (referenced by DOJ guidance and Section 508). This is a design constraint applied to every future stage, not just a one-off pass.
*   **Tasks (initial pass):**
    *   ✅ Color contrast: chat palette defined as `COLOR_RX` / `COLOR_TX` / `COLOR_ERROR` / `COLOR_WARN` / `PILL_*` module constants in `main.py`, picked from the Tailwind palette to meet ≥4.5:1 text contrast and ≥3:1 UI-border contrast. Previous bare HTML color names (`"red"`, `"orange"`) which failed AA against white were retired.
    *   ✅ Color is never the sole cue: every chat line carries a text prefix (`[RX HH:MM:SS]:`, `[TX to …]:`, `[TX ID]:`, "Error:", "Warning:") so the line type reads correctly without color perception.
    *   ✅ Full keyboard operation: explicit `setTabOrder` for the main controls, unique Alt-mnemonics on every actionable label (Alt+L / Alt+T / Alt+I / Alt+S → Alt+C / Alt+N), global `QShortcut` keys (Ctrl+L, Ctrl+Return, Ctrl+Enter, Ctrl+I), and platform-aware menu shortcuts (`QKeySequence.StandardKey.Preferences`, Ctrl+B).
    *   ✅ Programmatic semantics: `accessibleName` and `accessibleDescription` set on the header, chat log, target dropdown, message field, Listen / Transmit / This-is buttons, and every pending-station pill. Listen button's description updates on toggle so screen readers report the right state.
    *   ✅ Font scaling: removed hard-coded `font-size:` from stylesheets; header bold sized via `QFont(pointSize + 2)` so the OS font-scale setting carries through. Main window minimum is 720×520 so 150–200 % font scale doesn't clip.
    *   ✅ Visible focus indicator preserved (no stylesheet overrides that strip the Fusion focus ring).
*   **Ongoing constraint:** any PR that introduces a new actionable widget must (a) give it a unique mnemonic / shortcut, (b) set `accessibleName`, (c) avoid pixel `font-size`, and (d) ensure any color used as a state cue is paired with a text or shape cue. The Accessibility section of `technical_spec.md` is the normative reference.

## Stage 7: Cross-Platform Packaging & Distribution — ⏳ pending
*   **Goal:** Produce installable artifacts for Windows, Linux, and Raspberry Pi (per spec §5.2).
*   **Tasks:**
    *   ⏳ Verify `sounddevice` / PortAudio works on Pi (ALSA), Linux desktop (PulseAudio / PipeWire), and Windows (WASAPI). Note device-enumeration quirks per platform in `README.md`.
    *   ⏳ Resolve platform-specific Python dependency issues (PySide6 wheels on ARM64, CTranslate2 ARM wheels, ONNX Runtime ARM wheels). Pin versions in `requirements.txt` to known-good combinations.
    *   ⏳ Benchmark STT latency on Raspberry Pi 4 / Pi 5 using bundled `small.en` int8. If unusable, fall back to `base.en` or `tiny.en` (already exposed via the `whisper_model` config key).
    *   ⏳ Package portable artifacts:
        *   Linux/Pi: tarball or `.deb` that bundles a Python venv, all wheels, and the `Models/` and `Voices/` directories.
        *   Windows: PyInstaller (or similar) one-folder distribution including the same bundled models.
    *   ⏳ Verify each artifact runs on a freshly imaged machine with networking disabled.

## Stage 8: Dockerization (Multi-Architecture) — ⏳ pending
*   **Goal:** Ship a single multi-arch container image for reproducible deployment on x86_64 and Raspberry Pi (per spec §5.3).
*   **Tasks:**
    *   ⏳ Write a `Dockerfile` based on a slim Python base (e.g., `python:3.13-slim`) that installs system packages needed for audio (PortAudio, ALSA dev libs, libsndfile), Qt platform plugins (`libxkbcommon`, `libxcb-*`, etc.), and any ONNX Runtime runtime deps.
    *   ⏳ Bake the `Models/` and `Voices/` directories into the image so the container is self-sufficient on first run with no external mounts required.
    *   ⏳ Build for `linux/amd64` and `linux/arm64` via `docker buildx`. Tag and publish as a single multi-arch manifest.
    *   ⏳ Provide a `docker-compose.yml` (or documented `docker run` recipe) that wires:
        *   Audio I/O: PulseAudio socket mount (`/run/user/$UID/pulse`) or ALSA device passthrough (`--device /dev/snd`).
        *   Display: X11 socket mount (`/tmp/.X11-unix`) plus `DISPLAY` env, with a Wayland note for users on `wlroots`/GNOME.
        *   USB passthrough: `/dev/ttyUSB*` (for serial PTT) and USB sound cards (Signalink/Digirig).
        *   Persistent volumes: `config.json`, `contacts.json`, and the `Voices/` directory mounted from host so user state survives image upgrades.
    *   ⏳ Verify air-gapped operation: run the image on a host with networking disabled and confirm full STT/TTS/UI functionality end-to-end.

## Stage 9: Future Hardware — ⏳ pending
*   **Goal:** Broaden the radio-interface options past serial PTT.
*   **Tasks:**
    *   ⏳ Bluetooth pairing for HTs and Mobile radios that expose a BT audio profile (evaluate `Bleak` for control, system audio stack for SCO/A2DP routing).
    *   ⏳ Optional CAT / CI-V rig control via `hamlib` for frequency/mode set on supported radios.

## Stage 10: TTY-to-Radio-Vernacular Translation on TX — ✅ complete
*   **Goal:** Let the user type compact TTY/chat abbreviations and have them spoken on-air as the equivalent radio vernacular, so the deaf/HoH operator's outgoing speech sounds natural to other GMRS users.
*   **Rationale:** TTY users have decades of muscle memory around abbreviations (`GA`, `SK`, `QSL`, `73`, `CUL`, `OM`, `XYL`, `WX`, `HW?`). On voice, the receiving operator expects the spoken form ("go ahead", "clear", "received", "best regards", "see you later", "weather", "how copy?"). Expanding at TTS time keeps typing fast for the sender while keeping the transmission readable on the air.
*   **Tasks:**
    *   ✅ Seed list landed in `gmrs_tty/text/shorthand.py::TTY_ABBREVIATIONS` alongside the existing TDD/TTY entries: `73`, `88`, `QSL`, `QSO`, `QTH`, `QRZ`, `QRM`, `QRN`, `QRT`, `HW`, `OM`, `XYL`, `WX`, `TNX`, `RST`, `ES`, `FB`, `AGN`, `B4`. `GA`, `SK`, and `CUL` were already present.
    *   ✅ Expansion runs in `MainWindow._synthesize_and_play()` — after GMRS framing / callsign-digit-spelling, before Piper. Word-bounded, case-insensitive, longest-key-first via the existing `_TTY_ABBREV_PATTERN` regex, so `QSO` resolves to "radio contact" rather than "Question mark SO".
    *   ⏳ Future polish (not blocking): externalize to a versioned JSON so power users can extend without editing source, and add a Configuration toggle ("Speak TTY shorthand as radio vernacular", default ON). Today the dict lives in code; the visible chat log still shows the original typed text — the expansion is a speech-layer transform only.
    *   ✅ Unit-tested in `tests/unit/text/test_shorthand.py::TestRadioVernacular` and `TestWordBoundaries` (Q-inside-QSO, `73`-inside-`1973`, case-insensitivity, longest-match precedence). Full unit suite is green.

## Stage 11: AI-Summarized Session Journal — ⏳ pending
*   **Goal:** Let the operator promote a finished listening session into a timestamped journal entry that an on-device LLM has summarized (who spoke, what was discussed, decisions/action items, notable callsigns), and browse historical entries from the UI — all fully offline.
*   **Rationale:** Long RX transcripts are noisy and hard to skim later. A short LLM-generated summary turns each session into a useful record for emergency comms, club nets, and personal logging. Doing it on-device with a small model keeps the air-gap promise and respects operator privacy (transcripts can include personal info / location).
*   **Backend choice:** `ollama` CLI driving **Gemma 3n E2B** (the small-footprint on-device variant; ~2 B effective params, designed for edge inference). Ollama is launched as a local subprocess; no network calls. If the user requested a different specific model variant, treat the model ID as a config field so it's swappable without code changes.
*   **Tasks:**
    *   ⏳ Detect / require `ollama` at startup. Surface a clear chat message and disable the journal UI if `ollama` isn't installed or the configured model isn't pulled locally. Document the one-time `ollama pull gemma3n:e2b` step in `README.md` (alongside the existing `bootstrap_models.py` air-gap workflow).
    *   ⏳ "Summarize session" action on the main dashboard: takes the current RX/TX chat buffer since the last journal save (or since app start), pipes it to the model via `ollama run --format json` with a fixed system prompt that asks for: 1-line headline, 3–5 bullet summary, list of callsigns heard, action items, and the wall-clock span. Time out gracefully (e.g., 60 s) and report the failure to chat without losing the raw transcript.
    *   ⏳ Persist each summary to a local journal store — append-only JSONL at `journal/YYYY/MM/DD.jsonl` (or a SQLite DB; decide at implementation time based on viewer ergonomics). Each entry: ISO 8601 start/end timestamps, model ID, raw transcript, structured summary, operator callsign at time of capture.
    *   ⏳ Journal viewer dialog accessible via the Settings menu: list view sorted by date (newest first), date-range filter, full-text search across summaries, and a detail pane showing the structured summary plus a collapsible raw transcript. Apply the existing WCAG 2.1 AA constraints (keyboard nav, accessibleName on every control, no pixel font-size, mnemonics that don't collide).
    *   ⏳ Privacy: never auto-summarize; the operator triggers each save explicitly. Provide a "Delete entry" affordance in the viewer. Document in `README.md` that summaries are stored in plaintext on disk and recommend filesystem encryption for shared machines.
    *   ⏳ Unit-test the journal store (round-trip, search, deletion) and the prompt/response parser (malformed model output must not corrupt the store). The Ollama subprocess invocation itself can be integration-tested behind a flag — skip in CI if `ollama` isn't present, similar to how Whisper-dependent tests already gate.

## Stage 12: Quick / Common Messages — ✅ complete
*   **Goal:** One-click transmission of frequently used phrases ("Radio check", "Standing by", "Acknowledged", "10-4", "Negative copy", "QSY to channel X", "Net check-in", "Clear", emergency phrases). Saves the deaf/HoH operator from re-typing common traffic and shortens time-to-air during nets and emergencies.
*   **Rationale:** The current input flow requires typing every message. On nets and during incidents, the same handful of acknowledgements and status phrases get sent repeatedly. A row of preset buttons closes that gap and keeps the keyboard free for true free-form traffic. It also pairs naturally with [[stage-10-vernacular]] — presets are *already* the canonical spoken form, so no expansion is needed for them.
*   **Tasks:**
    *   ✅ Quick-messages strip lives in `MainWindow.init_ui()` between the pending bar and the Tx row, backed by the existing `FlowLayout` so the buttons wrap when vertical space tightens. Built/rebuilt by `populate_quick_messages_strip()`; hidden when the saved list is empty so users without presets don't see an empty band.
    *   ✅ Seed list shipped in `config.example.json` under the new `quick_messages` key: `Radio check`, `Loud and clear`, `Standing by`, `Acknowledged`, `Say again`, `QSY to channel {N}`, `Clear`, `Monitoring`, `Net check-in`, `Emergency traffic` (10 entries).
    *   ✅ `QuickMessagesDialog` (`gmrs_tty/ui/quick_messages_dialog.py`) wired into **Settings → &Quick Messages…**. Add / Remove / Move Up / Move Down; OK saves to `config.json` and rebuilds the strip via `populate_quick_messages_strip()`.
    *   ✅ Presets ride the shared `MainWindow._transmit_text(body)` helper that `transmit_message()` was refactored onto, so callsign framing, the 15-minute ID rule, profanity masking, target-reset-to-All, PTT keying, and STT auto-pause are all guaranteed identical between the typed input box and the preset path.
    *   ✅ Placeholder support via `gmrs_tty/text/placeholders.py` (`find_placeholders`, `substitute_placeholders`): tokens like `{N}` or `{Channel Number}` trigger a `QInputDialog.getText` prompt per unique name; cancelling any prompt aborts the transmission so a half-filled preset never goes on-air.
    *   ✅ Accessibility: each preset button carries an `accessibleName` (`Quick message: {phrase}`), an `accessibleDescription`, and a tooltip enumerating the shortcut and any placeholders. The first nine slots claim Alt+1..Alt+9 via `QShortcut`; beyond that the strip stays mouse-only because user-defined phrases can't guarantee unique mnemonics.
    *   ✅ Unit-tested in `tests/unit/text/test_placeholders.py` (20 cases: ordering, dedup, missing/empty values, non-string coercion) and `tests/unit/ui/test_quick_messages_dialog.py` (10 cases: round-trip, blank-row filtering, add/remove, four-direction reorder, selection follows the moved row). The TX-side reuse is covered by inspection — `_transmit_text` is the single source of truth for both the typed message and preset paths.